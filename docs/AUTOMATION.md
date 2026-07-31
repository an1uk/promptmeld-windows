# ChatGPT automation and fallback behaviour

PromptMeld automates the repetitive parts of opening a suitable ChatGPT
conversation while avoiding blind clicks or typing into an unverified control.

## Submission sequence

For each writing action, PromptMeld:

1. Remembers the source window and captures its selected text.
2. Builds a prompt from the action, selected text, and enabled style options.
3. Opens or focuses the ChatGPT desktop app.
4. Selects **ChatGPT** in the global mode switch and starts a top-level new
   chat.
5. Looks for the exact folder-specific Project, such as
   `PromptMeld - Editing`.
6. Expands the Projects list before deciding that a Project is missing, then
   creates it only when no exact match exists.
7. Starts a fresh chat in that Project.
8. Verifies the active Project and message composer through Windows UI
   Automation.
9. Inserts the prompt through the composer's UI Automation text pattern when
   supported, otherwise uses a control-targeted clipboard paste.
10. Reads the composer back and continues only after the complete prompt is
    verified.
11. Presses Enter only when **Submit automatically** is enabled.
12. When generated-text output is enabled and automatic submission is on,
    waits for a verified ChatGPT **Copy** control and retrieves the response.
13. If replacement is enabled and the original selection came from an editable
    control, returns focus to that source window and pastes the response over
    the selected text. Otherwise the original selection is left untouched.

Root-level actions and custom instructions use the base Project name
`PromptMeld`. Nested action folders produce names such as
`PromptMeld - Correspondence - Email`.

You may find this Project instruction useful:

> Treat every chat as an independent writing request. Use only the text
> supplied in the current chat unless explicitly instructed otherwise.

## Automation progress

While PromptMeld works, a small non-focus-stealing window shows each operation
as a stacked history. New operations appear below completed ones, and the
current operation is highlighted near the centre while the history scrolls
up smoothly. A successful result is added as the final entry; a problem stays
visible so it can be acted on.

The window shows operational stage names only. It does not display the selected
text or assembled prompt, and it does not take focus away from ChatGPT.

## Safety and fallback

PromptMeld uses Windows accessibility controls rather than fixed screen
coordinates. It first tries UI Automation's Invoke and SelectionItem patterns,
then focused keyboard activation. A physical click is retained only as a final
compatibility fallback for controls that expose none of those methods.

That final fallback validates the control against the complete Windows virtual
desktop, supports negative coordinates used by monitors positioned above or to
the left of the primary display, and restores the pointer after clicking. It
does not use pywinauto's primary-screen coordinate conversion.

The ChatGPT desktop app may expose only its outer frame on some installations
or after an interface update. If PromptMeld cannot verify the required
controls or cannot confirm that the composer received the complete prompt, it
does not submit blindly. Instead, it focuses ChatGPT and leaves the completed
prompt on the clipboard. Open the intended Project, start a new chat, and paste
manually.

Generated-text output has an additional dependency: ChatGPT must expose a
completed response's **Copy** control through Windows UI Automation. If that
control is not exposed before the output timeout, PromptMeld reports that the
response was submitted but does not replace the original selection. The
selected text is never replaced based on an unverified clipboard value.

Automatic replacement is deliberately opt-in and shows a confirmation warning
when used. It is destructive: the generated text can be wrong and the original
selection may not be recoverable. This is especially important in Temporary
Chat, where the original text is not retained in ChatGPT. Windows Clipboard
History or a clipboard manager such as CopyQ may preserve the original
selection, but those tools can retain sensitive text and do not guarantee
recovery.

## Automation companion

UI Automation runs in `_internal\PromptMeldAutomation.exe`, a companion process
installed with PromptMeld. It starts on the first submission, is reused for
consecutive submissions, and exits after 45 seconds without another request.
It is an internal component and should not be launched manually.

The companion is Per-Monitor V2 DPI aware so its guarded physical-click
fallback uses the correct coordinates when ChatGPT opens on a display with a
different scale setting.

Prompt data is passed to the companion through a local pipe and is not written
to disk. Operational stage timings and errors are written to `promptmeld.log`,
but selected text and prompt contents are excluded. See
[Privacy](../PRIVACY.md) for the complete data-handling explanation.

## ChatGPT interface dependencies

PromptMeld depends on accessibility information exposed by the current ChatGPT
desktop application. Changes to control names or structure can require a
PromptMeld update even though the guarded clipboard fallback continues to work.

Related OpenAI documentation:

- [ChatGPT Work and Codex](https://help.openai.com/en/articles/20001275)
- [The ChatGPT desktop app](https://help.openai.com/en/articles/20001276/)
- [Projects in ChatGPT](https://help.openai.com/en/articles/10169521-projects-in-chatgpt)
