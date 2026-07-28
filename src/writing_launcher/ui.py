from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from .actions import ActionRegistry
from .branding import APP_NAME, TAGLINE
from .icons import ActionIconProvider


class LauncherPopup(QWidget):
    action_requested = Signal(str)
    custom_requested = Signal(str)
    natural_voice_changed = Signal(bool)
    auto_submit_changed = Signal(bool)
    ITEM_KIND_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(
        self,
        registry: ActionRegistry,
        icon_provider: ActionIconProvider | None = None,
        home_most_used_count: int = 3,
        folder_icons: dict[str, str] | None = None,
        natural_voice_enabled: bool = False,
        auto_submit_enabled: bool = False,
    ):
        super().__init__()
        self.registry = registry
        self.icon_provider = icon_provider
        self.home_most_used_count = home_most_used_count
        self.folder_icons = dict(folder_icons or {})
        self.natural_voice_enabled = natural_voice_enabled
        self.auto_submit_enabled = auto_submit_enabled
        self.current_folder = ""
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(500, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setObjectName("launcherFrame")
        root.addWidget(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        self.title = QLabel(APP_NAME)
        self.title.setObjectName("title")
        self.tagline = QLabel(TAGLINE)
        self.tagline.setObjectName("tagline")
        hint = QLabel("Enter to run  •  Esc to close")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        title_row.addWidget(self.title)
        title_row.addStretch(1)
        title_row.addWidget(self.tagline)
        title_row.addSpacing(12)
        title_row.addWidget(hint)
        layout.addLayout(title_row)


        self.location = QLabel()
        self.location.setObjectName("breadcrumb")
        self.location.hide()
        layout.addWidget(self.location)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search writing actions…")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setUniformItemSizes(False)
        self.list.setSpacing(2)
        self.list.setIconSize(QSize(36, 36))
        layout.addWidget(self.list, 1)

        self.natural_voice = QCheckBox("Preserve my natural voice")
        self.natural_voice.setChecked(self.natural_voice_enabled)
        self.natural_voice.setToolTip(
            "Keep your vocabulary and level of formality, avoid generic filler, "
            "and make only the changes needed for the selected task."
        )
        self.auto_submit = QCheckBox("Submit automatically")
        self.auto_submit.setChecked(self.auto_submit_enabled)
        self.auto_submit.setToolTip(
            "When off, the prompt is pasted into ChatGPT but left unsent so you "
            "can choose the model or reasoning level before pressing Enter."
        )
        option_row = QHBoxLayout()
        option_row.addWidget(self.natural_voice)
        option_row.addStretch(1)
        option_row.addWidget(self.auto_submit)
        layout.addLayout(option_row)

        custom_label = QLabel("Or use a one-off instruction")
        custom_label.setObjectName("hint")
        layout.addWidget(custom_label)

        custom_row = QHBoxLayout()
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("e.g. Make this more diplomatic")
        self.custom_send = QPushButton("Send")
        self.custom_send.setDefault(False)
        custom_row.addWidget(self.custom, 1)
        custom_row.addWidget(self.custom_send)
        layout.addLayout(custom_row)

        self.search.textChanged.connect(self.refresh)
        self.search.returnPressed.connect(self._run_current)
        self.custom.returnPressed.connect(self._run_custom)
        self.custom_send.clicked.connect(self._run_custom)
        self.list.itemActivated.connect(self._run_item)
        self.list.itemDoubleClicked.connect(self._run_item)
        self.natural_voice.toggled.connect(self._natural_voice_toggled)
        self.auto_submit.toggled.connect(self._auto_submit_toggled)
        self._apply_style()
        self.refresh()

    def set_registry(
        self,
        registry: ActionRegistry,
        home_most_used_count: int | None = None,
        folder_icons: dict[str, str] | None = None,
        natural_voice_enabled: bool | None = None,
        auto_submit_enabled: bool | None = None,
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

    def _auto_submit_toggled(self, enabled: bool) -> None:
        self.auto_submit_enabled = enabled
        self.auto_submit_changed.emit(enabled)

    def show_at_cursor(self) -> None:
        self.current_folder = ""
        self.search.clear()
        self.custom.clear()
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
            for action in self.registry.search(query):
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
        most_used = self.registry.most_used(
            self.home_most_used_count,
            exclude_ids=direct_ids,
        )
        most_used_ids = {action.id for action in most_used}
        folders = self._child_folders()
        root_actions = [
            action
            for action in self.registry.search("")
            if not action.folder
            and action.id not in direct_ids
            and action.id not in most_used_ids
        ]

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
            for action in self.registry.search("")
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
        item.setToolTip(action.instruction)
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

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        if not self.isActiveWindow():
            self.hide()

    def _run_current(self) -> None:
        item = self.list.currentItem()
        if item:
            self._run_item(item)

    def _run_item(self, item: QListWidgetItem) -> None:
        kind = item.data(self.ITEM_KIND_ROLE)
        value = item.data(Qt.ItemDataRole.UserRole)
        if kind in {"folder", "back"}:
            self.current_folder = str(value or "")
            self.refresh()
            self.list.setFocus()
            return
        if kind == "action" and value:
            self.hide()
            self.action_requested.emit(str(value))

    def _run_custom(self) -> None:
        instruction = self.custom.text().strip()
        if instruction:
            self.hide()
            self.custom_requested.emit(instruction)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QFrame#launcherFrame {
                background: #16181d;
                border: 1px solid #343842;
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
            QLineEdit {
                color: #f4f5f7;
                background: #22252c;
                border: 1px solid #3a3f4a;
                border-radius: 8px;
                padding: 9px 10px;
                selection-background-color: #3e6ae1;
            }
            QLineEdit:focus { border-color: #6d8df2; }
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
            QCheckBox {
                color: #d9dce3;
                spacing: 8px;
                padding: 2px 1px;
            }
            """
        )
