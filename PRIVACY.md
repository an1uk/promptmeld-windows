# Privacy

PromptMeld runs locally and does not include telemetry, analytics, advertising, or an AI API client.

## Text handling

- Selected text is copied through the Windows clipboard after an explicit hotkey or Actions Ring command.
- A prompt is assembled in memory and pasted into the signed-in ChatGPT desktop app.
- The prompt is passed in memory to a short-lived local automation companion
  process; it is not written to a temporary file.
- If desktop automation cannot verify the required controls, the prompt remains on the clipboard for manual pasting.
- CopyQ or another clipboard-history application may independently retain clipboard contents according to its own settings.

## Stored data

PromptMeld stores:

- User-editable settings and action definitions.
- Per-action usage counts and last-used timestamps for ranking.
- Operational log messages and automation errors.

The application does not log selected text, custom instructions, assembled prompts, or ChatGPT responses.

## Network access

PromptMeld itself makes no network requests. ChatGPT receives text only when the launcher submits it through the desktop app or you paste the fallback prompt manually.
