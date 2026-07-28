from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .config import (
    DEFAULT_FOLDER_ICONS,
    load_default_actions,
    normalize_folder,
    save_actions,
    save_settings,
)
from .branding import APP_NAME, TAGLINE
from .icons import ActionIconProvider
from .models import (
    DEFAULT_NATURAL_VOICE_INSTRUCTION,
    PRIMARY_LANGUAGE_OPTIONS,
    AppSettings,
    WritingAction,
)
from .paths import AppPaths
from .windows import HotkeyParseError, parse_hotkey


class NoWheelComboBox(QComboBox):
    """Prevent an incidental wheel gesture from changing a closed dropdown."""

    def wheelEvent(self, event) -> None:
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class NoWheelSpinBox(QSpinBox):
    """Require keyboard or explicit button interaction for value changes."""

    def wheelEvent(self, event) -> None:
        event.ignore()


class ActionSettingsDialog(QDialog):
    actions_saved = Signal()
    ITEM_KIND_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(
        self,
        actions: list[WritingAction],
        paths: AppPaths,
        icon_provider: ActionIconProvider,
        popup_hotkey: str,
        settings: AppSettings | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.paths = paths
        self.icon_provider = icon_provider
        self.popup_hotkey = popup_hotkey
        self.settings = settings
        self.folder_icons = dict(settings.folder_icons if settings else {})
        self.actions = list(actions)
        self.current_row = -1
        self.selected_folder = ""
        self._loading = False

        self.setMinimumSize(900, 650)
        self.setWindowTitle(f"{APP_NAME} - Configuration")
        self.resize(1020, 740)

        root = QVBoxLayout(self)
        heading_row = QHBoxLayout()
        heading = QLabel(f"{APP_NAME} configuration")
        heading.setObjectName("settingsTitle")
        self.tagline = QLabel(TAGLINE)
        self.tagline.setObjectName("tagline")
        self.tagline.setAlignment(Qt.AlignmentFlag.AlignRight)
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        heading_row.addWidget(self.tagline)
        description = QLabel(
            "Configure writing actions separately from launcher defaults and "
            "style preferences."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        root.addLayout(heading_row)
        root.addWidget(description)

        voice_settings = settings or AppSettings()
        home_row = QHBoxLayout()
        home_label = QLabel("Most-used actions shown on launcher home")
        home_label.setObjectName("formLabel")
        self.most_used_count = NoWheelSpinBox()
        self.most_used_count.setRange(0, 10)
        self.most_used_count.setValue(
            settings.home_most_used_count if settings is not None else 3
        )
        self.most_used_count.setSpecialValueText("Off")
        self.most_used_count.setToolTip(
            "Pinned direct actions are not counted or duplicated in this section."
        )
        home_row.addWidget(home_label)
        home_row.addWidget(self.most_used_count)
        home_row.addStretch(1)
        language_label = QLabel("Primary writing language")
        language_label.setObjectName("formLabel")
        self.primary_language = NoWheelComboBox()
        self.primary_language.setEditable(True)
        self.primary_language.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.primary_language.addItems(PRIMARY_LANGUAGE_OPTIONS)
        self.primary_language.setCurrentText(
            voice_settings.primary_language
        )
        self.primary_language.setMinimumWidth(190)
        self.primary_language.setToolTip(
            "Used unless an action explicitly requests translation or another "
            "language."
        )
        home_row.addWidget(language_label)
        home_row.addWidget(self.primary_language)

        submission_group = QGroupBox("Submission")
        submission_layout = QVBoxLayout(submission_group)
        self.auto_submit_default = QCheckBox(
            "Submit automatically after pasting the prompt"
        )
        self.auto_submit_default.setChecked(
            voice_settings.auto_submit_enabled
        )
        self.auto_submit_default.setToolTip(
            "This is also the remembered state of the checkbox in the launcher."
        )
        self.submission_description = QLabel(
            f"When off, {APP_NAME} opens a fresh chat in the configured "
            "project and pastes the complete prompt without pressing Enter. "
            "Choose the model or reasoning level in ChatGPT, then submit it "
            "yourself. This avoids depending on model-picker labels that can "
            "change over time or vary by account."
        )
        self.submission_description.setObjectName("muted")
        self.submission_description.setWordWrap(True)
        submission_layout.addWidget(self.auto_submit_default)
        submission_layout.addWidget(self.submission_description)

        voice_group = QGroupBox("Preserve my natural voice")
        voice_layout = QVBoxLayout(voice_group)
        self.natural_voice_default = QCheckBox(
            "Enable by default in the launcher"
        )
        self.natural_voice_default.setChecked(
            voice_settings.natural_voice_enabled
        )
        self.natural_voice_default.setToolTip(
            "This is also the remembered state of the checkbox in the launcher."
        )
        self.voice_description = QLabel(
            "When enabled, this modifier helps retain your vocabulary, level of "
            "formality, and personal phrasing. It may help make the result less "
            "likely to be flagged by AI-detection tools, but those tools are "
            "unreliable and avoidance is far from guaranteed."
        )
        self.voice_description.setObjectName("muted")
        self.voice_description.setWordWrap(True)
        modifier_label = QLabel("Instruction added to the prompt")
        modifier_label.setObjectName("formLabel")
        self.natural_voice_instruction = QPlainTextEdit()
        self.natural_voice_instruction.setObjectName(
            "naturalVoiceInstruction"
        )
        self.natural_voice_instruction.setPlainText(
            voice_settings.natural_voice_instruction
        )
        self.natural_voice_instruction.setMaximumHeight(110)
        self.natural_voice_instruction.setPlaceholderText(
            "Describe how ChatGPT should preserve your voice."
        )
        voice_note = QLabel(
            "Each writing action can follow, always apply, or ignore this modifier."
        )
        voice_note.setObjectName("muted")
        self.reset_voice_button = QPushButton("Restore recommended wording")
        reset_row = QHBoxLayout()
        reset_row.addWidget(voice_note)
        reset_row.addStretch(1)
        reset_row.addWidget(self.reset_voice_button)
        voice_layout.addWidget(self.natural_voice_default)
        voice_layout.addWidget(self.voice_description)
        voice_layout.addWidget(modifier_label)
        voice_layout.addWidget(self.natural_voice_instruction)
        voice_layout.addLayout(reset_row)

        guided_group = QGroupBox("Guided drafting")
        guided_layout = QVBoxLayout(guided_group)
        self.guided_drafting_default = QCheckBox(
            "Allow guided questions for supported actions"
        )
        self.guided_drafting_default.setChecked(
            voice_settings.guided_drafting_enabled
        )
        guided_description = QLabel(
            "When essential context is missing, ChatGPT can ask up to three "
            "concise questions, with choices where helpful, before drafting. "
            "It drafts immediately when the selected text is already sufficient."
        )
        guided_description.setObjectName("muted")
        guided_description.setWordWrap(True)
        guided_note = QLabel(
            "Questions and answers stay in the ChatGPT chat. Each writing action "
            "must also be marked as supporting guided drafting."
        )
        guided_note.setObjectName("muted")
        guided_note.setWordWrap(True)
        guided_layout.addWidget(self.guided_drafting_default)
        guided_layout.addWidget(guided_description)
        guided_layout.addWidget(guided_note)

        content = QHBoxLayout()
        content.setSpacing(18)

        left = QVBoxLayout()
        self.action_list = QTreeWidget()
        self.action_list.setHeaderHidden(True)
        self.action_list.setIconSize(QSize(34, 34))
        self.action_list.setMinimumWidth(285)
        self.action_list.currentItemChanged.connect(self._selection_changed)
        left.addWidget(self.action_list, 1)

        list_buttons = QHBoxLayout()
        self.add_button = QPushButton("Add")
        self.duplicate_button = QPushButton("Duplicate")
        self.delete_button = QPushButton("Delete")
        list_buttons.addWidget(self.add_button)
        list_buttons.addWidget(self.duplicate_button)
        list_buttons.addWidget(self.delete_button)
        left.addLayout(list_buttons)

        order_buttons = QHBoxLayout()
        self.up_button = QPushButton("Move up")
        self.down_button = QPushButton("Move down")
        order_buttons.addWidget(self.up_button)
        order_buttons.addWidget(self.down_button)
        left.addLayout(order_buttons)

        self.starter_button = QPushButton("Load starter action set…")
        left.addWidget(self.starter_button)

        left_widget = QWidget()
        left_widget.setLayout(left)
        content.addWidget(left_widget)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        content.addWidget(divider)

        editor_widget = QWidget()
        editor = QVBoxLayout(editor_widget)
        editor.setContentsMargins(0, 0, 6, 0)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignTop)
        form.setVerticalSpacing(5)

        self.enabled = QCheckBox("Show this action in the launcher")
        form.addRow(self._form_label("Availability"), self.enabled)

        self.show_on_home = QCheckBox(
            "Show as a fixed direct action on launcher home"
        )
        form.addRow(self._form_label("Home shortcut"), self.show_on_home)

        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. Make more diplomatic")
        form.addRow(self._form_label("Name"), self.name)

        id_row = QHBoxLayout()
        self.action_id = QLabel()
        self.action_id.setObjectName("codeValue")
        id_hint = QLabel("Stable internal ID")
        id_hint.setObjectName("muted")
        id_row.addWidget(self.action_id)
        id_row.addStretch(1)
        id_row.addWidget(id_hint)
        form.addRow(self._form_label("ID"), id_row)

        self.folder_combo = NoWheelComboBox()
        self.folder_combo.setEditable(True)
        self.folder_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.folder_combo.lineEdit().setPlaceholderText(
            "Top level, or e.g. Replies / Sarcastic"
        )
        self._populate_folder_choices()
        form.addRow(self._form_label("Folder"), self.folder_combo)

        folder_help = QLabel(
            "Leave blank for the launcher root. Use / to create nested subfolders."
        )
        folder_help.setObjectName("muted")
        folder_help.hide()
        form.addRow("", folder_help)

        icon_row = QHBoxLayout()
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(42, 42)
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_combo = NoWheelComboBox()
        self.icon_combo.setEditable(True)
        self.icon_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.icon_combo.lineEdit().setPlaceholderText("Choose an icon or type an emoji")
        for label, spec in self.icon_provider.CATALOG:
            self.icon_combo.addItem(
                self.icon_provider.icon_for_spec(spec, spec, 30),
                label,
                spec,
            )
        self.choose_icon_button = QPushButton("Choose file…")
        icon_row.addWidget(self.icon_preview)
        icon_row.addWidget(self.icon_combo, 1)
        icon_row.addWidget(self.choose_icon_button)
        form.addRow(self._form_label("Icon"), icon_row)

        icon_help = QLabel(
            "Built-in icons are from Lucide. You can also type an emoji or choose "
            "a PNG, SVG, ICO, JPG, BMP, or WebP file."
        )
        icon_help.setObjectName("muted")
        icon_help.setWordWrap(True)
        icon_help.hide()
        form.addRow("", icon_help)

        self.keywords = QLineEdit()
        self.keywords.setPlaceholderText("comma-separated search words")
        form.addRow(self._form_label("Keywords"), self.keywords)

        self.hotkey = QLineEdit()
        self.hotkey.setPlaceholderText("Optional, e.g. Ctrl+Alt+7")
        form.addRow(self._form_label("Global hotkey"), self.hotkey)

        self.natural_voice_mode = NoWheelComboBox()
        self.natural_voice_mode.addItem(
            "Use launcher checkbox",
            "inherit",
        )
        self.natural_voice_mode.addItem("Always apply", "always")
        self.natural_voice_mode.addItem("Never apply", "never")
        self.natural_voice_mode.setToolTip(
            "Choose whether this action follows or overrides the launcher checkbox."
        )
        form.addRow(
            self._form_label("Natural voice"),
            self.natural_voice_mode,
        )

        self.guided_drafting = QCheckBox(
            "Allow guided questions when enabled globally"
        )
        self.guided_drafting.setToolTip(
            "If the selected text lacks essential context, ChatGPT may ask up "
            "to three concise questions before drafting. It still drafts "
            "immediately when enough context is available."
        )
        form.addRow(
            self._form_label("Guided drafting"),
            self.guided_drafting,
        )

        self.instruction = QPlainTextEdit()
        self.instruction.setObjectName("actionInstruction")
        self.instruction.setPlaceholderText(
            "Describe how ChatGPT should transform the selected text."
        )
        self.instruction.setMinimumHeight(105)
        form.addRow(self._form_label("Instruction"), self.instruction)
        editor.addLayout(form)
        editor.addStretch(1)
        content.addWidget(editor_widget, 1)

        self.tabs = QTabWidget()
        actions_page = QWidget()
        actions_page.setObjectName("settingsPage")
        actions_page.setLayout(content)
        defaults_page = QWidget()
        defaults_page.setObjectName("settingsPage")
        defaults_layout = QVBoxLayout(defaults_page)
        defaults_layout.setContentsMargins(22, 18, 22, 18)
        defaults_layout.setSpacing(16)
        defaults_layout.addLayout(home_row)
        defaults_layout.addWidget(submission_group)
        defaults_layout.addWidget(voice_group)
        defaults_layout.addWidget(guided_group)
        defaults_layout.addStretch(1)
        self.tabs.addTab(actions_page, "Writing actions")
        self.tabs.addTab(defaults_page, "Defaults & style")
        root.addWidget(self.tabs, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Close
        )
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        footer = QHBoxLayout()
        self.save_status = QLabel()
        self.save_status.setObjectName("saveStatus")
        footer.addWidget(self.save_status)
        footer.addStretch(1)
        footer.addWidget(self.buttons)
        root.addLayout(footer)

        self.add_button.clicked.connect(self._add_action)
        self.duplicate_button.clicked.connect(self._duplicate_action)
        self.delete_button.clicked.connect(self._delete_action)
        self.up_button.clicked.connect(lambda: self._move_action(-1))
        self.down_button.clicked.connect(lambda: self._move_action(1))
        self.starter_button.clicked.connect(self._load_starter_set)
        self.reset_voice_button.clicked.connect(
            self._restore_natural_voice_wording
        )
        self.choose_icon_button.clicked.connect(self._choose_icon_file)
        self.icon_combo.currentIndexChanged.connect(self._update_icon_preview)
        self.icon_combo.lineEdit().textChanged.connect(self._update_icon_preview)

        for signal in (
            self.enabled.toggled,
            self.show_on_home.toggled,
            self.name.textChanged,
            self.folder_combo.currentTextChanged,
            self.icon_combo.currentTextChanged,
            self.keywords.textChanged,
            self.hotkey.textChanged,
            self.natural_voice_mode.currentIndexChanged,
            self.guided_drafting.toggled,
            self.instruction.textChanged,
            self.most_used_count.valueChanged,
            self.primary_language.currentTextChanged,
            self.auto_submit_default.toggled,
            self.natural_voice_default.toggled,
            self.natural_voice_instruction.textChanged,
            self.guided_drafting_default.toggled,
        ):
            signal.connect(self._mark_unsaved)

        self._apply_style()
        self._refresh_list(0 if self.actions else -1)
        self._set_save_status("")

    def _refresh_list(self, selected_row: int) -> None:
        self._loading = True
        self.action_list.clear()
        folder_items: dict[str, QTreeWidgetItem] = {}
        action_items: dict[str, QTreeWidgetItem] = {}

        def ensure_folder(path: str) -> QTreeWidgetItem:
            if path in folder_items:
                return folder_items[path]
            parent_path, _, name = path.rpartition("/")
            parent = (
                ensure_folder(parent_path)
                if parent_path
                else self.action_list.invisibleRootItem()
            )
            item = QTreeWidgetItem(parent, [name])
            item.setIcon(
                0,
                self.icon_provider.folder_icon_for(
                    path,
                    self.folder_icons.get(path, ""),
                    34,
                ),
            )
            item.setData(0, Qt.ItemDataRole.UserRole, path)
            item.setData(0, self.ITEM_KIND_ROLE, "folder")
            item.setForeground(0, QColor("#c4cad5"))
            item.setToolTip(0, f"Folder: {path}")
            folder_items[path] = item
            return item

        for action in self.actions:
            parent = (
                ensure_folder(action.folder)
                if action.folder
                else self.action_list.invisibleRootItem()
            )
            label = action.name if action.enabled else f"{action.name} (disabled)"
            item = QTreeWidgetItem(parent, [label])
            item.setIcon(0, self.icon_provider.icon_for(action))
            item.setForeground(
                0,
                QColor("#e8eaf0" if action.enabled else "#858b98"),
            )
            item.setData(0, Qt.ItemDataRole.UserRole, action.id)
            item.setData(0, self.ITEM_KIND_ROLE, "action")
            tooltip = action.instruction
            if action.folder:
                tooltip = f"Folder: {action.folder}\n\n{tooltip}"
            if action.show_on_home:
                tooltip = f"Pinned to launcher home\n\n{tooltip}"
            item.setToolTip(0, tooltip)
            action_items[action.id] = item

        self.action_list.expandAll()
        if 0 <= selected_row < len(self.actions):
            self.current_row = selected_row
            self.selected_folder = self.actions[selected_row].folder
            selected_item = action_items[self.actions[selected_row].id]
            self.action_list.setCurrentItem(selected_item)
            self.action_list.scrollToItem(selected_item)
        else:
            self.current_row = -1
            self.selected_folder = ""
        self._loading = False
        self._load_current()
        self._update_button_states()

    def _selection_changed(
        self,
        current: QTreeWidgetItem | None,
        previous: QTreeWidgetItem | None,
    ) -> None:
        if self._loading:
            return
        self._commit_current()
        self.current_row = -1
        self.selected_folder = ""
        if current is not None:
            kind = current.data(0, self.ITEM_KIND_ROLE)
            value = str(current.data(0, Qt.ItemDataRole.UserRole) or "")
            if kind == "action":
                self.current_row = next(
                    (
                        index
                        for index, action in enumerate(self.actions)
                        if action.id == value
                    ),
                    -1,
                )
                if self.current_row >= 0:
                    self.selected_folder = self.actions[self.current_row].folder
            elif kind == "folder":
                self.selected_folder = value
        self._load_current()
        self._update_button_states()

    def _load_current(self) -> None:
        self._loading = True
        has_action = 0 <= self.current_row < len(self.actions)
        has_folder = bool(self.selected_folder) and not has_action
        for widget in (
            self.enabled,
            self.show_on_home,
            self.name,
            self.folder_combo,
            self.keywords,
            self.hotkey,
            self.natural_voice_mode,
            self.guided_drafting,
            self.instruction,
        ):
            widget.setEnabled(has_action)
        self.icon_combo.setEnabled(has_action or has_folder)
        self.choose_icon_button.setEnabled(has_action or has_folder)

        if has_action:
            action = self.actions[self.current_row]
            self.enabled.setChecked(action.enabled)
            self.show_on_home.setChecked(action.show_on_home)
            self.name.setText(action.name)
            self.action_id.setText(action.id)
            self.folder_combo.setCurrentText(action.folder)
            self._set_icon_spec(action.icon)
            self.keywords.setText(", ".join(action.keywords))
            self.hotkey.setText(action.hotkey or "")
            voice_index = self.natural_voice_mode.findData(
                action.natural_voice
            )
            self.natural_voice_mode.setCurrentIndex(max(voice_index, 0))
            self.guided_drafting.setChecked(action.guided_drafting)
            self.instruction.setPlainText(action.instruction)
            self._set_instruction_colour()
        elif has_folder:
            self.enabled.setChecked(False)
            self.show_on_home.setChecked(False)
            self.name.setText(self.selected_folder.rpartition("/")[2])
            self.action_id.setText("Folder")
            self.folder_combo.setCurrentText(self.selected_folder)
            self._set_icon_spec(self.folder_icons.get(self.selected_folder, ""))
            self.keywords.clear()
            self.hotkey.clear()
            self.natural_voice_mode.setCurrentIndex(0)
            self.guided_drafting.setChecked(False)
            self.instruction.clear()
        else:
            self.enabled.setChecked(False)
            self.show_on_home.setChecked(False)
            self.name.clear()
            self.action_id.setText("Folder selected" if self.selected_folder else "—")
            self.folder_combo.setCurrentText(self.selected_folder)
            self.icon_combo.setCurrentIndex(-1)
            self.icon_combo.clearEditText()
            self.keywords.clear()
            self.hotkey.clear()
            self.natural_voice_mode.setCurrentIndex(0)
            self.guided_drafting.setChecked(False)
            self.instruction.clear()
        self._loading = False
        self._update_icon_preview()

    def _commit_current(self) -> None:
        if self._loading:
            return
        if not 0 <= self.current_row < len(self.actions):
            if self.selected_folder:
                icon = self._selected_icon_spec()
                if icon:
                    self.folder_icons[self.selected_folder] = icon
                else:
                    self.folder_icons.pop(self.selected_folder, None)
            return
        current = self.actions[self.current_row]
        keywords = tuple(
            item.strip() for item in self.keywords.text().split(",") if item.strip()
        )
        self.actions[self.current_row] = replace(
            current,
            name=self.name.text().strip(),
            keywords=keywords,
            instruction=self.instruction.toPlainText().strip(),
            hotkey=self.hotkey.text().strip() or None,
            enabled=self.enabled.isChecked(),
            show_on_home=self.show_on_home.isChecked(),
            icon=self._selected_icon_spec(),
            folder=self.folder_combo.currentText().strip(),
            natural_voice=str(
                self.natural_voice_mode.currentData() or "inherit"
            ),
            guided_drafting=self.guided_drafting.isChecked(),
        )

    def _set_icon_spec(self, spec: str) -> None:
        icon_index = self.icon_combo.findData(spec)
        if icon_index >= 0:
            self.icon_combo.setCurrentIndex(icon_index)
        else:
            self.icon_combo.setCurrentIndex(-1)
            self.icon_combo.setEditText(spec)

    @staticmethod
    def _form_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("formLabel")
        return label

    def _set_instruction_colour(self) -> None:
        cursor = self.instruction.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        text_format = QTextCharFormat()
        text_format.setForeground(QColor("#ffffff"))
        cursor.mergeCharFormat(text_format)
        cursor.clearSelection()
        self.instruction.setTextCursor(cursor)
        self.instruction.setCurrentCharFormat(text_format)

    def _mark_unsaved(self, *args) -> None:
        if self._loading:
            return
        self._set_save_status("Unsaved changes", saved=False)

    def _set_save_status(
        self,
        message: str,
        saved: bool | None = None,
    ) -> None:
        self.save_status.setText(message)
        colour = (
            "#79d69a"
            if saved is True
            else "#d9b56d"
            if saved is False
            else "#9298a5"
        )
        self.save_status.setStyleSheet(f"color: {colour}; font-weight: 600;")

    def _selected_icon_spec(self) -> str:
        index = self.icon_combo.currentIndex()
        if (
            index >= 0
            and self.icon_combo.currentText() == self.icon_combo.itemText(index)
        ):
            return str(self.icon_combo.itemData(index))
        return self.icon_combo.currentText().strip()

    def _update_icon_preview(self, *args) -> None:
        if self._loading:
            return
        if self.selected_folder and not 0 <= self.current_row < len(self.actions):
            icon = self.icon_provider.folder_icon_for(
                self.selected_folder,
                self._selected_icon_spec(),
                38,
            )
        else:
            action_id = (
                self.actions[self.current_row].id
                if 0 <= self.current_row < len(self.actions)
                else "preview"
            )
            icon = self.icon_provider.icon_for_spec(
                self._selected_icon_spec(),
                action_id,
                38,
            )
        self.icon_preview.setPixmap(icon.pixmap(38, 38))

    def _add_action(self) -> None:
        self._commit_current()
        folder = self.selected_folder
        action_id = self._unique_id("new-action")
        self.actions.append(
            WritingAction(
                id=action_id,
                name="New action",
                keywords=(),
                instruction="Rewrite the text as requested.",
                icon="lucide:wand-sparkles",
                folder=folder,
            )
        )
        self._refresh_list(len(self.actions) - 1)
        self._mark_unsaved()
        self.name.selectAll()
        self.name.setFocus()

    def _duplicate_action(self) -> None:
        self._commit_current()
        if not 0 <= self.current_row < len(self.actions):
            return
        source = self.actions[self.current_row]
        duplicate = replace(
            source,
            id=self._unique_id(f"{source.id}-copy"),
            name=f"{source.name} copy",
            hotkey=None,
        )
        insert_at = self.current_row + 1
        self.actions.insert(insert_at, duplicate)
        self._refresh_list(insert_at)
        self._mark_unsaved()

    def _delete_action(self) -> None:
        if not 0 <= self.current_row < len(self.actions):
            return
        self.actions.pop(self.current_row)
        next_row = min(self.current_row, len(self.actions) - 1)
        self._refresh_list(next_row)
        self._mark_unsaved()

    def _move_action(self, offset: int) -> None:
        self._commit_current()
        if not 0 <= self.current_row < len(self.actions):
            return
        folder = self.actions[self.current_row].folder
        peers = [
            index
            for index, action in enumerate(self.actions)
            if action.folder == folder
        ]
        peer_position = peers.index(self.current_row)
        destination_position = peer_position + offset
        if not 0 <= destination_position < len(peers):
            return
        destination = peers[destination_position]
        self.actions[self.current_row], self.actions[destination] = (
            self.actions[destination],
            self.actions[self.current_row],
        )
        self._refresh_list(destination)
        self._mark_unsaved()

    def _choose_icon_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Choose action icon",
            str(Path.home()),
            "Images (*.png *.svg *.ico *.jpg *.jpeg *.bmp *.webp)",
        )
        if filename:
            self.icon_combo.setCurrentIndex(-1)
            self.icon_combo.setEditText(filename)
            self._update_icon_preview()

    def _load_starter_set(self) -> None:
        response = QMessageBox.question(
            self,
            "Load starter action set",
            "Replace the actions currently shown in this editor with the shipped "
            "starter set?\n\nNothing is written until you choose Save. Canceling "
            "the window will keep your existing configuration.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        self.actions = load_default_actions()
        self.folder_icons = dict(DEFAULT_FOLDER_ICONS)
        self._populate_folder_choices()
        self._refresh_list(0 if self.actions else -1)
        self._mark_unsaved()

    def _restore_natural_voice_wording(self) -> None:
        self.natural_voice_instruction.setPlainText(
            DEFAULT_NATURAL_VOICE_INSTRUCTION
        )

    def _save(self) -> None:
        self._commit_current()
        try:
            actions = self._validated_actions()
            folder_icons = self._validated_folder_icons(actions)
            if self.settings is not None:
                self.settings = replace(
                    self.settings,
                    home_most_used_count=self.most_used_count.value(),
                    folder_icons=folder_icons,
                    natural_voice_enabled=(
                        self.natural_voice_default.isChecked()
                    ),
                    natural_voice_instruction=(
                        self.natural_voice_instruction.toPlainText().strip()
                    ),
                    auto_submit_enabled=(
                        self.auto_submit_default.isChecked()
                    ),
                    primary_language=(
                        self.primary_language.currentText().strip()
                    ),
                    guided_drafting_enabled=(
                        self.guided_drafting_default.isChecked()
                    ),
                )
                save_settings(self.paths.settings_file, self.settings)
            save_actions(self.paths.actions_file, actions)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Cannot save actions", str(exc))
            return
        self.actions = actions
        self.actions_saved.emit()
        self._set_save_status("Changes saved", saved=True)

    def _validated_folder_icons(
        self,
        actions: list[WritingAction],
    ) -> dict[str, str]:
        valid_folders: set[str] = set()
        for action in actions:
            parts = action.folder.split("/") if action.folder else []
            for depth in range(1, len(parts) + 1):
                valid_folders.add("/".join(parts[:depth]))

        validated: dict[str, str] = {}
        for folder in valid_folders:
            icon = self.folder_icons.get(folder, "").strip()
            if not icon:
                continue
            icon_path = self.icon_provider.resolve_image(icon)
            if icon_path is not None and not icon.startswith("lucide:"):
                try:
                    icon = icon_path.resolve().relative_to(
                        self.paths.data_dir.resolve()
                    ).as_posix()
                except ValueError:
                    icon = self.icon_provider.install_image(icon_path)
            validated[folder] = icon
        return validated

    def _validated_actions(self) -> list[WritingAction]:
        ids: set[str] = set()
        hotkeys: dict[tuple[int, int], str] = {}
        popup = parse_hotkey(self.popup_hotkey)
        hotkeys[(popup.modifiers, popup.virtual_key)] = "Open launcher"
        validated: list[WritingAction] = []

        for index, action in enumerate(self.actions, start=1):
            if not action.id or action.id in ids:
                raise ValueError(f"Action {index} has an invalid or duplicate ID.")
            ids.add(action.id)
            if not action.name:
                raise ValueError(f"Action {index} needs a name.")
            if not action.instruction:
                raise ValueError(f"'{action.name}' needs an instruction.")
            if action.natural_voice not in {
                "inherit",
                "always",
                "never",
            }:
                raise ValueError(
                    f"'{action.name}' has an invalid natural voice setting."
                )
            if action.hotkey:
                try:
                    parsed = parse_hotkey(action.hotkey)
                except HotkeyParseError as exc:
                    raise ValueError(f"'{action.name}': {exc}") from exc
                if action.enabled:
                    key = (parsed.modifiers, parsed.virtual_key)
                    if key in hotkeys:
                        raise ValueError(
                            f"'{action.name}' uses the same hotkey as "
                            f"'{hotkeys[key]}'."
                        )
                    hotkeys[key] = action.name

            icon = action.icon
            icon_path = self.icon_provider.resolve_image(icon)
            if icon_path is not None and not icon.startswith("lucide:"):
                try:
                    icon = icon_path.resolve().relative_to(
                        self.paths.data_dir.resolve()
                    ).as_posix()
                except ValueError:
                    icon = self.icon_provider.install_image(icon_path)
            validated.append(
                replace(
                    action,
                    icon=icon,
                    folder=normalize_folder(action.folder),
                )
            )
        return validated

    def _populate_folder_choices(self) -> None:
        current = (
            self.folder_combo.currentText()
            if hasattr(self, "folder_combo")
            else ""
        )
        folders = list(
            dict.fromkeys(action.folder for action in self.actions if action.folder)
        )
        if not hasattr(self, "folder_combo"):
            return
        self.folder_combo.blockSignals(True)
        self.folder_combo.clear()
        self.folder_combo.addItem("")
        self.folder_combo.addItems(folders)
        self.folder_combo.setCurrentText(current)
        self.folder_combo.blockSignals(False)

    def _unique_id(self, preferred: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", preferred.casefold()).strip("-")
        slug = slug or "action"
        existing = {action.id for action in self.actions}
        candidate = slug
        suffix = 2
        while candidate in existing:
            candidate = f"{slug}-{suffix}"
            suffix += 1
        return candidate

    def _update_button_states(self) -> None:
        has_action = 0 <= self.current_row < len(self.actions)
        self.duplicate_button.setEnabled(has_action)
        self.delete_button.setEnabled(has_action)
        if not has_action:
            self.up_button.setEnabled(False)
            self.down_button.setEnabled(False)
            return
        folder = self.actions[self.current_row].folder
        peers = [
            index
            for index, action in enumerate(self.actions)
            if action.folder == folder
        ]
        position = peers.index(self.current_row)
        self.up_button.setEnabled(position > 0)
        self.down_button.setEnabled(position < len(peers) - 1)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog { background: #17191e; color: #e9ebef; }
            QLabel { color: #e9ebef; }
            QLabel#settingsTitle {
                color: #f4f5f7;
                font-size: 22px;
                font-weight: 650;
            }
            QLabel#tagline {
                color: #9fb2ef;
                font-size: 12px;
                font-style: italic;
            }
            QLabel#muted { color: #9298a5; }
            QLabel#formLabel { color: #aeb4c0; }
            QLabel#inlineLabel { color: #9298a5; padding: 0 3px; }
            QLabel#codeValue {
                color: #b8c8ff;
                background: #242730;
                border-radius: 5px;
                padding: 4px 7px;
                font-family: Consolas;
            }
            QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
                color: #f4f5f7;
                background: #22252c;
                border: 1px solid #3a3f4a;
                border-radius: 7px;
                padding: 7px 9px;
                selection-background-color: #3e6ae1;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {
                border-color: #6d8df2;
            }
            QPlainTextEdit#actionInstruction {
                color: #ffffff;
                background: #191d24;
                border: 1px solid #596273;
                font-size: 13px;
            }
            QPlainTextEdit#actionInstruction:focus {
                color: #ffffff;
                background: #1c2129;
                border-color: #85a0ff;
            }
            QPlainTextEdit#naturalVoiceInstruction {
                color: #ffffff;
                background: #1d222a;
                border-color: #4c5565;
            }
            QComboBox QAbstractItemView {
                color: #f4f5f7;
                background: #22252c;
                selection-background-color: #304a91;
            }
            QTreeWidget {
                color: #e8eaf0;
                background: #202229;
                border: 1px solid #343842;
                border-radius: 8px;
                outline: 0;
            }
            QTreeWidget::item { padding: 7px; }
            QTreeWidget::item:selected { background: #304a91; color: white; }
            QTabWidget::pane {
                background: #17191e;
                border: 1px solid #343842;
                border-radius: 7px;
                top: -1px;
            }
            QTabBar::tab {
                color: #aeb4c0;
                background: #22252c;
                border: 1px solid #343842;
                border-bottom: 0;
                padding: 9px 16px;
                min-width: 130px;
            }
            QTabBar::tab:selected {
                color: #ffffff;
                background: #304a91;
            }
            QTabBar::tab:hover:!selected { background: #2b2e36; }
            QWidget#settingsPage {
                background: #17191e;
            }
            QPushButton {
                color: white;
                background: #30343d;
                border: 1px solid #454b57;
                border-radius: 7px;
                padding: 7px 11px;
            }
            QPushButton:hover { background: #3a3f49; }
            QPushButton:disabled { color: #6f7580; background: #25272d; }
            QDialogButtonBox QPushButton {
                min-width: 82px;
                background: #315ecb;
                border: 0;
                font-weight: 600;
            }
            QCheckBox { color: #e9ebef; spacing: 8px; }
            QGroupBox {
                color: #aeb4c0;
                border: 1px solid #343842;
                border-radius: 7px;
                margin-top: 8px;
                padding-top: 7px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QFrame { color: #343842; }
            """
        )
