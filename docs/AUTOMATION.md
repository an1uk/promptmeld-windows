# ChatGPT automation and fallback behaviour

PromptMeld automates the repetitive parts of opening a suitable ChatGPT
conversation while avoiding blind clicks or typing into an unverified control.

## Submission sequence

For each writing action, PromptMeld:

1. Remembers the source window and captures its selected text.
2. Builds a prompt from the action, selected text, and enabled style options.
3. Scans the completed prompt locally for possible private information. If any
   is found, waits for the user to select reversible redactions, continue
   unchanged, or cancel.
4. Opens or focuses the ChatGPT desktop app.
5. Selects **ChatGPT** in the global mode switch and starts a top-level new
   chat.
6. Looks for the exact folder-specific Project, such as
   `PromptMeld - Editing`.
7. Expands the Projects list before deciding that a Project is missing. When
   ChatGPT asks whether a new Project is Cloud or Local, PromptMeld requires
   the complete paired choice and selects **Cloud** explicitly; it never falls
   back to Local.
8. Starts a fresh chat in that Project.
9. Verifies the active Project and message composer through Windows UI
   Automation.
10. Inserts the prompt through the composer's UI Automation text pattern when
   supported, otherwise uses a control-targeted clipboard paste.
11. Reads the composer back and continues only after the complete prompt is
    verified.
12. Presses Enter only when **Submit automatically** is enabled. Before
    submission it records the response controls already present. After
    activating Send, it requires evidence that ChatGPT accepted this request,
    such as the composer clearing, generation beginning, or a new response
    control appearing. An ambiguous submission is never retried or copied to
    the clipboard automatically; PromptMeld requires ChatGPT inspection.
13. When generated-text output or alternative review is enabled and automatic
    submission is on,
    waits for ChatGPT's generating control to disappear and remain absent,
    then uses a verified **Copy** control only when it belongs to the submitted
    user message and the same conversation container. Stable UI Automation
    identities, not the global position of a Copy control, exclude unrelated
    chats, reordered controls, and stale wrappers.
14. Restores any exact privacy placeholders locally in the retrieved response.
15. Transfers the verified response to PromptMeld's main process before any
    source-document action. The companion never receives source text, a source
    window handle, or permission to paste into another application.
16. Revalidates the captured process creation identity, top-level window,
    exact focused control, control classes, supported adapter, and selection
    range. Automatic replacement is available only through an adapter that can
    read the inserted range back.
17. Applies the response and proves the prefix, inserted range, and suffix from
    a second read. A mismatch is rolled back when that can be proved safe. An
    unsupported or unverified source retains the result for **Copy result** or
    a later verified **Apply now** action and is never reported as replaced.

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
up smoothly. If Windows animations are disabled, the stage is positioned
immediately instead. Every new stage updates its accessible name for screen
readers without raising a routine alert that Windows may turn into a sound.
History items expose whether they are current, completed, successful, or need
attention. A successful result is added as the final entry; a problem stays
visible so it can be acted on. Choose **Cancel** or press Escape to request
cooperative cancellation. The companion acknowledges the request, completes
checkpoint-safe cleanup, and is terminated only if it does not respond within
the cleanup grace period. ChatGPT may continue if the prompt was already
submitted, so the final message tells you what to inspect before retrying.

Only one automation can run at a time. Pressing a PromptMeld hotkey while a run
is active restores the current progress window without capturing another
selection, changing the clipboard, or queuing text that may become stale.

ChatGPT can take several minutes to answer. The companion sends activity
heartbeats every two seconds while navigation or response monitoring is making
progress; PromptMeld stops only a no-progressing companion rather than applying
a fixed total helper deadline. The progress window reports that it is still
waiting every 30 seconds. The inherited response limit is five minutes; an application
profile can select one, three, five, ten, or twenty minutes, or wait
indefinitely until cancelled. You may continue working in another application
while it waits. When the response is ready, a requested automatic replacement
returns to the captured source window and rechecks the original selection. If
another application is currently in use, PromptMeld does not interrupt it and
copies the generated result instead. Changed or unavailable source content is
also left untouched.

Project creation is complete only when the exact Project context, Project row,
or Project-specific new-chat action is exposed. A dismissed creation dialog is
not proof of success. If the Create action has an ambiguous outcome,
PromptMeld does not activate it again automatically; recovery offers ChatGPT
inspection and a copied prompt instead. Privacy-safe diagnostic codes identify
the failed creation checkpoint without recording Project names.

When PromptMeld retrieves a completed response, the completion window offers
**Copy result** and, when the captured source has a verified adapter,
**Apply now**.
Matching tray commands remain available after the window closes. A delayed
apply performs the same process, window, control, range, and read-back checks
as an automatic replacement; failure offers a copy of the generated result.

For a request containing two or three alternatives, PromptMeld asks ChatGPT to
place each complete option between numbered marker lines. It retrieves the
response without automatically copying or replacing text, parses only a full
set of numbered alternatives, and opens a separate review window. A tolerant
fallback recognises clearly numbered Alternative headings. If neither format
is complete, the entire response remains available as one review option.

The automation progress window shows operational stage names only. It does not
display the selected text, assembled prompt, or response, and it does not take
focus away from ChatGPT. The separate alternatives review window necessarily
displays the generated options so the user can compare and choose one.

