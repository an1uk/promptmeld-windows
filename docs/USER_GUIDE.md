# PromptMeld user guide

This guide explains everyday use of PromptMeld. For individual settings and
editable JSON files, see [Configuration and customisation](CONFIGURATION.md).

## Requirements and compatibility

PromptMeld requires Windows 10 or 11 and the current ChatGPT desktop app for
Windows, signed in to your account. It currently supports the new desktop
experience, not:

- The Classic ChatGPT desktop experience.
- ChatGPT in a web browser.

No OpenAI API key is required. A free ChatGPT account can be used, but models,
reasoning controls, Projects, writing blocks, and related features depend on
your account and plan.

## Basic workflow

The first launch opens a short setup guide. It explains the three-step workflow,
lets you record and test the global launcher shortcut against Windows and the
included action shortcuts, and optionally enables startup with Windows. The
guide can be opened again from **Configuration > General > Launcher**.

1. Select text in another application.
2. Press `Ctrl+Alt+Space`.
3. Search for or choose a writing action.

The shortcut preserves the source application's focus and selection while the
launcher opens. PromptMeld combines the selected text with the action's
instruction, opens ChatGPT, selects or creates the appropriate Project, starts
a fresh chat, and inserts the completed prompt.

Automatic submission is off by default. You can review the prompt and choose a
model or reasoning level in ChatGPT before sending it. If PromptMeld cannot
verify the required ChatGPT controls, it focuses ChatGPT and leaves the complete
prompt on the clipboard for manual pasting.

Double-click the PromptMeld notification-area icon to open Configuration. The
tray menu also shows the configured launcher shortcut, cancellation and recovery
commands when relevant, updates, and application exit.

## Writing actions and guidance

PromptMeld includes 26 actions for editing, replies and arguments, tone and
polish, technical help, and correspondence. **Add** and **Duplicate** open a
short wizard for the action's instruction, location, search terms, icon,
behaviour, and optional tested shortcut. Its final page combines sample text
with the action and shows the complete request PromptMeld would send, without
contacting ChatGPT. Actions can then be reorganised, disabled, or removed in
Configuration. A one-off custom instruction remains available in the launcher.

The Writing actions tab can import and export human-readable JSON action packs.
Export either the selected action or the complete library. Imported actions are
added without replacing the current library; duplicate internal IDs are
adapted and shortcut clashes are cleared. Custom image files are referenced by
the JSON but are not embedded, so use built-in icons or emoji for a pack that
will move between computers.

Five optional starter packs add focused sets for editing, email, complaints,
reports, and social posts. They can be combined, edited, exported, or removed
like any other actions.

Use **This request: intent or additional context** to add a desired outcome,
constraint, or point that is not already present in the source. PromptMeld
keeps this guidance separate from the selected text.

The **Change this request** menu provides per-request controls for:

- **Editing strength:** Default, Proofread, Improve, or Rewrite.
- **Preserve facts and specifics:** protects names, dates, amounts, quotations,
  URLs, product details, policies, and commitments.
- **Recipient or audience:** adapts wording for personal, workplace, customer,
  support, public, or general-reader contexts.

These choices reset for each newly captured selection unless the source
application has configured defaults.

## Application profiles

The **Applications** tab can give each Windows executable its own writing and
delivery defaults. Double-click an application row to configure:

- Audience and primary language.
- Result length, formatting, editing strength, and factual preservation.
- Natural voice, guided questions, and writing blocks.
- ChatGPT Project base name, automatic submission, and Temporary Chat.
- Whether the generated result is left in ChatGPT, copied, or used to replace
  the original selection.

Every setting can inherit the overall default, so a profile only needs to
specify what is different for that application.

Under **Configuration > General > ChatGPT Projects**, choose how normal chats
are organised:

- **Writing action or folder** retains the current behaviour, producing names
  such as `PromptMeld - Editing`.
- **One project for everything** always uses `PromptMeld`.
- **Application the text came from** produces names such as
  `PromptMeld - Microsoft Outlook` or `PromptMeld - Google Chrome`.

The project base name can be changed from `PromptMeld`. An application profile
can supply a different base for that application, after which the same naming
strategy is applied. **One project for everything** deliberately ignores those
application overrides so every normal request uses the same project. Temporary
Chat continues to bypass Projects entirely.

The hierarchy is deliberate: **Overall defaults** are remembered, an
application profile overrides them for one executable, and controls labelled
**This request** reset when a new selection is captured.

![Example Microsoft Outlook application configuration](configure-application.png)

New configurations include useful examples:

- Word replaces a verified editable selection.
- Notepad replaces the selection and requests plain text.
- Outlook and New Outlook copy plain-text results for manual placement.
- Chrome, Edge, and Firefox copy the result rather than assuming the original
  browser content is editable.
- Teams and Slack copy short, plain-text wording aimed at a colleague or peer.

All starter profiles can be edited or removed.

## Generated results, replacement, and recovery

After automatic submission, PromptMeld can copy generated text or replace the
original selection. Before replacement it returns to the source window and
verifies that the same text remains selected in an editable control.

If focus, selection, editability, or paste access changed, PromptMeld leaves the
original alone and copies the generated result instead. The original text is
preserved in memory and the tray offers **Undo last replacement** and
**Copy preserved original**. Preserved text is never written to disk and is
forgotten when PromptMeld closes or a newer original replaces it.

The automation progress window can be cancelled with its button or Escape.
Actionable failures remain visible, while Configuration can copy
privacy-filtered diagnostics or open the local log folder. For the detailed
automation sequence, see [ChatGPT automation and fallback behaviour](AUTOMATION.md).

## Backup and restore

Use **Configuration > Backup & recovery** to save actions, settings,
application profiles, hotkeys, and installed custom icons in one portable ZIP
file. The backup excludes usage history, logs, update state, selected text,
prompts, and responses. Its suggested filename includes the PromptMeld version
and creation time, while the internal manifest records the app version, backup
format version, and timestamp for validated future restoration.

Before restoring a validated backup, PromptMeld automatically saves the current
configuration as a separate safety backup. The restored configuration is then
reloaded immediately. The same tab contains privacy-filtered diagnostics and
log-folder access.

## Temporary Chat

Turn on **Temporary Chat** in the launcher or an application profile when you
do not want an action to use its configured Project. On first use, ChatGPT may
show an explanation with a **Continue** button. PromptMeld pauses so you can
read and respond to that dialog yourself; it never accepts it for you.

## Default shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Alt+Space` | Capture selected text and open the launcher |
| `Ctrl+Alt+1` | Edit, revise, and improve |
| `Ctrl+Alt+2` | Shorten and make punchier |
| `Ctrl+Alt+3` | Expand and strengthen argument |
| `Ctrl+Alt+4` | Reply to selected comment |
| `Ctrl+Alt+5` | Sarcastic reply |
| `Ctrl+Alt+6` | Polite but firm reply |

Shortcuts can be changed in **Configuration > Hotkeys**. PromptMeld identifies
duplicates and asks Windows whether a shortcut is already registered by another
application.

## Updates

Installed copies check the latest stable GitHub release at most once per day.
When a newer version is available, PromptMeld shows one Windows notification
and keeps an **Update available** entry in its tray menu. You can also choose
**Check now** in **Configuration > General > Updates**.

PromptMeld validates the expected installer name, advertised size, secure
download location, and GitHub-provided SHA-256 digest. It then opens the normal
visible installer, which performs the update and can relaunch PromptMeld.
Automatic checks can be disabled; manual checks remain available.
