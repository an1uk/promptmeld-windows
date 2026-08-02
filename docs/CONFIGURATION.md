# Configuration and customisation

PromptMeld is designed to be configured through **Configuration…** in
the notification-area menu. Direct JSON editing remains available for advanced
use and troubleshooting.

The **General** tab also controls daily GitHub update checks. Automatic checks
are enabled by default and can be disabled without removing the manual
**Check now** option. When an update is available, the same section provides
the release notes and verified installer actions.

## Action manager

The action manager lets you:

- Add, duplicate, delete, enable, and reorder actions.
- Organise actions in folders and nested folders.
- Edit action names, search keywords, and ChatGPT instructions.
- Pin actions to the launcher home screen.
- Choose whether an action follows, always applies, or ignores the
  **Preserve my natural voice** setting.
- Allow suitable actions to use optional guided drafting.
- Choose bundled Lucide icons, type an emoji or symbol, or import a local image.
- Configure badged folder icons.
- Control how many genuinely used actions appear in **Most used**.

Changes take effect immediately after **Save**. Required fields and action IDs
are validated before saving.

Use `/` in a folder name to create nesting, for example
`Replies & arguments/Analysis`. Search covers every folder, while frequently
and recently used actions rank first within the current scope.

## General settings

The **General** tab controls:

- Appearance: Auto (the default, following the Windows app colour mode), Light,
  or Dark.
- Primary writing language: English (UK), English (US), source language, or a
  custom language.
- The number of most-used actions shown on the launcher home screen.
- Whether PromptMeld starts automatically when you sign in to Windows.

## Hotkeys

The **Hotkeys** tab shows the required launcher shortcut in its own section,
separate from the writing-action shortcuts below it. Click a shortcut field,
then press the actual combination you want to use, or choose **Change** and
then press it. A shortcut must contain one supported key together with Ctrl,
Alt, Shift, or the Windows key. Use **Clear** to remove an action shortcut; the
launcher shortcut is required but can be replaced with **Change**. Actions with
assigned shortcuts are grouped above actions without shortcuts.

PromptMeld flags duplicates immediately. It also asks Windows whether an active
shortcut is already registered by the operating system or another application.
This is a useful clash check, but some applications handle keys without
registering a Windows global hotkey and therefore cannot be detected in
advance.

## Defaults and writing style

The **Defaults & style** tab controls:

- Automatic submission, which is off by default.
- Copying generated text to the clipboard after ChatGPT responds. This also
  requires automatic submission.
- Replacing selected text automatically when the source selection was detected
  in an editable control. This also requires automatic submission; selections
  from non-editable fields continue to use the normal PromptMeld workflow.
- Temporary Chat, which opens a top-level chat instead of using the writing
  action's configured Project. ChatGPT may show a one-time explanation;
  PromptMeld waits while you read and respond to it and does not activate
  **Continue** for you.
- Resulting text length, with qualitative choices from **Extra short** to
  **Extra long**. **Default** adds no length instruction to the prompt.
- Result formatting: use ChatGPT's default behaviour, prevent newly added
  formatting, or request restrained formatting where it improves readability.
- A best-effort request for ChatGPT to place the finished result in an editable,
  copyable writing block. Availability depends on the current ChatGPT plan,
  device, workspace settings, model, and rollout.
- The default state and wording of **Preserve my natural voice**.
- Guided drafting, which allows supported actions to ask up to three concise
  questions when essential context is missing.

These settings provide the initial remembered states of the corresponding
launcher checkboxes. Changing **Preserve my natural voice**, **Guided
questions** and **Submit automatically** in the launcher updates that remembered
setting for the next use. The launcher's **Temporary Chat** checkbox is also
remembered. Less frequently changed length, formatting, and writing-block
settings are grouped under the launcher's **Output options** menu and are
remembered in the same way.

Automatic replacement is destructive and opt-in. The generated response may be
wrong or unsuitable, and the existing selection may be lost if the result is
incorrect or the paste fails. With Temporary Chat enabled, the original text
is not retained in ChatGPT and may not be recoverable. Consider enabling
Windows Clipboard History (`Win+V`) or using a clipboard manager such as
[CopyQ](https://copyq.readthedocs.io/en/stable/) before using replacement.
Clipboard history may preserve the original selection because PromptMeld
captures it through the clipboard, but clipboard tools can retain sensitive
text and are not guaranteed recovery.

The launcher's **Intent or additional context** field is deliberately temporary
and is cleared whenever a new selection is captured. It adds the desired
outcome, supplementary context, constraints, or points to include to either a
configured action or a one-off instruction. PromptMeld separates these notes
from the selected source text in the generated prompt.

The **Writing guidance** menu also applies only to the current request:

- **Editing strength** adds no extra instruction at Default. Proofread limits
  changes to corrections, Improve permits useful rephrasing, and Rewrite
  permits broader restructuring. These rules are explicitly limited to tasks
  that edit existing text, so they do not reinterpret a received message as a
  draft reply.
- **Preserve facts and specifics** is On by default and protects concrete
  details while preventing invented facts, promises, actions, or attachments.
- **Recipient or audience** adapts the result for common personal, workplace,
  customer, support, public, or general-reader contexts. Use **Other** together
  with the intent/context field for a recipient not listed.

All three controls reset when PromptMeld captures a new selection. This avoids
guidance intended for one request silently affecting another.

See OpenAI's guide to
[writing blocks](https://help.openai.com/en/articles/20001246-working-with-writing-blocks-and-code-blocks-in-chatgpt)
for current availability and supported actions.

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

After manual JSON changes, exit and restart PromptMeld. Changes made through
the configuration window take effect immediately after saving.

## Manual defaults editing

Home-screen, submission, language, and style settings are stored in
`settings.json`:

```json
{
  "project_name": "PromptMeld",
  "popup_hotkey": "Ctrl+Alt+Space",
  "home_most_used_count": 3,
  "auto_submit_enabled": false,
  "replace_selected_text_enabled": false,
  "copy_generated_text_enabled": false,
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
