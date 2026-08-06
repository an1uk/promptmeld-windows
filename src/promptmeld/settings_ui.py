from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from html import escape
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QPainter,
    QPalette,
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
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QMenu,
    QPlainTextEdit,
    QProxyStyle,
    QPushButton,
    QSpinBox,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWizard,
    QWizardPage,
    QWidget,
)

from . import display_version
from .action_packs import (
    ActionPack,
    ActionPackError,
    load_action_pack,
    load_builtin_action_packs,
    merge_action_pack,
    save_action_pack,
)
from .config import (
    DEFAULT_FOLDER_ICONS,
    load_default_actions,
    normalize_folder,
    save_actions,
    save_settings,
)
from .configuration_backup import (
    ConfigurationBackupError,
    create_configuration_backup,
    inspect_configuration_backup,
    reset_configuration_to_defaults,
    restore_configuration_backup,
)
from .branding import APP_NAME, REPOSITORY_URL, TAGLINE
from .icons import ActionIconProvider
from .models import (
    DEFAULT_NATURAL_VOICE_INSTRUCTION,
    EDITING_STRENGTH_OPTIONS,
    PRIMARY_LANGUAGE_OPTIONS,
    PROJECT_NAMING_OPTIONS,
    RECIPIENT_AUDIENCE_OPTIONS,
    RESULTING_TEXT_FORMATTING_OPTIONS,
    RESULTING_TEXT_LENGTH_OPTIONS,
    TITLE_SUBJECT_OPTIONS,
    AppSettings,
    ApplicationProfile,
    CapturedSelection,
    WritingAction,
)
from .paths import AppPaths
from .prompting import PromptBuilder
from .returning import (
    APPLICATION_RESPONSE_WAIT_OPTIONS,
    APPLICATION_RETURN_MODE_OPTIONS,
    APPLICATION_TOGGLE_OPTIONS,
    COMMON_APPLICATIONS,
    application_display_name,
    normalize_application_name,
)
from .theme import (
    apply_message_box_theme,
    high_contrast_stylesheet,
    message_box_stylesheet,
    resolve_theme,
    system_high_contrast_enabled,
)
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


def _hotkey_sort_key(value: str) -> tuple[tuple[int, object], ...]:
    """Return a natural, case-insensitive key for shortcut display order."""

    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", value)
        if part
    )


class ApplicationProfileDialog(QDialog):
    """Dedicated editor for one application's writing and delivery defaults."""

    def __init__(
        self,
        application: str,
        profile: ApplicationProfile,
        overall: AppSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.application = application
        self.appearance_parent = parent
        self.theme = overall.theme
        label = application_display_name(application)
        self.setWindowTitle(f"Configure {label}")
        self.setAccessibleName(f"Application configuration for {label}")
        self.setModal(True)
        self.resize(650, 760)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())
        elif system_high_contrast_enabled():
            self.setStyleSheet(
                high_contrast_stylesheet()
                + message_box_stylesheet(self.theme)
            )
        app = QApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._system_appearance_changed)

        root = QVBoxLayout(self)
        heading = QLabel(f"{label} ({application})")
        heading.setObjectName("settingsTitle")
        root.addWidget(heading)
        explanation = QLabel(
            "Choose only the defaults that should differ for this application. "
            "Inherited options continue to follow Overall defaults. Request "
            "guidance can still be changed in the launcher for one selection."
        )
        explanation.setObjectName("muted")
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        writing_group = QGroupBox("Writing defaults")
        writing_form = QFormLayout(writing_group)
        self.audience = self._combo(
            (("inherit", "Use launcher default"), *RECIPIENT_AUDIENCE_OPTIONS),
            profile.recipient_audience,
            "Default recipient or audience",
        )
        self.primary_language = QLineEdit(profile.primary_language)
        self.primary_language.setPlaceholderText(
            f"Use overall default ({overall.primary_language})"
        )
        self.primary_language.setAccessibleName("Default language")
        self.length = self._combo(
            (("inherit", "Use overall default"), *RESULTING_TEXT_LENGTH_OPTIONS),
            profile.resulting_text_length,
            "Default resulting text length",
        )
        self.formatting = self._combo(
            (
                ("inherit", "Use overall default"),
                *RESULTING_TEXT_FORMATTING_OPTIONS,
            ),
            profile.resulting_text_formatting,
            "Default resulting text formatting",
        )
        self.title_subject = self._combo(
            (("inherit", "Use overall default"), *TITLE_SUBJECT_OPTIONS),
            profile.title_subject,
            "Default title or subject generation",
        )
        self.editing_strength = self._combo(
            (("inherit", "Use launcher default"), *EDITING_STRENGTH_OPTIONS),
            profile.editing_strength,
            "Default editing strength",
        )
        self.preserve_facts = self._combo(
            APPLICATION_TOGGLE_OPTIONS,
            profile.preserve_facts,
            "Preserve facts and specifics",
        )
        self.natural_voice = self._combo(
            APPLICATION_TOGGLE_OPTIONS,
            profile.natural_voice,
            "Preserve natural voice",
        )
        self.guided_drafting = self._combo(
            APPLICATION_TOGGLE_OPTIONS,
            profile.guided_drafting,
            "Guided drafting questions",
        )
        self.writing_block = self._combo(
            APPLICATION_TOGGLE_OPTIONS,
            profile.writing_block,
            "Copyable writing block",
        )
        self._add_row(writing_form, "Recipient or audience", self.audience)
        self._add_row(writing_form, "Language", self.primary_language)
        self._add_row(writing_form, "Result length", self.length)
        self._add_row(writing_form, "Formatting", self.formatting)
        self._add_row(writing_form, "Title or subject", self.title_subject)
        self._add_row(writing_form, "Editing strength", self.editing_strength)
        self._add_row(writing_form, "Preserve facts", self.preserve_facts)
        self._add_row(writing_form, "Natural voice", self.natural_voice)
        self._add_row(writing_form, "Guided questions", self.guided_drafting)
        self._add_row(writing_form, "Writing block", self.writing_block)
        root.addWidget(writing_group)

        delivery_group = QGroupBox("ChatGPT and result handling")
        delivery_form = QFormLayout(delivery_group)
        self.project_name = QLineEdit(profile.project_name)
        self.project_name.setPlaceholderText(
            f"Use overall project base ({overall.project_name})"
        )
        self.project_name.setAccessibleName(
            "Application-specific ChatGPT project base name"
        )
        if overall.project_naming_mode == "single":
            self.project_name.setEnabled(False)
            self.project_name.setToolTip(
                "One-project mode always uses the overall project base name."
            )
        self.auto_submit = self._combo(
            APPLICATION_TOGGLE_OPTIONS,
            profile.auto_submit,
            "Automatic submission",
        )
        self.temporary_chat = self._combo(
            APPLICATION_TOGGLE_OPTIONS,
            profile.temporary_chat,
            "Temporary Chat",
        )
        self.privacy_preview = self._combo(
            APPLICATION_TOGGLE_OPTIONS,
            profile.privacy_preview,
            "Privacy preview and redaction",
        )
        self.privacy_preview.setToolTip(
            "Show the local privacy preview before this application's prompts "
            "are opened in ChatGPT. It can offer reversible placeholders for "
            "possible email addresses, phone numbers, account numbers, and "
            "names. Off sends the prompt without this preview."
        )
        self.return_mode = self._combo(
            APPLICATION_RETURN_MODE_OPTIONS,
            profile.return_mode,
            "Generated result handling",
        )
        self.response_wait = self._combo(
            APPLICATION_RESPONSE_WAIT_OPTIONS,
            profile.response_wait,
            "Maximum response wait",
        )
        self.response_wait_help = self._help_button(
            "ChatGPT may take seconds or several minutes to generate a response, "
            "especially for longer requests, reasoning-heavy tasks, or when the "
            "service is busy. After automatic submission, PromptMeld checks in "
            "the background until this limit is reached, then follows this "
            "application's completion behaviour. This does not make ChatGPT "
            "respond faster and does not stop you using other windows. You can "
            "cancel a wait at any time; indefinite means wait until cancelled.",
            "Explain response wait time",
        )
        response_wait_field = QWidget()
        response_wait_layout = QHBoxLayout(response_wait_field)
        response_wait_layout.setContentsMargins(0, 0, 0, 0)
        response_wait_layout.setSpacing(6)
        response_wait_layout.addWidget(self.response_wait, 1)
        response_wait_layout.addWidget(self.response_wait_help)
        self._add_row(
            delivery_form,
            "Project base override",
            self.project_name,
        )
        self._add_row(delivery_form, "Submit automatically", self.auto_submit)
        self._add_row(delivery_form, "Temporary Chat", self.temporary_chat)
        self._add_row(
            delivery_form,
            "Privacy preview and redaction",
            self.privacy_preview,
        )
        self._add_row(
            delivery_form,
            "When the response completes",
            self.return_mode,
        )
        self._add_row(
            delivery_form,
            "Wait for response",
            response_wait_field,
        )
        root.addWidget(delivery_group)

        note = QLabel(
            "Applying, reviewing, or copying a generated result requires "
            "automatic submission. An indefinite wait remains cancellable. "
            "Unsafe replacement still falls back to copying. "
            "The overall project-naming strategy still applies to any project "
            "base override above; one-project mode ignores this override."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _combo(options, selected: str, accessible_name: str) -> NoWheelComboBox:
        combo = NoWheelComboBox()
        for value, label in options:
            combo.addItem(label, value)
        combo.setCurrentIndex(max(0, combo.findData(selected)))
        combo.setAccessibleName(accessible_name)
        return combo

    @staticmethod
    def _add_row(form: QFormLayout, text: str, field: QWidget) -> None:
        label = QLabel(text)
        label.setObjectName("formLabel")
        label.setBuddy(field)
        form.addRow(label, field)

    @staticmethod
    def _help_button(text: str, accessible_name: str) -> QToolButton:
        button = QToolButton()
        button.setText("?")
        button.setObjectName("helpIcon")
        button.setAccessibleName(accessible_name)
        button.setAccessibleDescription(text)
        button.setToolTip(
            "<qt><table width='340' cellspacing='0' cellpadding='0'>"
            f"<tr><td>{escape(text)}</td></tr></table></qt>"
        )
        button.setAutoRaise(True)
        button.setFixedSize(20, 20)
        button.setCursor(Qt.CursorShape.WhatsThisCursor)
        return button

    def _system_appearance_changed(self, *args) -> None:
        QTimer.singleShot(0, self._sync_appearance)

    def _sync_appearance(self) -> None:
        if system_high_contrast_enabled():
            self.setStyleSheet(
                high_contrast_stylesheet()
                + message_box_stylesheet(self.theme)
            )
        elif self.appearance_parent is not None:
            self.setStyleSheet(self.appearance_parent.styleSheet())
        else:
            self.setStyleSheet("")

    def profile(self) -> ApplicationProfile:
        return ApplicationProfile(
            return_mode=str(self.return_mode.currentData() or "default"),
            recipient_audience=str(
                self.audience.currentData() or "inherit"
            ),
            primary_language=self.primary_language.text().strip(),
            resulting_text_length=str(
                self.length.currentData() or "inherit"
            ),
            resulting_text_formatting=str(
                self.formatting.currentData() or "inherit"
            ),
            title_subject=str(
                self.title_subject.currentData() or "inherit"
            ),
            editing_strength=str(
                self.editing_strength.currentData() or "inherit"
            ),
            preserve_facts=str(
                self.preserve_facts.currentData() or "inherit"
            ),
            natural_voice=str(
                self.natural_voice.currentData() or "inherit"
            ),
            guided_drafting=str(
                self.guided_drafting.currentData() or "inherit"
            ),
            writing_block=str(
                self.writing_block.currentData() or "inherit"
            ),
            auto_submit=str(self.auto_submit.currentData() or "inherit"),
            temporary_chat=str(
                self.temporary_chat.currentData() or "inherit"
            ),
            privacy_preview=str(
                self.privacy_preview.currentData() or "inherit"
            ),
            response_wait=str(
                self.response_wait.currentData() or "inherit"
            ),
            project_name=self.project_name.text().strip(),
        )


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


class FirstRunSetupWizard(QWizard):
    """Short first-run guide with a Windows hotkey availability check."""

    def __init__(
        self,
        popup_hotkey: str,
        hotkey_availability: Callable[[str], bool],
        action_hotkeys: dict[str, str] | None = None,
        startup_enabled: bool = False,
        parent: QWidget | None = None,
        theme: str = "auto",
    ) -> None:
        super().__init__(parent)
        self.theme = theme
        self.resolved_theme = resolve_theme(theme)
        self.native_header_style = ""
        self.hotkey_availability = hotkey_availability
        self.action_hotkeys: dict[tuple[int, int], str] = {}
        for hotkey, name in (action_hotkeys or {}).items():
            try:
                parsed = parse_hotkey(hotkey)
            except HotkeyParseError:
                continue
            self.action_hotkeys[
                (parsed.modifiers, parsed.virtual_key)
            ] = name
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setAccessibleName(f"{APP_NAME} first-use setup guide")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)
        self.resize(720, 500)

        welcome = QWizardPage()
        welcome.setTitle("Write from anywhere in Windows")
        welcome.setSubTitle(
            "A quick introduction to selecting text and opening the launcher."
        )
        welcome_layout = QVBoxLayout(welcome)
        welcome_text = QLabel(
            "Select text in Word, Outlook, a browser, or another application, "
            "then open PromptMeld with one keyboard shortcut. Choose a writing "
            "action and review the prepared request in ChatGPT."
        )
        welcome_text.setWordWrap(True)
        welcome_text.setObjectName("setupBody")
        welcome_layout.addWidget(welcome_text)
        steps = QLabel(
            "<b>1&nbsp;&nbsp; Select text</b><br>"
            "<b>2&nbsp;&nbsp; Press the launcher shortcut</b><br>"
            "<b>3&nbsp;&nbsp; Choose a writing action</b>"
        )
        steps.setObjectName("setupSteps")
        steps.setTextFormat(Qt.TextFormat.RichText)
        welcome_layout.addWidget(steps)
        welcome_layout.addStretch(1)
        self.addPage(welcome)

        hotkey_page = QWizardPage()
        hotkey_page.setTitle("Choose and test the launcher shortcut")
        hotkey_page.setSubTitle(
            "Confirm that the shortcut is valid and available in Windows."
        )
        hotkey_layout = QVBoxLayout(hotkey_page)
        hotkey_text = QLabel(
            "PromptMeld uses this global shortcut to capture the current "
            "selection. Test it now to make sure Windows and other applications "
            "have not reserved it."
        )
        hotkey_text.setWordWrap(True)
        hotkey_text.setObjectName("setupBody")
        hotkey_layout.addWidget(hotkey_text)
        hotkey_row = QHBoxLayout()
        self.hotkey_editor = HotkeyCaptureEdit(popup_hotkey)
        self.hotkey_editor.setAccessibleName("Launcher shortcut")
        change_button = QPushButton("Change")
        change_button.clicked.connect(self.hotkey_editor.begin_capture)
        self.test_hotkey_button = QPushButton("Test availability")
        self.test_hotkey_button.clicked.connect(self._test_hotkey)
        hotkey_row.addWidget(self.hotkey_editor, 1)
        hotkey_row.addWidget(change_button)
        hotkey_row.addWidget(self.test_hotkey_button)
        hotkey_layout.addLayout(hotkey_row)
        self.hotkey_status = QLabel()
        self.hotkey_status.setObjectName("hotkeyStatus")
        self.hotkey_status.setWordWrap(True)
        hotkey_layout.addWidget(self.hotkey_status)
        hotkey_layout.addStretch(1)
        self.hotkey_editor.hotkey_changed.connect(self._test_hotkey)
        self.hotkey_editor.capture_rejected.connect(
            lambda message: self._set_hotkey_result(False, message)
        )
        self.addPage(hotkey_page)

        finish = QWizardPage()
        finish.setTitle("Understand which choices are remembered")
        finish.setSubTitle(
            "PromptMeld keeps global and application-specific choices separate."
        )
        finish_layout = QVBoxLayout(finish)
        explanation = QLabel(
            "Overall defaults in Configuration are remembered for future "
            "requests. Application profiles can override them for a particular "
            "source application. Audience, editing strength, factual protection, "
            "intent, and other request guidance in the launcher apply only to "
            "the current selection unless an application profile supplies them."
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("setupBody")
        finish_layout.addWidget(explanation)
        self.start_with_windows = QCheckBox(
            "Start PromptMeld when I sign in to Windows"
        )
        self.start_with_windows.setChecked(startup_enabled)
        finish_layout.addWidget(self.start_with_windows)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("setupSummary")
        self.summary_label.setWordWrap(True)
        finish_layout.addWidget(self.summary_label)
        finish_layout.addStretch(1)
        self.addPage(finish)

        self.currentIdChanged.connect(self._update_summary)
        self._apply_appearance()
        app = QApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._system_appearance_changed)
        self._test_hotkey()
        self._update_summary()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._style_native_wizard_frames()

    def _style_native_wizard_frames(self) -> None:
        """Theme Qt's unlabelled ModernStyle header and separator widgets."""

        page = self.currentPage()
        if page is None:
            return
        title_label = next(
            (
                label
                for label in self.findChildren(QLabel)
                if label.text() == page.title()
            ),
            None,
        )
        if title_label is None:
            return
        header = title_label.parentWidget()
        if header is None:
            return
        if system_high_contrast_enabled():
            palette = self.palette()
            background = palette.color(QPalette.ColorRole.Window).name()
            border = palette.color(QPalette.ColorRole.WindowText).name()
        else:
            background = (
                "#f5f7fa" if self.resolved_theme == "light" else "#17191e"
            )
            border = (
                "#cbd2dc" if self.resolved_theme == "light" else "#343842"
            )
        self.native_header_style = (
            f"background-color: {background}; border-bottom: 1px solid {border};"
        )
        header.setStyleSheet(self.native_header_style)
        container = header.parentWidget()
        if container is None:
            return
        for child in container.findChildren(
            QWidget,
            options=Qt.FindChildOption.FindDirectChildrenOnly,
        ):
            if child is not header and child.height() <= 3:
                child.setStyleSheet(f"background-color: {border};")

    def _apply_appearance(self) -> None:
        self.resolved_theme = resolve_theme(self.theme)
        apply_message_box_theme(self.theme)
        if system_high_contrast_enabled():
            app = QApplication.instance()
            if app is not None:
                self.setPalette(app.palette())
            self.setStyleSheet(high_contrast_stylesheet())
            self._style_native_wizard_frames()
            return
        checkmark = str(
            files("promptmeld").joinpath(
                "resources",
                "icons",
                "check-white.svg",
            )
        ).replace("\\", "/")
        if self.resolved_theme == "light":
            palette = self.palette()
            palette.setColor(QPalette.ColorRole.Window, QColor("#f5f7fa"))
            palette.setColor(QPalette.ColorRole.Base, QColor("#f5f7fa"))
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#202631"))
            palette.setColor(QPalette.ColorRole.Text, QColor("#202631"))
            palette.setColor(QPalette.ColorRole.Mid, QColor("#cbd2dc"))
            self.setPalette(palette)
            self.setStyleSheet(
                """
                QWizard, QWizardPage {
                    color: #202631;
                    background: #f5f7fa;
                }
                QWizard QLabel { color: #202631; }
                QLabel#qt_wizard_title {
                    color: #171c25;
                    font-size: 20px;
                    font-weight: 650;
                }
                QLabel#qt_wizard_subtitle { color: #596575; }
                QLabel#setupBody {
                    color: #303846;
                    font-size: 14px;
                    line-height: 1.35;
                }
                QLabel#setupSteps, QLabel#setupSummary {
                    color: #244fae;
                    background: #e8efff;
                    border: 1px solid #a9bae7;
                    border-radius: 9px;
                    padding: 12px 14px;
                    font-size: 14px;
                }
                QLabel#hotkeyStatus[state="available"] { color: #18733b; }
                QLabel#hotkeyStatus[state="error"] { color: #a32626; }
                QLineEdit {
                    color: #202631;
                    background: #ffffff;
                    border: 1px solid #aeb8c5;
                    border-radius: 7px;
                    padding: 8px 10px;
                    selection-background-color: #b9ceff;
                }
                QPushButton {
                    color: #202631;
                    background: #e4e9ef;
                    border: 1px solid #b8c1cc;
                    border-radius: 7px;
                    padding: 8px 13px;
                }
                QPushButton:hover { background: #d7dee7; }
                QPushButton:default {
                    color: #ffffff;
                    background: #315ecb;
                    border-color: #315ecb;
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
                QCheckBox::indicator:checked {
                    border-color: #244fae;
                    background: #315ecb;
                    image: url("__CHECKMARK__");
                }
                """.replace("__CHECKMARK__", checkmark)
            )
            self.setStyleSheet(
                self.styleSheet() + message_box_stylesheet("light")
            )
            return
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#17191e"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#17191e"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#f4f5f7"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#f4f5f7"))
        palette.setColor(QPalette.ColorRole.Mid, QColor("#343842"))
        self.setPalette(palette)
        self.setStyleSheet(
            """
            QWizard, QWizardPage {
                color: #f4f5f7;
                background: #17191e;
            }
            QWizard QLabel { color: #f4f5f7; }
            QLabel#qt_wizard_title {
                color: #ffffff;
                font-size: 20px;
                font-weight: 650;
            }
            QLabel#qt_wizard_subtitle { color: #b4bbc8; }
            QLabel#setupBody {
                color: #e2e5eb;
                font-size: 14px;
                line-height: 1.35;
            }
            QLabel#setupSteps, QLabel#setupSummary {
                color: #d9e2ff;
                background: #242b3a;
                border: 1px solid #52658f;
                border-radius: 9px;
                padding: 12px 14px;
                font-size: 14px;
            }
            QLabel#hotkeyStatus[state="available"] { color: #7ee2a8; }
            QLabel#hotkeyStatus[state="error"] { color: #ff9d9d; }
            QLineEdit {
                color: #ffffff;
                background: #22252c;
                border: 1px solid #596273;
                border-radius: 7px;
                padding: 8px 10px;
                selection-background-color: #3e6ae1;
            }
            QLineEdit:focus { border-color: #85a0ff; }
            QPushButton {
                color: #f4f5f7;
                background: #30343d;
                border: 1px solid #596273;
                border-radius: 7px;
                padding: 8px 13px;
            }
            QPushButton:hover { background: #3a404c; }
            QPushButton:default {
                color: #ffffff;
                background: #4f73df;
                border-color: #7592ec;
                font-weight: 600;
            }
            QCheckBox { color: #f4f5f7; spacing: 8px; }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #798291;
                border-radius: 3px;
                background: #22252c;
            }
            QCheckBox::indicator:checked {
                border-color: #7592ec;
                background: #4f73df;
                image: url("__CHECKMARK__");
            }
            """.replace("__CHECKMARK__", checkmark)
        )
        self.setStyleSheet(
            self.styleSheet() + message_box_stylesheet("dark")
        )

    def _system_appearance_changed(self, *args) -> None:
        self._apply_appearance()

    def selected_hotkey(self) -> str:
        return self.hotkey_editor.text().strip()

    def _set_hotkey_result(self, available: bool, message: str) -> None:
        self.hotkey_is_available = available
        self.hotkey_status.setProperty(
            "state",
            "available" if available else "error",
        )
        self.hotkey_status.setText(message)
        self.hotkey_status.style().unpolish(self.hotkey_status)
        self.hotkey_status.style().polish(self.hotkey_status)
        self._update_summary()

    def _test_hotkey(self, *args) -> None:
        hotkey = self.selected_hotkey()
        try:
            parsed = parse_hotkey(hotkey)
        except HotkeyParseError as exc:
            self._set_hotkey_result(False, str(exc))
            return
        conflict = self.action_hotkeys.get(
            (parsed.modifiers, parsed.virtual_key)
        )
        if conflict:
            self._set_hotkey_result(
                False,
                f"Already assigned to the writing action: {conflict}",
            )
            return
        try:
            available = self.hotkey_availability(hotkey)
        except Exception:
            available = False
        self._set_hotkey_result(
            available,
            (
                "Available - Windows accepted this shortcut."
                if available
                else "Unavailable - Windows or another application is using it."
            ),
        )

    def _update_summary(self, *args) -> None:
        if not hasattr(self, "summary_label"):
            return
        status = "tested and available" if self.hotkey_is_available else "not ready"
        self.summary_label.setText(
            f"Launcher shortcut: {self.selected_hotkey() or 'Not set'} "
            f"({status})"
        )

    def accept(self) -> None:
        self._test_hotkey()
        if not self.hotkey_is_available:
            QMessageBox.warning(
                self,
                "Choose an available shortcut",
                "Test and choose an available launcher shortcut before "
                "finishing setup.",
            )
            return
        super().accept()


