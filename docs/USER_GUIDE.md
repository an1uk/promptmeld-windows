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
polish, technical help, and correspondence. You can add, organise, duplicate,
disable, or remove actions in Configuration, and can enter a one-off custom
instruction from the launcher.

Use **Intent or additional context** to add a desired outcome, constraint, or
point that is not already present in the source. PromptMeld keeps this guidance
separate from the selected text.

The **Writing guidance** menu provides per-request controls for:

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
