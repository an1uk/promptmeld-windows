from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .selective_review import (
    ReviewDocument,
    SelectiveTextDiff,
    parse_selective_review_result,
)
from .theme import (
    high_contrast_stylesheet,
    resolve_theme,
    system_high_contrast_enabled,
)


class ResultReviewDialog(QDialog):
    """Review rewrites, accept individual changes, and inspect feedback."""

    selected_result_changed = Signal(str)
    copy_result_requested = Signal()
    apply_result_requested = Signal()

    CHANGE_INDEX_ROLE = Qt.ItemDataRole.UserRole

    def __init__(self, theme: str = "auto"):
        super().__init__()
        self.theme = theme
        self.requested_count = 1
        self.results: list[str] = []
        self.documents: list[ReviewDocument] = []
        self.source_text = ""
        self.safe_review = False
        self.can_apply_base = False
        self.diff: SelectiveTextDiff | None = None
        self._updating_changes = False
        self.setWindowTitle("Review generated alternatives")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setModal(False)
        self.resize(980, 700)
        self.setMinimumSize(720, 520)
        self.setAccessibleName("Review generated alternatives")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        self.title = QLabel("Choose a result")
        self.title.setObjectName("reviewTitle")
        layout.addWidget(self.title)
        self.explanation = QLabel()
        self.explanation.setObjectName("reviewExplanation")
        self.explanation.setWordWrap(True)
        layout.addWidget(self.explanation)
        self.parse_note = QLabel()
        self.parse_note.setObjectName("reviewWarning")
        self.parse_note.setWordWrap(True)
        self.parse_note.hide()
        layout.addWidget(self.parse_note)

        self.options = QListWidget()
        self.options.setMaximumHeight(94)
        self.options.setAccessibleName("Generated alternatives")
        self.options.currentRowChanged.connect(self._selection_changed)
        layout.addWidget(self.options)

        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Rewrite and editorial feedback")
        layout.addWidget(self.tabs, 1)

        rewrite_page = QWidget()
        rewrite_layout = QVBoxLayout(rewrite_page)
        rewrite_layout.setContentsMargins(10, 10, 10, 10)
        rewrite_controls = QHBoxLayout()
        self.change_summary = QLabel("No changes to review")
        self.change_summary.setObjectName("reviewExplanation")
        self.accept_all_button = QPushButton("Accept all changes")
        self.reject_all_button = QPushButton("Reject all changes")
        self.accept_all_button.clicked.connect(
            lambda: self._set_all_changes(True)
        )
        self.reject_all_button.clicked.connect(
            lambda: self._set_all_changes(False)
        )
        rewrite_controls.addWidget(self.change_summary, 1)
        rewrite_controls.addWidget(self.accept_all_button)
        rewrite_controls.addWidget(self.reject_all_button)
        rewrite_layout.addLayout(rewrite_controls)

        self.changes = QTreeWidget()
        self.changes.setColumnCount(3)
        self.changes.setHeaderLabels(("Use", "Before", "After"))
        self.changes.setAccessibleName("Individual proposed changes")
        self.changes.setRootIsDecorated(False)
        self.changes.setAlternatingRowColors(True)
        self.changes.setMaximumHeight(190)
        self.changes.header().setStretchLastSection(True)
        self.changes.setColumnWidth(0, 58)
        self.changes.setColumnWidth(1, 350)
        self.changes.itemChanged.connect(self._change_toggled)
        self.changes.itemSelectionChanged.connect(self._focus_selected_change)
        rewrite_layout.addWidget(self.changes)

        diff_splitter = QSplitter(Qt.Orientation.Horizontal)
        before_group = QGroupBox("Before")
        before_layout = QVBoxLayout(before_group)
        self.before_preview = QTextEdit()
        self.before_preview.setReadOnly(True)
        self.before_preview.setAccessibleName("Original selected text")
        before_layout.addWidget(self.before_preview)
        after_group = QGroupBox("After - selected changes")
        after_layout = QVBoxLayout(after_group)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName("Rewrite with selected changes")
        after_layout.addWidget(self.preview)
        diff_splitter.addWidget(before_group)
        diff_splitter.addWidget(after_group)
        diff_splitter.setSizes((470, 470))
        rewrite_layout.addWidget(diff_splitter, 1)
        self.rewrite_tab_index = self.tabs.addTab(rewrite_page, "Rewrite")

        feedback_page = QWidget()
        feedback_layout = QVBoxLayout(feedback_page)
        feedback_layout.setContentsMargins(10, 10, 10, 10)
        overview_label = QLabel("Editorial feedback")
        overview_label.setObjectName("formLabel")
        feedback_layout.addWidget(overview_label)
        self.feedback_overview = QPlainTextEdit()
        self.feedback_overview.setReadOnly(True)
        self.feedback_overview.setAccessibleName("Editorial feedback overview")
        feedback_layout.addWidget(self.feedback_overview, 1)
        comments_label = QLabel("Comments linked to source passages")
        comments_label.setObjectName("formLabel")
        feedback_layout.addWidget(comments_label)
        self.comments = QTreeWidget()
        self.comments.setColumnCount(2)
        self.comments.setHeaderLabels(("Source passage", "Comment"))
        self.comments.setAccessibleName("Passage-linked editorial comments")
        self.comments.setRootIsDecorated(False)
        self.comments.setAlternatingRowColors(True)
        self.comments.header().setStretchLastSection(True)
        self.comments.setColumnWidth(0, 360)
        self.comments.itemSelectionChanged.connect(
            self._focus_selected_comment
        )
        feedback_layout.addWidget(self.comments, 1)
        self.comment_link_status = QLabel()
        self.comment_link_status.setObjectName("reviewExplanation")
        self.comment_link_status.setWordWrap(True)
        feedback_layout.addWidget(self.comment_link_status)
        self.feedback_tab_index = self.tabs.addTab(
            feedback_page,
            "Editorial feedback",
        )

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.copy_button = QPushButton("Copy result")
        self.copy_button.clicked.connect(self.copy_result_requested.emit)
        buttons.addWidget(self.copy_button)
        self.apply_button = QPushButton("Apply now")
        self.apply_button.setToolTip(
            "Verify the original selection and apply the accepted changes."
        )
        self.apply_button.clicked.connect(self.apply_result_requested.emit)
        buttons.addWidget(self.apply_button)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.setTabOrder(self.options, self.tabs)
        self.setTabOrder(self.tabs, self.changes)
        self.setTabOrder(self.changes, self.copy_button)
        self.setTabOrder(self.copy_button, self.apply_button)
        self.setTabOrder(self.apply_button, self.close_button)
        self._apply_style()
        app = QApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._system_appearance_changed)

    def set_results(
        self,
        results: list[str],
        *,
        requested_count: int,
        can_apply: bool,
        action_purpose: str = "",
        safe_review: bool = False,
        source_text: str = "",
    ) -> None:
        self.results = [value for value in results if value.strip()]
        self.documents = [
            parse_selective_review_result(
                value,
                prefer_feedback=safe_review,
            )
            for value in self.results
        ]
        self.requested_count = requested_count
        self.source_text = str(source_text or "")
        self.safe_review = safe_review
        self.can_apply_base = bool(can_apply and not safe_review)
        self.options.clear()
        self.preview.clear()
        self.before_preview.clear()
        self.feedback_overview.clear()
        self.comments.clear()
        self.copy_button.setText("Copy result")
        self.apply_button.setText("Apply now")
        for index, _value in enumerate(self.results, start=1):
            self.options.addItem(f"Alternative {index}")

        single_result = requested_count <= 1
        self.options.setVisible(not single_result)
        if single_result:
            purpose_name = {
                "analyse": "analysis",
                "extract": "extracted information",
                "develop": "idea development",
            }.get(action_purpose, "generated")
            self.setWindowTitle("Review generated result")
            self.setAccessibleName("Review generated result")
            self.title.setText(f"Review the {purpose_name} result")
            if safe_review:
                self.explanation.setText(
                    "This action produces supporting material rather than "
                    "replacement prose. PromptMeld has preserved the original "
                    "selection and withheld Apply now. Copy any useful material "
                    "from the result when you are ready."
                )
            else:
                self.explanation.setText(
                    "Review the rewrite beside the source, accept or reject "
                    "individual changes, and inspect editorial feedback before "
                    "copying or applying the selected changes."
                )
        else:
            self.setWindowTitle("Review generated alternatives")
            self.setAccessibleName("Review generated alternatives")
            self.title.setText("Choose a result")
            self.explanation.setText(
                f"ChatGPT generated {len(self.results)} alternative"
                f"{'s' if len(self.results) != 1 else ''}. Choose one, then "
                "review and accept its individual changes."
            )

        parsed_all = len(self.results) == requested_count
        structured_all = all(
            document.structured for document in self.documents
        ) if self.documents else False
        warning = ""
        if not parsed_all:
            warning = (
                f"PromptMeld requested {requested_count} alternatives but "
                "could not separate the response reliably. The complete "
                "response is shown as one option."
            )
        elif self.source_text and not structured_all:
            warning = (
                "ChatGPT did not separate the rewrite and editorial feedback. "
                "PromptMeld has still created a local before-and-after diff."
            )
        self.parse_note.setText(warning)
        self.parse_note.setVisible(bool(warning))
        if self.results:
            self.options.setCurrentRow(0)
        else:
            self._clear_document()

    def clear_results(self) -> None:
        self.results.clear()
        self.documents.clear()
        self.diff = None
        self.options.clear()
        self._clear_document()
        self.hide()

    def selected_result(self) -> str:
        if self.diff is not None:
            return self.diff.selected_text()
        index = self.options.currentRow()
        if 0 <= index < len(self.documents):
            return self.documents[index].primary_text
        return ""

    def is_selective_review(self) -> bool:
        return self.diff is not None

    def has_selected_changes(self) -> bool:
        return self.diff is None or self.diff.accepted_count > 0

    def mark_result_copied(self) -> None:
        self.copy_button.setText("Copied")

    def mark_result_applied(self) -> None:
        self.apply_button.setText("Applied")
        self.apply_button.setEnabled(False)

    def _selection_changed(self, index: int) -> None:
        if not 0 <= index < len(self.documents):
            return
        document = self.documents[index]
        self.copy_button.setText("Copy result")
        self.diff = (
            SelectiveTextDiff(self.source_text, document.rewrite)
            if self.source_text and document.rewrite
            else None
        )
        self.tabs.setTabEnabled(
            self.rewrite_tab_index,
            bool(document.rewrite or self.source_text),
        )
        has_feedback = bool(document.feedback or document.comments)
        self.tabs.setTabEnabled(self.feedback_tab_index, has_feedback)
        if document.rewrite:
            self.tabs.setCurrentIndex(self.rewrite_tab_index)
        elif has_feedback:
            self.tabs.setCurrentIndex(self.feedback_tab_index)
        self._populate_changes()
        self._populate_feedback(document)
        self._render_diff(document)
        self._update_action_buttons()
        selected = self.selected_result()
        if selected:
            self.selected_result_changed.emit(selected)

    def _populate_changes(self) -> None:
        self._updating_changes = True
        self.changes.clear()
        if self.diff is not None:
            for segment in self.diff.segments:
                if not segment.changed:
                    continue
                item = QTreeWidgetItem(
                    (
                        "",
                        self._one_line(segment.original) or "[insert]",
                        self._one_line(segment.revised) or "[delete]",
                    )
                )
                item.setData(0, self.CHANGE_INDEX_ROLE, segment.change_index)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked)
                item.setToolTip(1, segment.original or "Inserted text")
                item.setToolTip(2, segment.revised or "Deleted text")
                self.changes.addTopLevelItem(item)
        self._updating_changes = False

    def _populate_feedback(self, document: ReviewDocument) -> None:
        self.feedback_overview.setPlainText(document.feedback)
        self.comments.clear()
        for comment in document.comments:
            item = QTreeWidgetItem(
                (comment.source_passage, comment.comment)
            )
            item.setToolTip(0, comment.source_passage)
            item.setToolTip(1, comment.comment)
            self.comments.addTopLevelItem(item)
        self.comment_link_status.setText(
            "Select a comment to highlight its quoted passage in Before."
            if document.comments
            else "No passage-linked comments were returned."
        )

    def _change_toggled(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating_changes or column != 0 or self.diff is None:
            return
        change_index = int(item.data(0, self.CHANGE_INDEX_ROLE))
        self.diff.set_accepted(
            change_index,
            item.checkState(0) == Qt.CheckState.Checked,
        )
        self._render_diff(self.documents[self.options.currentRow()])
        self._update_action_buttons()
        self.selected_result_changed.emit(self.diff.selected_text())

    def _set_all_changes(self, accepted: bool) -> None:
        if self.diff is None:
            return
        self.diff.set_all(accepted)
        self._updating_changes = True
        state = Qt.CheckState.Checked if accepted else Qt.CheckState.Unchecked
        for row in range(self.changes.topLevelItemCount()):
            self.changes.topLevelItem(row).setCheckState(0, state)
        self._updating_changes = False
        self._render_diff(self.documents[self.options.currentRow()])
        self._update_action_buttons()
        self.selected_result_changed.emit(self.diff.selected_text())

    def _render_diff(self, document: ReviewDocument) -> None:
        if self.diff is None:
            self.before_preview.setPlainText(self.source_text)
            self.preview.setPlainText(
                document.rewrite
                or (document.feedback if not self.source_text else "")
            )
            return
        before_parts: list[str] = []
        after_parts: list[str] = []
        for segment in self.diff.segments:
            if not segment.changed:
                value = escape(segment.original)
                before_parts.append(value)
                after_parts.append(value)
                continue
            original = escape(segment.original)
            revised = escape(segment.revised)
            before_parts.append(
                f'<span class="removed">{original}</span>'
            )
            if self.diff.accepted.get(segment.change_index, True):
                after_parts.append(
                    f'<span class="accepted">{revised}</span>'
                )
            else:
                after_parts.append(
                    f'<span class="rejected">{original}</span>'
                )
        self.before_preview.setHtml(self._diff_html("".join(before_parts)))
        self.preview.setHtml(self._diff_html("".join(after_parts)))

    def _diff_html(self, body: str) -> str:
        if system_high_contrast_enabled():
            styles = (
                ".removed { text-decoration: line-through; font-weight: 700; }"
                ".accepted { text-decoration: underline; font-weight: 700; }"
                ".rejected { border-bottom: 2px dotted currentColor; }"
            )
        elif resolve_theme(self.theme) == "light":
            styles = (
                ".removed { background:#ffe0e0; color:#7a1f1f; }"
                ".accepted { background:#dcf4df; color:#185b27; }"
                ".rejected { background:#fff1c7; color:#694b00; }"
            )
        else:
            styles = (
                ".removed { background:#562b31; color:#ffd7dc; }"
                ".accepted { background:#234a31; color:#d7ffe0; }"
                ".rejected { background:#55451f; color:#ffe8a6; }"
            )
        return (
            f"<style>{styles}</style>"
            '<pre style="white-space:pre-wrap; font-family:inherit; margin:0">'
            f"{body}</pre>"
        )

    def _update_action_buttons(self) -> None:
        selective = self.diff is not None
        accepted = self.diff.accepted_count if selective else 0
        total = self.diff.change_count if selective else 0
        if selective:
            self.change_summary.setText(
                f"{accepted} of {total} proposed change"
                f"{'s' if total != 1 else ''} selected"
            )
            self.copy_button.setText("Copy selected rewrite")
            self.apply_button.setText("Apply selected changes")
        else:
            self.change_summary.setText("No selectable rewrite changes")
            self.copy_button.setText("Copy result")
            self.apply_button.setText("Apply now")
        self.accept_all_button.setEnabled(selective and accepted < total)
        self.reject_all_button.setEnabled(selective and accepted > 0)
        apply_available = bool(
            self.can_apply_base
            and (not selective or accepted > 0)
        )
        self.apply_button.setVisible(self.can_apply_base)
        self.apply_button.setEnabled(apply_available)

    def _focus_selected_change(self) -> None:
        selected = self.changes.selectedItems()
        if not selected or self.diff is None:
            return
        change_index = int(selected[0].data(0, self.CHANGE_INDEX_ROLE))
        segment = next(
            (
                value
                for value in self.diff.segments
                if value.change_index == change_index
            ),
            None,
        )
        if segment is not None:
            self._highlight_source_passage(segment.original)

    def _focus_selected_comment(self) -> None:
        selected = self.comments.selectedItems()
        if not selected:
            return
        passage = selected[0].text(0)
        if self._highlight_source_passage(passage):
            self.comment_link_status.setText(
                "The linked source passage is highlighted in Before."
            )
            self.tabs.setCurrentIndex(self.rewrite_tab_index)
        else:
            self.comment_link_status.setText(
                "The quoted passage could not be matched exactly. It remains "
                "visible in the comment list for manual reference."
            )

    def _highlight_source_passage(self, passage: str) -> bool:
        clean = str(passage or "")
        if not clean:
            return False
        cursor = self.before_preview.document().find(clean)
        if cursor.isNull():
            return False
        self.before_preview.setTextCursor(cursor)
        self.before_preview.ensureCursorVisible()
        return True

    def _clear_document(self) -> None:
        self.diff = None
        self.changes.clear()
        self.comments.clear()
        self.preview.clear()
        self.before_preview.clear()
        self.feedback_overview.clear()
        self._update_action_buttons()

    @staticmethod
    def _one_line(value: str, limit: int = 180) -> str:
        compact = " ".join(str(value or "").split())
        return compact if len(compact) <= limit else compact[: limit - 1] + "\u2026"

    def _apply_style(self) -> None:
        if system_high_contrast_enabled():
            self.setStyleSheet(high_contrast_stylesheet())
            return
        if resolve_theme(self.theme) == "light":
            self.setStyleSheet(
                """
                QDialog { color: #202631; background: #ffffff; }
                QLabel, QGroupBox { color: #202631; }
                QLabel#reviewTitle { font-size: 19px; font-weight: 650; }
                QLabel#reviewExplanation { color: #596270; }
                QLabel#reviewWarning {
                    color: #7a4b00; background: #fff4d6;
                    border: 1px solid #e4c36f; border-radius: 7px;
                    padding: 8px;
                }
                QListWidget, QTreeWidget, QPlainTextEdit, QTextEdit {
                    color: #202631; background: #f5f7fa;
                    border: 1px solid #c5ccd6; border-radius: 8px;
                    padding: 6px; selection-background-color: #dce7ff;
                }
                QTabWidget::pane { border: 1px solid #c5ccd6; border-radius: 7px; }
                QTabBar::tab { color:#394150; padding:8px 14px; }
                QTabBar::tab:selected { color:#173a87; background:#e8efff; }
                QPushButton {
                    color: white; background: #315ecb; border: 0;
                    border-radius: 7px; padding: 8px 15px; font-weight: 600;
                }
                QPushButton:hover { background: #244fae; }
                QPushButton:disabled { color: #7a8491; background: #e5e9ef; }
                """
            )
            return
        self.setStyleSheet(
            """
            QDialog { color: #e9ebef; background: #1b1d23; }
            QLabel, QGroupBox { color: #e9ebef; }
            QLabel#reviewTitle { color: #f4f5f7; font-size: 19px; font-weight: 650; }
            QLabel#reviewExplanation { color: #b8bec9; }
            QLabel#reviewWarning {
                color: #ffd98a; background: #3f3218;
                border: 1px solid #7b622d; border-radius: 7px;
                padding: 8px;
            }
            QListWidget, QTreeWidget, QPlainTextEdit, QTextEdit {
                color: #f4f5f7; background: #23262d;
                border: 1px solid #3a3f4a; border-radius: 8px;
                padding: 6px; selection-background-color: #304a91;
            }
            QTabWidget::pane { border: 1px solid #3a3f4a; border-radius: 7px; }
            QTabBar::tab { color:#b8bec9; padding:8px 14px; }
            QTabBar::tab:selected { color:white; background:#304a91; }
            QPushButton {
                color: white; background: #4f7cff; border: 0;
                border-radius: 7px; padding: 8px 15px; font-weight: 600;
            }
            QPushButton:hover { background: #6d8df2; }
            QPushButton:disabled { color: #858c98; background: #292d34; }
            """
        )

    def _system_appearance_changed(self, *args) -> None:
        self._apply_style()
