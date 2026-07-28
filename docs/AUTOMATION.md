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
9. Pastes the prompt only after the destination is verified.
10. Presses Enter only when **Submit automatically** is enabled.

Root-level actions and custom instructions use the base Project name
`PromptMeld`. Nested action folders produce names such as
`PromptMeld - Correspondence - Email`.

You may find this Project instruction useful:

> Treat every chat as an independent writing request. Use only the text
> supplied in the current chat unless explicitly instructed otherwise.

## Safety and fallback

PromptMeld uses Windows accessibility controls rather than fixed screen
coordinates. Buttons are activated with UI Automation's Invoke pattern where
ChatGPT exposes it. A physical click is retained only as a compatibility
fallback for controls that do not expose that pattern.

The ChatGPT desktop app may expose only its outer frame on some installations
or after an interface update. If PromptMeld cannot verify the required
controls, it does not paste blindly. Instead, it focuses ChatGPT and leaves the
completed prompt on the clipboard. Open the intended Project, start a new chat,
and paste manually.

## Automation companion

UI Automation runs in `_internal\PromptMeldAutomation.exe`, a companion process
installed with PromptMeld. It starts on the first submission, is reused for
consecutive submissions, and exits after 45 seconds without another request.
It is an internal component and should not be launched manually.

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
