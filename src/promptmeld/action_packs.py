from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from importlib.resources import files
from pathlib import Path

from .config import ConfigurationError, action_to_dict, actions_from_data
from .models import WritingAction
from .windows import HotkeyParseError, parse_hotkey

ACTION_PACK_FORMAT = "promptmeld-action-pack"
ACTION_PACK_FORMAT_VERSION = 1
BUILTIN_PACKS_FORMAT = "promptmeld-built-in-action-packs"
MAX_ACTION_PACK_BYTES = 2 * 1024 * 1024
MAX_ACTIONS_PER_PACK = 250


class ActionPackError(ValueError):
    """Raised when an action pack is unreadable, unsafe, or invalid."""


@dataclass(frozen=True, slots=True)
class ActionPack:
    name: str
    description: str
    actions: tuple[WritingAction, ...]
    pack_id: str = ""
    category: str = ""
    intended_use: str = ""


@dataclass(frozen=True, slots=True)
class ActionPackMergeResult:
    actions: list[WritingAction]
    added_count: int
    renamed_count: int
    cleared_hotkey_count: int
    first_added_index: int


@dataclass(frozen=True, slots=True)
class ActionPackInstallation:
    status: str
    installed_count: int
    missing_count: int
    modified_count: int
    update_count: int = 0

    @property
    def label(self) -> str:
        return {
            "not_installed": "Not installed",
            "partial": "Partially installed",
            "installed": "Installed",
            "modified": "Installed — personalised settings",
            "update_available": "Content differs from catalogue",
        }[self.status]


@dataclass(frozen=True, slots=True)
class ActionPackChangeResult:
    actions: list[WritingAction]
    added_count: int = 0
    updated_count: int = 0
    removed_count: int = 0
    first_changed_index: int = -1


PACK_CATEGORY_ORDER = (
    "Reply or respond",
    "Edit or revise",
    "Draft or create",
    "Summarise or extract",
    "Plan or decide",
    "Review or develop",
    "Explain or learn",
)
PACK_CATEGORIES = {
    "replies-arguments": "Reply or respond",
    "social-replies": "Reply or respond",
    "customer-relations": "Reply or respond",
    "email": "Reply or respond",
    "complaints": "Reply or respond",
    "editing": "Edit or revise",
    "tone-voice": "Edit or revise",
    "social-editing": "Edit or revise",
    "argument-editing": "Edit or revise",
    "reviews-feedback": "Edit or revise",
    "draft-from-selection": "Draft or create",
    "reports": "Draft or create",
    "social-posts": "Draft or create",
    "meetings": "Draft or create",
    "career-writing": "Draft or create",
    "summaries-extraction": "Summarise or extract",
    "decisions-planning": "Plan or decide",
    "authors-fiction": "Review or develop",
    "authors-nonfiction": "Review or develop",
    "technical-communication": "Explain or learn",
    "learning": "Explain or learn",
}
PACK_CATEGORY_INTENDED_USE = {
    "Reply or respond": (
        "Use when the selected text is something you need to answer."
    ),
    "Edit or revise": (
        "Use when the selection is your draft and should remain the same kind "
        "of text after improvement."
    ),
    "Draft or create": (
        "Use when selected notes or source material should become a new, "
        "complete piece of writing."
    ),
    "Summarise or extract": (
        "Use when you need supporting information from the selection rather "
        "than replacement prose."
    ),
    "Plan or decide": (
        "Use when the selection contains options, goals, risks, or material "
        "that needs organising into a decision."
    ),
    "Review or develop": (
        "Use when you want feedback, questions, or deeper analysis without "
        "silently rewriting the source."
    ),
    "Explain or learn": (
        "Use when selected material needs explaining, teaching, or turning "
        "into learning aids."
    ),
}
def _pack_from_payload(payload: object, source_name: str) -> ActionPack:
    if not isinstance(payload, dict):
        raise ActionPackError(f"{source_name} must contain a JSON object.")
    if payload.get("format") != ACTION_PACK_FORMAT:
        raise ActionPackError("This is not a PromptMeld action pack.")
    if payload.get("format_version") != ACTION_PACK_FORMAT_VERSION:
        raise ActionPackError(
            "This action-pack version is not supported by this PromptMeld version."
        )
    name = payload.get("name")
    description = payload.get("description", "")
    pack_id = payload.get("id", "")
    category = payload.get("category", "")
    intended_use = payload.get("intended_use", "")
    if not isinstance(name, str) or not name.strip():
        raise ActionPackError("The action pack needs a name.")
    if not all(
        isinstance(value, str)
        for value in (description, pack_id, category, intended_use)
    ):
        raise ActionPackError("The action-pack metadata must be text.")
    raw_actions = payload.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        raise ActionPackError("The action pack must contain at least one action.")
    if len(raw_actions) > MAX_ACTIONS_PER_PACK:
        raise ActionPackError(
            f"An action pack cannot contain more than {MAX_ACTIONS_PER_PACK} actions."
        )
    try:
        actions = actions_from_data(raw_actions, source_name)
    except ConfigurationError as exc:
        raise ActionPackError(
            f"The action pack contains invalid actions: {exc}"
        ) from exc
    return ActionPack(
        name=name.strip(),
        description=description.strip(),
        actions=tuple(actions),
        pack_id=pack_id.strip(),
        category=category.strip(),
        intended_use=intended_use.strip(),
    )