class NestedFolderDialog(QDialog):
    """Choose a parent and name one folder level without typing a path."""

    def __init__(
        self,
        folders: tuple[str, ...],
        selected_parent: str = "",
        *,
        moving_action: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create a writing action folder")
        self.setAccessibleName("Create a writing action folder")
        self.setModal(True)
        self.setMinimumWidth(470)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())

        root = QVBoxLayout(self)
        heading = QLabel("Choose where the new folder belongs")
        heading.setObjectName("settingsTitle")
        root.addWidget(heading)
        explanation = QLabel(
            (
                "The selected writing action will move into the new folder."
                if moving_action
                else "A writing action will be created in the new folder. "
                "Folders are kept only when they contain an action."
            )
        )
        explanation.setObjectName("muted")
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        form = QFormLayout()
        self.parent_folder = NoWheelComboBox()
        self.parent_folder.setAccessibleName("Parent writing action folder")
        self.parent_folder.addItem("Top level", "")
        for folder in folders:
            self.parent_folder.addItem(folder, folder)
        parent_index = self.parent_folder.findData(selected_parent)
        self.parent_folder.setCurrentIndex(max(0, parent_index))
        self.folder_name = QLineEdit()
        self.folder_name.setAccessibleName("New folder name")
        self.folder_name.setPlaceholderText("e.g. Customer replies")
        form.addRow("Parent folder", self.parent_folder)
        form.addRow("New folder name", self.folder_name)
        root.addLayout(form)

        self.error_label = QLabel()
        self.error_label.setObjectName("errorText")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.create_button = buttons.button(
            QDialogButtonBox.StandardButton.Ok
        )
        self.create_button.setText(
            "Move action" if moving_action else "Continue to new action"
        )
        self.create_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.folder_name.textChanged.connect(
            lambda text: self.create_button.setEnabled(bool(text.strip()))
        )
        root.addWidget(buttons)

    def folder_path(self) -> str:
        parent = str(self.parent_folder.currentData() or "")
        name = self.folder_name.text().strip()
        return normalize_folder("/".join(part for part in (parent, name) if part))

    def accept(self) -> None:
        name = self.folder_name.text().strip()
        if not name:
            self._show_error("Enter a name for the new folder.")
            return
        if "/" in name or "\\" in name:
            self._show_error(
                "Enter one folder name only. Choose its parent from the list."
            )
            return
        try:
            self.folder_path()
        except ValueError as exc:
            self._show_error(str(exc))
            return
        super().accept()

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()
        self.folder_name.setFocus()


