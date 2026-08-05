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


@dataclass(frozen=True, slots=True)
class ActionPackMergeResult:
    actions: list[WritingAction]
    added_count: int
    renamed_count: int
    cleared_hotkey_count: int
    first_added_index: int


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
    if not isinstance(name, str) or not name.strip():
        raise ActionPackError("The action pack needs a name.")
    if not isinstance(description, str) or not isinstance(pack_id, str):
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
    packs = tuple(
        _pack_from_payload(item, "builtin_action_packs.json")
        for item in payload["packs"]
    )
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
