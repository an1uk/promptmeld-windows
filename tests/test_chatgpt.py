from __future__ import annotations

from dataclasses import dataclass

from promptmeld.chatgpt import (
    ChatGPTDesktop,
    _click_control_on_virtual_desktop,
)


@dataclass
class ElementInfo:
    name: str
    control_type: str
    class_name: str = ""
    enabled: bool = True
    visible: bool = True
    automation_id: str = ""


class FakeControl:
    def __init__(
        self,
        name: str,
        control_type: str,
        events: list[str],
        class_name: str = "",
        enabled: bool = True,
        visible: bool = True,
        automation_id: str = "",
        on_click=None,
    ):
        self.element_info = ElementInfo(
            name,
            control_type,
            class_name,
            enabled,
            visible,
            automation_id,
        )
        self.events = events
        self.on_click = on_click

    def click_input(self):
        self.events.append(f"mouse:{self.element_info.name}")
        if self.on_click is not None:
            self.on_click()

    def click(self):
        self.events.append(f"click:{self.element_info.name}")
        if self.on_click is not None:
            self.on_click()

    def set_focus(self):
        self.events.append(f"focus:{self.element_info.name}")


class FakeComposer(FakeControl):
    def __init__(self, events: list[str]):
        super().__init__("Message ChatGPT", "Edit", events)
        self.value = ""

    def set_edit_text(self, text: str):
        self.events.append("set-text:Message ChatGPT")
        self.value = text

    def get_value(self):
        return self.value


class FakeWindow(FakeControl):
    def __init__(self, controls, events):
        super().__init__("ChatGPT", "Window", events)
        self.controls = controls

    def descendants(self):
        return self.controls


class FakeDesktop:
    def __init__(self, window):
        self.window = window

    def windows(self, **kwargs):
        return [self.window]


def test_submit_navigates_project_and_restores_clipboard():
    events: list[str] = []
    clipboard: list[str] = []
    controls = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeControl("WritingLauncher", "Button", events),
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        ),
        FakeComposer(events),
    ]
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=clipboard.append,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.submitted is True
    assert events == [
        "focus:ChatGPT",
        "click:New chat",
        "click:Chat",
        "click:WritingLauncher",
        "set-text:Message ChatGPT",
        "focus:Message ChatGPT",
        "keys:{ENTER}",
    ]
    assert clipboard == ["selected source"]


def test_prepare_only_inserts_prompt_without_pressing_enter():
    events: list[str] = []
    clipboard: list[str] = []
    controls = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeControl("WritingLauncher", "Button", events),
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        ),
        FakeComposer(events),
    ]
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=clipboard.append,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )

    result = adapter.submit(
        "complete prompt",
        "WritingLauncher",
        auto_submit=False,
    )

    assert result.submitted is False
    assert result.prepared is True
    assert result.fallback_copied is False
    assert "model or reasoning level" in result.message
    assert "set-text:Message ChatGPT" in events
    assert "keys:{ENTER}" not in events
    assert clipboard == ["selected source"]


def test_composer_uses_targeted_clipboard_paste_when_uia_input_fails():
    clipboard = {"text": "selected source"}
    events: list[str] = []

    class ClipboardComposer(FakeComposer):
        def set_edit_text(self, text: str):
            raise RuntimeError("ValuePattern unavailable")

        def type_keys(self, keys: str, **kwargs):
            self.events.append(f"type-keys:{keys}")
            self.value = clipboard["text"]

    composer = ClipboardComposer(events)
    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: clipboard.update(text=text),
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.2,
    )

    method = adapter._set_composer_prompt(composer, "complete prompt")

    assert method == "clipboard"
    assert composer.value == "complete prompt"
    assert events == ["type-keys:^a^v"]