class ActionCreationWizard(QWizard):
    """Guide creation or duplication of a writing action."""

    def __init__(
        self,
        source: WritingAction,
        icon_provider: ActionIconProvider,
        folders: tuple[str, ...] = (),
        used_hotkeys: dict[str, str] | None = None,
        hotkey_availability: Callable[[str], bool] | None = None,
        mode: str = "create",
        parent: QWidget | None = None,
        theme: str = "auto",
    ) -> None:
        super().__init__(parent)
        self.theme = theme
        self.resolved_theme = resolve_theme(theme)
        self.native_header_style = ""
        self.icon_provider = icon_provider
        self.used_hotkeys: dict[tuple[int, int], str] = {}
        for hotkey, name in (used_hotkeys or {}).items():
            try:
                parsed = parse_hotkey(hotkey)
            except HotkeyParseError:
                continue
            self.used_hotkeys[
                (parsed.modifiers, parsed.virtual_key)
            ] = name
        self.hotkey_availability = hotkey_availability
        self.hotkey_is_available = not bool(source.hotkey)
        duplicate = mode == "duplicate"
        window_title = (
            "Duplicate writing action" if duplicate else "Create writing action"
        )
        self.setWindowTitle(window_title)
        self.setAccessibleName(window_title)
        self.setAccessibleDescription(
            "A four-step guide for configuring and testing a writing action."
        )
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)
        self.resize(720, 560)

        essentials = QWizardPage()
        essentials.setTitle(
            "Name the copy" if duplicate else "Describe the writing action"
        )
        essentials.setSubTitle(
            "These are the details people see and the instruction sent with "
            "the selected text."
        )
        essentials.setAccessibleName(essentials.title())
        essentials.setAccessibleDescription(essentials.subTitle())
        essentials_form = QFormLayout(essentials)
        self.name = QLineEdit(source.name)
        self.name.setPlaceholderText("e.g. Make more diplomatic")
        self.name.setAccessibleName("Writing action name")
        self.folder = NoWheelComboBox()
        self.folder.setEditable(True)
        self.folder.setAccessibleName("Writing action folder")
        self.folder.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.folder.addItem("Top level", "")
        for folder in folders:
            self.folder.addItem(folder, folder)
        self.folder.setCurrentText(source.folder)
        self.folder.lineEdit().setPlaceholderText(
            "Top level, or e.g. Replies / Customer service"
        )
        self.instruction = QPlainTextEdit(source.instruction)
        self.instruction.setAccessibleName("Writing action instruction")
        self.instruction.setPlaceholderText(
            "Describe how ChatGPT should transform the selected text."
        )
        self.instruction.setMinimumHeight(180)
        essentials_form.addRow("Name", self.name)
        essentials_form.addRow("Folder path", self.folder)
        folder_help = QLabel(
            "Choose an existing folder or type a path such as "
            "Reply / Customer service. A slash creates each nested level."
        )
        folder_help.setObjectName("muted")
        folder_help.setWordWrap(True)
        essentials_form.addRow("", folder_help)
        essentials_form.addRow("Instruction", self.instruction)
        self.addPage(essentials)

        discovery = QWizardPage()
        discovery.setTitle("Make the action easy to find")
        discovery.setSubTitle(
            "Keywords improve launcher search. Choose a familiar icon, or use "
            "an image of your own."
        )
        discovery.setAccessibleName(discovery.title())
        discovery.setAccessibleDescription(discovery.subTitle())
        discovery_form = QFormLayout(discovery)
        self.keywords = QLineEdit(", ".join(source.keywords))
        self.keywords.setAccessibleName("Writing action search keywords")
        self.keywords.setPlaceholderText("e.g. polite, tone, tactful")
        icon_row = QHBoxLayout()
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(44, 44)
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon = NoWheelComboBox()
        self.icon.setEditable(True)
        self.icon.setAccessibleName("Writing action icon")
        self.icon.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.icon.lineEdit().setPlaceholderText(
            "Choose an icon or type an emoji"
        )
        for label, spec in icon_provider.CATALOG:
            self.icon.addItem(
                icon_provider.icon_for_spec(spec, spec, 30),
                label,
                spec,
            )
        selected_icon = self.icon.findData(source.icon)
        if selected_icon >= 0:
            self.icon.setCurrentIndex(selected_icon)
        else:
            self.icon.setCurrentText(source.icon)
        self.choose_icon_button = QPushButton("Choose file…")
        self.choose_icon_button.clicked.connect(self._choose_icon_file)
        icon_row.addWidget(self.icon_preview)
        icon_row.addWidget(self.icon, 1)
        icon_row.addWidget(self.choose_icon_button)
        discovery_form.addRow("Search keywords", self.keywords)
        discovery_form.addRow("Icon", icon_row)
        self.addPage(discovery)

        behaviour = QWizardPage()
        behaviour.setTitle("Choose behaviour and an optional shortcut")
        behaviour.setSubTitle(
            "These choices can be changed later under Writing actions."
        )
        behaviour.setAccessibleName(behaviour.title())
        behaviour.setAccessibleDescription(behaviour.subTitle())
        behaviour_layout = QVBoxLayout(behaviour)
        behaviour_form = QFormLayout()
        self.enabled = QCheckBox("Show this action in the launcher")
        self.enabled.setChecked(source.enabled)
        self.show_on_home = QCheckBox(
            "Show as a fixed direct action on launcher home"
        )
        self.show_on_home.setChecked(source.show_on_home)
        self.natural_voice = NoWheelComboBox()
        self.natural_voice.addItem("Follow the launcher choice", "inherit")
        self.natural_voice.addItem("Always apply", "always")
        self.natural_voice.addItem("Never apply", "never")
        self.natural_voice.setCurrentIndex(
            max(0, self.natural_voice.findData(source.natural_voice))
        )
        self.recipient_audience = NoWheelComboBox()
        self.recipient_audience.setAccessibleName(
            "Writing action default audience"
        )
        self.recipient_audience.addItem(
            "Use application or launcher default",
            "inherit",
        )
        for value, label in RECIPIENT_AUDIENCE_OPTIONS:
            self.recipient_audience.addItem(label, value)
        self.recipient_audience.setCurrentIndex(
            max(
                0,
                self.recipient_audience.findData(
                    source.recipient_audience
                ),
            )
        )
        self.recipient_audience.setToolTip(
            "Used when this action is selected. A choice made in the launcher "
            "for the current request takes priority."
        )
        self.guided_drafting = QCheckBox(
            "Allow guided questions when enabled overall"
        )
        self.guided_drafting.setChecked(source.guided_drafting)
        behaviour_form.addRow("Availability", self.enabled)
        behaviour_form.addRow("Launcher home", self.show_on_home)
        behaviour_form.addRow("Natural voice", self.natural_voice)
        behaviour_form.addRow("Default audience", self.recipient_audience)
        behaviour_form.addRow("Guided drafting", self.guided_drafting)
        behaviour_layout.addLayout(behaviour_form)
        shortcut_label = QLabel("Optional global shortcut")
        shortcut_label.setObjectName("formLabel")
        behaviour_layout.addWidget(shortcut_label)
        shortcut_row = QHBoxLayout()
        self.hotkey = HotkeyCaptureEdit(source.hotkey or "")
        self.hotkey.setAccessibleName("Writing action shortcut")
        change_button = QPushButton("Change")
        change_button.clicked.connect(self.hotkey.begin_capture)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.hotkey.clear_hotkey)
        self.test_hotkey_button = QPushButton("Test availability")
        self.test_hotkey_button.clicked.connect(self._test_hotkey)
        shortcut_row.addWidget(self.hotkey, 1)
        shortcut_row.addWidget(change_button)
        shortcut_row.addWidget(clear_button)
        shortcut_row.addWidget(self.test_hotkey_button)
        behaviour_layout.addLayout(shortcut_row)
        self.hotkey_status = QLabel()
        self.hotkey_status.setObjectName("hotkeyStatus")
        self.hotkey_status.setWordWrap(True)
        behaviour_layout.addWidget(self.hotkey_status)
        behaviour_layout.addStretch(1)
        self.hotkey.hotkey_changed.connect(self._test_hotkey)
        self.hotkey.capture_rejected.connect(
            lambda message: self._set_hotkey_result(False, message)
        )
        self.addPage(behaviour)

        preview = QWizardPage()
        preview.setTitle("Test the action with sample text")
        preview.setSubTitle(
            "Preview the complete request that PromptMeld would prepare. "
            "Nothing is sent to ChatGPT from this page."
        )
        preview.setAccessibleName(preview.title())
        preview.setAccessibleDescription(preview.subTitle())
        preview_layout = QVBoxLayout(preview)
        sample_label = QLabel("Sample selected text")
        sample_label.setObjectName("formLabel")
        preview_layout.addWidget(sample_label)
        self.sample_text = QPlainTextEdit()
        self.sample_text.setAccessibleName("Sample selected text")
        self.sample_text.setPlaceholderText(
            "Paste or type a short example that this action should handle."
        )
        self.sample_text.setPlainText(
            "I wanted to check whether you can send the revised document by Friday."
        )
        self.sample_text.setMaximumHeight(95)
        preview_layout.addWidget(self.sample_text)
        preview_button_row = QHBoxLayout()
        preview_note = QLabel(
            "The preview includes PromptMeld's safety and output requirements."
        )
        preview_note.setObjectName("muted")
        self.preview_action_button = QPushButton("Refresh test preview")
        self.preview_action_button.clicked.connect(self._preview_action)
        preview_button_row.addWidget(preview_note, 1)
        preview_button_row.addWidget(self.preview_action_button)
        preview_layout.addLayout(preview_button_row)
        prompt_label = QLabel("Prepared ChatGPT request")
        prompt_label.setObjectName("formLabel")
        preview_layout.addWidget(prompt_label)
        self.prompt_preview = QPlainTextEdit()
        self.prompt_preview.setReadOnly(True)
        self.prompt_preview.setAccessibleName(
            "Prepared ChatGPT request preview"
        )
        preview_layout.addWidget(self.prompt_preview, 1)
        self.addPage(preview)

        self.icon.currentIndexChanged.connect(self._update_icon_preview)
        self.icon.lineEdit().textChanged.connect(self._update_icon_preview)
        self.currentIdChanged.connect(self._wizard_page_changed)
        self._apply_appearance()
        app = QApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._system_appearance_changed)
        self._update_icon_preview()
        self._test_hotkey()
        self._update_accessible_page(self.currentId())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._style_native_wizard_frames()

    def _style_native_wizard_frames(self) -> None:
        """Keep Qt's native ModernStyle header readable in every theme."""

        page = self.currentPage()
        if page is None:
            return
        title_label = next(
            (
                label
                for label in self.findChildren(QLabel)
                if label.text() == page.title()
            ),
            None,
        )
        if title_label is None:
            return
        header = title_label.parentWidget()
        if header is None:
            return
        if system_high_contrast_enabled():
            palette = self.palette()
            background = palette.color(QPalette.ColorRole.Window).name()
            border = palette.color(QPalette.ColorRole.WindowText).name()
        else:
            background = (
                "#f5f7fa" if self.resolved_theme == "light" else "#17191e"
            )
            border = (
                "#cbd2dc" if self.resolved_theme == "light" else "#343842"
            )
        self.native_header_style = (
            f"background-color: {background}; border-bottom: 1px solid {border};"
        )
        header.setStyleSheet(self.native_header_style)

    def _apply_appearance(self) -> None:
        """Give the standalone action wizard explicit, readable colours."""

        self.resolved_theme = resolve_theme(self.theme)
        apply_message_box_theme(self.theme)
        if system_high_contrast_enabled():
            app = QApplication.instance()
            if app is not None:
                self.setPalette(app.palette())
            self.setStyleSheet(
                high_contrast_stylesheet()
                + message_box_stylesheet(self.theme)
            )
            self._style_native_wizard_frames()
            return
        checkmark = str(
            files("promptmeld").joinpath(
                "resources",
                "icons",
                "check-white.svg",
            )
        ).replace("\\", "/")
        if self.resolved_theme == "light":
            palette = self.palette()
            palette.setColor(QPalette.ColorRole.Window, QColor("#f5f7fa"))
            palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#202631"))
            palette.setColor(QPalette.ColorRole.Text, QColor("#202631"))
            palette.setColor(
                QPalette.ColorRole.PlaceholderText,
                QColor("#697381"),
            )
            self.setPalette(palette)
            style = """
                QWizard, QWizardPage {
                    color: #202631;
                    background: #f5f7fa;
                }
                QWizard QLabel { color: #202631; }
                QLabel#qt_wizard_title {
                    color: #171c25;
                    font-size: 20px;
                    font-weight: 650;
                }
                QLabel#qt_wizard_subtitle { color: #4b5563; }
                QLabel#muted { color: #596575; }
                QLabel#hotkeyStatus[state="available"] { color: #18733b; }
                QLabel#hotkeyStatus[state="error"] { color: #a32626; }
                QLineEdit, QPlainTextEdit, QComboBox {
                    color: #202631;
                    background: #ffffff;
                    border: 1px solid #aeb8c5;
                    border-radius: 7px;
                    padding: 7px 9px;
                    selection-color: #111827;
                    selection-background-color: #b9ceff;
                }
                QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
                    border-color: #315ecb;
                }
                QComboBox QAbstractItemView {
                    color: #202631;
                    background: #ffffff;
                    selection-color: #102e70;
                    selection-background-color: #dce7ff;
                }
                QCheckBox { color: #202631; spacing: 8px; }
                QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                    border: 1px solid #687585;
                    border-radius: 3px;
                    background: #ffffff;
                }
                QCheckBox::indicator:checked {
                    border-color: #244fae;
                    background: #315ecb;
                    image: url("__CHECKMARK__");
                }
                QPushButton {
                    color: #202631;
                    background: #e4e9ef;
                    border: 1px solid #b8c1cc;
                    border-radius: 7px;
                    padding: 8px 13px;
                }
                QPushButton:hover { background: #d7dee7; }
                QPushButton:default {
                    color: #ffffff;
                    background: #315ecb;
                    border-color: #244fae;
                    font-weight: 600;
                }
            """
        else:
            palette = self.palette()
            palette.setColor(QPalette.ColorRole.Window, QColor("#17191e"))
            palette.setColor(QPalette.ColorRole.Base, QColor("#22252c"))
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#f4f5f7"))
            palette.setColor(QPalette.ColorRole.Text, QColor("#f4f5f7"))
            palette.setColor(
                QPalette.ColorRole.PlaceholderText,
                QColor("#b4bbc8"),
            )
            self.setPalette(palette)
            style = """
                QWizard, QWizardPage {
                    color: #f4f5f7;
                    background: #17191e;
                }
                QWizard QLabel { color: #f4f5f7; }
                QLabel#qt_wizard_title {
                    color: #ffffff;
                    font-size: 20px;
                    font-weight: 650;
                }
                QLabel#qt_wizard_subtitle { color: #d2d7e0; }
                QLabel#muted { color: #c1c7d0; }
                QLabel#hotkeyStatus[state="available"] { color: #7ee2a8; }
                QLabel#hotkeyStatus[state="error"] { color: #ff9d9d; }
                QLineEdit, QPlainTextEdit, QComboBox {
                    color: #ffffff;
                    background: #22252c;
                    border: 1px solid #646d7d;
                    border-radius: 7px;
                    padding: 7px 9px;
                    selection-color: #ffffff;
                    selection-background-color: #3e6ae1;
                }
                QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
                    border-color: #85a0ff;
                }
                QComboBox QAbstractItemView {
                    color: #ffffff;
                    background: #22252c;
                    selection-color: #ffffff;
                    selection-background-color: #3e6ae1;
                }
                QCheckBox { color: #f4f5f7; spacing: 8px; }
                QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                    border: 1px solid #8b94a3;
                    border-radius: 3px;
                    background: #22252c;
                }
                QCheckBox::indicator:checked {
                    border-color: #8fa8ff;
                    background: #4f73df;
                    image: url("__CHECKMARK__");
                }
                QPushButton {
                    color: #f4f5f7;
                    background: #30343d;
                    border: 1px solid #646d7d;
                    border-radius: 7px;
                    padding: 8px 13px;
                }
                QPushButton:hover { background: #3a404c; }
                QPushButton:default {
                    color: #ffffff;
                    background: #4f73df;
                    border-color: #8fa8ff;
                    font-weight: 600;
                }
            """
        self.setStyleSheet(
            style.replace("__CHECKMARK__", checkmark)
            + message_box_stylesheet(self.theme)
        )
        self._style_native_wizard_frames()

    def _system_appearance_changed(self, *args) -> None:
        self._apply_appearance()

    def _update_accessible_page(self, page_id: int) -> None:
        page = self.page(page_id)
        if page is None:
            return
        self.setAccessibleDescription(
            f"Current step: {page.title()}. {page.subTitle()}"
        )

    def _selected_icon_spec(self) -> str:
        index = self.icon.currentIndex()
        if index >= 0 and self.icon.currentText() == self.icon.itemText(index):
            return str(self.icon.itemData(index) or "")
        return self.icon.currentText().strip()

    def _update_icon_preview(self, *args) -> None:
        icon = self.icon_provider.icon_for_spec(
            self._selected_icon_spec(),
            "action-wizard-preview",
            38,
        )
        self.icon_preview.setPixmap(icon.pixmap(38, 38))

    def _choose_icon_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Choose action icon",
            str(Path.home()),
            "Images (*.png *.svg *.ico *.jpg *.jpeg *.bmp *.webp)",
        )
        if filename:
            self.icon.setCurrentText(filename)

    def _set_hotkey_result(self, available: bool, message: str) -> None:
        self.hotkey_is_available = available
        self.hotkey_status.setProperty(
            "state",
            "available" if available else "error",
        )
        self.hotkey_status.setText(message)
        self.hotkey_status.style().unpolish(self.hotkey_status)
        self.hotkey_status.style().polish(self.hotkey_status)

    def _test_hotkey(self, *args) -> None:
        hotkey = self.hotkey.text().strip()
        if not hotkey:
            self._set_hotkey_result(
                True,
                "No shortcut assigned. The action remains available in the launcher.",
            )
            return
        try:
            parsed = parse_hotkey(hotkey)
        except HotkeyParseError as exc:
            self._set_hotkey_result(False, str(exc))
            return
        conflict = self.used_hotkeys.get(
            (parsed.modifiers, parsed.virtual_key)
        )
        if conflict:
            self._set_hotkey_result(
                False,
                f"Already assigned to: {conflict}",
            )
            return
        if self.hotkey_availability is None:
            self._set_hotkey_result(
                True,
                "Shortcut format is valid. Save to register it with Windows.",
            )
            return
        try:
            available = self.hotkey_availability(hotkey)
        except Exception:
            available = False
        self._set_hotkey_result(
            available,
            (
                "Available - Windows accepted this shortcut."
                if available
                else "Unavailable - Windows or another application is using it."
            ),
        )

    def _wizard_page_changed(self, page_id: int) -> None:
        self._update_accessible_page(page_id)
        QTimer.singleShot(0, self._style_native_wizard_frames)
        if page_id == 3:
            self._preview_action()

    def _preview_action(self) -> None:
        sample = self.sample_text.toPlainText().strip()
        if not self.instruction.toPlainText().strip():
            self.prompt_preview.setPlainText(
                "Add the writing instruction on the first page to preview it."
            )
            return
        if not sample:
            self.prompt_preview.setPlainText(
                "Add sample selected text to preview this action."
            )
            return
        try:
            prompt = PromptBuilder().build(
                self.action("action-preview"),
                CapturedSelection(sample, 0, "Action test"),
                natural_voice_enabled=True,
                natural_voice_instruction=(
                    DEFAULT_NATURAL_VOICE_INSTRUCTION
                ),
                guided_drafting_enabled=True,
            )
        except ValueError as exc:
            self.prompt_preview.setPlainText(str(exc))
            return
        self.prompt_preview.setPlainText(prompt)

    def action(self, action_id: str) -> WritingAction:
        return WritingAction(
            id=action_id,
            name=self.name.text().strip(),
            keywords=tuple(
                keyword.strip()
                for keyword in self.keywords.text().split(",")
                if keyword.strip()
            ),
            instruction=self.instruction.toPlainText().strip(),
            hotkey=self.hotkey.text().strip() or None,
            enabled=self.enabled.isChecked(),
            icon=self._selected_icon_spec(),
            folder=normalize_folder(self.folder.currentText()),
            show_on_home=self.show_on_home.isChecked(),
            natural_voice=str(self.natural_voice.currentData() or "inherit"),
            guided_drafting=self.guided_drafting.isChecked(),
            recipient_audience=str(
                self.recipient_audience.currentData() or "inherit"
            ),
        )

    def _go_back_to(self, page_id: int) -> None:
        while self.currentId() > page_id:
            self.back()

    def accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(
                self,
                "Action name required",
                "Enter a short name for this writing action.",
            )
            self._go_back_to(0)
            self.name.setFocus()
            return
        if not self.instruction.toPlainText().strip():
            QMessageBox.warning(
                self,
                "Instruction required",
                "Describe how ChatGPT should transform the selected text.",
            )
            self._go_back_to(0)
            self.instruction.setFocus()
            return
        try:
            normalize_folder(self.folder.currentText())
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid folder", str(exc))
            self._go_back_to(0)
            self.folder.setFocus()
            return
        self._test_hotkey()
        if not self.hotkey_is_available:
            QMessageBox.warning(
                self,
                "Choose an available shortcut",
                "Clear the shortcut or choose one that is available before "
                "finishing.",
            )
            self._go_back_to(2)
            return
        super().accept()


