<p align="center">
  <img src="src/promptmeld/resources/branding/promptmeld.png" alt="PromptMeld logo" width="160">
</p>

<h1 align="center">PromptMeld</h1>

<p align="center"><em>Write well and prosper.</em></p>

PromptMeld is a Windows writing assistant for ChatGPT. Select text in another
application, press a shortcut, and choose how you want to transform or respond
to it. PromptMeld prepares the request, opens an organised ChatGPT conversation,
and can return the result to your original application.

> [!IMPORTANT]
> PromptMeld is an early release and changes to the ChatGPT desktop app can
> affect its automation. Please report problems through
> [GitHub Issues](https://github.com/an1uk/promptmeld-windows/issues).

## What it does

- Turns selected text into focused ChatGPT requests using 26 included writing
  actions or your own instruction.
- Handles editing, rewriting, replies, tone, correspondence, technical help,
  and other everyday writing tasks.
- Opens a fresh chat in the appropriate ChatGPT Project, or optionally uses
  Temporary Chat.
- Provides concise controls for audience, editing strength, factual
  preservation, natural voice, language, length, formatting, and context.
- Supports application profiles: Outlook can use different writing defaults
  from Word, Teams, browsers, or any other Windows application.
- Can leave the prompt for review, submit it automatically, copy the result, or
  safely replace the original selection when possible.
- Includes cancellation, verified replacement, clipboard fallback, Undo,
  local diagnostics, configurable shortcuts, and keyboard-accessible controls.
- Runs locally without an OpenAI API key, telemetry, advertising, or a required
  Logitech device. Compatible Logitech Options+ Actions Ring hardware remains
  optional.

![PromptMeld launcher and ChatGPT automation progress](docs/promptmeld-overview.png)

## Install

PromptMeld requires Windows 10 or 11 and the current ChatGPT desktop app for
Windows, signed in to your account. It does not currently automate ChatGPT in a
web browser or the Classic desktop experience.

1. Download the installer from the
   [latest GitHub release](https://github.com/an1uk/promptmeld-windows/releases/latest).
2. Run `PromptMeld-Setup-v<version>.exe`.
3. Open **PromptMeld** from the Start menu.

No OpenAI API key or separate Python installation is required. PromptMeld can
be used with a free ChatGPT account, although available models, Projects,
reasoning controls, and writing blocks depend on the account and plan.

The installer is not yet code-signed, so Microsoft Defender SmartScreen may
describe it as an unrecognised app. Only install a copy downloaded from this
repository.

## Quick start

1. Select text in Word, Outlook, a browser, or another application.
2. Press `Ctrl+Alt+Space`.
3. Choose a writing action.

Prompts are left unsubmitted by default, allowing you to review them and choose
ChatGPT settings first. Double-click the PromptMeld notification-area icon to
open Configuration.

See the [user guide](docs/USER_GUIDE.md) for application profiles, writing
guidance, generated-result handling, shortcuts, updates, recovery, and the
example Outlook configuration.

## Configure

Configuration manages writing actions, folders, icons, shortcuts, writing
defaults, updates, and application-specific profiles. Editable files are kept
under `%LOCALAPPDATA%\PromptMeld`.

See [Configuration and customisation](docs/CONFIGURATION.md) for the interface,
JSON formats, local files, and migration behaviour.

## Privacy

PromptMeld processes selected text locally and does not write selected text,
prompts, or ChatGPT responses to its settings, usage records, or logs. Text
sent to ChatGPT is governed by your ChatGPT account settings and OpenAI's
policies. Update checks contact GitHub only.

Read the [full privacy explanation](PRIVACY.md), including clipboard behaviour,
locally stored data, network connections, and removal instructions.

## Documentation

- [User guide](docs/USER_GUIDE.md)
- [Configuration and customisation](docs/CONFIGURATION.md)
- [ChatGPT automation and fallback behaviour](docs/AUTOMATION.md)
- [Safety, compatibility, and limitations](docs/SAFETY_AND_LIMITATIONS.md)
- [Optional Logitech Actions Ring setup](docs/LOGITECH_ACTIONS_RING.md)
- [Development, testing, and building](docs/DEVELOPMENT.md)
- [Research report: AI Writing — Promise, Resistance and Access](docs/AI_WRITING_PROMISE_RESISTANCE_AND_ACCESS.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## Get involved

PromptMeld is open source. You can
[report a problem or suggest an improvement](https://github.com/an1uk/promptmeld-windows/issues),
help test releases, improve the documentation, or submit a pull request.

## Licence

PromptMeld's original source code is available under the
[MIT Licence](LICENSE). The software is experimental and supplied without a
warranty; read [Safety, compatibility, and limitations](docs/SAFETY_AND_LIMITATIONS.md)
before relying on it. Bundled components retain their own licences; see
[Third-party notices](THIRD_PARTY_NOTICES.md).