def test_submit_does_not_press_enter_when_composer_rejects_prompt():
    events: list[str] = []
    clipboard: list[str] = []

    class RejectingComposer(FakeComposer):
        def set_edit_text(self, text: str):
            self.events.append("reject-uia")

        def type_keys(self, keys: str, **kwargs):
            self.events.append(f"reject-type-keys:{keys}")

    composer = RejectingComposer(events)
    controls = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeControl("WritingLauncher", "Button", events),
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        ),
        composer,
    ]
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(
            FakeWindow(controls, events)
        ),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=clipboard.append,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.1,
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.submitted is False
    assert result.fallback_copied is True
    assert "keys:{ENTER}" not in events
    assert clipboard[-1] == "complete prompt"


def test_submit_copies_prompt_when_project_controls_are_missing():
    events: list[str] = []
    clipboard: list[str] = []
    window = FakeWindow([], events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=clipboard.append,
        send_keys=lambda *args, **kwargs: None,
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.submitted is False
    assert result.fallback_copied is True
    assert clipboard == ["complete prompt"]


def test_submit_switches_from_codex_to_chatgpt_before_selecting_project():
    events: list[str] = []
    mode_switch = FakeControl(
        "Switch mode, current mode: Codex",
        "Button",
        events,
    )
    mode_item = FakeControl(
        "ChatGPT Create, learn, and explore",
        "MenuItem",
        events,
        on_click=lambda: setattr(
            mode_switch.element_info,
            "name",
            "Switch mode, current mode: ChatGPT",
        ),
    )
    controls = [
        mode_switch,
        mode_item,
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeControl("WritingLauncher", "Button", events),
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        ),
        FakeComposer(events),
    ]
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.submitted is True
    assert events.index("click:Switch mode, current mode: Codex") < events.index(
        "click:ChatGPT Create, learn, and explore"
    )
    assert events.index(
        "click:ChatGPT Create, learn, and explore"
    ) < events.index("click:Chat")
    assert events.index("click:Chat") < events.index("click:WritingLauncher")


def test_submit_creates_missing_writinglauncher_project():
    events: list[str] = []
    clipboard: list[str] = []
    controls: list[FakeControl] = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeComposer(events),
        FakeControl("Add new project", "Button", events),
        FakeControl(
            "Project name",
            "Edit",
            events,
            automation_id="chatgpt-project-name",
        ),
    ]

    def finish_creation():
        controls.extend(
            [
                FakeControl(
                    "Change project: WritingLauncher",
                    "Button",
                    events,
                ),
            ]
        )

    controls.append(
        FakeControl(
            "Create project",
            "Button",
            events,
            on_click=finish_creation,
        )
    )
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=clipboard.append,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.submitted is True
    assert "click:Add new project" in events
    assert "focus:Project name" in events
    assert "click:Create project" in events
    assert clipboard == [
        "WritingLauncher",
        "selected source",
    ]


def test_existing_empty_project_is_selected_after_show_more():
    events: list[str] = []
    controls: list[FakeControl] = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item focus-visible:outline",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeComposer(events),
        FakeControl("Projects", "Button", events),
    ]

    def reveal_projects():
        for _ in range(3):
            new_chat = FakeControl(
                "New chat in WritingLauncher",
                "Button",
                events,
            )
            new_chat.on_click = lambda: controls.append(
                FakeControl(
                    "Change project: WritingLauncher",
                    "Button",
                    events,
                )
            )
            controls.append(new_chat)

    controls.append(
        FakeControl(
            "Show more",
            "Button",
            events,
            on_click=reveal_projects,
        )
    )
    controls.append(FakeControl("Add new project", "Button", events))
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.2,
    )

    result = adapter.submit("complete prompt", "WritingLauncher")

    assert result.submitted is True
    assert events.count("click:Show more") == 1
    assert events.count("click:New chat in WritingLauncher") == 1
    assert "click:Add new project" not in events


