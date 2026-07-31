from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPen,
    QPolygonF,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProxyStyle,
    QPushButton,
    QSpinBox,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import display_version
from .config import (
    DEFAULT_FOLDER_ICONS,
    load_default_actions,
    normalize_folder,
    save_actions,
    save_settings,
)
from .branding import APP_NAME, REPOSITORY_URL, TAGLINE
from .icons import ActionIconProvider
from .models import (
    DEFAULT_NATURAL_VOICE_INSTRUCTION,
    PRIMARY_LANGUAGE_OPTIONS,
    RESULTING_TEXT_FORMATTING_OPTIONS,
    RESULTING_TEXT_LENGTH_OPTIONS,
    AppSettings,
    WritingAction,
)
from .paths import AppPaths
from .theme import resolve_theme
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


class BranchArrowStyle(QProxyStyle):
    """Draw only compact folder arrows, never native connector lines."""

    def __init__(self):
        super().__init__()
        self._arrow_colour = QColor("#c9d1e2")

    def set_arrow_colour(self, colour: str) -> None:
        self._arrow_colour = QColor(colour)

    def drawPrimitive(self, element, option, painter, widget=None) -> None:
        if element != QStyle.PrimitiveElement.PE_IndicatorBranch:
            super().drawPrimitive(element, option, painter, widget)
            return
        if not option.state & QStyle.StateFlag.State_Children:
            return

        centre = option.rect.center()
        if option.state & QStyle.StateFlag.State_Open:
            points = QPolygonF(
                (
                    QPointF(centre.x() - 3.0, centre.y() - 1.5),
                    QPointF(centre.x(), centre.y() + 1.5),
                    QPointF(centre.x() + 3.0, centre.y() - 1.5),
                )
            )
        else:
            points = QPolygonF(
                (
                    QPointF(centre.x() - 1.5, centre.y() - 3.0),
                    QPointF(centre.x() + 1.5, centre.y()),
                    QPointF(centre.x() - 1.5, centre.y() + 3.0),
                )
            )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(
            QPen(
                self._arrow_colour,
                1.5,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(points)
        painter.restore()


class HotkeyCaptureEdit(QLineEdit):
    """Capture one supported global-hotkey chord without free-text entry."""

    hotkey_changed = Signal(str)
    capture_started = Signal()
    capture_rejected = Signal(str)

    _MODIFIER_KEYS = {
        int(Qt.Key.Key_Control),
        int(Qt.Key.Key_Alt),
        int(Qt.Key.Key_Shift),
        int(Qt.Key.Key_Meta),
    }
    _NAMED_KEYS = {
        int(Qt.Key.Key_Space): "Space",
        int(Qt.Key.Key_Return): "Enter",
        int(Qt.Key.Key_Enter): "Enter",
        int(Qt.Key.Key_Tab): "Tab",
        int(Qt.Key.Key_Escape): "Escape",
    }

    def __init__(self, hotkey: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Click here, then press a shortcut")
        self.setToolTip(
            "Click this field and press one key together with Ctrl, Alt, "
            "Shift, or the Windows key."
        )
        self.set_hotkey(hotkey)

    def set_hotkey(self, hotkey: str) -> None:
        blocked = self.blockSignals(True)
        self.setText(hotkey)
        self.blockSignals(blocked)

    def clear_hotkey(self) -> None:
        if not self.text():
            return
        self.setText("")
        self.hotkey_changed.emit("")

    def begin_capture(self) -> None:
        QTimer.singleShot(0, self._focus_for_capture)
        self.capture_started.emit()

    def _focus_for_capture(self) -> None:
        self.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.selectAll()

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        key = int(event.key())
        if key in self._MODIFIER_KEYS:
            event.accept()
            return

        modifiers = event.modifiers()
        names: list[str] = []
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            names.append("Ctrl")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            names.append("Alt")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            names.append("Shift")
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            names.append("Win")
        if not names:
            self.capture_rejected.emit(
                "Include Ctrl, Alt, Shift, or the Windows key."
            )
            event.accept()
            return

        key_name = self._key_name(key)
        if key_name is None:
            self.capture_rejected.emit(
                "That key is not supported. Use A-Z, 0-9, F1-F24, "
                "Space, Enter, Tab, or Escape."
            )
            event.accept()
            return

        hotkey = "+".join((*names, key_name))
        self.setText(hotkey)
        self.hotkey_changed.emit(hotkey)
        event.accept()

    @classmethod
    def _key_name(cls, key: int) -> str | None:
        if int(Qt.Key.Key_A) <= key <= int(Qt.Key.Key_Z):
            return chr(ord("A") + key - int(Qt.Key.Key_A))
        if int(Qt.Key.Key_0) <= key <= int(Qt.Key.Key_9):
            return str(key - int(Qt.Key.Key_0))
        if int(Qt.Key.Key_F1) <= key <= int(Qt.Key.Key_F24):
            return f"F{key - int(Qt.Key.Key_F1) + 1}"
        return cls._NAMED_KEYS.get(key)


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
        hotkey_availability: Callable[[str], bool] | None = None,
    ):
        super().__init__(parent)
        self.paths = paths
        self.icon_provider = icon_provider
        self.popup_hotkey = popup_hotkey
        self.hotkey_availability = hotkey_availability
        self.hotkey_editors: dict[str, HotkeyCaptureEdit] = {}
        self.hotkey_status_labels: dict[str, QLabel] = {}
        self.settings = settings
        self.folder_icons = dict(settings.folder_icons if settings else {})
        self.actions = list(actions)
        self.current_row = -1
        self.selected_folder = ""
        self._loading = False
        self._saved_state: tuple | None = None

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
            "Configure writing actions, hotkeys, launcher preferences, and "
            "writing defaults."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        root.addLayout(heading_row)
        root.addWidget(description)

        voice_settings = settings or AppSettings()
        appearance_group = QGroupBox("Appearance")
        appearance_layout = QHBoxLayout(appearance_group)
        appearance_label = QLabel("Colour theme")
        appearance_label.setObjectName("formLabel")
        self.theme = NoWheelComboBox()
        self.theme.addItem("Auto (follow Windows)", "auto")
        self.theme.addItem("Light", "light")
        self.theme.addItem("Dark", "dark")
        selected_theme = self.theme.findData(voice_settings.theme)
        self.theme.setCurrentIndex(max(0, selected_theme))
        appearance_note = QLabel(
            "Auto updates when the Windows app colour mode changes."
        )
        appearance_note.setObjectName("muted")
        appearance_layout.addWidget(appearance_label)
        appearance_layout.addWidget(self.theme)
        appearance_layout.addWidget(appearance_note)
        appearance_layout.addStretch(1)

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

        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout(output_group)
        length_row = QHBoxLayout()
        length_label = QLabel("Resulting text length")
        length_label.setObjectName("formLabel")
        self.resulting_text_length = NoWheelComboBox()
        for value, label in RESULTING_TEXT_LENGTH_OPTIONS:
            self.resulting_text_length.addItem(label, value)
        selected_length = self.resulting_text_length.findData(
            voice_settings.resulting_text_length
        )
        self.resulting_text_length.setCurrentIndex(max(0, selected_length))
        self.resulting_text_length.setMinimumWidth(140)
        self.resulting_text_length.setToolTip(
            "This is also the remembered selection in the launcher. Default "
            "adds no text-length instruction to the prompt."
        )
        length_row.addWidget(length_label)
        length_row.addWidget(self.resulting_text_length)
        length_row.addSpacing(20)
        formatting_label = QLabel("Formatting")
        formatting_label.setObjectName("formLabel")
        self.resulting_text_formatting = NoWheelComboBox()
        for value, label in RESULTING_TEXT_FORMATTING_OPTIONS:
            self.resulting_text_formatting.addItem(label, value)
        selected_formatting = self.resulting_text_formatting.findData(
            voice_settings.resulting_text_formatting
        )
        self.resulting_text_formatting.setCurrentIndex(
            max(0, selected_formatting)
        )
        self.resulting_text_formatting.setMinimumWidth(190)
        self.resulting_text_formatting.setToolTip(
            "Default adds no formatting instruction. The other choices either "
            "prevent new formatting or request restrained helpful formatting."
        )
        length_row.addWidget(formatting_label)
        length_row.addWidget(self.resulting_text_formatting)
        length_row.addStretch(1)
        self.writing_block_default = QCheckBox(
            "Request a copyable writing block when available"
        )
        self.writing_block_default.setChecked(
            voice_settings.writing_block_enabled
        )
        self.writing_block_default.setToolTip(
            "This is also the remembered state of the checkbox in the launcher."
        )
        output_description = QLabel(
            "Length choices add qualitative guidance; Default adds none. "
            "Writing blocks are editable and copyable in ChatGPT, but their "
            "availability depends on ChatGPT."
        )
        output_description.setObjectName("muted")
        output_description.setWordWrap(True)
        output_layout.addLayout(length_row)
        output_layout.addWidget(self.writing_block_default)
        output_layout.addWidget(output_description)

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
        self.temporary_chat_default = QCheckBox(
            "Turn on Temporary Chat by default"
        )
        self.temporary_chat_default.setChecked(
            voice_settings.temporary_chat_enabled
        )
        self.temporary_chat_default.setToolTip(
            "This is also the remembered state of the checkbox in the launcher. "
            "Temporary chats are opened outside ChatGPT Projects."
        )
        self.submission_description = QLabel(
            f"When automatic submission is off, {APP_NAME} pastes the complete "
            "prompt without pressing Enter so you can choose the model or "
            "reasoning level first. Temporary Chat opens a top-level chat and "
            "skips the configured Project because temporary chats cannot be "
            "used inside Projects. ChatGPT may show a one-time explanation "
            "which you must review and confirm yourself."
        )
        self.submission_description.setObjectName("muted")
        self.submission_description.setWordWrap(True)
        submission_layout.addWidget(self.auto_submit_default)
        submission_layout.addWidget(self.temporary_chat_default)
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
        self.branch_arrow_style = BranchArrowStyle()
        self.branch_arrow_style.setParent(self.action_list)
        self.action_list.setStyle(self.branch_arrow_style)
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
        hotkeys_page = QWidget()
        hotkeys_page.setObjectName("settingsPage")
        hotkeys_layout = QVBoxLayout(hotkeys_page)
        hotkeys_layout.setContentsMargins(22, 18, 22, 18)
        hotkeys_layout.setSpacing(12)
        hotkeys_description = QLabel(
            "Click a shortcut field and press the actual key combination. "
            "Each shortcut must contain one key together with Ctrl, Alt, "
            "Shift, or the Windows key."
        )
        hotkeys_description.setObjectName("muted")
        hotkeys_description.setWordWrap(True)
        hotkeys_layout.addWidget(hotkeys_description)
        launcher_hotkey_group = QGroupBox("Launcher shortcut")
        launcher_hotkey_layout = QHBoxLayout(launcher_hotkey_group)
        launcher_hotkey_label = QLabel("Open launcher")
        launcher_hotkey_label.setObjectName("formLabel")
        self.launcher_hotkey_editor = HotkeyCaptureEdit(self.popup_hotkey)
        self.launcher_hotkey_editor.setMinimumWidth(220)
        self.launcher_hotkey_editor.hotkey_changed.connect(
            lambda value: self._hotkey_changed("__popup__", value)
        )
        self.launcher_hotkey_editor.capture_rejected.connect(
            lambda message: self._set_hotkey_status(
                "__popup__",
                "error",
                message,
            )
        )
        self.launcher_hotkey_editor.capture_started.connect(
            lambda: self._set_hotkey_status(
                "__popup__",
                "unchecked",
                "Press the new shortcut now",
            )
        )
        self.change_launcher_hotkey_button = QPushButton("Change")
        self.change_launcher_hotkey_button.setObjectName(
            "changeHotkeyButton"
        )
        self.change_launcher_hotkey_button.setFocusPolicy(
            Qt.FocusPolicy.NoFocus
        )
        self.change_launcher_hotkey_button.setToolTip(
            "Press the actual key combination after choosing Change."
        )
        self.change_launcher_hotkey_button.clicked.connect(
            self.launcher_hotkey_editor.begin_capture
        )
        self.launcher_hotkey_status = QLabel()
        self.launcher_hotkey_status.setObjectName("hotkeyStatus")
        self.launcher_hotkey_status.setWordWrap(True)
        launcher_hotkey_layout.addWidget(launcher_hotkey_label)
        launcher_hotkey_layout.addWidget(self.launcher_hotkey_editor, 1)
        launcher_hotkey_layout.addWidget(
            self.change_launcher_hotkey_button
        )
        launcher_hotkey_layout.addWidget(self.launcher_hotkey_status, 1)
        hotkeys_layout.addWidget(launcher_hotkey_group)
        action_hotkeys_label = QLabel("Writing-action shortcuts")
        action_hotkeys_label.setObjectName("formLabel")
        hotkeys_layout.addWidget(action_hotkeys_label)
        self.hotkey_table = QTableWidget()
        self.hotkey_table.setObjectName("hotkeyTable")
        self.hotkey_table.setColumnCount(3)
        self.hotkey_table.setHorizontalHeaderLabels(
            ("Writing action", "Shortcut", "Status")
        )
        self.hotkey_table.verticalHeader().hide()
        self.hotkey_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.hotkey_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.hotkey_table.setAlternatingRowColors(True)
        hotkey_header = self.hotkey_table.horizontalHeader()
        hotkey_header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        hotkey_header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        hotkey_header.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Fixed,
        )
        hotkey_header.resizeSection(2, 150)
        self.hotkey_table.horizontalHeaderItem(2).setTextAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.hotkey_table.setMinimumWidth(760)
        hotkeys_layout.addWidget(self.hotkey_table, 1)
        hotkey_footer = QHBoxLayout()
        hotkey_note = QLabel(
            "Windows can detect shortcuts registered by other applications, "
            "but not every application reserves shortcuts this way."
        )
        hotkey_note.setObjectName("muted")
        hotkey_note.setWordWrap(True)
        self.check_hotkeys_button = QPushButton("Check availability")
        self.check_hotkeys_button.clicked.connect(
            lambda: self._update_hotkey_statuses(check_windows=True)
        )
        hotkey_footer.addWidget(hotkey_note, 1)
        hotkey_footer.addWidget(self.check_hotkeys_button)
        hotkeys_layout.addLayout(hotkey_footer)
        general_page = QWidget()
        general_page.setObjectName("settingsPage")
        general_layout = QVBoxLayout(general_page)
        general_layout.setContentsMargins(22, 18, 22, 18)
        general_layout.setSpacing(16)
        launcher_group = QGroupBox("Launcher")
        launcher_layout = QVBoxLayout(launcher_group)
        launcher_layout.addLayout(home_row)
        startup_group = QGroupBox("Windows")
        startup_layout = QVBoxLayout(startup_group)
        self.start_with_windows = QCheckBox(
            "Start PromptMeld when I sign in to Windows"
        )
        self.start_with_windows.setChecked(voice_settings.startup_enabled)
        startup_layout.addWidget(self.start_with_windows)
        about_group = QGroupBox(f"About {APP_NAME}")
        about_layout = QVBoxLayout(about_group)
        self.version_label = QLabel(f"Version {display_version()}")
        self.version_label.setObjectName("formLabel")
        about_description = QLabel(
            f"{APP_NAME} is an open-source Windows companion for turning "
            "selected text into focused ChatGPT writing requests."
        )
        about_description.setObjectName("muted")
        about_description.setWordWrap(True)
        self.github_link = QLabel()
        self.github_link.setObjectName("githubLink")
        self.github_link.setOpenExternalLinks(True)
        self.github_link.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        about_layout.addWidget(self.version_label)
        about_layout.addWidget(about_description)
        about_layout.addWidget(self.github_link)
        general_layout.addWidget(appearance_group)
        general_layout.addWidget(launcher_group)
        general_layout.addWidget(startup_group)
        general_layout.addWidget(about_group)
        general_layout.addStretch(1)
        defaults_page = QWidget()
        defaults_page.setObjectName("settingsPage")
        defaults_layout = QVBoxLayout(defaults_page)
        defaults_layout.setContentsMargins(22, 18, 22, 18)
        defaults_layout.setSpacing(12)
        defaults_layout.addWidget(output_group)
        defaults_layout.addWidget(submission_group)
        defaults_layout.addWidget(voice_group)
        defaults_layout.addWidget(guided_group)
        defaults_layout.addStretch(1)
        self.tabs.addTab(general_page, "General")
        self.tabs.addTab(actions_page, "Writing actions")
        self.tabs.addTab(hotkeys_page, "Hotkeys")
        self.tabs.addTab(defaults_page, "Defaults & style")
        self.tabs.currentChanged.connect(self._tab_changed)
        root.addWidget(self.tabs, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Close
        )
        self.close_button = self.buttons.button(
            QDialogButtonBox.StandardButton.Close
        )
        self._set_close_button_dirty(False)
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
            self.natural_voice_mode.currentIndexChanged,
            self.guided_drafting.toggled,
            self.instruction.textChanged,
            self.most_used_count.valueChanged,
            self.primary_language.currentTextChanged,
            self.resulting_text_length.currentIndexChanged,
            self.resulting_text_formatting.currentIndexChanged,
            self.writing_block_default.toggled,
            self.auto_submit_default.toggled,
            self.temporary_chat_default.toggled,
            self.natural_voice_default.toggled,
            self.natural_voice_instruction.textChanged,
            self.guided_drafting_default.toggled,
            self.theme.currentIndexChanged,
            self.start_with_windows.toggled,
        ):
            signal.connect(self._mark_unsaved)

        self.theme.currentIndexChanged.connect(self._apply_style)
        app = QApplication.instance()
        if app is not None:
            app.styleHints().colorSchemeChanged.connect(
                self._system_colour_scheme_changed
            )
        self._apply_style()
        self._refresh_list(0 if self.actions else -1)
        self._saved_state = self._configuration_state()
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
        if hasattr(self, "hotkey_table"):
            self._refresh_hotkey_rows()

    def _tab_changed(self, index: int) -> None:
        if self.tabs.tabText(index) != "Hotkeys":
            return
        self._commit_current()
        self._refresh_hotkey_rows()

    def _refresh_hotkey_rows(self) -> None:
        self.hotkey_table.setRowCount(0)
        self.launcher_hotkey_editor.set_hotkey(self.popup_hotkey)
        self.hotkey_editors = {
            "__popup__": self.launcher_hotkey_editor,
        }
        self.hotkey_status_labels = {
            "__popup__": self.launcher_hotkey_status,
        }
        assigned_actions = [action for action in self.actions if action.hotkey]
        unassigned_actions = [
            action for action in self.actions if not action.hotkey
        ]
        rows = [
            (
                action.id,
                (
                    action.name
                    if action.enabled
                    else f"{action.name} (disabled)"
                ),
                action.hotkey or "",
            )
            for action in (*assigned_actions, *unassigned_actions)
        ]
        self.hotkey_table.setRowCount(len(rows))
        for row, (command_id, name, hotkey) in enumerate(rows):
            command_item = QTableWidgetItem(name)
            action = next(
                action for action in self.actions if action.id == command_id
            )
            if action.folder:
                command_item.setToolTip(f"Folder: {action.folder}")
            self.hotkey_table.setItem(row, 0, command_item)

            shortcut_widget = QWidget()
            shortcut_layout = QHBoxLayout(shortcut_widget)
            shortcut_layout.setContentsMargins(0, 0, 0, 0)
            shortcut_layout.setSpacing(6)
            editor = HotkeyCaptureEdit(hotkey)
            editor.setMinimumWidth(220)
            editor.hotkey_changed.connect(
                lambda value, item_id=command_id: self._hotkey_changed(
                    item_id,
                    value,
                )
            )
            editor.capture_rejected.connect(
                lambda message, item_id=command_id: (
                    self._set_hotkey_status(item_id, "error", message)
                )
            )
            editor.capture_started.connect(
                lambda item_id=command_id: self._set_hotkey_status(
                    item_id,
                    "unchecked",
                    "Press the new shortcut now",
                )
            )
            clear_button = QPushButton("Clear")
            clear_button.setObjectName("clearHotkeyButton")
            clear_button.setToolTip("Remove this action's global shortcut.")
            clear_button.clicked.connect(editor.clear_hotkey)
            change_button = QPushButton("Change")
            change_button.setObjectName("changeHotkeyButton")
            change_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            change_button.setToolTip(
                "Press the actual key combination after choosing Change."
            )
            change_button.clicked.connect(editor.begin_capture)
            shortcut_layout.addWidget(editor, 1)
            shortcut_layout.addWidget(change_button)
            shortcut_layout.addWidget(clear_button)
            self.hotkey_table.setCellWidget(row, 1, shortcut_widget)

            status = QLabel()
            status.setObjectName("hotkeyStatus")
            status.setWordWrap(True)
            status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.hotkey_table.setCellWidget(row, 2, status)
            self.hotkey_editors[command_id] = editor
            self.hotkey_status_labels[command_id] = status
            self.hotkey_table.setRowHeight(row, 46)
        self._update_hotkey_statuses(
            check_windows=self.hotkey_availability is not None
        )

    def _hotkey_changed(self, command_id: str, hotkey: str) -> None:
        if command_id == "__popup__":
            self.popup_hotkey = hotkey
        else:
            self.actions = [
                replace(action, hotkey=hotkey or None)
                if action.id == command_id
                else action
                for action in self.actions
            ]
        self._mark_unsaved()
        self._update_hotkey_statuses(check_windows=True)

    def _update_hotkey_statuses(self, check_windows: bool = False) -> None:
        entries = [
            ("__popup__", "Open launcher", self.popup_hotkey, True),
            *[
                (
                    action.id,
                    action.name,
                    action.hotkey or "",
                    action.enabled,
                )
                for action in self.actions
            ],
        ]
        parsed_entries: dict[str, tuple[int, int]] = {}
        names = {command_id: name for command_id, name, _, _ in entries}

        for command_id, _, hotkey, enabled in entries:
            if not hotkey:
                state = "error" if command_id == "__popup__" else "empty"
                message = (
                    "Required"
                    if command_id == "__popup__"
                    else "Not assigned"
                )
                self._set_hotkey_status(command_id, state, message)
                continue
            try:
                parsed = parse_hotkey(hotkey)
            except HotkeyParseError as exc:
                self._set_hotkey_status(command_id, "error", str(exc))
                continue
            if not enabled:
                self._set_hotkey_status(
                    command_id,
                    "inactive",
                    "Inactive while action is disabled",
                )
                continue
            parsed_entries[command_id] = (
                parsed.modifiers,
                parsed.virtual_key,
            )

        by_chord: dict[tuple[int, int], list[str]] = {}
        for command_id, chord in parsed_entries.items():
            by_chord.setdefault(chord, []).append(command_id)
        clashing: set[str] = set()
        for command_ids in by_chord.values():
            if len(command_ids) < 2:
                continue
            clashing.update(command_ids)
            for command_id in command_ids:
                others = [
                    names[other]
                    for other in command_ids
                    if other != command_id
                ]
                self._set_hotkey_status(
                    command_id,
                    "error",
                    f"Clashes with {', '.join(others)}",
                )

        for command_id, _, hotkey, _ in entries:
            if command_id not in parsed_entries or command_id in clashing:
                continue
            if not check_windows or self.hotkey_availability is None:
                self._set_hotkey_status(
                    command_id,
                    "unchecked",
                    "Not checked",
                )
                continue
            try:
                available = self.hotkey_availability(hotkey)
            except Exception:
                available = False
            self._set_hotkey_status(
                command_id,
                "available" if available else "error",
                (
                    "Available"
                    if available
                    else "Already used by Windows or another app"
                ),
            )

    def _set_hotkey_status(
        self,
        command_id: str,
        state: str,
        message: str,
    ) -> None:
        label = self.hotkey_status_labels.get(command_id)
        if label is None:
            return
        label.setProperty("state", state)
        label.setText(message)
        label.style().unpolish(label)
        label.style().polish(label)

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
        colour = (
            "#202631"
            if resolve_theme(str(self.theme.currentData() or "auto")) == "light"
            else "#ffffff"
        )
        text_format.setForeground(QColor(colour))
        self.instruction.blockSignals(True)
        cursor.mergeCharFormat(text_format)
        cursor.clearSelection()
        self.instruction.setTextCursor(cursor)
        self.instruction.setCurrentCharFormat(text_format)
        self.instruction.blockSignals(False)

    def _mark_unsaved(self, *args) -> None:
        if self._loading or self._saved_state is None:
            return
        is_dirty = self._configuration_state() != self._saved_state
        self._set_close_button_dirty(is_dirty)
        if not is_dirty:
            self._set_save_status("")
        else:
            self._set_save_status("Unsaved changes", saved=False)

    def _set_close_button_dirty(self, is_dirty: bool) -> None:
        if is_dirty:
            self.close_button.setText("Discard changes and close")
            self.close_button.setToolTip(
                "Discard changes made since the last time you chose Save."
            )
        else:
            self.close_button.setText("Close")
            self.close_button.setToolTip("Close configuration.")

    def _configuration_state(self) -> tuple:
        self._commit_current()
        return (
            tuple(self.actions),
            tuple(sorted(self.folder_icons.items())),
            self.popup_hotkey,
            str(self.theme.currentData() or "auto"),
            self.start_with_windows.isChecked(),
            self.most_used_count.value(),
            self.primary_language.currentText().strip(),
            str(self.resulting_text_length.currentData() or "default"),
            str(self.resulting_text_formatting.currentData() or "default"),
            self.writing_block_default.isChecked(),
            self.auto_submit_default.isChecked(),
            self.temporary_chat_default.isChecked(),
            self.natural_voice_default.isChecked(),
            self.natural_voice_instruction.toPlainText().strip(),
            self.guided_drafting_default.isChecked(),
        )

    def _set_save_status(
        self,
        message: str,
        saved: bool | None = None,
    ) -> None:
        self.save_status.setText(message)
        light = (
            resolve_theme(str(self.theme.currentData() or "auto")) == "light"
        )
        colour = (
            "#267245" if light else "#79d69a"
        ) if saved is True else (
            "#8a5a00" if light else "#d9b56d"
        ) if saved is False else (
            "#697381" if light else "#9298a5"
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
                    popup_hotkey=self.popup_hotkey,
                    theme=str(self.theme.currentData() or "auto"),
                    startup_enabled=self.start_with_windows.isChecked(),
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
                    temporary_chat_enabled=(
                        self.temporary_chat_default.isChecked()
                    ),
                    primary_language=(
                        self.primary_language.currentText().strip()
                    ),
                    resulting_text_length=str(
                        self.resulting_text_length.currentData() or "default"
                    ),
                    resulting_text_formatting=str(
                        self.resulting_text_formatting.currentData()
                        or "default"
                    ),
                    writing_block_enabled=(
                        self.writing_block_default.isChecked()
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
        self.folder_icons = folder_icons
        self._saved_state = self._configuration_state()
        self._set_close_button_dirty(False)
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
        try:
            popup = parse_hotkey(self.popup_hotkey)
        except HotkeyParseError as exc:
            raise ValueError(f"Open launcher: {exc}") from exc
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

    def _system_colour_scheme_changed(self, colour_scheme) -> None:
        if str(self.theme.currentData() or "auto") == "auto":
            self._apply_style()

    def _update_about_link(self, light: bool) -> None:
        colour = "#244fae" if light else "#b8c8ff"
        self.github_link.setText(
            f'<a href="{REPOSITORY_URL}" style="color: {colour};">'
            "View PromptMeld on GitHub</a>"
        )

    def _apply_style(self, *args) -> None:
        checkmark = str(
            files("promptmeld").joinpath(
                "resources",
                "icons",
                "check-white.svg",
            )
        ).replace("\\", "/")
        if resolve_theme(str(self.theme.currentData() or "auto")) == "light":
            self.branch_arrow_style.set_arrow_colour("#4b5563")
            self.action_list.viewport().update()
            self.setStyleSheet(
                """
                QDialog { background: #f5f7fa; color: #202631; }
                QLabel { color: #202631; }
                QLabel#settingsTitle {
                    color: #171c25;
                    font-size: 22px;
                    font-weight: 650;
                }
                QLabel#tagline {
                    color: #365fc7;
                    font-size: 12px;
                    font-style: italic;
                }
                QLabel#muted { color: #697381; }
                QLabel#formLabel { color: #3f4855; }
                QLabel#inlineLabel { color: #697381; padding: 0 3px; }
                QLabel#codeValue {
                    color: #244fae;
                    background: #e7edfa;
                    border-radius: 5px;
                    padding: 4px 7px;
                    font-family: Consolas;
                }
                QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
                    color: #202631;
                    background: #ffffff;
                    border: 1px solid #c5ccd6;
                    border-radius: 7px;
                    padding: 7px 9px;
                    selection-background-color: #b9ceff;
                }
                QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {
                    border-color: #4d72d8;
                }
                QPlainTextEdit#actionInstruction {
                    color: #202631;
                    background: #ffffff;
                    border: 1px solid #aeb8c5;
                    font-size: 13px;
                }
                QPlainTextEdit#actionInstruction:focus {
                    color: #202631;
                    background: #ffffff;
                    border-color: #4d72d8;
                }
                QPlainTextEdit#naturalVoiceInstruction {
                    color: #202631;
                    background: #ffffff;
                    border-color: #aeb8c5;
                }
                QComboBox QAbstractItemView {
                    color: #202631;
                    background: #ffffff;
                    selection-background-color: #dce7ff;
                }
                QComboBox QAbstractItemView::item {
                    color: #202631;
                    background: #ffffff;
                    min-height: 28px;
                }
                QComboBox QAbstractItemView::item:selected {
                    color: #102e70;
                    background: #dce7ff;
                }
                QTreeWidget {
                    color: #202631;
                    background: #ffffff;
                    border: 1px solid #cbd2dc;
                    border-radius: 8px;
                    outline: 0;
                    show-decoration-selected: 0;
                }
                QTreeWidget::item {
                    color: #202631;
                    background: transparent;
                    padding: 7px;
                }
                QTreeWidget::item:hover:!selected {
                    color: #173a87;
                    background: #edf3ff;
                }
                QTreeWidget::item:selected {
                    background: #dce7ff;
                    color: #173a87;
                }
                QTableWidget {
                    color: #202631;
                    background: #ffffff;
                    alternate-background-color: #f5f7fa;
                    gridline-color: #d8dee8;
                    border: 1px solid #cbd2dc;
                    border-radius: 8px;
                }
                QTableWidget#hotkeyTable::item {
                    color: #000000;
                }
                QHeaderView::section {
                    color: #344052;
                    background: #e8edf5;
                    border: 0;
                    border-right: 1px solid #cbd2dc;
                    border-bottom: 1px solid #cbd2dc;
                    padding: 7px;
                    font-weight: 600;
                }
                QLabel#hotkeyStatus[state="available"] { color: #18733b; }
                QLabel#hotkeyStatus[state="error"] { color: #a32626; }
                QLabel#hotkeyStatus[state="inactive"],
                QLabel#hotkeyStatus[state="unchecked"],
                QLabel#hotkeyStatus[state="empty"] { color: #667085; }
                QTabWidget::pane {
                    background: #f5f7fa;
                    border: 1px solid #cbd2dc;
                    border-radius: 7px;
                    top: -1px;
                }
                QTabBar::tab {
                    color: #202631;
                    background: #e1e6ec;
                    border: 1px solid #b8c1cc;
                    border-bottom: 0;
                    padding: 9px 16px;
                    min-width: 130px;
                    font-weight: 600;
                }
                QTabBar::tab:selected {
                    color: #173a87;
                    background: #dce7ff;
                }
                QTabBar::tab:hover:!selected { background: #dde3ea; }
                QWidget#settingsPage { background: #f5f7fa; }
                QPushButton {
                    color: #202631;
                    background: #e4e9ef;
                    border: 1px solid #c2cad4;
                    border-radius: 7px;
                    padding: 7px 11px;
                }
                QPushButton:hover { background: #d7dee7; }
                QPushButton:disabled { color: #929aa5; background: #edf0f3; }
                QDialogButtonBox QPushButton {
                    min-width: 82px;
                    color: white;
                    background: #315ecb;
                    border: 0;
                    font-weight: 600;
                }
                QCheckBox { color: #202631; spacing: 8px; }
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
                QGroupBox {
                    color: #3f4855;
                    border: 1px solid #cbd2dc;
                    border-radius: 7px;
                    margin-top: 8px;
                    padding-top: 7px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 4px;
                }
                QFrame { color: #cbd2dc; }
                """.replace(
                    "__CHECKMARK__",
                    checkmark,
                )
            )
            self._set_instruction_colour()
            self._update_about_link(light=True)
            return
        self.branch_arrow_style.set_arrow_colour("#c9d1e2")
        self.action_list.viewport().update()
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
                show-decoration-selected: 0;
            }
            QTreeWidget::item { padding: 7px; }
            QTreeWidget::item:hover:!selected {
                background: #292e38;
                color: #ffffff;
            }
            QTreeWidget::item:selected { background: #304a91; color: white; }
            QTableWidget {
                color: #f6f7fa;
                background: #191c22;
                alternate-background-color: #22262e;
                gridline-color: #343842;
                border: 1px solid #343842;
                border-radius: 8px;
            }
            QTableWidget::item {
                color: #f6f7fa;
                background: transparent;
            }
            QHeaderView::section {
                color: #d7dbe4;
                background: #292c34;
                border: 0;
                border-right: 1px solid #414650;
                border-bottom: 1px solid #414650;
                padding: 7px;
                font-weight: 600;
            }
            QLabel#hotkeyStatus[state="available"] { color: #7ee2a8; }
            QLabel#hotkeyStatus[state="error"] { color: #ff9d9d; }
            QLabel#hotkeyStatus[state="inactive"],
            QLabel#hotkeyStatus[state="unchecked"],
            QLabel#hotkeyStatus[state="empty"] { color: #aeb4c0; }
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
            """.replace(
                "__CHECKMARK__",
                checkmark,
            )
        )
        self._set_instruction_colour()
        self._update_about_link(light=False)
