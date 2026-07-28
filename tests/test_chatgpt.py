from __future__ import annotations

from dataclasses import dataclass

from writing_launcher.chatgpt import ChatGPTDesktop


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
        self.events.append(f"click:{self.element_info.name}")
        if self.on_click is not None:
            self.on_click()

    def set_focus(self):
        self.events.append(f"focus:{self.element_info.name}")


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
        FakeControl("Message ChatGPT", "Edit", events),
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
        "focus:Message ChatGPT",
        "keys:^v",
        "keys:{ENTER}",
    ]
    assert clipboard == ["complete prompt", "selected source"]


def test_prepare_only_pastes_prompt_without_pressing_enter():
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
        FakeControl("Message ChatGPT", "Edit", events),
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
    assert "keys:^v" in events
    assert "keys:{ENTER}" not in events
    assert clipboard == ["complete prompt", "selected source"]


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
        FakeControl("Message ChatGPT", "Edit", events),
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
        FakeControl("Message ChatGPT", "Edit", events),
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
        "complete prompt",
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
        FakeControl("Message ChatGPT", "Edit", events),
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

    ChatGPTDesktop._activate_control(control)

    assert events == ["invoke:Chat"]


def test_control_activation_falls_back_to_mouse_when_invoke_fails():
    events: list[str] = []

    class FailingInvokableControl(FakeControl):
        def invoke(self):
            raise RuntimeError("Invoke pattern unavailable")

    control = FailingInvokableControl("Chat", "Button", events)

    ChatGPTDesktop._activate_control(control)

    assert events == ["click:Chat"]


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
        FakeControl("Message ChatGPT", "Edit", events),
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