def test_project_creation_supports_two_stage_projects_index():
    events: list[str] = []
    controls: list[FakeControl] = []
    add_project = FakeControl("Add new project", "Button", events)
    search = FakeControl(
        "Search projects",
        "Edit",
        events,
        automation_id="projects-index-search",
    )
    name_edit = FakeControl(
        "Project name",
        "Edit",
        events,
        automation_id="chatgpt-project-name",
    )
    create = FakeControl("Create project", "Button", events)
    controls.append(add_project)
    activations = 0

    def advance_creation():
        nonlocal activations
        activations += 1
        if activations == 1:
            controls.append(search)
        else:
            controls.remove(search)
            controls.extend([name_edit, create])

    add_project.on_click = advance_creation
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        timeout_seconds=0.2,
    )
    create.on_click = lambda: controls.append(
        FakeControl(
            "Change project: WritingLauncher",
            "Button",
            events,
        )
    )

    assert adapter._create_project(window, "WritingLauncher") is True
    assert events.count("click:Add new project") == 2
    assert "focus:Project name" in events


def test_project_lookup_rejects_same_named_chat_sidebar_row():
    events: list[str] = []
    chat_row = FakeControl(
        "WritingLauncher",
        "Button",
        events,
        class_name="sidebar-item",
    )
    project = FakeControl(
        "WritingLauncher",
        "Button",
        events,
        class_name="sidebar-item group/folder-row",
    )
    adapter = ChatGPTDesktop()

    assert (
        adapter._find_project_control(
            FakeWindow([chat_row, project], events),
            "WritingLauncher",
        )
        is project
    )


def test_top_new_chat_lookup_rejects_same_named_history_row():
    events: list[str] = []
    top_new_chat = FakeControl(
        "New chat",
        "Button",
        events,
        class_name="sidebar-item focus-visible:outline",
    )
    history_row = FakeControl(
        "New chat",
        "Button",
        events,
        class_name="group relative sidebar-item",
    )

    assert ChatGPTDesktop._is_top_new_chat_control(top_new_chat) is True
    assert ChatGPTDesktop._is_top_new_chat_control(history_row) is False


def test_current_do_anything_composer_is_recognised():
    events: list[str] = []
    composer = FakeControl(
        "Do anything",
        "Edit",
        events,
        class_name="ProseMirror",
    )
    adapter = ChatGPTDesktop()

    assert adapter._find_composer(FakeWindow([composer], events)) is composer


def test_prosemirror_class_is_a_constrained_composer_fallback():
    events: list[str] = []
    search = FakeControl("Search", "Edit", events, class_name="SearchBox")
    renamed_composer = FakeControl(
        "Current placeholder",
        "Edit",
        events,
        class_name="ProseMirror",
    )
    adapter = ChatGPTDesktop()

    assert (
        adapter._find_composer(
            FakeWindow([search, renamed_composer], events)
        )
        is renamed_composer
    )


def test_unknown_edit_control_is_not_treated_as_composer():
    events: list[str] = []
    search = FakeControl("Search", "Edit", events, class_name="SearchBox")
    adapter = ChatGPTDesktop()

    assert adapter._find_composer(FakeWindow([search], events)) is None


def test_control_activation_prefers_uia_invoke_without_moving_mouse():
    events: list[str] = []

    class InvokableControl(FakeControl):
        def invoke(self):
            self.events.append(f"invoke:{self.element_info.name}")

    control = InvokableControl("Chat", "Button", events)
    adapter = ChatGPTDesktop()

    adapter._activate_control(control)

    assert events == ["invoke:Chat"]


def test_control_activation_uses_pattern_click_when_invoke_fails():
    events: list[str] = []

    class FailingInvokableControl(FakeControl):
        def invoke(self):
            raise RuntimeError("Invoke pattern unavailable")

    control = FailingInvokableControl("Chat", "Button", events)
    adapter = ChatGPTDesktop()

    adapter._activate_control(control)

    assert events == ["click:Chat"]