def load_action_pack(path: Path) -> ActionPack:
    path = Path(path)
    try:
        if path.stat().st_size > MAX_ACTION_PACK_BYTES:
            raise ActionPackError("The action pack is larger than the safe limit.")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ActionPackError:
        raise
    except FileNotFoundError as exc:
        raise ActionPackError(f"Action pack not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise ActionPackError("The action pack must be UTF-8 JSON text.") from exc
    except json.JSONDecodeError as exc:
        raise ActionPackError(
            f"Invalid JSON at line {exc.lineno}, column {exc.colno}."
        ) from exc
    except OSError as exc:
        raise ActionPackError(f"The action pack could not be read: {exc}") from exc
    return _pack_from_payload(payload, path.name)


def action_pack_to_dict(pack: ActionPack) -> dict[str, object]:
    payload: dict[str, object] = {
        "format": ACTION_PACK_FORMAT,
        "format_version": ACTION_PACK_FORMAT_VERSION,
        "name": pack.name,
        "description": pack.description,
        "actions": [action_to_dict(action) for action in pack.actions],
    }
    if pack.pack_id:
        payload["id"] = pack.pack_id
    if pack.category:
        payload["category"] = pack.category
    if pack.intended_use:
        payload["intended_use"] = pack.intended_use
    return payload


def save_action_pack(path: Path, pack: ActionPack) -> None:
    if not pack.name.strip() or not pack.actions:
        raise ActionPackError("An action pack needs a name and at least one action.")
    if len(pack.actions) > MAX_ACTIONS_PER_PACK:
        raise ActionPackError(
            f"An action pack cannot contain more than {MAX_ACTIONS_PER_PACK} actions."
        )
    payload = action_pack_to_dict(pack)
    encoded = (
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_ACTION_PACK_BYTES:
        raise ActionPackError("The action pack is larger than the safe limit.")
    _pack_from_payload(payload, Path(path).name)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        temporary.write_bytes(encoded)
        os.replace(temporary, destination)
    except OSError as exc:
        raise ActionPackError(f"The action pack could not be saved: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def load_builtin_action_packs() -> tuple[ActionPack, ...]:
    resource = files("promptmeld").joinpath(
        "resources",
        "builtin_action_packs.json",
    )
    try:
        payload = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActionPackError("The built-in action packs could not be read.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("format") != BUILTIN_PACKS_FORMAT
        or payload.get("format_version") != ACTION_PACK_FORMAT_VERSION
        or not isinstance(payload.get("packs"), list)
    ):
        raise ActionPackError("The built-in action-pack catalogue is invalid.")
    def builtin_pack(item: object) -> ActionPack:
        pack = _pack_from_payload(item, "builtin_action_packs.json")
        category = pack.category or PACK_CATEGORIES.get(pack.pack_id, "Other")
        return replace(
            pack,
            category=category,
            intended_use=(
                pack.intended_use
                or PACK_CATEGORY_INTENDED_USE.get(
                    category,
                    "Use this pack when its included actions match your work.",
                )
            ),
        )

    packs = tuple(builtin_pack(item) for item in payload["packs"])
    identifiers = [pack.pack_id for pack in packs]
    if any(not identifier for identifier in identifiers) or len(identifiers) != len(
        set(identifiers)
    ):
        raise ActionPackError("Built-in action-pack IDs must be present and unique.")
    return packs


def _hotkey_identity(hotkey: str | None) -> tuple[int, int] | None:
    if not hotkey:
        return None
    try:
        parsed = parse_hotkey(hotkey)
    except HotkeyParseError:
        return None
    return parsed.modifiers, parsed.virtual_key


def merge_action_pack(
    existing: list[WritingAction],
    pack: ActionPack,
) -> ActionPackMergeResult:
    """Append a pack, adapting IDs and clashing enabled shortcuts safely."""

    merged = list(existing)
    existing_ids = {action.id for action in merged}
    used_hotkeys = {
        identity
        for action in merged
        if action.enabled and (identity := _hotkey_identity(action.hotkey))
    }
    renamed_count = 0
    cleared_hotkey_count = 0
    first_added_index = len(merged)
    for source in pack.actions:
        action_id = source.id
        suffix = 2
        while action_id in existing_ids:
            action_id = f"{source.id}-{suffix}"
            suffix += 1
        if action_id != source.id:
            renamed_count += 1
        existing_ids.add(action_id)

        hotkey = source.hotkey
        identity = _hotkey_identity(hotkey)
        if source.enabled and identity is not None:
            if identity in used_hotkeys:
                hotkey = None
                cleared_hotkey_count += 1
            else:
                used_hotkeys.add(identity)
        merged.append(replace(source, id=action_id, hotkey=hotkey))
    return ActionPackMergeResult(
        actions=merged,
        added_count=len(pack.actions),
        renamed_count=renamed_count,
        cleared_hotkey_count=cleared_hotkey_count,
        first_added_index=first_added_index,
    )


def action_pack_installation(
    existing: list[WritingAction],
    pack: ActionPack,
) -> ActionPackInstallation:
    """Describe how the canonical pack currently appears in an action library."""

    existing_by_id = {action.id: action for action in existing}
    installed = [
        source for source in pack.actions if source.id in existing_by_id
    ]
    missing_count = len(pack.actions) - len(installed)
    modified_count = sum(
        existing_by_id[source.id] != source for source in installed
    )
    update_count = sum(
        _updated_pack_action(existing_by_id[source.id], source)
        != existing_by_id[source.id]
        for source in installed
    )
    if not installed:
        status = "not_installed"
    elif missing_count:
        status = "partial"
    elif update_count:
        status = "update_available"
    elif modified_count:
        status = "modified"
    else:
        status = "installed"
    return ActionPackInstallation(
        status=status,
        installed_count=len(installed),
        missing_count=missing_count,
        modified_count=modified_count,
        update_count=update_count,
    )


def _updated_pack_action(
    current: WritingAction,
    source: WritingAction,
) -> WritingAction:
    return replace(
        current,
        name=source.name,
        keywords=source.keywords,
        instruction=source.instruction,
        icon=source.icon,
        guided_drafting=source.guided_drafting,
        recipient_audience=source.recipient_audience,
        purpose=source.purpose,
        result_handling=source.result_handling,
    )


def update_builtin_action_pack(
    existing: list[WritingAction],
    pack: ActionPack,
) -> ActionPackChangeResult:
    """Update managed pack content while retaining personal library choices."""

    source_by_id = {action.id: action for action in pack.actions}
    updated: list[WritingAction] = []
    updated_count = 0
    first_changed_index = -1
    seen: set[str] = set()
    for index, current in enumerate(existing):
        source = source_by_id.get(current.id)
        if source is None:
            updated.append(current)
            continue
        seen.add(current.id)
        replacement = _updated_pack_action(current, source)
        if replacement != current:
            updated_count += 1
            if first_changed_index < 0:
                first_changed_index = index
        updated.append(replacement)

    missing = [action for action in pack.actions if action.id not in seen]
    if missing and first_changed_index < 0:
        first_changed_index = len(updated)
    updated.extend(missing)
    return ActionPackChangeResult(
        actions=updated,
        added_count=len(missing),
        updated_count=updated_count,
        first_changed_index=first_changed_index,
    )


def restore_builtin_action_pack(
    existing: list[WritingAction],
    pack: ActionPack,
) -> ActionPackChangeResult:
    """Replace every canonical pack action with the current shipped version."""

    pack_ids = {action.id for action in pack.actions}
    matching_indexes = [
        index for index, action in enumerate(existing) if action.id in pack_ids
    ]
    insert_at = min(matching_indexes, default=len(existing))
    retained = [action for action in existing if action.id not in pack_ids]
    insert_at = min(insert_at, len(retained))
    restored = [
        *retained[:insert_at],
        *pack.actions,
        *retained[insert_at:],
    ]
    return ActionPackChangeResult(
        actions=restored,
        added_count=len(pack.actions),
        removed_count=len(matching_indexes),
        first_changed_index=insert_at,
    )


def remove_builtin_action_pack(
    existing: list[WritingAction],
    pack: ActionPack,
) -> ActionPackChangeResult:
    """Remove actions identified as members of one built-in pack."""

    pack_ids = {action.id for action in pack.actions}
    matching_indexes = [
        index for index, action in enumerate(existing) if action.id in pack_ids
    ]
    remaining = [action for action in existing if action.id not in pack_ids]
    return ActionPackChangeResult(
        actions=remaining,
        removed_count=len(matching_indexes),
        first_changed_index=(
            min(matching_indexes, default=max(0, len(remaining) - 1))
        ),
    )
