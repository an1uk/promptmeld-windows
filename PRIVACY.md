# PromptMeld privacy

PromptMeld runs on your Windows computer. It does not contain telemetry,
analytics, advertising, an OpenAI API client, or any other cloud service of its
own.

## The short version

- Avoid selecting personal, confidential, or otherwise sensitive details unless
  you are comfortable sending them to ChatGPT. Once pasted, ChatGPT may retain,
  store, and record them according to your account settings and OpenAI's
  policies; PromptMeld cannot prevent that.
- PromptMeld captures text only after you invoke a shortcut or optional Actions
  Ring command.
- Selected text is transferred through the Windows clipboard and held
  transiently in process memory while PromptMeld assembles the request.
- The completed prompt is placed on the clipboard and pasted into the ChatGPT
  desktop app.
- PromptMeld does not save selected text, one-off custom instructions,
  completed prompts, or ChatGPT responses to disk.
- PromptMeld makes no network requests. The ChatGPT desktop app communicates
  with OpenAI after text is pasted into it.

## What happens to selected text

1. PromptMeld remembers the application you were using.
2. It clears the text clipboard and sends that application `Ctrl+C`.
3. The selected text enters the Windows clipboard and is read into PromptMeld's
   process memory.
4. PromptMeld combines the selected text with the chosen action and any enabled
   style options. This completed prompt is held in memory and passed to the
   local automation companion through a local inter-process pipe.
5. PromptMeld places the completed prompt on the clipboard and pastes it into a
   verified ChatGPT message composer.
6. After a successful paste, PromptMeld restores the original selected text to
   the clipboard.

The selected text and completed prompt are used only for this immediate
operation. PromptMeld does not write them to a temporary file, database,
configuration file, usage file, or log.

If PromptMeld cannot verify a safe place to paste, it does not type into an
unknown control. It focuses ChatGPT and leaves the completed prompt on the
clipboard so you can paste it manually. In that case, the original clipboard
contents are not restored automatically because doing so would remove the
fallback prompt.

## The Windows clipboard

The clipboard is a shared Windows facility, not private storage owned by
PromptMeld. Windows Clipboard History, cloud clipboard synchronisation, CopyQ,
and other clipboard managers may retain or synchronise copied text according
to their own settings. Other software with clipboard access may also be able to
read its current contents.

If you work with sensitive text, review or disable clipboard history and any
third-party clipboard manager before using PromptMeld. You can also clear
clipboard history after use.

## What reaches ChatGPT

Do not use PromptMeld to send passwords, payment details, private identifiers,
confidential business information, or other sensitive material unless you have
checked that ChatGPT is an appropriate destination and understand how your
account handles conversations. Treat selected text as information you are
deliberately sending to ChatGPT, not as text that remains private because
PromptMeld itself does not store it.

PromptMeld transfers only the assembled writing request to the ChatGPT desktop
app. It does this by pasting into the message composer, just as if you had
copied and pasted the text yourself.

With **Submit automatically** disabled, PromptMeld does not press Enter. With
it enabled, PromptMeld presses Enter after the paste. Once text is present in
the ChatGPT application, its processing, transmission, storage, and use are
controlled by the ChatGPT application, your OpenAI account settings, and
OpenAI's policies. PromptMeld cannot control that handling.

PromptMeld does not read, record, or export ChatGPT's response.

## What PromptMeld stores

PromptMeld stores the following files under `%LOCALAPPDATA%\PromptMeld`:

- `actions.json`: action names, instructions, shortcuts, folders, and icons.
- `settings.json`: launcher and writing-style preferences.
- `usage.json`: per-action usage counts and last-used timestamps for ranking.
- `promptmeld.log`: operational messages, timings, and errors.
- `icons\`: images you import for actions or folders.
- Migration backups of older configuration files, when applicable.

The operational log does not include selected text, one-off custom
instructions, completed prompts, clipboard contents, or ChatGPT responses.

## Network access

PromptMeld itself makes no network requests and does not send information to
the PromptMeld developer, Logitech, or an analytics provider.

The separate ChatGPT desktop app requires network access to provide its
service. Optional Logitech integration starts PromptMeld actions but is not
used by PromptMeld to transmit selected text.

## Removing local data

Uninstalling PromptMeld removes the installed application. To remove your
settings, usage history, imported icons, logs, and migration backups as well,
delete:

```text
%LOCALAPPDATA%\PromptMeld
```

Review and clear Windows Clipboard History or any third-party clipboard history
separately if required.