def test_control_activation_uses_keyboard_before_physical_mouse():
    events: list[str] = []

    class KeyboardControl(FakeControl):
        def invoke(self):
            raise RuntimeError("Invoke pattern unavailable")

        def click(self):
            raise RuntimeError("Pattern click unavailable")

        def select(self):
            raise RuntimeError("SelectionItem unavailable")

    control = KeyboardControl("Chat", "Button", events)
    adapter = ChatGPTDesktop(
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        mouse_clicker=lambda item: events.append(
            f"mouse:{item.element_info.name}"
        ),
    )

    adapter._activate_control(control)

    assert events == ["focus:Chat", "keys:{ENTER}"]


def test_control_activation_uses_physical_mouse_only_as_last_resort():
    events: list[str] = []

    class MouseOnlyControl(FakeControl):
        def invoke(self):
            raise RuntimeError("Invoke pattern unavailable")

        def click(self):
            raise RuntimeError("Pattern click unavailable")

        def select(self):
            raise RuntimeError("SelectionItem unavailable")

        def set_focus(self):
            raise RuntimeError("Keyboard focus unavailable")

    control = MouseOnlyControl("Chat", "Button", events)
    adapter = ChatGPTDesktop(
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
        mouse_clicker=lambda item: events.append(
            f"mouse:{item.element_info.name}"
        ),
    )

    adapter._activate_control(control)

    assert events == ["mouse:Chat"]


def test_physical_fallback_supports_negative_virtual_desktop_coordinates():
    @dataclass
    class Rectangle:
        left: int
        top: int
        right: int
        bottom: int

    class RectangleControl:
        @staticmethod
        def rectangle():
            return Rectangle(-2200, 100, -1800, 500)

    class FakeWin32Api:
        metrics = {
            76: -2520,
            77: 0,
            78: 8280,
            79: 1728,
        }

        def __init__(self):
            self.cursor = (400, 200)
            self.positions = []
            self.events = []

        def GetSystemMetrics(self, index):
            return self.metrics[index]

        def GetCursorPos(self):
            return self.cursor

        def SetCursorPos(self, position):
            self.cursor = position
            self.positions.append(position)

        def mouse_event(self, flags, dx, dy, data, extra):
            self.events.append((flags, dx, dy, data, extra))

    win32api = FakeWin32Api()

    _click_control_on_virtual_desktop(
        RectangleControl(),
        win32api_module=win32api,
    )

    assert win32api.positions == [(-2000, 300), (400, 200)]
    assert win32api.events == [
        (0x0002, 0, 0, 0, 0),
        (0x0004, 0, 0, 0, 0),
    ]


def test_visible_project_new_chat_uses_fast_path():
    events: list[str] = []
    controls: list[FakeControl] = [
        FakeControl(
            "Switch mode, current mode: ChatGPT",
            "Button",
            events,
        ),
        FakeControl(
            "New chat",
            "Button",
            events,
            class_name="sidebar-item",
        ),
        FakeControl(
            "Chat",
            "Button",
            events,
            class_name="text-token-text-primary",
        ),
        FakeComposer(events),
    ]
    project_action = FakeControl(
        "New chat in PromptMeld - Editing",
        "Button",
        events,
        on_click=lambda: controls.append(
            FakeControl(
                "Change project: PromptMeld - Editing",
                "Button",
                events,
            )
        ),
    )
    controls.append(project_action)
    window = FakeWindow(controls, events)
    adapter = ChatGPTDesktop(
        desktop_factory=lambda **kwargs: FakeDesktop(window),
        clipboard_reader=lambda: "selected source",
        clipboard_writer=lambda text: None,
        send_keys=lambda keys, **kwargs: events.append(f"keys:{keys}"),
    )

    result = adapter.submit(
        "complete prompt",
        "PromptMeld - Editing",
    )

    assert result.submitted is True
    assert "click:New chat in PromptMeld - Editing" in events
    assert "click:New chat" not in events
    assert "click:Chat" not in events
