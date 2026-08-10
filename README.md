<p align="center">
  <img src="src/promptmeld/resources/branding/promptmeld.png" alt="PromptMeld logo" width="160">
</p>

<h1 align="center">PromptMeld</h1>

<p align="center"><em>Write well and prosper.</em></p>

PromptMeld is a Windows writing assistant for ChatGPT. Select text in another
application, press a shortcut, and choose whether you want ChatGPT to rewrite,
respond to, summarise, or review it. PromptMeld prepares the request, opens it
in an organised ChatGPT conversation, and safely handles the result according
to its purpose—including feedback that should not replace the original text.

> [!IMPORTANT]
> PromptMeld is an early release. Changes to the ChatGPT desktop app may affect
> its automation. Please report any problems through
> [GitHub Issues](https://github.com/an1uk/promptmeld-windows/issues).

## What it does

* Turns selected text into focused ChatGPT requests using four universal
  essentials, optional starter packs, or your own custom instruction.
* Guides first-time setup, including a live Windows check of the launcher
  shortcut, and provides step-by-step creation and duplication of actions.
* Includes a searchable starter-pack catalogue with action previews, installed
  status, and safe pack updates, without scanning other installed applications.
  Twenty-one packs cover replying, editing, drafting, summarising, planning,
  reviewing, and learning; nested folders keep larger libraries manageable.
* Suggests useful actions locally from the source application, text length and
  type, and recent use—for example, placing email replies first in Outlook.
* Supports editing, rewriting, replies, customer relations, tone changes,
  correspondence, technical help, platform-aware social writing, and
  developmental feedback for fiction and non-fiction authors.
* Gives every action a purpose and a result policy. Analysis, extraction, and
  idea-development actions open a non-destructive review by default instead of
  treating feedback or notes as replacement prose.
* Opens a new chat in the appropriate ChatGPT Project or, optionally, uses
  Temporary Chat to avoid filling your chat history with unrelated
  conversations. Projects can be organised by writing action, source
  application, or one shared PromptMeld project.
* Provides straightforward controls for audience, editing strength, factual
  preservation, natural voice, language, length, formatting, optional titles
  or subject lines, and additional context. Actions can supply a sensible
  audience default that remains overridable for one request.
* Clearly separates remembered overall defaults, application-specific
  overrides, and guidance that applies only to the current request.
* Previews possible email addresses, phone numbers, account numbers, and names
  before sending when enabled, with optional reversible placeholders and no
  silent redaction.
* Supports application profiles, allowing Outlook to use different writing
  defaults, response waits, and completion behaviour from Word, Teams,
  browsers, or other Windows applications.
* Can leave the prompt for review, submit it automatically, copy the result, or
  safely replace the original selection where possible.
* Provides a selective review window with before-and-after differences,
  individually accepted changes, passage-linked editorial comments, and
  separate rewrite and feedback views. Copy or apply only the accepted rewrite.
* Can request two or three alternatives, compare each with the source, and
  selectively apply the chosen option.
* Includes cancellation, verified text replacement, clipboard fallback, Undo,
  local diagnostics, configurable shortcuts, screen-reader stage
  announcements, reduced-motion behaviour, and Windows High Contrast support.
* Runs locally without an OpenAI API key, telemetry, or advertising.

![PromptMeld launcher and ChatGPT automation progress](docs/promptmeld-overview.png)

## Use ChatGPT as a beta reader

PromptMeld is not limited to producing replacement text. Select a passage from
fiction or non-fiction and use the author starter packs to ask for beta-reader
reactions, deeper questions, continuity or point-of-view checks, scene-craft
feedback, argument and evidence testing, or a review of the reader's journey.

These actions treat ChatGPT as a developmental reader rather than a substitute
author. PromptMeld preserves the selected passage and presents the response as
editorial feedback, so comments and questions are not mistaken for prose that
should overwrite the original.

## Install

PromptMeld requires Windows 10 or 11 and the current ChatGPT desktop app for
Windows, signed in to your account. It does not currently automate ChatGPT in a
web browser or through the classic desktop experience.

1. Download the installer from the
   [latest GitHub release](https://github.com/an1uk/promptmeld-windows/releases/latest).
2. Run `PromptMeld-Setup-v<version>.exe`.
3. Open **PromptMeld** from the Start menu.

On first use, a short setup guide explains the difference between ChatGPT in a
browser and the required Windows desktop app. It checks that the desktop app is
installed, links to the official OpenAI download page when needed, and tests
whether the chosen launcher shortcut is available before saving it.

No OpenAI API key or separate Python installation is required. PromptMeld can
be used with a free ChatGPT account, although the available models, Projects,
reasoning controls, and writing blocks depend on your account and plan.

The installer is not yet code-signed, so Microsoft Defender SmartScreen may
describe it as an unrecognised app. Only install copies downloaded from this
repository.

## Quick start

1. Select text in Word, Outlook, a browser, or another application.
2. Press `Ctrl+Alt+Space`.
3. Choose a writing action and select **Send _action name_** (or press Enter).

Prompts are left unsubmitted by default, giving you an opportunity to review
them and choose your ChatGPT settings before submission. Application profiles
can choose how long PromptMeld waits for an automatic result—including until
cancelled—and whether it applies, copies, or simply notifies you when ready.

Double-click the PromptMeld notification-area icon to open Configuration.

See the [user guide](docs/USER_GUIDE.md) for information about application
profiles, writing guidance, generated-result handling, shortcuts, updates,
recovery, and the example Outlook configuration.

> [!IMPORTANT]
> PromptMeld cannot verify or guarantee the accuracy of content generated by
> ChatGPT. Always review generated content carefully before using or sharing it.

## Configure

Configuration allows you to manage guided writing-action creation and testing,
portable action packs, folders, icons, shortcuts, overall defaults, updates,
application-specific profiles, versioned single-file backups, restoration, and
factory reset, and diagnostics. Editable files are stored under
`%LOCALAPPDATA%\PromptMeld`.

See [Configuration and customisation](docs/CONFIGURATION.md) for details of the
interface, JSON formats, local files, and migration behaviour.

## Privacy

PromptMeld processes selected text locally and does not save selected text,
generated prompts, or ChatGPT responses in its settings, usage records, or
logs. Smart action ranking is also performed locally and does not transmit the
selected text.

PromptMeld does not scan for Word, Outlook, browsers, editors, messaging tools,
or other installed applications. Its first-use availability check is limited
to the required ChatGPT Windows desktop app and reads only local launch
registration; the result is not logged or transmitted.

Text sent to ChatGPT is governed by your ChatGPT account settings and OpenAI's
policies. PromptMeld makes no network connections other than update checks
through GitHub.

Read the [full privacy explanation](PRIVACY.md) for details about clipboard
behaviour, locally stored data, network connections, and removal instructions.

## Documentation

* [User guide](docs/USER_GUIDE.md)
* [Configuration and customisation](docs/CONFIGURATION.md)
* [ChatGPT automation and fallback behaviour](docs/AUTOMATION.md)
* [Safety, compatibility, and limitations](docs/SAFETY_AND_LIMITATIONS.md)
* [Optional Logitech Actions Ring setup](docs/LOGITECH_ACTIONS_RING.md)
* [Development, testing, and building](docs/DEVELOPMENT.md)
* [Research report: AI Writing - Promise, Resistance and Access](docs/AI_WRITING_PROMISE_RESISTANCE_AND_ACCESS.md)
* [Third-party notices](THIRD_PARTY_NOTICES.md)

## Get involved

PromptMeld is open source. You can
[report a problem or suggest an improvement](https://github.com/an1uk/promptmeld-windows/issues),
help test releases, improve the documentation, or submit a pull request.

## Licence

PromptMeld's original source code is available under the
[MIT Licence](LICENSE).

The software is experimental and supplied without a warranty. Read
[Safety, compatibility, and limitations](docs/SAFETY_AND_LIMITATIONS.md) before
relying on it. Bundled components retain their own licences; see
[Third-party notices](THIRD_PARTY_NOTICES.md).
