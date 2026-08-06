# PromptMeld privacy

PromptMeld runs on your Windows computer. It does not contain telemetry,
analytics, advertising, or an OpenAI API client. Its only direct network
feature is the optional GitHub release check and installer download described
below.

## The short version

- Avoid selecting personal, confidential, or otherwise sensitive details unless
  you are comfortable sending them to ChatGPT. Once inserted, ChatGPT may retain,
  store, and record them according to your account settings and OpenAI's
  policies; PromptMeld cannot prevent that.
- PromptMeld captures text only after you invoke a shortcut or optional Actions
  Ring command.
- Selected text is transferred through the Windows clipboard and held
  transiently in process memory while PromptMeld assembles the request.
- Smart action suggestions inspect the captured text locally and retain only
  the source executable, word count and length band, and detected type labels
  while the launcher is open. No ranking request is made over the network.
- The completed prompt is inserted into the verified ChatGPT composer through
  local Windows accessibility controls. The clipboard is used when direct
  insertion is unavailable and for the manual fallback.
- When the enabled privacy-preview setting finds likely email addresses, phone
  numbers, account numbers, or names, it shows an optional redaction preview.
  No replacement happens without an explicit choice.
- PromptMeld does not save selected text, one-off custom instructions,
  completed prompts, or ChatGPT responses to disk.
- The automation progress window shows stage descriptions only, not the
  selected text or completed prompt.
- The alternatives review window displays generated response text locally when
  two or three results were requested.
- By default, PromptMeld checks GitHub at most once per day for a stable update.
  This can be disabled in Configuration. No selected text, prompt, response, or
  configuration content is included in the request.
- The ChatGPT desktop app communicates with OpenAI after text is inserted into
  it.

## Privacy preview and reversible redaction

Before a prompt is opened in ChatGPT, PromptMeld locally checks it for patterns
that may be email addresses, phone numbers, account numbers, or personal names.
This is deterministic pattern matching inside PromptMeld; no text is sent to a
detection service. Name detection includes common titles, greetings, labelled
fields, signatures, and capitalised full names in user-content blocks. The
check can produce false positives and false negatives.

Privacy preview is enabled by default. It can be disabled under
**Configuration > Overall defaults > Submission**, or inherited, enabled, or
disabled for a particular executable under **Configuration > Applications**.
When it is enabled and matches are found, PromptMeld displays the preview. The
user chooses each value to redact, continues with the original prompt unchanged,
or cancels. No detected value is replaced silently. Selected values become
tokens such as `[EMAIL_1]` or `[NAME_1]`, and only the redacted prompt is
inserted into ChatGPT. When it is disabled, PromptMeld does not perform the
local check or offer redaction for that prompt.

The placeholder-to-original replacement key is held in process memory and sent
only through PromptMeld's local automation-helper pipe. It is not written to
settings, usage history, logs, diagnostics, backups, or update state. When
PromptMeld retrieves a completed response, exact placeholders are restored
locally before the result is copied or applied. If PromptMeld does not retrieve
the result, placeholders remain in ChatGPT. A placeholder that ChatGPT changes
or omits cannot be restored automatically. The replacement key is forgotten
when the request finishes or PromptMeld exits.

## Local action suggestions

PromptMeld locally classifies the selection into broad categories such as
email, question, complaint, technical text, notes, review, or online argument.
It combines those labels with the source executable, a word-count length band,
and local action usage history to order suggestions and equally relevant search
results. The classifier is deterministic Python code included with PromptMeld;
it does not call ChatGPT or another detection or ranking service.

The suggestion context does not contain the selected words and is discarded
when replaced by a later capture or when PromptMeld exits. Only normal
per-action counts and last-used times remain in `usage.json`; they contain no
source text, derived text-type history, source-application history, or prompt.

## What happens to selected text

1. PromptMeld remembers the application you were using.
2. It clears the text clipboard and sends that application `Ctrl+C`.
3. The selected text enters the Windows clipboard and is read into PromptMeld's
   process memory.
4. PromptMeld combines the selected text with the chosen action and any enabled
   style options. This completed prompt is held in memory.
5. PromptMeld checks the prompt locally. If possible private details are found,
   the privacy preview waits for an explicit redaction, unchanged, or cancel
   choice.
6. The chosen prompt and any in-memory replacement key pass to the local
   automation companion through a local inter-process pipe.
7. PromptMeld inserts the chosen prompt into a verified ChatGPT message
   composer through local Windows accessibility controls. If that direct method
   is unavailable, it places the prompt on the clipboard and performs a
   control-targeted paste instead.
8. PromptMeld reads the composer back and continues only after verifying the
   complete prompt. After successful insertion, it restores the original
   selected text to the clipboard.