When Windows High Contrast is active, the progress window and other PromptMeld
windows use the system palette rather than their normal fixed theme colours.
This preserves the user's chosen foreground, background, selection, border,
and focus contrast.

## Safety and fallback

PromptMeld uses Windows accessibility controls rather than fixed screen
coordinates. It first tries UI Automation's Invoke and SelectionItem patterns,
then focused keyboard activation. A physical click is retained only as a final
compatibility fallback for controls that expose none of those methods.

The current ChatGPT app is verified by its installed package and process, not
only by the visible window title. ChatGPT Classic and unknown processes are
ignored. A cold launch allows up to 60 seconds for the app and accessibility
tree to become ready, while already-ready windows keep the fast path.

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
control is not exposed within the configured finite wait, PromptMeld reports
that the response was submitted but does not replace the original selection.
An indefinite wait continues until a response is exposed or the user cancels.
PromptMeld does not activate **Copy** while a visible, enabled **Stop
generating** control indicates that the answer is still streaming, and it
confirms the generating control remains absent before copying. The selected
text is never replaced based on an incomplete or unverified clipboard value.
Response controls that existed before submission are excluded, and a newly
indexed Copy control is insufficient by itself: the submitted message and its
conversation ownership must still be present.

Short clipboard operations preserve the prior Windows clipboard data object
when possible. PromptMeld restores a clipboard value only while it still owns
the most recent clipboard change; content copied by the user or another
application while PromptMeld is waiting is never overwritten.

## Guided recovery

Recoverable failures remain in the progress window with actions appropriate to
the last verified checkpoint. Before submission, **Retry** repeats delivery of
the already prepared prompt. After confirmed submission, **Retry response**
retrieves the existing response without sending the prompt again. Ambiguous
submission offers **Open ChatGPT** and **Copy prompt**, but deliberately omits
automatic retry to avoid duplicate messages.

PromptMeld writes an atomic, metadata-only pending-run journal containing the
run ID, timestamps, checkpoint, and submission disposition. It never stores
selected text, prompts, responses, Project names, or source titles. After a
restart, PromptMeld explains whether the prior run stopped before Send, may
have submitted, or definitely submitted. Cross-restart recovery is guided
inspection only: it never resubmits or reapplies automatically.

The tray's **Diagnostics > Test ChatGPT connection** action performs a
non-destructive package, launch, sign-in, and accessibility readiness check. It
does not create a chat, insert text, or submit anything.

**Diagnostics > Run full automation test** is a separate, explicit opt-in
canary. Its confirmation explains that one harmless unique test phrase is
submitted in a verified Temporary Chat. The returned phrase crosses the
companion boundary, is correlated to the canary request, and is applied and
read back through a
fingerprinted PromptMeld-owned scratch adapter, and is then reversed with
read-back verification. A private text-plus-custom-format clipboard marker
proves full clipboard restoration; a newer user copy is never overwritten. It
never uses a user selection or document.

Automatic replacement is deliberately opt-in. PromptMeld keeps the original
selection in memory and exposes an adapter-specific reversal plus a
copy-original recovery action in the tray. Reversal first verifies that the
exact inserted range is unchanged; otherwise it offers **Copy original** and
does not dispatch a delayed generic Ctrl+Z. Preserved text is never written to
disk. The generated result can still be wrong, so users remain responsible for
reviewing it.

Configuration's **Applications** tab can override the global output defaults,
response wait, and completion behaviour for individual executables. A
replacement policy automatically degrades to copy-only when the captured
control is not editable.

## Automation companion

ChatGPT UI Automation runs in `_internal\PromptMeldAutomation.exe`, a companion
process installed with PromptMeld. A versioned startup handshake precedes every
warm session. Each request, progress event, heartbeat, cancellation, response
capture, and result carries protocol version, request ID, run ID, checkpoint,
and attempt number. An incompatible warm companion is restarted once only
while the request is still before Send; any later mismatch fails safely
without reissuing delivery. The companion accepts only this versioned server
protocol. It starts on the first
submission, is reused for consecutive submissions, and exits after 45 seconds
without another request. It is an internal component and should not be launched
manually.

The companion is Per-Monitor V2 DPI aware so its guarded physical-click
fallback uses the correct coordinates when ChatGPT opens on a display with a
different scale setting.

Prompt and retrieved response data are passed between PromptMeld and the
companion through a local pipe and are not written to disk. A captured response
is retained in main-process memory as soon as it crosses that boundary, so a
later helper failure cannot discard it. Operational stage
timings and errors are written to `promptmeld.log`, but selected text, prompt
contents, and responses are excluded. See
[Privacy](../PRIVACY.md) for the complete data-handling explanation.

## ChatGPT interface dependencies

PromptMeld depends on accessibility information exposed by the current ChatGPT
desktop application. Changes to control names or structure can require a
PromptMeld update even though the guarded clipboard fallback continues to work.
Semantic control selectors are centralized and diagnostics record only the
privacy-safe selector identifier that was used, making interface drift easier
to isolate without logging control text.

Related OpenAI documentation:

- [ChatGPT Work and Codex](https://help.openai.com/en/articles/20001275)
- [The ChatGPT desktop app](https://help.openai.com/en/articles/20001276/)
- [Projects in ChatGPT](https://help.openai.com/en/articles/10169521-projects-in-chatgpt)
