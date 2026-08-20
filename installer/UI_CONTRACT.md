# AuraDE installer UI contract

The graphical and text installers are two views of the same engine. A front end
may change presentation, but it may not create a second safety policy.

## Shared rules

- Show the target disk identity and the erase warning immediately before any
  destructive action.
- Keep the reversible and irreversible stages visible.
- Never place passwords, LUKS keys, or Wi-Fi credentials in a journal, log,
  diagnostic export, command line, or screen that is not a secret field.
- Explain failures in plain language and give one useful next action.
- Keep a text path available when graphics, a compositor, or a display driver
  is unavailable.
- Do not expire a decision or move focus without the user's action.
- Preserve keyboard navigation, readable contrast, and screen-reader labels.

## Flow

The shared question manifest owns validation, defaults, help text, and the engine
flag for each answer. The GUI and text front ends read that manifest; they do
not duplicate validators or silently apply hidden defaults.

The journal is append-only. It records stage, attempt, target identity, and a
bounded failure cause without recording raw command output or secrets.

## Adding a front end

Add a renderer only after the shared flow and refusal tests pass. Exercise the
welcome, network, language, disk, erase, progress, failure, and completion
states in both light and dark presentation where applicable. Run
bash installer/tests/run.sh before describing the front end as complete.