When **Copy generated text to the clipboard** is enabled, the generated ChatGPT
response replaces the restored clipboard contents after ChatGPT responds. When
automatic replacement is enabled for an editable selection, PromptMeld also
returns focus to the original application and pastes that response over the
selection. The response is held transiently in memory while this happens and
is not written to PromptMeld files.

The selected text and completed prompt are used only for this immediate
operation. PromptMeld does not write them to a temporary file, database,
configuration file, usage file, or log.

If PromptMeld cannot verify a safe place to insert the prompt, it does not type
into an unknown control. It focuses ChatGPT and leaves the completed prompt on
the clipboard so you can paste it manually. In that case, the original
clipboard contents are not restored automatically because doing so would
remove the fallback prompt.

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

### Do not assume the text is private until you press Return

There is evidence that text merely entered into the ChatGPT message box may be
sent to or processed by OpenAI before you press Return. PromptMeld cannot see
or control that behaviour. Do not assume that editing, replacing, or leaving a
prompt unsent will prevent OpenAI from having seen the earlier text.

This means you should select and activate PromptMeld only with text that you
are willing to expose to ChatGPT, even when **Submit automatically** is disabled.
ChatGPT data controls and Temporary Chat may change how content is retained or
used, but should not be treated as a guarantee that unsent composer text was
never transmitted.

PromptMeld transfers only the assembled writing request to the ChatGPT desktop
app. It inserts the text into the verified message composer through Windows
accessibility controls or a control-targeted clipboard paste.

With **Submit automatically** disabled, PromptMeld does not press Enter. With
it enabled, PromptMeld presses Enter after verifying the complete composer
text. Once text is present in the ChatGPT application, its processing,
transmission, storage, and use are controlled by the ChatGPT application, your
OpenAI account settings, and OpenAI's policies. PromptMeld cannot control that
handling.

When generated-result copying or replacement is enabled, PromptMeld reads the
completed response through ChatGPT's local Copy control. The response is held
briefly in memory and placed on the clipboard or pasted into the verified
source selection. The latest retrieved response remains in process memory so
the completion window and tray can offer **Copy result** and **Apply now**. It
is replaced by the next retrieved response and forgotten when PromptMeld
exits. It is not written to PromptMeld's files or diagnostics.

When alternatives are requested, the retrieved response and its separated
options remain in process memory while the review window is available. The
chosen option becomes the latest result used by the tray commands. Alternatives
are cleared when a newer response arrives and are forgotten when PromptMeld
exits; they are never written to settings, logs, diagnostics, or backups.

For replacement, the original selected text is preserved in memory so the
tray can copy it for recovery and invoke the source application's native Undo
command. Only the most recently preserved original is retained, and it is
forgotten when PromptMeld exits. It is not included in logs, diagnostics,
settings, usage records, or update requests.

## What PromptMeld stores

PromptMeld stores the following files under `%LOCALAPPDATA%\PromptMeld`:

- `actions.json`: action names, instructions, shortcuts, folders, and icons.
- `settings.json`: launcher and writing-style preferences.
- `usage.json`: per-action usage counts and last-used timestamps for ranking.
- `promptmeld.log`: operational messages, timings, and errors.
- `update-state.json`: the last update attempt, cached public release metadata,
  and the last version for which a notification was shown.
- `updates\`: a verified installer while an update is being applied; old update
  downloads are removed on a later launch.
- `icons\`: images you import for actions or folders.
- `backups\`: automatic pre-restore configuration safety backups. These contain
  saved actions, settings, application profiles, hotkeys, and custom icons.
- Migration backups of older configuration files, when applicable.

Configuration backups you create manually are single ZIP files stored wherever
you choose. They contain the same saved configuration and custom-icon data, but
not usage history, logs, update state, selected text, prompts, or responses.

The operational log does not include selected text, one-off custom
instructions, completed prompts, clipboard contents, or ChatGPT responses.

## Network access

When automatic update checks are enabled, PromptMeld makes a standard HTTPS
request to GitHub's public API at most once per day to read the latest stable
release metadata. A manual check makes the same request. Downloading an update
retrieves the selected installer from GitHub's release infrastructure.

These requests contain a PromptMeld version User-Agent but no selected text,
prompts, ChatGPT responses, writing actions, preferences, machine identifier,
or analytics identifier. As with an ordinary visit to GitHub, GitHub and its
content-delivery providers receive normal connection information such as the
IP address and request headers. Automatic checks can be disabled under
**Configuration > General > Updates**; manual checks and the GitHub release
link remain available.

PromptMeld does not send information to the PromptMeld developer, Logitech, or
an analytics provider.

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

Delete any manually created `PromptMeld-backup-*.zip` files separately from
the locations where you saved them.

Review and clear Windows Clipboard History or any third-party clipboard history
separately if required.
