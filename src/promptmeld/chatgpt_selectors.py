from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SemanticSelector:
    identifier: str
    names: tuple[str, ...] = ()
    class_names: tuple[str, ...] = ()
    automation_ids: tuple[str, ...] = ()


MODE_SWITCH = SemanticSelector(
    "chatgpt.mode-switch.v1",
    ("Switch mode, current mode:",),
)
CHATGPT_MODE = SemanticSelector(
    "chatgpt.mode-item.v1",
    ("ChatGPT Create, learn, and explore",),
)
COMPOSER = SemanticSelector(
    "chatgpt.composer.v2",
    (
        "Do anything",
        "Message ChatGPT",
        "Message",
        "Ask anything",
        "Send a message",
        "Type a message",
    ),
    ("prosemirror",),
)
SEND = SemanticSelector(
    "chatgpt.send.v1",
    ("Send", "Send message"),
)
RESPONSE_COPY = SemanticSelector(
    "chatgpt.response-copy.v2",
    ("Copy", "Copy response"),
)
USER_MESSAGE_COPY = SemanticSelector(
    "chatgpt.user-message-copy.v1",
    ("Copy message",),
)
GENERATION_STOP = SemanticSelector(
    "chatgpt.generation-stop.v1",
    (
        "Stop",
        "Stop generating",
        "Stop generation",
        "Stop response",
        "Stop streaming",
    ),
)
CHAT_HOME = SemanticSelector("chatgpt.chat-home.v1", ("New chat",))
CHAT_MODE_TAB = SemanticSelector("chatgpt.chat-mode-tab.v1", ("Chat",))
PROJECT_ROW = SemanticSelector("chatgpt.project-row.v2")
PROJECT_NEW_CHAT = SemanticSelector("chatgpt.project-new-chat.v2")
PROJECTS_SECTION = SemanticSelector("chatgpt.projects-section.v1", ("Projects",))
PROJECT_SHOW_MORE = SemanticSelector("chatgpt.projects-show-more.v1", ("Show more",))
PROJECT_ADD = SemanticSelector("chatgpt.project-add.v1", ("Add new project",))
PROJECT_CREATE = SemanticSelector("chatgpt.project-create.v1", ("Create project",))
PROJECT_NAME = SemanticSelector(
    "chatgpt.project-name.v1",
    ("Project name",),
    automation_ids=("chatgpt-project-name",),
)
PROJECT_INDEX_SEARCH = SemanticSelector(
    "chatgpt.project-index-search.v1",
    automation_ids=("projects-index-search",),
)
TEMPORARY_CHAT = SemanticSelector(
    "chatgpt.temporary-chat.v1",
    ("Turn on temporary chat", "Turn off temporary chat"),
)
TEMPORARY_CHAT_DIALOG = SemanticSelector(
    "chatgpt.temporary-chat-dialog.v1",
    ("Temporary Chat",),
)
PROJECT_STORAGE = SemanticSelector(
    "chatgpt.project-storage.v1",
    ("Cloud", "Local"),
)
PROJECT_TYPE_NEXT = SemanticSelector(
    "chatgpt.project-type-next.v1",
    ("Next",),
)
PROJECT_DESTINATION = SemanticSelector(
    "chatgpt.project-destination.v1",
    ("Change project:", "New chat in ", "Start new chat in "),
)
