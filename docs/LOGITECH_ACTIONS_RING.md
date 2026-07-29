# Optional Logitech Actions Ring setup

*Write well and prosper.*

PromptMeld works fully through keyboard shortcuts without Logitech hardware or
software. This optional integration uses Logi Options+ Smart Actions as a
reliable bridge for compatible devices. No custom Logitech plugin is required.

## Before you begin

1. Start PromptMeld.
2. Confirm that `Ctrl+Alt+Space` opens its popup when text is selected.
3. Open Logi Options+ and make sure Actions Ring and Smart Actions are enabled for the MX Master 4.

Logitech documents that Smart Actions can use device or Actions Ring triggers and perform keystroke actions: [creating Smart Actions](https://support.logi.com/hc/en-ca/articles/14307858722327-How-to-create-a-new-Smart-Actions-on-Logi-Options).

## Create the “More…” action

1. Open **Smart Actions** in Logi Options+.
2. Choose **Create**.
3. Name it `PromptMeld – More`.
4. Add a **Keystroke** action.
5. Record `Ctrl+Alt+Space`.
6. Save it.
7. Open the Actions Ring configuration.
8. Assign the new Smart Action to a ring position and label it `More…`.

This captures the selected text and opens the searchable launcher.

## Create direct writing actions

Repeat the same process for the actions you want directly on the ring:

| Smart Action name | Keystroke | Suggested label |
|---|---|---|
| PromptMeld – Edit | `Ctrl+Alt+1` | Edit |
| PromptMeld – Shorten | `Ctrl+Alt+2` | Shorten |
| PromptMeld – Strengthen | `Ctrl+Alt+3` | Strengthen |
| PromptMeld – Reply | `Ctrl+Alt+4` | Reply |
| PromptMeld – Sarcastic | `Ctrl+Alt+5` | Sarcastic |
| PromptMeld – Firm reply | `Ctrl+Alt+6` | Firm reply |

Direct actions capture the current selection and submit immediately. They do not open the launcher popup.

## Recommended layout

Use six direct actions, one `More…` action, and leave the final ring position
for another frequently used system action. The popup supports folders and
nested subfolders, and search covers every folder. Actions inside a folder are
ranked from usage; Smart Action positions remain fixed in V1.

## Troubleshooting

- If nothing happens, confirm PromptMeld is visible in the Windows notification area.
- Test the keyboard shortcut outside Logi Options+ first.
- If PromptMeld reports a shortcut conflict, change it in the **Hotkeys** tab
  of **Configuration…**, then update the matching Smart Action.
- If ChatGPT opens but does not receive the prompt, check the clipboard. The full prompt is copied whenever safe desktop automation is unavailable.
- Logi Options+ can require a brief delay after application switching, but PromptMeld itself performs the ChatGPT wait and does not require a delay in the Smart Action.

## Future plugin decision

A custom C# Logi Actions plugin is worth adding only if the launcher's folders
and icons should synchronize into Actions Ring itself, Marketplace
distribution is wanted, or MX Master 4 haptic feedback becomes important.
Logitech’s SDK supports plugin-to-application IPC and C# haptics:
[plugin model](https://logitech.github.io/actions-sdk-docs/plugin-basics/) and
[supported devices](https://logitech.github.io/actions-sdk-docs/supported-devices/).
