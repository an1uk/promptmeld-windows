from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from .actions import ActionRegistry
from .branding import APP_NAME, TAGLINE
from .icons import ActionIconProvider
from .models import (
    EDITING_STRENGTH_OPTIONS,
    RECIPIENT_AUDIENCE_OPTIONS,
    RESULTING_TEXT_FORMATTING_OPTIONS,
    RESULTING_TEXT_LENGTH_OPTIONS,
    TITLE_SUBJECT_OPTIONS,
)
from .returning import EffectiveApplicationProfile, ReturnDecision
from .suggestions import SuggestionContext, classify_suggestion_context
from .theme import (
    high_contrast_stylesheet,
    message_box_stylesheet,
    resolve_theme,
    system_high_contrast_enabled,
)


class LauncherPopup(QWidget):
    action_requested = Signal(str, str, str, bool, str, int)
    action_highlighted = Signal(str)
    custom_requested = Signal(str, str, str, bool, str, int)
    natural_voice_changed = Signal(bool)
    auto_submit_changed = Signal(bool)
    replace_selected_text_changed = Signal(bool)
    temporary_chat_changed = Signal(bool)
    guided_drafting_changed = Signal(bool)
    resulting_text_length_changed = Signal(str)
    writing_block_changed = Signal(bool)
    resulting_text_formatting_changed = Signal(str)
    title_subject_changed = Signal(str)
    ITEM_KIND_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(
        self,
        registry: ActionRegistry,
        icon_provider: ActionIconProvider | None = None,
        home_most_used_count: int = 3,
        folder_icons: dict[str, str] | None = None,
        natural_voice_enabled: bool = False,
        auto_submit_enabled: bool = False,
        temporary_chat_enabled: bool = False,
        theme: str = "auto",
        guided_drafting_enabled: bool = False,
        resulting_text_length: str = "default",
        writing_block_enabled: bool = False,
        resulting_text_formatting: str = "default",
        replace_selected_text_enabled: bool = False,
        title_subject: str = "none",
    ):
        super().__init__()
        self.registry = registry
        self.icon_provider = icon_provider
        self.home_most_used_count = home_most_used_count
        self.folder_icons = dict(folder_icons or {})
        self.natural_voice_enabled = natural_voice_enabled
        self.auto_submit_enabled = auto_submit_enabled
        self.replace_selected_text_enabled = replace_selected_text_enabled
        self.source_is_editable = True
        self.application_policy_override = False
        self.action_result_policy_lock = False
        self._source_profile_note = ""
        self.temporary_chat_enabled = temporary_chat_enabled
        self.guided_drafting_enabled = guided_drafting_enabled
        self.resulting_text_length_value = resulting_text_length
        self.writing_block_enabled = writing_block_enabled
        self.resulting_text_formatting_value = resulting_text_formatting
        self.title_subject_value = title_subject
        self.editing_strength_value = "default"
        self.preserve_facts_enabled = True
        self.recipient_audience_value = "unspecified"
        self.audience_explicitly_selected = False
        self.alternative_count_value = 1
        self.application_editing_strength_default = "default"
        self.application_preserve_facts_default = True
        self.application_audience_default = "unspecified"
        self.application_overridden_fields: frozenset[str] = frozenset()
        self.suggestion_context: SuggestionContext | None = None
        self.suggestion_reasons: dict[str, tuple[str, ...]] = {}
        self.theme = theme
        self.current_folder = ""
        self._dragging = False
        self._drag_offset = None
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(500, 680)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setObjectName("launcherFrame")
        root.addWidget(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self.header = QFrame()
        self.header.setObjectName("launcherHeader")
        title_row = QGridLayout(self.header)
        title_row.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel(APP_NAME)
        self.title.setObjectName("title")
        self.tagline = QLabel(TAGLINE)
        self.tagline.setObjectName("tagline")
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("launcherCloseButton")
        self.close_button.setAccessibleName("Close launcher")
        self.close_button.setToolTip("Close launcher")
        self.close_button.setFixedSize(28, 28)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_row.addWidget(
            self.title,
            0,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        title_row.addWidget(
            self.tagline,
            0,
            0,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
        )
        title_row.addWidget(
            self.close_button,
            0,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
        )
        layout.addWidget(self.header)
        self._drag_handles = {
            self.header,
            self.title,
            self.tagline,
        }


        self.location = QLabel()
        self.location.setObjectName("breadcrumb")
        self.location.hide()
        layout.addWidget(self.location)

        self.source_context = QLabel()
        self.source_context.setObjectName("breadcrumb")
        self.source_context.setWordWrap(True)
        self.source_context.setAccessibleName("Generated result destination")
        self.source_context.hide()
        layout.addWidget(self.source_context)

        self.suggestion_context_label = QLabel()
        self.suggestion_context_label.setObjectName("hint")
        self.suggestion_context_label.setWordWrap(True)
        self.suggestion_context_label.setAccessibleName(
            "Local action suggestion context"
        )
        self.suggestion_context_label.hide()
        layout.addWidget(self.suggestion_context_label)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search writing actions…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search writing actions")
        self.search.setAccessibleDescription(
            "Type to filter actions. Press Down Arrow to move to the results."
        )
        self.focus_search_shortcut = QShortcut(
            QKeySequence.StandardKey.Find,
            self,
        )
        self.focus_search_shortcut.activated.connect(self._focus_search)
        self.close_shortcut = QShortcut(
            QKeySequence.StandardKey.Close,
            self,
        )
        self.close_shortcut.activated.connect(self.hide)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setUniformItemSizes(False)
        self.list.setSpacing(2)
        self.list.setIconSize(QSize(36, 36))
        self.list.installEventFilter(self)
        self.list.setAccessibleName("Writing actions")
        self.list.setAccessibleDescription(
            "Use arrow keys to choose an action and Enter to run it."
        )
        layout.addWidget(self.list, 1)
        selected_action_row = QHBoxLayout()
        selected_action_hint = QLabel(
            "Select an action, then send it or press Enter."
        )
        selected_action_hint.setObjectName("hint")
        self.send_selected_action = QPushButton("Send selected action")
        self.send_selected_action.setAccessibleName(
            "Send selected writing action"
        )
        self.send_selected_action.setToolTip(
            "Start the request using the selected writing action."
        )
        self.send_selected_action.setEnabled(False)
        selected_action_row.addWidget(selected_action_hint)
        selected_action_row.addStretch(1)
        selected_action_row.addWidget(self.send_selected_action)
        layout.addLayout(selected_action_row)

        self.options_toggle = QPushButton("Request options and custom instruction")
        self.options_toggle.setCheckable(True)
        self.options_toggle.setChecked(False)
        self.options_toggle.setAccessibleName(
            "Show request options and custom instruction"
        )
        self.options_toggle.setToolTip(
            "Show remembered choices, output and guidance controls, additional "
            "context, and the one-off instruction field."
        )
        layout.addWidget(self.options_toggle)
        self.options_panel = QFrame()
        self.options_panel.setObjectName("launcherOptionsPanel")
        options_layout = QVBoxLayout(self.options_panel)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(10)
        self.options_panel.hide()
        layout.addWidget(self.options_panel)

        self.remembered_options_label = QLabel(
            "Remembered choices (unless an application profile overrides them)"
        )
        self.remembered_options_label.setObjectName("hint")
        self.remembered_options_label.setWordWrap(True)
        options_layout.addWidget(self.remembered_options_label)

        self.natural_voice = QCheckBox("Preserve my natural voice")
        self.natural_voice.setChecked(self.natural_voice_enabled)
        self.natural_voice.setToolTip(
            "Keep your vocabulary and level of formality, avoid generic filler, "
            "and make only the changes needed for the selected task."
        )
        self.natural_voice.setAccessibleDescription(
            self.natural_voice.toolTip()
        )
        self.auto_submit = QCheckBox("Submit automatically")
        self.auto_submit.setChecked(self.auto_submit_enabled)
        self.auto_submit.setToolTip(
            "When off, the prompt is pasted into ChatGPT but left unsent so you "
            "can choose the model or reasoning level before pressing Enter."
        )
        self.auto_submit.setAccessibleDescription(self.auto_submit.toolTip())
        self.replace_selected_text = QCheckBox("Paste result back")
        self.replace_selected_text.setChecked(
            self.replace_selected_text_enabled
        )
        self.replace_selected_text.setToolTip(
            "After ChatGPT responds, replace the selected text in its original "
            "editable box. Requires automatic submission."
        )
        self.replace_selected_text.setAccessibleDescription(
            self.replace_selected_text.toolTip()
        )
        self.guided_drafting = QCheckBox("Guided questions")
        self.guided_drafting.setChecked(self.guided_drafting_enabled)
        self.guided_drafting.setToolTip(
            "Allow supported writing actions to ask concise questions when "
            "important context is missing."
        )
        self.guided_drafting.setAccessibleDescription(
            self.guided_drafting.toolTip()
        )
        self.temporary_chat = QCheckBox("Turn on temporary chat")
        self.temporary_chat.setChecked(self.temporary_chat_enabled)
        self.temporary_chat.setToolTip(
            "Open a top-level Temporary Chat. Temporary chats cannot be used "
            "inside a ChatGPT Project, so the action's configured Project is "
            "skipped."
        )
        self.temporary_chat.setAccessibleDescription(
            self.temporary_chat.toolTip()
        )
        option_row = QHBoxLayout()
        option_row.addWidget(self.natural_voice)
        option_row.addStretch(1)
        option_row.addWidget(self.guided_drafting)
        option_row.addStretch(1)
        option_row.addWidget(self.auto_submit)
        options_layout.addLayout(option_row)
        temporary_row = QHBoxLayout()
        temporary_row.addWidget(self.temporary_chat)
        temporary_row.addStretch(1)
        temporary_row.addWidget(self.replace_selected_text)
        options_layout.addLayout(temporary_row)
        self.setTabOrder(self.search, self.list)
        self.setTabOrder(self.list, self.send_selected_action)
        self.setTabOrder(self.send_selected_action, self.options_toggle)
        self.setTabOrder(self.options_toggle, self.natural_voice)
        self.setTabOrder(self.natural_voice, self.guided_drafting)
        self.setTabOrder(self.guided_drafting, self.auto_submit)
        self.setTabOrder(self.auto_submit, self.temporary_chat)
        self.setTabOrder(self.temporary_chat, self.replace_selected_text)
        self.setTabOrder(self.replace_selected_text, self.close_button)

        self.output_menu = QMenu(self)
        length_menu = self.output_menu.addMenu("Resulting text length")
        self.length_menu_action = length_menu.menuAction()
        self.length_action_labels = dict(RESULTING_TEXT_LENGTH_OPTIONS)
        self.length_actions = {}
        for value, label in RESULTING_TEXT_LENGTH_OPTIONS:
            action = length_menu.addAction(label)
            action.setData(value)
            action.triggered.connect(
                lambda _checked=False, selected=value: (
                    self._resulting_text_length_selected(selected)
                )
            )
            self.length_actions[value] = action

        formatting_menu = self.output_menu.addMenu("Formatting")
        self.formatting_menu_action = formatting_menu.menuAction()
        self.formatting_action_labels = dict(
            RESULTING_TEXT_FORMATTING_OPTIONS
        )
        self.formatting_actions = {}
        for value, label in RESULTING_TEXT_FORMATTING_OPTIONS:
            action = formatting_menu.addAction(label)
            action.setData(value)
            action.triggered.connect(
                lambda _checked=False, selected=value: (
                    self._resulting_text_formatting_selected(selected)
                )
            )
            self.formatting_actions[value] = action

        title_subject_menu = self.output_menu.addMenu("Title or subject")
        self.title_subject_menu_action = title_subject_menu.menuAction()
        self.title_subject_action_labels = dict(TITLE_SUBJECT_OPTIONS)
        self.title_subject_actions = {}
        for value, label in TITLE_SUBJECT_OPTIONS:
            action = title_subject_menu.addAction(label)
            action.setData(value)
            action.triggered.connect(
                lambda _checked=False, selected=value: (
                    self._title_subject_selected(selected)
                )
            )
            self.title_subject_actions[value] = action

        writing_block_menu = self.output_menu.addMenu(
            "Copyable writing block"
        )
        self.writing_block_menu_action = writing_block_menu.menuAction()
        self.writing_block_action_labels = {
            False: "Off",
            True: "On",
        }
        self.writing_block_actions = {}
        for enabled, label in self.writing_block_action_labels.items():
            action = writing_block_menu.addAction(label)
            action.setData(enabled)
            action.triggered.connect(
                lambda _checked=False, selected=enabled: (
                    self._writing_block_selected(selected)
                )
            )
            self.writing_block_actions[enabled] = action
        self.output_summary = QLabel()
        self.output_summary.setObjectName("hint")
        self.output_button = QPushButton("Remembered output")
        self.output_button.setMenu(self.output_menu)
        self.output_button.setToolTip(
            "Configure resulting text length, formatting, an optional title "
            "or subject line, and writing blocks."
        )
        self.set_resulting_text_length(self.resulting_text_length_value)
        self.set_resulting_text_formatting(
            self.resulting_text_formatting_value
        )
        self.set_writing_block_enabled(self.writing_block_enabled)
        self.set_title_subject(self.title_subject_value)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_summary)
        output_row.addStretch(1)
        output_row.addWidget(self.output_button)
        options_layout.addLayout(output_row)

        self.guidance_menu = QMenu(self)
        editing_menu = self.guidance_menu.addMenu("Editing strength")
        self.editing_menu_action = editing_menu.menuAction()
        self.editing_action_labels = dict(EDITING_STRENGTH_OPTIONS)
        self.editing_actions = {}
        for value, label in EDITING_STRENGTH_OPTIONS:
            action = editing_menu.addAction(label)
            action.setData(value)
            action.triggered.connect(
                lambda _checked=False, selected=value: (
                    self._editing_strength_selected(selected)
                )
            )
            self.editing_actions[value] = action

        preserve_menu = self.guidance_menu.addMenu(
            "Preserve facts and specifics"
        )
        self.preserve_menu_action = preserve_menu.menuAction()
        self.preserve_action_labels = {
            False: "Off",
            True: "On",
        }
        self.preserve_actions = {}
        for enabled, label in self.preserve_action_labels.items():
            action = preserve_menu.addAction(label)
            action.setData(enabled)
            action.triggered.connect(
                lambda _checked=False, selected=enabled: (
                    self._preserve_facts_selected(selected)
                )
            )
            self.preserve_actions[enabled] = action

        audience_menu = self.guidance_menu.addMenu("Recipient or audience")
        self.audience_menu_action = audience_menu.menuAction()
        self.audience_action_labels = dict(RECIPIENT_AUDIENCE_OPTIONS)
        self.audience_actions = {}
        for value, label in RECIPIENT_AUDIENCE_OPTIONS:
            action = audience_menu.addAction(label)
            action.setData(value)
            action.triggered.connect(
                lambda _checked=False, selected=value: (
                    self._recipient_audience_selected(selected)
                )
            )
            self.audience_actions[value] = action

        alternatives_menu = self.guidance_menu.addMenu(
            "Number of alternatives"
        )
        self.alternatives_menu_action = alternatives_menu.menuAction()
        self.alternative_action_labels = {
            1: "One result",
            2: "Two alternatives",
            3: "Three alternatives",
        }
        self.alternative_actions = {}
        for count, label in self.alternative_action_labels.items():
            action = alternatives_menu.addAction(label)
            action.setData(count)
            action.triggered.connect(
                lambda _checked=False, selected=count: (
                    self._alternative_count_selected(selected)
                )
            )
            self.alternative_actions[count] = action

        self.guidance_summary = QLabel()
        self.guidance_summary.setObjectName("hint")
        self.guidance_button = QPushButton("Change this request")
        self.guidance_button.setMenu(self.guidance_menu)
        self.guidance_button.setToolTip(
            "Choose editing strength, factual protection, and the intended "
            "recipient or audience, or request two or three alternatives."
        )
        self.set_editing_strength(self.editing_strength_value)
        self.set_preserve_facts_enabled(self.preserve_facts_enabled)
        self.set_recipient_audience(self.recipient_audience_value)
        self.set_alternative_count(self.alternative_count_value)
        guidance_row = QHBoxLayout()
        guidance_row.addWidget(self.guidance_summary)
        guidance_row.addStretch(1)
        guidance_row.addWidget(self.guidance_button)
        options_layout.addLayout(guidance_row)

        additional_label = QLabel(
            "This request: intent or additional context (optional)"
        )
        additional_label.setObjectName("hint")
        options_layout.addWidget(additional_label)
        self.additional_information = QPlainTextEdit()
        self.additional_information.setPlaceholderText(
            "e.g. Make clear that I can collect on Friday"
        )
        self.additional_information.setToolTip(
            "Add your desired outcome, relevant context, constraints, or a "
            "specific point to include. It will be separated from the source "
            "text and sent to ChatGPT as part of the prompt."
        )
        self.additional_information.setMinimumHeight(50)
        self.additional_information.setMaximumHeight(62)
        options_layout.addWidget(self.additional_information)

        custom_label = QLabel("Or use a one-off instruction")
        custom_label.setObjectName("hint")
        options_layout.addWidget(custom_label)

        custom_row = QHBoxLayout()
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("e.g. Make this more diplomatic")
        self.custom_send = QPushButton("Use instruction")
        self.custom_send.setDefault(False)
        self.custom_send.setEnabled(False)
        self.custom_send.setToolTip(
            "Start the request using the one-off instruction entered here."
        )
        custom_row.addWidget(self.custom, 1)
        custom_row.addWidget(self.custom_send)
        options_layout.addLayout(custom_row)

        self.search.textChanged.connect(self.refresh)
        self.search.returnPressed.connect(self._run_current)
        self.custom.returnPressed.connect(self._run_custom)
        self.custom_send.clicked.connect(self._run_custom)
        self.custom.textChanged.connect(self._custom_text_changed)
        self.close_button.clicked.connect(self.hide)
        self.list.itemClicked.connect(self._open_folder_item)
        self.list.itemDoubleClicked.connect(self._run_action_item)
        self.list.currentItemChanged.connect(
            self._selected_action_changed
        )
        self.send_selected_action.clicked.connect(self._run_current)
        self.options_toggle.toggled.connect(self._set_options_expanded)
        self.natural_voice.toggled.connect(self._natural_voice_toggled)
        self.auto_submit.toggled.connect(self._auto_submit_toggled)
        self.replace_selected_text.toggled.connect(
            self._replace_selected_text_toggled
        )
        self.temporary_chat.toggled.connect(self._temporary_chat_toggled)
        self.guided_drafting.toggled.connect(self._guided_drafting_toggled)
        self.setTabOrder(self.replace_selected_text, self.custom)
        self.setTabOrder(self.custom, self.custom_send)
        self.setTabOrder(self.custom_send, self.close_button)
        for drag_handle in self._drag_handles:
            drag_handle.installEventFilter(self)
            drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        app = QApplication.instance()
        if app is not None:
            app.styleHints().colorSchemeChanged.connect(
                self._system_colour_scheme_changed
            )
            app.paletteChanged.connect(self._system_appearance_changed)
        self._apply_style()
        self._update_replace_selected_text_availability()
        self._set_options_expanded(False)
        self.refresh()

    def set_registry(
        self,
        registry: ActionRegistry,
        home_most_used_count: int | None = None,
        folder_icons: dict[str, str] | None = None,
        natural_voice_enabled: bool | None = None,
        auto_submit_enabled: bool | None = None,
        temporary_chat_enabled: bool | None = None,
        guided_drafting_enabled: bool | None = None,
        resulting_text_length: str | None = None,
        writing_block_enabled: bool | None = None,
        resulting_text_formatting: str | None = None,
        replace_selected_text_enabled: bool | None = None,
        title_subject: str | None = None,
    ) -> None:
        self.registry = registry
        if home_most_used_count is not None:
            self.home_most_used_count = home_most_used_count
        if folder_icons is not None:
            self.folder_icons = dict(folder_icons)
        if natural_voice_enabled is not None:
            self.set_natural_voice_enabled(natural_voice_enabled)
        if auto_submit_enabled is not None:
            self.set_auto_submit_enabled(auto_submit_enabled)
        if temporary_chat_enabled is not None:
            self.set_temporary_chat_enabled(temporary_chat_enabled)
        if guided_drafting_enabled is not None:
            self.set_guided_drafting_enabled(guided_drafting_enabled)
        if resulting_text_length is not None:
            self.set_resulting_text_length(resulting_text_length)
        if writing_block_enabled is not None:
            self.set_writing_block_enabled(writing_block_enabled)
        if resulting_text_formatting is not None:
            self.set_resulting_text_formatting(resulting_text_formatting)
        if replace_selected_text_enabled is not None:
            self.set_replace_selected_text_enabled(
                replace_selected_text_enabled
            )
        if title_subject is not None:
            self.set_title_subject(title_subject)
        self.refresh()

    def set_natural_voice_enabled(self, enabled: bool) -> None:
        self.natural_voice_enabled = enabled
        self.natural_voice.blockSignals(True)
        self.natural_voice.setChecked(enabled)
        self.natural_voice.blockSignals(False)

    def _natural_voice_toggled(self, enabled: bool) -> None:
        self.natural_voice_enabled = enabled
        self.natural_voice_changed.emit(enabled)

    def set_auto_submit_enabled(self, enabled: bool) -> None:
        self.auto_submit_enabled = enabled
        self.auto_submit.blockSignals(True)
        self.auto_submit.setChecked(enabled)
        self.auto_submit.blockSignals(False)
        self._update_replace_selected_text_availability()

    def set_replace_selected_text_enabled(self, enabled: bool) -> None:
        self.replace_selected_text_enabled = enabled
        self.replace_selected_text.blockSignals(True)
        self.replace_selected_text.setChecked(enabled)
        self.replace_selected_text.blockSignals(False)

    def set_source_is_editable(self, editable: bool) -> None:
        self.source_is_editable = editable
        self._update_replace_selected_text_availability()

    def set_source_context(
        self,
        source_app: str,
        decision: ReturnDecision,
        effective: EffectiveApplicationProfile | None = None,
        selected_text: str = "",
    ) -> None:
        # A new capture should open at its best suggestion rather than retain
        # the row selected for the previous capture (or initial empty state).
        self.list.setCurrentRow(-1)
        self.suggestion_context = classify_suggestion_context(
            selected_text,
            source_app,
        )
        self.suggestion_context_label.setText(
            "Local suggestions use: " + self.suggestion_context.summary
        )
        self.suggestion_context_label.setAccessibleDescription(
            "Only the application, text type, and word-count band are kept "
            "for ranking. Selected text is not stored or transmitted."
        )
        self.suggestion_context_label.show()
        self.application_overridden_fields = (
            effective.overridden_fields if effective is not None else frozenset()
        )
        self._source_profile_note = (
            f" \u00b7 {len(self.application_overridden_fields)} application default"
            + ("s" if len(self.application_overridden_fields) != 1 else "")
            if self.application_overridden_fields
            else ""
        )
        self._apply_return_decision(decision)
        if effective is not None:
            self.set_natural_voice_enabled(effective.natural_voice_enabled)
            self.set_auto_submit_enabled(effective.auto_submit_enabled)
            self.set_temporary_chat_enabled(effective.temporary_chat_enabled)
            self.set_guided_drafting_enabled(
                effective.guided_drafting_enabled
            )
            self.set_resulting_text_length(effective.resulting_text_length)
            self.set_resulting_text_formatting(
                effective.resulting_text_formatting
            )
            self.set_title_subject(effective.title_subject)
            self.set_writing_block_enabled(effective.writing_block_enabled)
            self.application_editing_strength_default = (
                effective.editing_strength
            )
            self.application_preserve_facts_default = effective.preserve_facts
            self.application_audience_default = effective.recipient_audience
            self.natural_voice.setEnabled(
                "natural_voice" not in self.application_overridden_fields
            )
            self.auto_submit.setEnabled(
                "auto_submit" not in self.application_overridden_fields
            )
            self.temporary_chat.setEnabled(
                "temporary_chat" not in self.application_overridden_fields
            )
            self.guided_drafting.setEnabled(
                "guided_drafting" not in self.application_overridden_fields
            )
            self.output_button.setEnabled(
                not self.application_overridden_fields.intersection(
                    {
                        "resulting_text_length",
                        "resulting_text_formatting",
                        "title_subject",
                        "writing_block",
                    }
                )
            )
        self._update_replace_selected_text_availability()

    def set_action_context(self, decision: ReturnDecision) -> None:
        """Update the destination shown after an action is highlighted."""

        self._apply_return_decision(decision)
        self._update_replace_selected_text_availability()

    def _apply_return_decision(self, decision: ReturnDecision) -> None:
        self.application_policy_override = decision.overridden
        self.action_result_policy_lock = decision.action_policy_locked
        self.source_context.setText(
            f"Result: {decision.summary}{self._source_profile_note}"
        )
        self.source_context.setAccessibleDescription(
            decision.fallback_reason or decision.summary
        )
        self.source_context.show()
        self.replace_selected_text.blockSignals(True)
        self.replace_selected_text.setChecked(decision.replace_selection)
        self.replace_selected_text.blockSignals(False)
        if decision.purpose_safe_review:
            label = "Paste result back (disabled for this action)"
            tooltip = (
                "This action produces analysis, extracted information, or "
                "idea development rather than replacement prose. Change its "
                "Result handling in Configuration > Writing actions to "
                "override the safe review behaviour."
            )
        elif decision.action_policy_locked:
            label = "Paste result back (action policy)"
            tooltip = (
                "This action's result policy is configured under "
                "Configuration > Writing actions."
            )
        elif decision.overridden:
            label = "Paste result back (application policy)"
            tooltip = (
                "This application's result policy is configured under "
                "Configuration > Applications."
            )
        else:
            label = "Paste result back"
            tooltip = (
                "After ChatGPT responds, replace the selected text in its "
                "original editable box. Requires automatic submission."
            )
        self.replace_selected_text.setText(label)
        self.replace_selected_text.setToolTip(tooltip)
        self.replace_selected_text.setAccessibleDescription(tooltip)

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _update_replace_selected_text_availability(self) -> None:
        self.replace_selected_text.setEnabled(
            not self.application_policy_override
            and not self.action_result_policy_lock
            and self.auto_submit_enabled
            and self.source_is_editable
        )

    def set_guided_drafting_enabled(self, enabled: bool) -> None:
        self.guided_drafting_enabled = enabled
        self.guided_drafting.blockSignals(True)
        self.guided_drafting.setChecked(enabled)
        self.guided_drafting.blockSignals(False)

    def set_temporary_chat_enabled(self, enabled: bool) -> None:
        self.temporary_chat_enabled = enabled
        self.temporary_chat.blockSignals(True)
        self.temporary_chat.setChecked(enabled)
        self.temporary_chat.blockSignals(False)

    def set_resulting_text_length(self, value: str) -> None:
        selected = value if value in self.length_actions else "default"
        self.resulting_text_length_value = selected
        self._mark_selected_output_action(
            self.length_actions,
            self.length_action_labels,
            selected,
        )
        self.length_menu_action.setText(
            "Resulting text length: "
            f"{self.length_action_labels[selected]}"
        )
        self._update_output_summary()

    def set_writing_block_enabled(self, enabled: bool) -> None:
        self.writing_block_enabled = enabled
        self._mark_selected_output_action(
            self.writing_block_actions,
            self.writing_block_action_labels,
            enabled,
        )
        self.writing_block_menu_action.setText(
            f"Copyable writing block: {'On' if enabled else 'Off'}"
        )
        self._update_output_summary()

    def set_resulting_text_formatting(self, value: str) -> None:
        selected = value if value in self.formatting_actions else "default"
        self.resulting_text_formatting_value = selected
        self._mark_selected_output_action(
            self.formatting_actions,
            self.formatting_action_labels,
            selected,
        )
        self.formatting_menu_action.setText(
            f"Formatting: {self.formatting_action_labels[selected]}"
        )
        self._update_output_summary()

    def set_title_subject(self, value: str) -> None:
        selected = value if value in self.title_subject_actions else "none"
        self.title_subject_value = selected
        self._mark_selected_output_action(
            self.title_subject_actions,
            self.title_subject_action_labels,
            selected,
        )
        self.title_subject_menu_action.setText(
            "Title or subject: "
            f"{self.title_subject_action_labels[selected]}"
        )
        self._update_output_summary()

    def set_editing_strength(self, value: str) -> None:
        selected = value if value in self.editing_actions else "default"
        self.editing_strength_value = selected
        self._mark_selected_output_action(
            self.editing_actions,
            self.editing_action_labels,
            selected,
        )
        self.editing_menu_action.setText(
            f"Editing strength: {self.editing_action_labels[selected]}"
        )
        self._update_guidance_summary()

    def set_preserve_facts_enabled(self, enabled: bool) -> None:
        self.preserve_facts_enabled = enabled
        self._mark_selected_output_action(
            self.preserve_actions,
            self.preserve_action_labels,
            enabled,
        )
        self.preserve_menu_action.setText(
            f"Preserve facts and specifics: {'On' if enabled else 'Off'}"
        )
        self._update_guidance_summary()

    def set_recipient_audience(self, value: str) -> None:
        selected = (
            value if value in self.audience_actions else "unspecified"
        )
        self.recipient_audience_value = selected
        self._mark_selected_output_action(
            self.audience_actions,
            self.audience_action_labels,
            selected,
        )
        self.audience_menu_action.setText(
            "Recipient or audience: "
            f"{self.audience_action_labels[selected]}"
        )
        self._update_guidance_summary()

    def set_alternative_count(self, value: int) -> None:
        selected = value if value in self.alternative_actions else 1
        self.alternative_count_value = selected
        self._mark_selected_output_action(
            self.alternative_actions,
            self.alternative_action_labels,
            selected,
        )
        self.alternatives_menu_action.setText(
            "Number of alternatives: "
            f"{self.alternative_action_labels[selected]}"
        )
        self._update_guidance_summary()

    @staticmethod
    def _mark_selected_output_action(
        actions: dict,
        labels: dict,
        selected,
    ) -> None:
        for value, action in actions.items():
            is_selected = value == selected
            action.setText(
                f"{labels[value]}  (selected)"
                if is_selected
                else labels[value]
            )
            font = action.font()
            font.setBold(is_selected)
            action.setFont(font)

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self._apply_style()

    def _system_colour_scheme_changed(self, colour_scheme) -> None:
        if self.theme == "auto":
            self._apply_style()

    def _system_appearance_changed(self, *args) -> None:
        self._apply_style()

    def _set_options_expanded(self, expanded: bool) -> None:
        """Give the action chooser priority until extra controls are needed."""

        self.options_panel.setVisible(expanded)
        if expanded:
            self.options_toggle.setText("Hide request options")
            self.options_toggle.setAccessibleName(
                "Hide request options and custom instruction"
            )
            self.options_toggle.setToolTip(
                "Hide the secondary request controls to give the writing "
                "action list more space."
            )
        else:
            self.options_toggle.setText(
                "Request options and custom instruction"
            )
            self.options_toggle.setAccessibleName(
                "Show request options and custom instruction"
            )
            self.options_toggle.setToolTip(
                "Show remembered choices, output and guidance controls, "
                "additional context, and the one-off instruction field."
            )
        self.updateGeometry()

    def _auto_submit_toggled(self, enabled: bool) -> None:
        self.auto_submit_enabled = enabled
        self._update_replace_selected_text_availability()
        self.auto_submit_changed.emit(enabled)

    def _replace_selected_text_toggled(self, enabled: bool) -> None:
        self.replace_selected_text_enabled = enabled
        self.replace_selected_text_changed.emit(enabled)

    def _guided_drafting_toggled(self, enabled: bool) -> None:
        self.guided_drafting_enabled = enabled
        self.guided_drafting_changed.emit(enabled)

    def _temporary_chat_toggled(self, enabled: bool) -> None:
        self.temporary_chat_enabled = enabled
        self.temporary_chat_changed.emit(enabled)

    def _resulting_text_length_selected(self, value: str) -> None:
        self.set_resulting_text_length(value)
        self.resulting_text_length_changed.emit(value)

    def _writing_block_selected(self, enabled: bool) -> None:
        self.set_writing_block_enabled(enabled)
        self.writing_block_changed.emit(enabled)

    def _resulting_text_formatting_selected(self, value: str) -> None:
        self.set_resulting_text_formatting(value)
        self.resulting_text_formatting_changed.emit(value)

    def _title_subject_selected(self, value: str) -> None:
        self.set_title_subject(value)
        self.title_subject_changed.emit(value)

    def _editing_strength_selected(self, value: str) -> None:
        self.set_editing_strength(value)

    def _preserve_facts_selected(self, enabled: bool) -> None:
        self.set_preserve_facts_enabled(enabled)

    def _recipient_audience_selected(self, value: str) -> None:
        self.audience_explicitly_selected = True
        self.set_recipient_audience(value)

    def _custom_text_changed(self, text: str) -> None:
        self.custom_send.setEnabled(bool(text.strip()))
        if text.strip() and not self.audience_explicitly_selected:
            self.set_recipient_audience(
                self.application_audience_default
            )

    def _alternative_count_selected(self, value: int) -> None:
        self.set_alternative_count(value)

    def _update_output_summary(self) -> None:
        parts: list[str] = []
        if self.resulting_text_length_value != "default":
            parts.append(
                dict(RESULTING_TEXT_LENGTH_OPTIONS)[
                    self.resulting_text_length_value
                ]
            )
        formatting_labels = {
            "plain": "No added formatting",
            "formatted": "Helpful formatting",
        }
        formatting = formatting_labels.get(
            self.resulting_text_formatting_value
        )
        if formatting:
            parts.append(formatting)
        if self.writing_block_enabled:
            parts.append("Writing block")
        title_subject_labels = {
            "automatic": "Automatic title/subject",
            "title": "Include title",
            "subject": "Include subject",
        }
        title_subject = title_subject_labels.get(self.title_subject_value)
        if title_subject:
            parts.append(title_subject)
        summary = " · ".join(parts) if parts else "ChatGPT defaults"
        self.output_summary.setText(f"Remembered output: {summary}")

    def _update_guidance_summary(self) -> None:
        parts = [
            self.editing_action_labels[self.editing_strength_value],
            (
                "Preserve specifics"
                if self.preserve_facts_enabled
                else "Specifics unprotected"
            ),
        ]
        parts.append(
            "No audience"
            if self.recipient_audience_value == "unspecified"
            else self.audience_action_labels[
                self.recipient_audience_value
            ]
        )
        if self.alternative_count_value > 1:
            parts.append(
                self.alternative_action_labels[self.alternative_count_value]
            )
        self.guidance_summary.setText(
            "This request: " + " · ".join(parts)
        )

    def show_at_cursor(self) -> None:
        self.current_folder = ""
        self.search.clear()
        self.custom.clear()
        self.additional_information.clear()
        self.options_toggle.setChecked(False)
        self.set_editing_strength(self.application_editing_strength_default)
        self.set_preserve_facts_enabled(
            self.application_preserve_facts_default
        )
        self.audience_explicitly_selected = False
        self.set_recipient_audience(self.application_audience_default)
        self.set_alternative_count(1)
        self.refresh()
        cursor = QCursor.pos()
        screen = self.screen()
        if screen is None or not screen.geometry().contains(cursor):
            from PySide6.QtGui import QGuiApplication

            screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        geometry = screen.availableGeometry()
        x = min(cursor.x() + 12, geometry.right() - self.width())
        y = min(cursor.y() + 12, geometry.bottom() - self.height())
        x = max(geometry.left(), x)
        y = max(geometry.top(), y)
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus(Qt.FocusReason.PopupFocusReason)

    def refresh(self) -> None:
        current_key = None
        if self.list.currentItem():
            current_key = (
                self.list.currentItem().data(self.ITEM_KIND_ROLE),
                self.list.currentItem().data(Qt.ItemDataRole.UserRole),
            )
        self.list.clear()
        selected_row = -1
        query = self.search.text().strip()
        if query:
            self.location.setText("Search results from all folders")
            self.location.show()
            for action in self.registry.search(
                query,
                context=self.suggestion_context,
            ):
                label = self._action_label(action, show_folder=True)
                item = self._action_item(action, label)
                self.list.addItem(item)
        else:
            if self.current_folder:
                self.location.setText(
                    " / ".join(("All actions", *self.current_folder.split("/")))
                )
                self.location.show()
                self.list.addItem(self._back_item())
                for folder_name, folder_path in self._child_folders():
                    self.list.addItem(self._folder_item(folder_name, folder_path))
                for action in self._actions_in_current_folder():
                    self.list.addItem(
                        self._action_item(action, self._action_label(action))
                    )
            else:
                self.location.hide()
                self._populate_home()

        for row in range(self.list.count()):
            item = self.list.item(row)
            item_key = (
                item.data(self.ITEM_KIND_ROLE),
                item.data(Qt.ItemDataRole.UserRole),
            )
            if item_key == current_key:
                selected_row = row
                break
        if selected_row < 0:
            selected_row = self._first_selectable_row()
        if selected_row >= 0:
            self.list.setCurrentRow(selected_row)

    def _populate_home(self) -> None:
        configured = self.registry.configured()
        direct = [action for action in configured if action.show_on_home]
        direct_ids = {action.id for action in direct}
        suggestions = (
            self.registry.suggest(
                self.suggestion_context,
                limit=4,
                exclude_ids=direct_ids,
            )
            if self.suggestion_context is not None
            else []
        )
        self.suggestion_reasons = {
            suggestion.action.id: suggestion.reasons
            for suggestion in suggestions
        }
        suggested_actions = [suggestion.action for suggestion in suggestions]
        suggested_ids = {action.id for action in suggested_actions}
        most_used = self.registry.most_used(
            self.home_most_used_count,
            exclude_ids=direct_ids | suggested_ids,
        )
        most_used_ids = {action.id for action in most_used}
        folders = self._child_folders()
        root_actions = [
            action
            for action in self.registry.search("")
            if not action.folder
            and action.id not in direct_ids
            and action.id not in suggested_ids
            and action.id not in most_used_ids
        ]

        self._add_action_section("Suggested", suggested_actions)
        self._add_action_section("Direct actions", direct)
        self._add_action_section("Most used", most_used)
        if folders:
            self.list.addItem(self._section_item("Folders"))
            for folder_name, folder_path in folders:
                self.list.addItem(self._folder_item(folder_name, folder_path))
        self._add_action_section("Other actions", root_actions)

    def _add_action_section(self, title: str, actions) -> None:
        if not actions:
            return
        self.list.addItem(self._section_item(title))
        for action in actions:
            self.list.addItem(
                self._action_item(action, self._action_label(action))
            )

    def _section_item(self, title: str) -> QListWidgetItem:
        item = QListWidgetItem(title.upper())
        item.setData(self.ITEM_KIND_ROLE, "header")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(QColor("#7f8796"))
        item.setSizeHint(QSize(0, 24))
        return item

    def _first_selectable_row(self) -> int:
        for row in range(self.list.count()):
            if self.list.item(row).data(self.ITEM_KIND_ROLE) != "header":
                return row
        return -1

    def _actions_in_current_folder(self):
        return [
            action
            for action in self.registry.search(
                "",
                context=self.suggestion_context,
            )
            if action.folder == self.current_folder
        ]

    def _child_folders(self) -> list[tuple[str, str]]:
        current_parts = tuple(
            part for part in self.current_folder.split("/") if part
        )
        folders: dict[str, str] = {}
        for action in self.registry.configured():
            parts = tuple(part for part in action.folder.split("/") if part)
            if (
                len(parts) <= len(current_parts)
                or parts[: len(current_parts)] != current_parts
            ):
                continue
            child = parts[len(current_parts)]
            full_path = "/".join((*current_parts, child))
            folders.setdefault(child, full_path)
        return list(folders.items())

    def _folder_item(self, name: str, path: str) -> QListWidgetItem:
        icon = (
            self.icon_provider.folder_icon_for(
                path,
                self.folder_icons.get(path, ""),
            )
            if self.icon_provider is not None
            else self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        )
        item = QListWidgetItem(
            icon,
            f"{name}  ›",
        )
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(self.ITEM_KIND_ROLE, "folder")
        item.setToolTip(f"Open {name}")
        item.setSizeHint(QSize(0, 48))
        return item

    def _back_item(self) -> QListWidgetItem:
        parent = self.current_folder.rpartition("/")[0]
        item = QListWidgetItem(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack),
            "Back",
        )
        item.setData(Qt.ItemDataRole.UserRole, parent)
        item.setData(self.ITEM_KIND_ROLE, "back")
        item.setSizeHint(QSize(0, 46))
        return item

    def _action_item(self, action, label: str) -> QListWidgetItem:
        item = QListWidgetItem(label)
        if self.icon_provider is not None:
            item.setIcon(self.icon_provider.icon_for(action))
        item.setSizeHint(QSize(0, 48))
        item.setData(Qt.ItemDataRole.UserRole, action.id)
        item.setData(self.ITEM_KIND_ROLE, "action")
        reasons = self.suggestion_reasons.get(action.id, ())
        tooltip = action.instruction
        if reasons:
            tooltip += "\n\nSuggested because: " + "; ".join(reasons) + "."
            item.setData(
                Qt.ItemDataRole.AccessibleDescriptionRole,
                "Suggested because " + ", ".join(reasons),
            )
        item.setToolTip(tooltip)
        return item

    @staticmethod
    def _action_label(action, show_folder: bool = False) -> str:
        label = action.name
        if show_folder and action.folder:
            label = f"{label}    ·    {action.folder.replace('/', ' / ')}"
        if action.hotkey:
            label = f"{label}    {action.hotkey}"
        return label

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() == Qt.Key.Key_F
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.search.setFocus()
            self.search.selectAll()
            event.accept()
            return
        if (
            event.key() == Qt.Key.Key_W
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.hide()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Down and self.search.hasFocus():
            self.list.setFocus()
            first_row = self._first_selectable_row()
            if first_row >= 0:
                self.list.setCurrentRow(first_row)
            event.accept()
            return
        if (
            event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Backspace)
            and self.list.hasFocus()
            and self.current_folder
            and not self.search.text()
        ):
            self.current_folder = self.current_folder.rpartition("/")[0]
            self.refresh()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if watched in self._drag_handles:
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._dragging = True
                self._drag_offset = (
                    event.globalPosition().toPoint()
                    - self.frameGeometry().topLeft()
                )
                for drag_handle in self._drag_handles:
                    drag_handle.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return True
            if event.type() == QEvent.Type.MouseMove and self._dragging:
                if event.buttons() & Qt.MouseButton.LeftButton:
                    self.move(
                        event.globalPosition().toPoint()
                        - self._drag_offset
                    )
                    event.accept()
                    return True
                self._dragging = False
                self._drag_offset = None
                for drag_handle in self._drag_handles:
                    drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._dragging = False
                self._drag_offset = None
                for drag_handle in self._drag_handles:
                    drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
                event.accept()
                return True
        if (
            watched is getattr(self, "list", None)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            self._run_current()
            return True
        return super().eventFilter(watched, event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        if not self.isActiveWindow():
            self.hide()

    def _run_current(self) -> None:
        item = self.list.currentItem()
        if item:
            self._run_item(item)

    def _update_selected_action_button(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None = None,
    ) -> None:
        is_action = bool(
            current is not None
            and current.data(self.ITEM_KIND_ROLE) == "action"
            and current.data(Qt.ItemDataRole.UserRole)
        )
        self.send_selected_action.setEnabled(is_action)
        if not is_action:
            self.send_selected_action.setText("Send selected action")
            return
        self.send_selected_action.setText("Send selected action")

    def _selected_action_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None = None,
    ) -> None:
        self._update_selected_action_button(current, previous)
        if current is None or current.data(self.ITEM_KIND_ROLE) != "action":
            self.action_highlighted.emit("")
            return
        action_id = str(
            current.data(Qt.ItemDataRole.UserRole) or ""
        )
        self.action_highlighted.emit(action_id)
        action = self.registry.get(action_id) if action_id else None
        if action is None:
            return
        if self.audience_explicitly_selected:
            return
        audience = (
            action.recipient_audience
            if action.recipient_audience not in {"", "inherit"}
            else self.application_audience_default
        )
        self.set_recipient_audience(audience)

    def _run_item(self, item: QListWidgetItem) -> None:
        kind = item.data(self.ITEM_KIND_ROLE)
        value = item.data(Qt.ItemDataRole.UserRole)
        if kind in {"folder", "back"}:
            self.current_folder = str(value or "")
            self.refresh()
            self.list.setFocus()
            return
        if kind == "action" and value:
            additional_information = (
                self.additional_information.toPlainText().strip()
            )
            self.hide()
            self.action_requested.emit(
                str(value),
                additional_information,
                self.editing_strength_value,
                self.preserve_facts_enabled,
                self.recipient_audience_value,
                self.alternative_count_value,
            )

    def _open_folder_item(self, item: QListWidgetItem) -> None:
        if item.data(self.ITEM_KIND_ROLE) in {"folder", "back"}:
            self._run_item(item)

    def _run_action_item(self, item: QListWidgetItem) -> None:
        if item.data(self.ITEM_KIND_ROLE) == "action":
            self._run_item(item)

    def _run_custom(self) -> None:
        instruction = self.custom.text().strip()
        if instruction:
            additional_information = (
                self.additional_information.toPlainText().strip()
            )
            self.hide()
            self.custom_requested.emit(
                instruction,
                additional_information,
                self.editing_strength_value,
                self.preserve_facts_enabled,
                self.recipient_audience_value,
                self.alternative_count_value,
            )

    def _apply_style(self) -> None:
        high_contrast = system_high_contrast_enabled()
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            not high_contrast,
        )
        if high_contrast:
            self.setStyleSheet(
                high_contrast_stylesheet()
                + message_box_stylesheet(self.theme)
            )
            return
        if resolve_theme(self.theme) == "light":
            checkmark = str(
                files("promptmeld").joinpath(
                    "resources",
                    "icons",
                    "check-white.svg",
                )
            ).replace("\\", "/")
            self.setStyleSheet(
                """
                QFrame#launcherFrame {
                    background: #ffffff;
                    border: 2px solid #aeb8c6;
                    border-radius: 14px;
                }
                QLabel { color: #202631; }
                QLabel#title { font-size: 18px; font-weight: 650; }
                QLabel#tagline {
                    color: #365fc7;
                    font-size: 11px;
                    font-style: italic;
                }
                QLabel#hint { color: #697381; font-size: 11px; }
                QLabel#breadcrumb {
                    color: #365fc7;
                    font-size: 11px;
                    padding: 0 2px 2px 2px;
                }
                QLineEdit, QPlainTextEdit {
                    color: #202631;
                    background: #f5f7fa;
                    border: 1px solid #c5ccd6;
                    border-radius: 8px;
                    padding: 9px 10px;
                    selection-background-color: #b9ceff;
                }
                QLineEdit:focus, QPlainTextEdit:focus {
                    border-color: #4d72d8;
                }
                QMenu {
                    color: #202631;
                    background: #ffffff;
                    border: 1px solid #c5ccd6;
                    padding: 5px;
                }
                QMenu::item {
                    padding: 7px 26px 7px 12px;
                    border-radius: 4px;
                }
                QMenu::item:selected {
                    color: #173a87;
                    background: #dce7ff;
                }
                QListWidget {
                    color: #202631;
                    background: transparent;
                    border: 0;
                    outline: 0;
                }
                QListWidget::item {
                    border-radius: 7px;
                    padding: 10px 10px;
                }
                QListWidget::item:selected {
                    background: #dce7ff;
                    color: #173a87;
                }
                QPushButton {
                    color: white;
                    background: #315ecb;
                    border: 0;
                    border-radius: 8px;
                    padding: 9px 15px;
                    font-weight: 600;
                }
                QPushButton:hover { background: #244fae; }
                QPushButton:disabled {
                    color: #7a8491;
                    background: #e5e9ef;
                }
                QPushButton#launcherCloseButton {
                    color: #4f5968;
                    background: transparent;
                    border: 1px solid transparent;
                    border-radius: 6px;
                    padding: 0;
                    font-size: 19px;
                    font-weight: 500;
                }
                QPushButton#launcherCloseButton:hover {
                    color: #202631;
                    background: #e8ecf2;
                    border-color: #c5ccd6;
                }
                QPushButton#launcherCloseButton:pressed {
                    background: #dce2ea;
                }
                QCheckBox {
                    color: #202631;
                    spacing: 8px;
                    padding: 2px 1px;
                }
                QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                    border: 1px solid #687585;
                    border-radius: 3px;
                    background: #ffffff;
                }
                QCheckBox::indicator:hover {
                    border-color: #315ecb;
                    background: #f2f5fa;
                }
                QCheckBox::indicator:checked {
                    border-color: #244fae;
                    background: #315ecb;
                    image: url("__CHECKMARK__");
                }
                QCheckBox::indicator:disabled {
                    border-color: #aeb6c0;
                    background: #e7eaee;
                }
                """.replace("__CHECKMARK__", checkmark)
            )
            self.setStyleSheet(
                self.styleSheet() + message_box_stylesheet("light")
            )
            return
        checkmark = str(
            files("promptmeld").joinpath(
                "resources",
                "icons",
                "check-white.svg",
            )
        ).replace("\\", "/")
        self.setStyleSheet(
            """
            QFrame#launcherFrame {
                background: #16181d;
                border: 2px solid #4a505d;
                border-radius: 14px;
            }
            QLabel { color: #e9ebef; }
            QLabel#title { font-size: 18px; font-weight: 650; }
            QLabel#tagline {
                color: #9fb2ef;
                font-size: 11px;
                font-style: italic;
            }
            QLabel#hint { color: #9298a5; font-size: 11px; }
            QLabel#breadcrumb {
                color: #9fb2ef;
                font-size: 11px;
                padding: 0 2px 2px 2px;
            }
            QLineEdit, QPlainTextEdit {
                color: #f4f5f7;
                background: #22252c;
                border: 1px solid #3a3f4a;
                border-radius: 8px;
                padding: 9px 10px;
                selection-background-color: #3e6ae1;
            }
            QLineEdit:focus, QPlainTextEdit:focus {
                border-color: #6d8df2;
            }
            QMenu {
                color: #f4f5f7;
                background: #22252c;
                border: 1px solid #3a3f4a;
                padding: 5px;
            }
            QMenu::item {
                padding: 7px 26px 7px 12px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                color: #ffffff;
                background: #304a91;
            }
            QListWidget {
                color: #e8eaf0;
                background: transparent;
                border: 0;
                outline: 0;
            }
            QListWidget::item {
                border-radius: 7px;
                padding: 10px 10px;
            }
            QListWidget::item:selected {
                background: #304a91;
                color: white;
            }
            QPushButton {
                color: white;
                background: #315ecb;
                border: 0;
                border-radius: 8px;
                padding: 9px 15px;
                font-weight: 600;
            }
            QPushButton:hover { background: #3d6ede; }
            QPushButton:disabled {
                color: #858c98;
                background: #292d34;
            }
            QPushButton#launcherCloseButton {
                color: #b5bbc6;
                background: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 0;
                font-size: 19px;
                font-weight: 500;
            }
            QPushButton#launcherCloseButton:hover {
                color: #ffffff;
                background: #2c3038;
                border-color: #4a505d;
            }
            QPushButton#launcherCloseButton:pressed {
                background: #383d47;
            }
            QCheckBox {
                color: #e9ebef;
                spacing: 8px;
                padding: 2px 1px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #9ba8ba;
                border-radius: 3px;
                background: #20242b;
            }
            QCheckBox::indicator:hover {
                border-color: #9fb2ef;
                background: #292e38;
            }
            QCheckBox::indicator:checked {
                border: 2px solid #ffffff;
                background: #4f7cff;
                image: url("__CHECKMARK__");
            }
            QCheckBox::indicator:checked:hover {
                background: #638cff;
            }
            QCheckBox::indicator:disabled {
                border-color: #59616d;
                background: #25282e;
            }
            """
            .replace("__CHECKMARK__", checkmark)
        )
        self.setStyleSheet(
            self.styleSheet() + message_box_stylesheet("dark")
        )