class ActionSettingsDialog(QDialog):
    actions_saved = Signal()
    update_check_requested = Signal()
    update_install_requested = Signal()
    update_release_requested = Signal()
    diagnostics_copy_requested = Signal()
    diagnostics_open_requested = Signal()
    configuration_restored = Signal()
    configuration_reset = Signal()
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
        self.builtin_action_packs = load_builtin_action_packs()
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
            "Set remembered overall defaults, application-specific overrides, "
            "writing actions, and shortcuts."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        root.addLayout(heading_row)
        root.addWidget(description)

        voice_settings = settings or AppSettings()
        self.application_profile_overall_settings = voice_settings
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
        appearance_note.setWordWrap(True)
        appearance_layout.addWidget(appearance_label)
        appearance_layout.addWidget(self.theme)
        appearance_layout.addWidget(appearance_note)
        appearance_layout.addStretch(1)

        home_row = QGridLayout()
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
        home_row.addWidget(home_label, 0, 0)
        home_row.addWidget(self.most_used_count, 0, 1)
        home_row.addWidget(language_label, 1, 0)
        home_row.addWidget(self.primary_language, 1, 1)
        home_row.setColumnStretch(1, 1)

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
        self.resulting_text_length_help = self._help_button(
            "This is also the remembered selection in the launcher. Default "
            "adds no text-length instruction to the prompt. The other choices "
            "add qualitative length guidance.",
            "Explain resulting text length",
        )
        length_row.addWidget(length_label)
        length_row.addWidget(self.resulting_text_length)
        length_row.addWidget(self.resulting_text_length_help)
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
        self.resulting_text_formatting_help = self._help_button(
            "Default adds no formatting instruction. The other choices either "
            "prevent new formatting or request restrained helpful formatting.",
            "Explain resulting text formatting",
        )
        length_row.addWidget(formatting_label)
        length_row.addWidget(self.resulting_text_formatting)
        length_row.addWidget(self.resulting_text_formatting_help)
        length_row.addStretch(1)
        title_subject_row = QHBoxLayout()
        title_subject_label = QLabel("Title or subject")
        title_subject_label.setObjectName("formLabel")
        self.title_subject = NoWheelComboBox()
        for value, label in TITLE_SUBJECT_OPTIONS:
            self.title_subject.addItem(label, value)
        selected_title_subject = self.title_subject.findData(
            voice_settings.title_subject
        )
        self.title_subject.setCurrentIndex(max(0, selected_title_subject))
        self.title_subject.setMinimumWidth(235)
        self.title_subject_help = self._help_button(
            "Optionally ask ChatGPT for a separate concise title or subject "
            "line as well as the complete main text. Automatic chooses the "
            "appropriate label from the writing task. The suggestion appears "
            "on the first line so it can be copied into a separate field, "
            "such as an Amazon review title or an email subject.",
            "Explain title or subject generation",
        )
        title_subject_row.addWidget(title_subject_label)
        title_subject_row.addWidget(self.title_subject)
        title_subject_row.addWidget(self.title_subject_help)
        title_subject_row.addStretch(1)
        self.writing_block_default = QCheckBox(
            "Request a copyable writing block when available"
        )
        self.writing_block_default.setChecked(
            voice_settings.writing_block_enabled
        )
        self.writing_block_help = self._help_button(
            "This is also the remembered state of the launcher option. Writing "
            "blocks are editable and copyable in ChatGPT, but their availability "
            "depends on ChatGPT.",
            "Explain copyable writing blocks",
        )
        writing_block_row = QHBoxLayout()
        writing_block_row.addWidget(self.writing_block_default)
        writing_block_row.addWidget(self.writing_block_help)
        writing_block_row.addStretch(1)
        output_layout.addLayout(length_row)
        output_layout.addLayout(title_subject_row)
        output_layout.addLayout(writing_block_row)

        submission_group = QGroupBox("Submission")
        submission_layout = QVBoxLayout(submission_group)
        self.auto_submit_default = QCheckBox(
            "Submit automatically after pasting the prompt"
        )
        self.auto_submit_default.setChecked(
            voice_settings.auto_submit_enabled
        )
        self.auto_submit_help = self._help_button(
            f"This is also the remembered state of the launcher checkbox. When "
            f"automatic submission is off, {APP_NAME} pastes the complete prompt "
            "without submitting it, so you can choose the model or reasoning "
            "level before pressing Enter.",
            "Explain automatic submission",
        )
        self.privacy_preview_default = QCheckBox(
            "Show a privacy preview and offer reversible redaction before sending"
        )
        self.privacy_preview_default.setChecked(
            voice_settings.privacy_preview_enabled
        )
        self.privacy_preview_help = self._help_button(
            "Before a prompt is opened in ChatGPT, look locally for possible "
            "email addresses, phone numbers, account numbers, and names. When "
            "matches are found, you can redact chosen values with reversible "
            "placeholders, continue unchanged, or cancel. Nothing is redacted "
            "without your explicit choice. Turning this off skips the preview "
            "and sends the prompt unchanged.",
            "Explain privacy preview and redaction",
        )
        self.replace_selected_text_default = QCheckBox(
            "Replace the original selection with the generated result"
        )
        self.replace_selected_text_default.setChecked(
            voice_settings.replace_selected_text_enabled
        )
        self.replace_selected_text_help = self._help_button(
            "After ChatGPT responds, paste the generated result over the original "
            "selection when it came from an editable field. Automatic submission "
            "must be enabled. The original text may be lost if the result is "
            "wrong or the paste fails. "
            "With Temporary Chat enabled, the original is not retained in "
            "ChatGPT. Consider enabling Windows Clipboard History (Win+V) or "
            "using a clipboard manager first; clipboard history may also retain "
            "sensitive text.",
            "Explain replacing the original selection",
        )
        self.replace_selected_text_warning = QLabel(
            "Warning: may irreversibly overwrite the original text"
        )
        self.replace_selected_text_warning.setObjectName("warning")
        self.copy_generated_text_default = QCheckBox(
            "Copy the generated result to the clipboard"
        )
        self.copy_generated_text_default.setChecked(
            voice_settings.copy_generated_text_enabled
        )
        self.copy_generated_text_help = self._help_button(
            "After ChatGPT responds, leave the generated result on the clipboard. "
            "Automatic submission must be enabled. This can be used on its own "
            "or together with replacement of the original selection.",
            "Explain copying the generated result",
        )
        self.temporary_chat_default = QCheckBox(
            "Turn on Temporary Chat by default"
        )
        self.temporary_chat_default.setChecked(
            voice_settings.temporary_chat_enabled
        )
        self.temporary_chat_help = self._help_button(
            "This is also the remembered state of the launcher checkbox. "
            "Temporary Chat opens a top-level chat and skips the configured "
            "Project because temporary chats cannot be used inside Projects. "
            "ChatGPT may show a one-time explanation which you must review and "
            "confirm yourself.",
            "Explain Temporary Chat",
        )
        for option, help_button in (
            (self.auto_submit_default, self.auto_submit_help),
            (self.privacy_preview_default, self.privacy_preview_help),
            (
                self.replace_selected_text_default,
                self.replace_selected_text_help,
            ),
            (
                self.copy_generated_text_default,
                self.copy_generated_text_help,
            ),
            (self.temporary_chat_default, self.temporary_chat_help),
        ):
            option_row = QHBoxLayout()
            option_row.addWidget(option)
            option_row.addWidget(help_button)
            if option is self.replace_selected_text_default:
                option_row.addSpacing(8)
                option_row.addWidget(self.replace_selected_text_warning)
            option_row.addStretch(1)
            submission_layout.addLayout(option_row)

        voice_group = QGroupBox("Preserve my natural voice")
        voice_layout = QVBoxLayout(voice_group)
        self.natural_voice_default = QCheckBox(
            "Enable by default in the launcher"
        )
        self.natural_voice_default.setChecked(
            voice_settings.natural_voice_enabled
        )
        self.natural_voice_help = self._help_button(
            "This is also the remembered state of the launcher checkbox. When "
            "enabled, this modifier helps retain your vocabulary, level of "
            "formality, and personal phrasing. It may help make the result less "
            "likely to be flagged by AI-detection tools, but those tools are "
            "unreliable and avoidance is far from guaranteed.",
            "Explain preserving natural voice",
        )
        natural_voice_row = QHBoxLayout()
        natural_voice_row.addWidget(self.natural_voice_default)
        natural_voice_row.addWidget(self.natural_voice_help)
        natural_voice_row.addStretch(1)
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
        voice_layout.addLayout(natural_voice_row)
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
        self.guided_drafting_help = self._help_button(
            "When essential context is missing, ChatGPT can ask up to three "
            "concise questions, with choices where helpful, before drafting. "
            "It drafts immediately when the selected text is already sufficient. "
            "Questions and answers stay in the ChatGPT chat. Each writing action "
            "must also be marked as supporting guided drafting.",
            "Explain guided drafting",
        )
        guided_row = QHBoxLayout()
        guided_row.addWidget(self.guided_drafting_default)
        guided_row.addWidget(self.guided_drafting_help)
        guided_row.addStretch(1)
        guided_layout.addLayout(guided_row)

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
        self.delete_button.setAccessibleName("Delete selected writing action")
        self.delete_button.setAccessibleDescription(
            "Delete the selected writing action. When a folder is selected, "
            "this button deletes that folder and every writing action inside it."
        )
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

        pack_buttons = QHBoxLayout()
        self.import_pack_button = QPushButton("Import pack…")
        self.export_pack_button = QPushButton("Export pack")
        self.export_pack_menu = QMenu(self.export_pack_button)
        self.export_selected_pack_action = self.export_pack_menu.addAction(
            "Export selected action…"
        )
        self.export_all_pack_action = self.export_pack_menu.addAction(
            "Export all actions…"
        )
        self.export_pack_button.setMenu(self.export_pack_menu)
        pack_buttons.addWidget(self.import_pack_button)
        pack_buttons.addWidget(self.export_pack_button)
        left.addLayout(pack_buttons)

        self.starter_pack_button = QPushButton("Add starter pack")
        self.starter_pack_menu = QMenu(self.starter_pack_button)
        self.starter_pack_actions: dict[str, QAction] = {}
        pack_groups = (
            (
                "Reply or respond",
                (
                    "replies-arguments",
                    "social-replies",
                    "customer-relations",
                    "email",
                    "complaints",
                ),
            ),
            (
                "Edit or revise",
                (
                    "editing",
                    "tone-voice",
                    "social-editing",
                    "argument-editing",
                    "reviews-feedback",
                ),
            ),
            (
                "Draft or create",
                (
                    "draft-from-selection",
                    "reports",
                    "social-posts",
                    "meetings",
                    "career-writing",
                ),
            ),
            (
                "Summarise or extract",
                ("summaries-extraction",),
            ),
            (
                "Plan or decide",
                ("decisions-planning",),
            ),
            (
                "Explain or learn",
                (
                    "technical-communication",
                    "learning",
                ),
            ),
        )
        packs_by_id = {
            pack.pack_id: pack for pack in self.builtin_action_packs
        }
        shown_pack_ids: set[str] = set()
        for group_name, pack_ids in pack_groups:
            group_menu = self.starter_pack_menu.addMenu(group_name)
            for pack_id in pack_ids:
                pack = packs_by_id.get(pack_id)
                if pack is None:
                    continue
                self._add_starter_pack_menu_action(group_menu, pack)
                shown_pack_ids.add(pack_id)
        for pack in self.builtin_action_packs:
            if pack.pack_id not in shown_pack_ids:
                self._add_starter_pack_menu_action(
                    self.starter_pack_menu,
                    pack,
                )
        self.starter_pack_button.setMenu(self.starter_pack_menu)
        left.addWidget(self.starter_pack_button)

        self.starter_button = QPushButton("Replace with essential actions…")
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
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_combo, 1)
        self.new_subfolder_button = QPushButton("New subfolder...")
        self.new_subfolder_button.setAccessibleName(
            "Create a nested writing action folder"
        )
        folder_row.addWidget(self.new_subfolder_button)
        form.addRow(self._form_label("Folder path"), folder_row)

        self.folder_help = QLabel(
            "Folders can be nested. Use New subfolder, or type a path with / "
            "between each level. Leave the path blank for the launcher root."
        )
        self.folder_help.setObjectName("muted")
        self.folder_help.setWordWrap(True)
        form.addRow("", self.folder_help)

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

        self.action_recipient_audience = NoWheelComboBox()
        self.action_recipient_audience.addItem(
            "Use application or launcher default",
            "inherit",
        )
        for value, label in RECIPIENT_AUDIENCE_OPTIONS:
            self.action_recipient_audience.addItem(label, value)
        self.action_recipient_audience.setAccessibleName(
            "Writing action default audience"
        )
        self.action_recipient_audience.setToolTip(
            "Used when this action is selected. A choice made in the launcher "
            "for the current request takes priority."
        )
        form.addRow(
            self._form_label("Default audience"),
            self.action_recipient_audience,
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
            self._refresh_hotkey_rows
        )
        hotkey_footer.addWidget(hotkey_note, 1)
        hotkey_footer.addWidget(self.check_hotkeys_button)
        hotkeys_layout.addLayout(hotkey_footer)
        general_page = QWidget()
        general_page.setObjectName("settingsPage")
        general_layout = QGridLayout(general_page)
        general_layout.setContentsMargins(22, 18, 22, 18)
        general_layout.setHorizontalSpacing(16)
        general_layout.setVerticalSpacing(12)
        launcher_group = QGroupBox("Launcher")
        launcher_layout = QVBoxLayout(launcher_group)
        launcher_layout.addLayout(home_row)
        setup_guide_row = QHBoxLayout()
        setup_guide_note = QLabel(
            "Review the basic workflow and test the global launcher shortcut."
        )
        setup_guide_note.setObjectName("muted")
        setup_guide_note.setWordWrap(True)
        self.setup_guide_button = QPushButton("Run first-use setup guide…")
        self.setup_guide_button.clicked.connect(self._open_setup_guide)
        setup_guide_row.addWidget(setup_guide_note, 1)
        setup_guide_row.addWidget(self.setup_guide_button)
        launcher_layout.addLayout(setup_guide_row)

        projects_group = QGroupBox("ChatGPT Projects")
        projects_layout = QVBoxLayout(projects_group)
        project_base_row = QHBoxLayout()
        project_base_label = QLabel("Project base name")
        project_base_label.setObjectName("formLabel")
        self.project_name = QLineEdit(voice_settings.project_name)
        self.project_name.setAccessibleName("ChatGPT project base name")
        self.project_name.setPlaceholderText("PromptMeld")
        project_base_row.addWidget(project_base_label)
        project_base_row.addWidget(self.project_name, 1)
        projects_layout.addLayout(project_base_row)
        project_mode_row = QHBoxLayout()
        project_mode_label = QLabel("Decide the project name by")
        project_mode_label.setObjectName("formLabel")
        self.project_naming_mode = NoWheelComboBox()
        for value, label in PROJECT_NAMING_OPTIONS:
            self.project_naming_mode.addItem(label, value)
        self.project_naming_mode.setCurrentIndex(
            max(
                0,
                self.project_naming_mode.findData(
                    voice_settings.project_naming_mode
                ),
            )
        )
        self.project_naming_mode.setAccessibleName(
            "ChatGPT project naming strategy"
        )
        project_mode_row.addWidget(project_mode_label)
        project_mode_row.addWidget(self.project_naming_mode, 1)
        projects_layout.addLayout(project_mode_row)
        self.project_naming_example = QLabel()
        self.project_naming_example.setObjectName("muted")
        self.project_naming_example.setWordWrap(True)
        projects_layout.addWidget(self.project_naming_example)
        self.project_name.textChanged.connect(
            self._update_project_naming_example
        )
        self.project_naming_mode.currentIndexChanged.connect(
            self._update_project_naming_example
        )
        self._update_project_naming_example()

        startup_group = QGroupBox("Windows")
        startup_layout = QVBoxLayout(startup_group)
        self.start_with_windows = QCheckBox(
            "Start PromptMeld when I sign in to Windows"
        )
        self.start_with_windows.setChecked(voice_settings.startup_enabled)
        startup_layout.addWidget(self.start_with_windows)
        updates_group = QGroupBox("Updates")
        updates_layout = QVBoxLayout(updates_group)
        self.check_for_updates = QCheckBox(
            "Check automatically for PromptMeld updates"
        )
        self.check_for_updates.setChecked(
            voice_settings.check_for_updates_enabled
        )
        update_explanation = QLabel(
            "PromptMeld checks the latest stable GitHub release at most once "
            "per day. No writing or configuration content is sent."
        )
        update_explanation.setObjectName("muted")
        update_explanation.setWordWrap(True)
        self.update_status = QLabel("Update status has not been checked yet.")
        self.update_status.setObjectName("muted")
        self.update_status.setWordWrap(True)
        update_buttons = QHBoxLayout()
        self.check_updates_button = QPushButton("Check now")
        self.view_update_release_button = QPushButton("View release notes")
        self.install_update_button = QPushButton("Download and install")
        self.view_update_release_button.setEnabled(False)
        self.install_update_button.setEnabled(False)
        self.check_updates_button.clicked.connect(
            self.update_check_requested.emit
        )
        self.view_update_release_button.clicked.connect(
            self.update_release_requested.emit
        )
        self.install_update_button.clicked.connect(
            self.update_install_requested.emit
        )
        update_buttons.addWidget(self.check_updates_button)
        update_buttons.addWidget(self.view_update_release_button)
        update_buttons.addStretch(1)
        update_buttons.addWidget(self.install_update_button)
        updates_layout.addWidget(self.check_for_updates)
        updates_layout.addWidget(update_explanation)
        updates_layout.addWidget(self.update_status)
        updates_layout.addLayout(update_buttons)
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
        general_left = QVBoxLayout()
        general_left.setSpacing(12)
        general_left.addWidget(appearance_group)
        general_left.addWidget(launcher_group)
        general_left.addWidget(startup_group)
        general_left.addStretch(1)
        general_right = QVBoxLayout()
        general_right.setSpacing(12)
        general_right.addWidget(projects_group)
        general_right.addWidget(updates_group)
        general_right.addWidget(about_group)
        general_right.addStretch(1)
        general_layout.addLayout(general_left, 0, 0)
        general_layout.addLayout(general_right, 0, 1)
        general_layout.setColumnStretch(0, 1)
        general_layout.setColumnStretch(1, 1)

        applications_page = QWidget()
        applications_page.setObjectName("settingsPage")
        applications_layout = QVBoxLayout(applications_page)
        applications_layout.setContentsMargins(22, 18, 22, 18)
        applications_layout.setSpacing(14)
        applications_intro = QLabel(
            "Give individual Windows applications writing and delivery "
            "defaults that override Overall defaults. Starter profiles "
            "demonstrate safer result handling and useful plain-text or "
            "concise output for common editors, mail and messaging apps."
        )
        applications_intro.setObjectName("muted")
        applications_intro.setWordWrap(True)
        applications_layout.addWidget(applications_intro)

        policies_group = QGroupBox("Application-specific defaults")
        policies_layout = QVBoxLayout(policies_group)
        policy_add_row = QHBoxLayout()
        self.application_picker = NoWheelComboBox()
        self.application_picker.setEditable(True)
        self.application_picker.setInsertPolicy(
            QComboBox.InsertPolicy.NoInsert
        )
        self.application_picker.lineEdit().setPlaceholderText(
            "Choose an application or type its executable, for example slack.exe"
        )
        self.application_picker.setAccessibleName(
            "Application executable for profile"
        )
        for label, executable in COMMON_APPLICATIONS:
            self.application_picker.addItem(
                f"{label} ({executable})",
                executable,
            )
        self.add_application_policy_button = QPushButton("Add application")
        self.add_application_policy_button.setAccessibleName(
            "Add application result policy"
        )
        policy_add_row.addWidget(self.application_picker, 1)
        policy_add_row.addWidget(self.add_application_policy_button)
        policies_layout.addLayout(policy_add_row)

        self.application_policy_table = QTableWidget()
        self.application_policy_table.setColumnCount(2)
        self.application_policy_table.setHorizontalHeaderLabels(
            ("Application", "Configured defaults")
        )
        self.application_policy_table.setAccessibleName(
            "Application profiles"
        )
        self.application_policy_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.application_policy_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.application_policy_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.application_policy_table.verticalHeader().hide()
        policy_header = self.application_policy_table.horizontalHeader()
        policy_header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        policy_header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Stretch,
        )
        self.application_policy_table.setMinimumHeight(250)
        policies_layout.addWidget(self.application_policy_table, 1)
        policy_footer = QHBoxLayout()
        policy_note = QLabel(
            "Double-click an application to configure its audience, language, "
            "writing, ChatGPT and result-handling defaults."
        )
        policy_note.setObjectName("muted")
        policy_note.setWordWrap(True)
        self.remove_application_policy_button = QPushButton(
            "Remove selected profile"
        )
        self.remove_application_policy_button.setAccessibleName(
            "Remove selected application profile"
        )
        self.configure_application_policy_button = QPushButton(
            "Configure selected"
        )
        self.configure_application_policy_button.setAccessibleName(
            "Configure selected application"
        )
        policy_footer.addWidget(policy_note, 1)
        policy_footer.addWidget(self.configure_application_policy_button)
        policy_footer.addWidget(self.remove_application_policy_button)
        policies_layout.addLayout(policy_footer)
        applications_layout.addWidget(policies_group, 1)

        recovery_page = QWidget()
        recovery_page.setObjectName("settingsPage")
        recovery_layout = QVBoxLayout(recovery_page)
        recovery_layout.setContentsMargins(22, 18, 22, 18)
        recovery_layout.setSpacing(16)

        backup_group = QGroupBox("Backup and restore")
        backup_layout = QVBoxLayout(backup_group)
        backup_note = QLabel(
            "Create one portable ZIP file containing writing actions, settings, "
            "application profiles, hotkeys, and installed custom icons. Usage "
            "history, logs, update state, selected text, prompts and responses "
            "are not included. Restore validates a backup and automatically "
            "saves the current configuration first."
        )
        backup_note.setObjectName("muted")
        backup_note.setWordWrap(True)
        self.backup_actions_layout = QHBoxLayout()
        self.create_backup_button = QPushButton("Create backup\u2026")
        self.create_backup_button.setAccessibleName(
            "Create configuration backup file"
        )
        self.restore_backup_button = QPushButton("Restore backup\u2026")
        self.restore_backup_button.setAccessibleName(
            "Restore configuration from backup file"
        )
        self.backup_actions_layout.addWidget(self.create_backup_button)
        self.backup_actions_layout.addWidget(self.restore_backup_button)
        self.backup_actions_layout.addStretch(1)
        backup_layout.addWidget(backup_note)
        backup_layout.addLayout(self.backup_actions_layout)

        reset_group = QGroupBox("Reset configuration")
        reset_layout = QVBoxLayout(reset_group)
        reset_note = QLabel(
            "Return actions, settings, application profiles, hotkeys, and "
            "custom icons to the original defaults. PromptMeld creates a "
            "safety backup, closes, and shows first-use setup on the next "
            "launch. Usage history and logs are kept."
        )
        reset_note.setObjectName("muted")
        reset_note.setWordWrap(True)
        reset_buttons = QHBoxLayout()
        self.reset_configuration_button = QPushButton(
            "Reset configuration\u2026"
        )
        self.reset_configuration_button.setObjectName("dangerButton")
        self.reset_configuration_button.setAccessibleName(
            "Reset PromptMeld configuration to defaults"
        )
        reset_buttons.addWidget(self.reset_configuration_button)
        reset_buttons.addStretch(1)
        reset_layout.addWidget(reset_note)
        reset_layout.addLayout(reset_buttons)

        diagnostics_group = QGroupBox("Diagnostics")
        diagnostics_layout = QVBoxLayout(diagnostics_group)
        diagnostics_note = QLabel(
            "Copy privacy-filtered technical information for troubleshooting, "
            "or open the local folder containing PromptMeld's rotating log. "
            "Selected text, prompts and responses are excluded."
        )
        diagnostics_note.setObjectName("muted")
        diagnostics_note.setWordWrap(True)
        diagnostics_buttons = QHBoxLayout()
        self.copy_diagnostics_button = QPushButton("Copy diagnostics")
        self.open_log_folder_button = QPushButton("Open log folder")
        self.copy_diagnostics_button.clicked.connect(
            self.diagnostics_copy_requested.emit
        )
        self.open_log_folder_button.clicked.connect(
            self.diagnostics_open_requested.emit
        )
        diagnostics_buttons.addWidget(self.copy_diagnostics_button)
        diagnostics_buttons.addWidget(self.open_log_folder_button)
        diagnostics_buttons.addStretch(1)
        diagnostics_layout.addWidget(diagnostics_note)
        diagnostics_layout.addLayout(diagnostics_buttons)
        recovery_layout.addWidget(backup_group)
        recovery_layout.addWidget(reset_group)
        recovery_layout.addWidget(diagnostics_group)
        recovery_layout.addStretch(1)

        self.create_backup_button.clicked.connect(
            self._create_configuration_backup
        )
        self.restore_backup_button.clicked.connect(
            self._restore_configuration_backup
        )
        self.reset_configuration_button.clicked.connect(
            self._reset_configuration
        )

        self._load_application_profiles(
            voice_settings.application_profiles
        )
        self.add_application_policy_button.clicked.connect(
            self._add_application_policy
        )
        self.remove_application_policy_button.clicked.connect(
            self._remove_application_policy
        )
        self.configure_application_policy_button.clicked.connect(
            self._edit_selected_application_profile
        )
        self.application_policy_table.cellDoubleClicked.connect(
            lambda row, _column: self._edit_application_profile(row)
        )
        defaults_page = QWidget()
        defaults_page.setObjectName("settingsPage")
        defaults_layout = QVBoxLayout(defaults_page)
        defaults_layout.setContentsMargins(22, 18, 22, 18)
        defaults_layout.setSpacing(12)
        defaults_intro = QLabel(
            "These choices are remembered across launches. An application "
            "profile can override them for one program; choices labelled "
            "This request in the launcher apply only to the current selection."
        )
        defaults_intro.setObjectName("muted")
        defaults_intro.setWordWrap(True)
        defaults_layout.addWidget(defaults_intro)
        defaults_layout.addWidget(output_group)
        defaults_layout.addWidget(submission_group)
        defaults_layout.addWidget(voice_group)
        defaults_layout.addWidget(guided_group)
        defaults_layout.addStretch(1)
        self.tabs.addTab(general_page, "General")
        self.tabs.addTab(applications_page, "Applications")
        self.tabs.addTab(actions_page, "Writing actions")
        self.tabs.addTab(hotkeys_page, "Hotkeys")
        self.tabs.addTab(defaults_page, "Overall defaults")
        self.tabs.addTab(recovery_page, "Backup && recovery")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.check_for_updates.stateChanged.connect(self._mark_unsaved)
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
        self.new_subfolder_button.clicked.connect(self._new_subfolder)
        self.duplicate_button.clicked.connect(self._duplicate_action)
        self.delete_button.clicked.connect(self._delete_action)
        self.up_button.clicked.connect(lambda: self._move_action(-1))
        self.down_button.clicked.connect(lambda: self._move_action(1))
        self.starter_button.clicked.connect(self._load_starter_set)
        self.import_pack_button.clicked.connect(self._import_action_pack)
        self.export_selected_pack_action.triggered.connect(
            lambda: self._export_action_pack(selected_only=True)
        )
        self.export_all_pack_action.triggered.connect(
            lambda: self._export_action_pack(selected_only=False)
        )
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
            self.action_recipient_audience.currentIndexChanged,
            self.guided_drafting.toggled,
            self.instruction.textChanged,
            self.most_used_count.valueChanged,
            self.primary_language.currentTextChanged,
            self.project_name.textChanged,
            self.project_naming_mode.currentIndexChanged,
            self.resulting_text_length.currentIndexChanged,
            self.resulting_text_formatting.currentIndexChanged,
            self.title_subject.currentIndexChanged,
            self.writing_block_default.toggled,
            self.auto_submit_default.toggled,
            self.privacy_preview_default.toggled,
            self.replace_selected_text_default.toggled,
            self.copy_generated_text_default.toggled,
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
            app.paletteChanged.connect(self._system_appearance_changed)
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
        self._refresh_starter_pack_actions()

    def _add_starter_pack_menu_action(
        self,
        menu: QMenu,
        pack: ActionPack,
    ) -> None:
        action = menu.addAction(pack.name)
        action.setToolTip(pack.description)
        action.triggered.connect(
            lambda _checked=False, selected=pack: (
                self._add_builtin_action_pack(selected)
            )
        )
        self.starter_pack_actions[pack.pack_id] = action

    def _refresh_starter_pack_actions(self) -> None:
        if not hasattr(self, "starter_pack_actions"):
            return
        existing_ids = {action.id for action in self.actions}
        any_available = False
        for pack in self.builtin_action_packs:
            menu_action = self.starter_pack_actions.get(pack.pack_id)
            if menu_action is None:
                continue
            missing_count = sum(
                action.id not in existing_ids for action in pack.actions
            )
            if missing_count:
                menu_action.setText(pack.name)
                menu_action.setEnabled(True)
                menu_action.setToolTip(
                    f"{pack.description} Adds {missing_count} action(s)."
                )
                any_available = True
            else:
                menu_action.setText(f"{pack.name} (added)")
                menu_action.setEnabled(False)
                menu_action.setToolTip(
                    f"{pack.description} This pack is already installed."
                )
        self.starter_pack_button.setEnabled(any_available)

    def _tab_changed(self, index: int) -> None:
        if self.tabs.tabText(index) != "Hotkeys":
            return
        self._commit_current()
        self._refresh_hotkey_rows()

    def _refresh_hotkey_rows(self) -> None:
        check_windows = self.hotkey_availability is not None
        assessments = self._hotkey_assessments(check_windows=check_windows)
        self.hotkey_table.setRowCount(0)
        self.launcher_hotkey_editor.set_hotkey(self.popup_hotkey)
        self.hotkey_editors = {
            "__popup__": self.launcher_hotkey_editor,
        }
        self.hotkey_status_labels = {
            "__popup__": self.launcher_hotkey_status,
        }
        def action_sort_key(action: WritingAction) -> tuple:
            state = assessments.get(action.id, ("unchecked", ""))[0]
            priority = (
                2
                if not action.hotkey
                else 0
                if state == "error"
                else 1
            )
            return (
                priority,
                _hotkey_sort_key(action.hotkey or ""),
                action.name.casefold(),
            )

        ordered_actions = sorted(self.actions, key=action_sort_key)
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
            for action in ordered_actions
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
        for command_id, (state, message) in assessments.items():
            self._set_hotkey_status(command_id, state, message)

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

    def _open_setup_guide(self) -> None:
        self._commit_current()
        action_hotkeys = {
            action.hotkey: action.name
            for action in self.actions
            if action.hotkey and action.enabled
        }
        wizard = FirstRunSetupWizard(
            self.popup_hotkey,
            self.hotkey_availability or (lambda _hotkey: True),
            action_hotkeys,
            self.start_with_windows.isChecked(),
            self,
            theme=str(self.theme.currentData() or "auto"),
        )
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return
        self.popup_hotkey = wizard.selected_hotkey()
        self.launcher_hotkey_editor.set_hotkey(self.popup_hotkey)
        self.start_with_windows.setChecked(
            wizard.start_with_windows.isChecked()
        )
        self._update_hotkey_statuses(check_windows=True)
        self._mark_unsaved()

    def _update_hotkey_statuses(self, check_windows: bool = False) -> None:
        for command_id, (state, message) in self._hotkey_assessments(
            check_windows=check_windows
        ).items():
            self._set_hotkey_status(command_id, state, message)

    def _hotkey_assessments(
        self,
        *,
        check_windows: bool,
    ) -> dict[str, tuple[str, str]]:
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
        assessments: dict[str, tuple[str, str]] = {}

        for command_id, _, hotkey, enabled in entries:
            if not hotkey:
                state = "error" if command_id == "__popup__" else "empty"
                message = (
                    "Required"
                    if command_id == "__popup__"
                    else "Not assigned"
                )
                assessments[command_id] = (state, message)
                continue
            try:
                parsed = parse_hotkey(hotkey)
            except HotkeyParseError as exc:
                assessments[command_id] = ("error", str(exc))
                continue
            if not enabled:
                assessments[command_id] = (
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
                assessments[command_id] = (
                    "error",
                    f"Clashes with {', '.join(others)}",
                )

        for command_id, _, hotkey, _ in entries:
            if command_id not in parsed_entries or command_id in clashing:
                continue
            if not check_windows or self.hotkey_availability is None:
                assessments[command_id] = ("unchecked", "Not checked")
                continue
            try:
                available = self.hotkey_availability(hotkey)
            except Exception:
                available = False
            assessments[command_id] = (
                "available" if available else "error",
                (
                    "Available"
                    if available
                    else "Already used by Windows or another app"
                ),
            )
        return assessments

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
            self.action_recipient_audience,
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
            audience_index = self.action_recipient_audience.findData(
                action.recipient_audience
            )
            self.action_recipient_audience.setCurrentIndex(
                max(audience_index, 0)
            )
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
            self.action_recipient_audience.setCurrentIndex(0)
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
            self.action_recipient_audience.setCurrentIndex(0)
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
            recipient_audience=str(
                self.action_recipient_audience.currentData() or "inherit"
            ),
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

    @staticmethod
    def _help_button(text: str, accessible_name: str) -> QToolButton:
        button = QToolButton()
        button.setText("?")
        button.setObjectName("helpIcon")
        button.setAccessibleName(accessible_name)
        button.setAccessibleDescription(text)
        tooltip_text = escape(text).replace(
            " Warning:",
            "<br><br><b>Warning:</b>",
        )
        button.setToolTip(
            "<qt><table width='340' cellspacing='0' cellpadding='0'>"
            f"<tr><td>{tooltip_text}</td></tr></table></qt>"
        )
        button.setAutoRaise(True)
        button.setFixedSize(20, 20)
        button.setCursor(Qt.CursorShape.WhatsThisCursor)
        return button

    def _set_instruction_colour(self) -> None:
        cursor = self.instruction.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        text_format = QTextCharFormat()
        colour = (
            self.palette().color(QPalette.ColorRole.Text)
            if system_high_contrast_enabled()
            else QColor(
                "#202631"
                if resolve_theme(str(self.theme.currentData() or "auto"))
                == "light"
                else "#ffffff"
            )
        )
        text_format.setForeground(colour)
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

    def _load_application_profiles(
        self,
        profiles: dict[str, ApplicationProfile],
    ) -> None:
        self._application_profile_values = dict(profiles)
        self.application_policy_table.setRowCount(0)
        for application, profile in sorted(profiles.items()):
            self._append_application_profile(application, profile)

    def _append_application_profile(
        self,
        application: str,
        profile: ApplicationProfile,
    ) -> None:
        application = normalize_application_name(application)
        if not application:
            return
        self._application_profile_values[application] = profile
        row = self.application_policy_table.rowCount()
        self.application_policy_table.insertRow(row)
        label = application_display_name(application)
        item = QTableWidgetItem(
            f"{label} ({application})" if label != application else application
        )
        item.setData(Qt.ItemDataRole.UserRole, application)
        self.application_policy_table.setItem(row, 0, item)
        summary = QTableWidgetItem(self._application_profile_summary(profile))
        summary.setData(Qt.ItemDataRole.UserRole, application)
        self.application_policy_table.setItem(row, 1, summary)

    @staticmethod
    def _application_profile_summary(profile: ApplicationProfile) -> str:
        result_labels = dict(APPLICATION_RETURN_MODE_OPTIONS)
        parts = []
        if profile.return_mode != "default":
            parts.append(result_labels[profile.return_mode])
        if profile.response_wait != "inherit":
            wait_labels = dict(APPLICATION_RESPONSE_WAIT_OPTIONS)
            parts.append("Wait: " + wait_labels[profile.response_wait])
        if profile.recipient_audience != "inherit":
            audience_labels = dict(RECIPIENT_AUDIENCE_OPTIONS)
            parts.append(
                "Audience: "
                + audience_labels.get(
                    profile.recipient_audience,
                    profile.recipient_audience,
                )
            )
        additional = sum(
            value not in {"", "default", "inherit"}
            for value in (
                profile.primary_language,
                profile.resulting_text_length,
                profile.resulting_text_formatting,
                profile.title_subject,
                profile.editing_strength,
                profile.preserve_facts,
                profile.natural_voice,
                profile.guided_drafting,
                profile.writing_block,
                profile.auto_submit,
                profile.temporary_chat,
                profile.privacy_preview,
                profile.project_name,
            )
        )
        if additional:
            parts.append(
                f"{additional} additional default"
                + ("s" if additional != 1 else "")
            )
        return " \u00b7 ".join(parts) if parts else "Uses overall defaults"

    def _application_profiles(self) -> dict[str, ApplicationProfile]:
        return dict(self._application_profile_values)

    def _application_policies(self) -> dict[str, str]:
        return {
            application: profile.return_mode
            for application, profile in self._application_profiles().items()
            if profile.return_mode != "default"
        }

    def _add_application_policy(self) -> None:
        selected_data = self.application_picker.currentData()
        typed = self.application_picker.currentText().strip()
        application = normalize_application_name(
            str(selected_data) if selected_data else typed
        )
        if not re.fullmatch(r"[a-z0-9_.-]+\.exe", application):
            QMessageBox.warning(
                self,
                "Application executable required",
                "Choose a common application or enter an executable filename "
                "such as slack.exe.",
            )
            return
        for row in range(self.application_policy_table.rowCount()):
            item = self.application_policy_table.item(row, 0)
            if item is not None and item.data(
                Qt.ItemDataRole.UserRole
            ) == application:
                self.application_policy_table.selectRow(row)
                self._edit_application_profile(row)
                return
        self._append_application_profile(
            application,
            ApplicationProfile(return_mode="copy"),
        )
        self.application_policy_table.selectRow(
            self.application_policy_table.rowCount() - 1
        )
        self._mark_unsaved()

    def _edit_selected_application_profile(self) -> None:
        self._edit_application_profile(
            self.application_policy_table.currentRow()
        )

    def _edit_application_profile(self, row: int) -> None:
        if row < 0:
            return
        item = self.application_policy_table.item(row, 0)
        if item is None:
            return
        application = normalize_application_name(
            str(item.data(Qt.ItemDataRole.UserRole) or "")
        )
        profile = self._application_profile_values.get(application)
        if not application or profile is None:
            return
        dialog = ApplicationProfileDialog(
            application,
            profile,
            replace(
                self.application_profile_overall_settings,
                project_name=(
                    self.project_name.text().strip()
                    or self.application_profile_overall_settings.project_name
                ),
                project_naming_mode=str(
                    self.project_naming_mode.currentData() or "action"
                ),
            ),
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.profile()
        self._application_profile_values[application] = updated
        summary = self.application_policy_table.item(row, 1)
        if summary is not None:
            summary.setText(self._application_profile_summary(updated))
        self._mark_unsaved()

    def _remove_application_policy(self) -> None:
        row = self.application_policy_table.currentRow()
        if row < 0:
            return
        item = self.application_policy_table.item(row, 0)
        if item is not None:
            application = normalize_application_name(
                str(item.data(Qt.ItemDataRole.UserRole) or "")
            )
            self._application_profile_values.pop(application, None)
        self.application_policy_table.removeRow(row)
        self._mark_unsaved()

    def _configuration_state(self) -> tuple:
        self._commit_current()
        return (
            tuple(self.actions),
            tuple(sorted(self.folder_icons.items())),
            self.popup_hotkey,
            str(self.theme.currentData() or "auto"),
            self.start_with_windows.isChecked(),
            self.check_for_updates.isChecked(),
            tuple(sorted(self._application_profiles().items())),
            self.most_used_count.value(),
            self.project_name.text().strip(),
            str(self.project_naming_mode.currentData() or "action"),
            self.primary_language.currentText().strip(),
            str(self.resulting_text_length.currentData() or "default"),
            str(self.resulting_text_formatting.currentData() or "default"),
            str(self.title_subject.currentData() or "none"),
            self.writing_block_default.isChecked(),
            self.auto_submit_default.isChecked(),
            self.privacy_preview_default.isChecked(),
            self.replace_selected_text_default.isChecked(),
            self.copy_generated_text_default.isChecked(),
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
        self._add_action_to_folder(self.selected_folder)

    def _add_action_to_folder(self, folder: str) -> None:
        action_id = self._unique_id("new-action")
        source = WritingAction(
            id=action_id,
            name="",
            keywords=(),
            instruction="",
            icon="lucide:wand-sparkles",
            folder=folder,
        )
        wizard = self._action_wizard(source, "create")
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return
        action = wizard.action(action_id)
        self.actions.append(action)
        self._ensure_default_folder_icons((action,))
        self._refresh_list(len(self.actions) - 1)
        self._populate_folder_choices()
        self._mark_unsaved()

    def _new_subfolder(self) -> None:
        self._commit_current()
        has_action = 0 <= self.current_row < len(self.actions)
        selected_parent = (
            self.actions[self.current_row].folder
            if has_action
            else self.selected_folder
        )
        dialog = NestedFolderDialog(
            self._folder_paths(),
            selected_parent,
            moving_action=has_action,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        folder = dialog.folder_path()
        if has_action:
            self.actions[self.current_row] = replace(
                self.actions[self.current_row],
                folder=folder,
            )
            self._ensure_default_folder_icons((self.actions[self.current_row],))
            selected_row = self.current_row
            self._refresh_list(selected_row)
            self._populate_folder_choices()
            self._mark_unsaved()
            return
        self._add_action_to_folder(folder)

    def _folder_paths(self) -> tuple[str, ...]:
        folders: set[str] = set()
        for folder in (
            *(action.folder for action in self.actions),
            *self.folder_icons,
        ):
            parts = folder.split("/") if folder else []
            folders.update(
                "/".join(parts[:depth])
                for depth in range(1, len(parts) + 1)
            )
        return tuple(
            sorted(
                folders,
                key=lambda folder: (folder.count("/"), folder.casefold()),
            )
        )

    def _duplicate_action(self) -> None:
        self._commit_current()
        if not 0 <= self.current_row < len(self.actions):
            return
        source = self.actions[self.current_row]
        action_id = self._unique_id(f"{source.id}-copy")
        source_copy = replace(
            source,
            id=action_id,
            name=f"{source.name} copy",
            hotkey=None,
        )
        wizard = self._action_wizard(source_copy, "duplicate")
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return
        duplicate = wizard.action(action_id)
        insert_at = self.current_row + 1
        self.actions.insert(insert_at, duplicate)
        self._refresh_list(insert_at)
        self._mark_unsaved()

    def _action_wizard(
        self,
        source: WritingAction,
        mode: str,
    ) -> ActionCreationWizard:
        folders = tuple(
            dict.fromkeys(
                action.folder for action in self.actions if action.folder
            )
        )
        used_hotkeys = {self.popup_hotkey: "Open launcher"}
        used_hotkeys.update(
            {
                action.hotkey: action.name
                for action in self.actions
                if action.hotkey and action.enabled
            }
        )
        return ActionCreationWizard(
            source,
            self.icon_provider,
            folders=folders,
            used_hotkeys=used_hotkeys,
            hotkey_availability=self.hotkey_availability,
            mode=mode,
            parent=self,
            theme=str(self.theme.currentData() or "auto"),
        )

    def _delete_action(self) -> None:
        if 0 <= self.current_row < len(self.actions):
            self.actions.pop(self.current_row)
            next_row = min(self.current_row, len(self.actions) - 1)
            self._refresh_list(next_row)
            self._mark_unsaved()
            return

        folder = self.selected_folder
        if not folder:
            return
        prefix = f"{folder}/"
        affected_indexes = [
            index
            for index, action in enumerate(self.actions)
            if action.folder == folder or action.folder.startswith(prefix)
        ]
        if not affected_indexes:
            return
        nested_folders = self._nested_folder_count(folder, affected_indexes)
        if not self._confirm_delete_folder(
            folder,
            len(affected_indexes),
            nested_folders,
        ):
            return

        first_removed = min(affected_indexes)
        affected = set(affected_indexes)
        self.actions = [
            action
            for index, action in enumerate(self.actions)
            if index not in affected
        ]
        for icon_folder in tuple(self.folder_icons):
            if icon_folder == folder or icon_folder.startswith(prefix):
                self.folder_icons.pop(icon_folder, None)
        next_row = min(first_removed, len(self.actions) - 1)
        self._refresh_list(next_row)
        self._populate_folder_choices()
        self._mark_unsaved()

    def _nested_folder_count(
        self,
        folder: str,
        affected_indexes: list[int],
    ) -> int:
        """Count visible descendant folders represented by affected actions."""

        base_depth = folder.count("/") + 1
        descendants: set[str] = set()
        for index in affected_indexes:
            action_folder = self.actions[index].folder
            parts = action_folder.split("/")
            for depth in range(base_depth + 1, len(parts) + 1):
                descendants.add("/".join(parts[:depth]))
        return len(descendants)

    def _confirm_delete_folder(
        self,
        folder: str,
        action_count: int,
        nested_folder_count: int,
    ) -> bool:
        message = self._folder_delete_confirmation_message(
            folder,
            action_count,
            nested_folder_count,
        )
        message.exec()
        return message.clickedButton() is message.delete_folder_button

    def _folder_delete_confirmation_message(
        self,
        folder: str,
        action_count: int,
        nested_folder_count: int,
    ) -> QMessageBox:
        action_word = "action" if action_count == 1 else "actions"
        nested_note = (
            f" and {nested_folder_count} nested "
            f"{'folder' if nested_folder_count == 1 else 'folders'}"
            if nested_folder_count
            else ""
        )
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("Delete writing action folder?")
        message.setText(f'Delete the folder "{folder}"?')
        message.setInformativeText(
            f"This will remove {action_count} writing {action_word}"
            f"{nested_note}. The change takes effect when you save "
            "Configuration."
        )
        message.setAccessibleName("Confirm writing action folder deletion")
        message.setAccessibleDescription(
            f"Delete {folder}, {action_count} writing {action_word}"
            f"{nested_note}."
        )
        delete_button = message.addButton(
            "Delete folder and actions",
            QMessageBox.ButtonRole.DestructiveRole,
        )
        delete_button.setObjectName("deleteWritingActionFolderButton")
        delete_button.setAccessibleName(
            f"Delete {folder} and all writing actions inside it"
        )
        cancel_button = message.addButton(QMessageBox.StandardButton.Cancel)
        cancel_button.setAccessibleName("Keep folder and actions")
        message.setDefaultButton(cancel_button)
        message.setEscapeButton(cancel_button)
        message.delete_folder_button = delete_button
        message.setMinimumWidth(540)
        message.setStyleSheet(
            message_box_stylesheet(str(self.theme.currentData() or "auto"))
        )
        return message

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

    def _create_configuration_backup(self) -> None:
        if self.has_unsaved_changes():
            response = QMessageBox.question(
                self,
                "Unsaved configuration changes",
                "Save the current changes before creating the backup?\n\n"
                "Choose Yes to save and include them. Choose No to back up "
                "the last saved configuration while keeping these editor "
                "changes open.",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if response == QMessageBox.StandardButton.Cancel:
                return
            if response == QMessageBox.StandardButton.Yes and not self._save():
                return

        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        default_name = (
            f"PromptMeld-backup-v{display_version()}-{timestamp}.zip"
        )
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Create PromptMeld configuration backup",
            str(Path.home() / default_name),
            "PromptMeld backup (*.zip)",
        )
        if not filename:
            return
        destination = Path(filename)
        if destination.suffix.casefold() != ".zip":
            destination = destination.with_name(destination.name + ".zip")
        if destination.exists():
            overwrite = QMessageBox.question(
                self,
                "Replace existing backup?",
                f"A file already exists at:\n\n{destination}\n\nReplace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                return
        try:
            summary = create_configuration_backup(self.paths, destination)
        except (ConfigurationBackupError, OSError) as exc:
            QMessageBox.warning(
                self,
                "Backup could not be created",
                str(exc),
            )
            return
        QMessageBox.information(
            self,
            "Configuration backup created",
            f"Saved one backup file containing {summary.action_count} writing "
            f"actions and {summary.icon_count} custom icon(s):\n\n"
            f"{destination}",
        )

    def _restore_configuration_backup(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Restore PromptMeld configuration backup",
            str(Path.home()),
            "PromptMeld backup (*.zip)",
        )
        if not filename:
            return
        archive = Path(filename)
        try:
            summary = inspect_configuration_backup(archive)
        except (ConfigurationBackupError, OSError) as exc:
            QMessageBox.warning(
                self,
                "Backup cannot be restored",
                str(exc),
            )
            return

        unsaved_note = (
            "\n\nUnsaved changes currently shown in Configuration will be "
            "discarded."
            if self.has_unsaved_changes()
            else ""
        )
        response = QMessageBox.question(
            self,
            "Restore configuration backup?",
            f"Backup created: {summary.created_at}\n"
            f"PromptMeld version: {summary.app_version or 'Unknown'}\n"
            f"Backup format: version {summary.format_version}\n"
            f"Writing actions: {summary.action_count}\n"
            f"Custom icons: {summary.icon_count}\n\n"
            "This will replace the saved actions and settings. PromptMeld "
            "will first create an automatic safety backup."
            f"{unsaved_note}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        try:
            result = restore_configuration_backup(self.paths, archive)
        except (ConfigurationBackupError, OSError) as exc:
            QMessageBox.warning(
                self,
                "Configuration could not be restored",
                str(exc),
            )
            return

        QMessageBox.information(
            self,
            "Configuration restored",
            "The backup was restored successfully. Configuration will close "
            "so PromptMeld can reload it.\n\n"
            f"Safety backup:\n{result.safety_backup}",
        )
        self.configuration_restored.emit()
        self.accept()

    def _confirm_configuration_reset(self) -> bool:
        message = self._configuration_reset_message()
        message.exec()
        return message.clickedButton() is message.reset_button

    def _configuration_reset_message(self) -> QMessageBox:
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("Reset PromptMeld configuration?")
        message.setText(
            "Reset all PromptMeld configuration to the original defaults?"
        )
        unsaved_note = (
            " Unsaved changes in this window will also be discarded."
            if self.has_unsaved_changes()
            else ""
        )
        message.setInformativeText(
            "Writing actions, application profiles, hotkeys, writing defaults, "
            "and custom icons will be reset. A safety backup will be created "
            "first. PromptMeld will then close, and the first-use setup guide "
            f"will appear on the next launch.{unsaved_note}"
        )
        reset_button = message.addButton(
            "Reset configuration",
            QMessageBox.ButtonRole.DestructiveRole,
        )
        reset_button.setObjectName("resetConfigurationButton")
        cancel_button = message.addButton(
            QMessageBox.StandardButton.Cancel
        )
        cancel_button.setObjectName("cancelConfigurationButton")
        message.setDefaultButton(cancel_button)
        message.reset_button = reset_button
        message.setMinimumWidth(560)
        message.setStyleSheet(self._reset_message_box_stylesheet())
        return message

    def _reset_message_box_stylesheet(self) -> str:
        return message_box_stylesheet(
            str(self.theme.currentData() or "auto")
        )

    def _reset_configuration(self) -> None:
        if not self._confirm_configuration_reset():
            return
        try:
            result = reset_configuration_to_defaults(self.paths)
        except (ConfigurationBackupError, OSError) as exc:
            QMessageBox.warning(
                self,
                "Configuration could not be reset",
                str(exc),
            )
            return

        QMessageBox.information(
            self,
            "Configuration reset",
            "PromptMeld has been reset to its original defaults and will now "
            "close. The first-use setup guide will appear the next time it is "
            "opened.\n\n"
            f"Safety backup:\n{result.safety_backup}",
        )
        self.accept()
        self.configuration_reset.emit()

    def _load_starter_set(self) -> None:
        response = QMessageBox.question(
            self,
            "Restore essential actions",
            "Replace the actions currently shown in this editor with the shipped "
            "set of four essential actions?\n\nNothing is written until you "
            "choose Save. Canceling the window will keep your existing "
            "configuration.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        self.actions = load_default_actions()
        self.folder_icons = {}
        self._ensure_default_folder_icons(self.actions)
        self._populate_folder_choices()
        self._refresh_list(0 if self.actions else -1)
        self._mark_unsaved()

    def _apply_action_pack(self, pack: ActionPack) -> None:
        self._commit_current()
        result = merge_action_pack(self.actions, pack)
        self.actions = result.actions
        self._ensure_default_folder_icons(pack.actions)
        self._populate_folder_choices()
        self._refresh_list(result.first_added_index)
        self._mark_unsaved()
        adjustments: list[str] = []
        if result.renamed_count:
            adjustments.append(
                f"adapted {result.renamed_count} duplicate internal ID(s)"
            )
        if result.cleared_hotkey_count:
            adjustments.append(
                f"cleared {result.cleared_hotkey_count} clashing shortcut(s)"
            )
        adjustment_note = (
            "\n\nPromptMeld " + " and ".join(adjustments) + "."
            if adjustments
            else ""
        )
        QMessageBox.information(
            self,
            "Action pack added",
            f"Added {result.added_count} action(s) from {pack.name}."
            f"{adjustment_note}\n\nChoose Save to keep these changes.",
        )

    def _add_builtin_action_pack(self, pack: ActionPack) -> None:
        self._commit_current()
        existing_ids = {action.id for action in self.actions}
        missing_actions = tuple(
            action for action in pack.actions if action.id not in existing_ids
        )
        if not missing_actions:
            QMessageBox.information(
                self,
                "Starter pack already added",
                f"All actions from {pack.name} are already in this library.",
            )
            self._refresh_starter_pack_actions()
            return

        action_list = "\n".join(
            f"  • {action.name}" for action in missing_actions
        )
        skipped_count = len(pack.actions) - len(missing_actions)
        existing_note = (
            f"\n\n{skipped_count} action(s) already in the library will not "
            "be duplicated."
            if skipped_count
            else ""
        )
        response = QMessageBox.question(
            self,
            f"Add {pack.name}?",
            f"{pack.description}\n\n"
            f"Add these {len(missing_actions)} actions?\n\n{action_list}"
            f"{existing_note}\n\n"
            "Existing actions will remain. Nothing is written until you "
            "choose Save.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if response == QMessageBox.StandardButton.Yes:
            self._apply_action_pack(replace(pack, actions=missing_actions))

    def _import_action_pack(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Import PromptMeld action pack",
            str(Path.home()),
            "PromptMeld action pack (*.json);;JSON files (*.json)",
        )
        if not filename:
            return
        try:
            pack = load_action_pack(Path(filename))
        except (ActionPackError, OSError) as exc:
            QMessageBox.warning(
                self,
                "Action pack could not be imported",
                str(exc),
            )
            return
        response = QMessageBox.question(
            self,
            f"Import {pack.name}?",
            f"{pack.description or 'No description supplied.'}\n\n"
            f"Add {len(pack.actions)} action(s) to the current library? "
            "Existing actions will remain. JSON packs do not embed custom "
            "image files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if response == QMessageBox.StandardButton.Yes:
            self._apply_action_pack(pack)

    def _export_action_pack(self, selected_only: bool) -> None:
        self._commit_current()
        if selected_only:
            if not 0 <= self.current_row < len(self.actions):
                QMessageBox.warning(
                    self,
                    "Choose an action",
                    "Select a writing action to export.",
                )
                return
            selected = self.actions[self.current_row]
            pack = ActionPack(
                name=selected.name,
                description=(
                    f"A PromptMeld action pack containing {selected.name}."
                ),
                actions=(selected,),
            )
            default_name = f"PromptMeld-action-{selected.id}.json"
        else:
            if not self.actions:
                QMessageBox.warning(
                    self,
                    "No actions to export",
                    "The action library is empty.",
                )
                return
            pack = ActionPack(
                name="My PromptMeld actions",
                description=(
                    "A readable export of my PromptMeld writing-action library."
                ),
                actions=tuple(self.actions),
            )
            default_name = "PromptMeld-action-library.json"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export PromptMeld action pack",
            str(Path.home() / default_name),
            "PromptMeld action pack (*.json)",
        )
        if not filename:
            return
        destination = Path(filename)
        if destination.suffix.casefold() != ".json":
            destination = destination.with_name(destination.name + ".json")
        if destination.exists():
            overwrite = QMessageBox.question(
                self,
                "Replace existing action pack?",
                f"A file already exists at:\n\n{destination}\n\nReplace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                return
        try:
            save_action_pack(destination, pack)
        except (ActionPackError, OSError) as exc:
            QMessageBox.warning(
                self,
                "Action pack could not be exported",
                str(exc),
            )
            return
        QMessageBox.information(
            self,
            "Action pack exported",
            f"Saved {len(pack.actions)} action(s) as readable JSON:\n\n"
            f"{destination}\n\nCustom image files are referenced but are not "
            "embedded in an action pack.",
        )

    def _restore_natural_voice_wording(self) -> None:
        self.natural_voice_instruction.setPlainText(
            DEFAULT_NATURAL_VOICE_INSTRUCTION
        )

    def _save(self) -> bool:
        self._commit_current()
        try:
            actions = self._validated_actions()
            folder_icons = self._validated_folder_icons(actions)
            if self.settings is not None:
                self.settings = replace(
                    self.settings,
                    project_name=self.project_name.text().strip(),
                    project_naming_mode=str(
                        self.project_naming_mode.currentData() or "action"
                    ),
                    popup_hotkey=self.popup_hotkey,
                    theme=str(self.theme.currentData() or "auto"),
                    startup_enabled=self.start_with_windows.isChecked(),
                    check_for_updates_enabled=(
                        self.check_for_updates.isChecked()
                    ),
                    application_return_policies=(
                        self._application_policies()
                    ),
                    application_profiles=self._application_profiles(),
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
                    privacy_preview_enabled=(
                        self.privacy_preview_default.isChecked()
                    ),
                    replace_selected_text_enabled=(
                        self.replace_selected_text_default.isChecked()
                    ),
                    copy_generated_text_enabled=(
                        self.copy_generated_text_default.isChecked()
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
                    title_subject=str(
                        self.title_subject.currentData() or "none"
                    ),
                    writing_block_enabled=(
                        self.writing_block_default.isChecked()
                    ),
                    guided_drafting_enabled=(
                        self.guided_drafting_default.isChecked()
                    ),
                )
                save_settings(self.paths.settings_file, self.settings)
                self.application_profile_overall_settings = self.settings
            save_actions(self.paths.actions_file, actions)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Cannot save actions", str(exc))
            return False
        self.actions = actions
        self.folder_icons = folder_icons
        self._saved_state = self._configuration_state()
        self._set_close_button_dirty(False)
        self.actions_saved.emit()
        self._set_save_status("Changes saved", saved=True)
        return True

    def has_unsaved_changes(self) -> bool:
        return bool(
            self._saved_state is not None
            and self._configuration_state() != self._saved_state
        )

    def save_changes(self) -> bool:
        return self._save()

    def set_update_status(
        self,
        message: str,
        *,
        checking: bool = False,
        release_available: bool = False,
        install_available: bool = False,
        version: str = "",
    ) -> None:
        self.update_status.setText(message)
        self.check_updates_button.setEnabled(not checking)
        self.view_update_release_button.setEnabled(release_available)
        self.install_update_button.setEnabled(
            install_available and not checking
        )
        self.install_update_button.setText(
            f"Download and install v{version}"
            if install_available and version
            else "Download and install"
        )

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
            if action.recipient_audience not in {
                "inherit",
                *dict(RECIPIENT_AUDIENCE_OPTIONS),
            }:
                raise ValueError(
                    f"'{action.name}' has an invalid default audience."
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

    def _ensure_default_folder_icons(
        self,
        actions: tuple[WritingAction, ...] | list[WritingAction],
    ) -> None:
        for action in actions:
            parts = action.folder.split("/") if action.folder else []
            for depth in range(1, len(parts) + 1):
                folder = "/".join(parts[:depth])
                icon = DEFAULT_FOLDER_ICONS.get(folder)
                if icon:
                    self.folder_icons.setdefault(folder, icon)

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
        has_folder = bool(self.selected_folder) and not has_action
        if has_action:
            self.new_subfolder_button.setToolTip(
                "Choose a parent folder, create one nested level, and move "
                "the selected writing action into it."
            )
            self.new_subfolder_button.setAccessibleDescription(
                "Moves the selected writing action into a newly named nested "
                "folder."
            )
        else:
            self.new_subfolder_button.setToolTip(
                "Choose a parent folder, name one nested level, then create "
                "the first writing action in it."
            )
            self.new_subfolder_button.setAccessibleDescription(
                "Creates a writing action in a newly named nested folder."
            )
        self.duplicate_button.setEnabled(has_action)
        self.delete_button.setEnabled(has_action or has_folder)
        if has_folder:
            self.delete_button.setText("Delete folder")
            self.delete_button.setAccessibleName(
                f"Delete folder {self.selected_folder} and its writing actions"
            )
            self.delete_button.setToolTip(
                "Delete this folder, its nested folders, and every writing "
                "action inside them. You will be asked to confirm."
            )
        elif has_action:
            self.delete_button.setText("Delete action")
            self.delete_button.setAccessibleName("Delete selected writing action")
            self.delete_button.setToolTip("Delete the selected writing action.")
        else:
            self.delete_button.setText("Delete")
            self.delete_button.setAccessibleName(
                "Delete selected writing action or folder"
            )
            self.delete_button.setToolTip(
                "Select a writing action or folder to delete it."
            )
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

    def _system_appearance_changed(self, *args) -> None:
        self._apply_style()

    def _update_project_naming_example(self, *args) -> None:
        base = self.project_name.text().strip() or "PromptMeld"
        mode = str(self.project_naming_mode.currentData() or "action")
        if mode == "single":
            example = base
            explanation = "Every request uses this one project."
        elif mode == "application":
            example = f"{base} - Microsoft Outlook"
            explanation = (
                "The source application's friendly name is appended."
            )
        else:
            example = f"{base} - Editing"
            explanation = (
                "The writing action's configured folder is appended."
            )
        self.project_naming_example.setText(
            f"Example: {example}. {explanation} Temporary Chat still skips "
            "Projects."
        )

    def _update_about_link(self, light: bool) -> None:
        if system_high_contrast_enabled():
            self.github_link.setText(
                f'<a href="{REPOSITORY_URL}">View PromptMeld on GitHub</a>'
            )
            return
        colour = "#244fae" if light else "#b8c8ff"
        self.github_link.setText(
            f'<a href="{REPOSITORY_URL}" style="color: {colour};">'
            "View PromptMeld on GitHub</a>"
        )

    def _apply_style(self, *args) -> None:
        apply_message_box_theme(str(self.theme.currentData() or "auto"))
        if system_high_contrast_enabled():
            colour = self.palette().color(QPalette.ColorRole.WindowText).name()
            self.branch_arrow_style.set_arrow_colour(colour)
            self.action_list.viewport().update()
            self.setStyleSheet(
                high_contrast_stylesheet()
                + message_box_stylesheet(
                    str(self.theme.currentData() or "auto")
                )
            )
            self._set_instruction_colour()
            self._update_about_link(light=True)
            return
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
                QToolButton#helpIcon {
                    color: #244fae;
                    background-color: #eef3ff;
                    border: 1px solid #9bafe2;
                    border-radius: 9px;
                    padding: 0;
                    font-weight: 700;
                }
                QToolButton#helpIcon:hover { background-color: #dce7ff; }
                QLabel#warning {
                    color: #8a1c1c;
                    background-color: #fff0f0;
                    border: 1px solid #d89a9a;
                    border-radius: 5px;
                    padding: 3px 6px;
                    font-weight: 600;
                }
                QToolTip {
                    color: #202631;
                    background-color: #ffffff;
                    border: 1px solid #aeb8c5;
                    padding: 5px;
                }
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
                QTableWidget::item {
                    color: #202631;
                    background: transparent;
                }
                QTableWidget::item:selected {
                    color: #173a87;
                    background: #dce7ff;
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
                QPushButton#dangerButton {
                    color: #8a1c1c;
                    background: #fff0f0;
                    border-color: #d89a9a;
                    font-weight: 600;
                }
                QPushButton#dangerButton:hover { background: #ffe1e1; }
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
            self.setStyleSheet(
                self.styleSheet() + message_box_stylesheet("light")
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
            QToolButton#helpIcon {
                color: #d9e2ff;
                background-color: #2b3347;
                border: 1px solid #6679ad;
                border-radius: 9px;
                padding: 0;
                font-weight: 700;
            }
            QToolButton#helpIcon:hover { background-color: #364468; }
            QLabel#warning {
                color: #ffd1d1;
                background-color: #3b2326;
                border: 1px solid #8a4a50;
                border-radius: 5px;
                padding: 3px 6px;
                font-weight: 600;
            }
            QToolTip {
                color: #f4f5f7;
                background-color: #22252c;
                border: 1px solid #596273;
                padding: 5px;
            }
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
            QPushButton#dangerButton {
                color: #ffd1d1;
                background: #3b2326;
                border-color: #8a4a50;
                font-weight: 600;
            }
            QPushButton#dangerButton:hover { background: #4a292d; }
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
        self.setStyleSheet(
            self.styleSheet() + message_box_stylesheet("dark")
        )
        self._set_instruction_colour()
        self._update_about_link(light=False)
