# Configuration and customisation

PromptMeld is designed to be configured through **Manage writing actions** in
the notification-area menu. Direct JSON editing remains available for advanced
use and troubleshooting.

## Action manager

The action manager lets you:

- Add, duplicate, delete, enable, and reorder actions.
- Organise actions in folders and nested folders.
- Edit action names, search keywords, ChatGPT instructions, and optional
  global hotkeys.
- Pin actions to the launcher home screen.
- Choose whether an action follows, always applies, or ignores the
  **Preserve my natural voice** setting.
- Allow suitable actions to use optional guided drafting.
- Choose bundled Lucide icons, type an emoji or symbol, or import a local image.
- Configure badged folder icons.
- Control how many genuinely used actions appear in **Most used**.

Changes take effect immediately after **Save**. Required fields, supported
hotkey syntax, and duplicate hotkeys are validated before saving.

Use `/` in a folder name to create nesting, for example
`Replies & arguments/Analysis`. Search covers every folder, while frequently
and recently used actions rank first within the current scope.

## Defaults and writing style

The **Defaults & style** tab controls:

- Appearance: Auto (the default, following the Windows app colour mode), Light,
  or Dark.
- Automatic submission, which is off by default.
- The default state and wording of **Preserve my natural voice**.
- Primary writing language: English (UK), English (US), source language, or a
  custom language.
- Guided drafting, which allows supported actions to ask up to three concise
  questions when essential context is missing.
- Folder icons and the number of most-used actions shown on the home screen.

PromptMeld deliberately does not automate ChatGPT's model picker because model
names, availability, and layout can change by account and application version.

## Starter actions

The starter set contains 26 actions grouped under:

- **Editing**, including **Reviews**.
- **Replies & arguments**, including **Replies** and **Analysis**.
- **Tone & polish**.
- **Technical help**.
- **Correspondence**, including **Email** and
  **Customer & marketplace**.

Correspondence actions avoid inventing facts, policies, dates, refunds, or
commitments. The home screen initially pins the most broadly useful editing and
reply actions; most-used entries appear only after actual use.

## Local files

PromptMeld stores editable data in:

```text
%LOCALAPPDATA%\PromptMeld
|-- actions.json
|-- icons\
|-- settings.json
|-- usage.json
`-- promptmeld.log
```

Imported icons are copied into `icons\`, so moving the original image does not
break the action.

## Manual action editing

Each entry in `actions.json` follows this shape:

```json
{
  "id": "shorten",
  "name": "Shorten",
  "keywords": ["concise", "brief", "trim"],
  "instruction": "Shorten the text while preserving its meaning and essential details.",
  "hotkey": "Ctrl+Alt+2",
  "enabled": true,
  "icon": "lucide:scissors",
  "folder": "Editing",
  "show_on_home": true,
  "natural_voice": "inherit",
  "guided_drafting": false
}
```

Action IDs must be unique. Set `hotkey` to `null` for actions that should only
appear through search. Icons may be a bundled `lucide:name`, an emoji or short
symbol, or a path relative to the PromptMeld data directory. Leave `folder`
empty for a root-level action.

Valid `natural_voice` values are `inherit`, `always`, and `never`. Set
`guided_drafting` to `true` only for actions that may benefit from requesting
missing context.

After manual changes, choose **Reload configuration** from the notification-area
menu.

## Manual defaults editing

Home-screen, submission, language, and style settings are stored in
`settings.json`:

```json
{
  "project_name": "PromptMeld",
  "home_most_used_count": 3,
  "auto_submit_enabled": false,
  "natural_voice_enabled": false,
  "natural_voice_instruction": "Preserve the writer's individual voice...",
  "primary_language": "English (UK)",
  "guided_drafting_enabled": false,
  "folder_icons": {
    "Editing": "lucide:pencil",
    "Editing/Reviews": "lucide:heart"
  }
}
```

## Upgrades and migration

When upgrading an untouched original eight-action starter file, PromptMeld
creates `actions.legacy-v1-backup.json` and installs the current grouped starter
set.

Existing customised configurations receive the correspondence actions through
an additive one-time migration. PromptMeld first creates
`actions.pre-correspondence-v2-backup.json`; existing actions and edits are
preserved, and actions deleted after migration are not added again.

When upgrading from Writing Launcher, PromptMeld copies
`%LOCALAPPDATA%\WritingLauncher` to `%LOCALAPPDATA%\PromptMeld` on first run.
The original directory remains as a backup. Existing settings are preserved,
while older default Project names are migrated to `PromptMeld`.

For details about logs, usage records, clipboard handling, and deletion, see
[Privacy](../PRIVACY.md).
