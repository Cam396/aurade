# AuraDE optional features

AuraDE keeps its base desktop small and predictable. Optional features can be
installed when a user wants them, without changing the core login, installer,
or recovery path.

## Base profile

The base profile provides the desktop session, local accounts, files and
settings integration, networking, audio, power, display, accessibility, and
the recovery tools needed by the selected filesystem layout.

## Optional local assistance

Local assistant features are opt-in. They should work without sending user
documents or prompts to a remote service, make resource use visible, and be
easy to remove. The base profile does not require a model, a cloud account, or
an API credential.

## Design rules

- Never make a remote service a hidden dependency of the desktop.
- Keep sensitive data on the machine unless the user explicitly chooses a
  remote provider.
- Show what is running and how to stop it.
- Keep package and image growth measured.
- Provide a text and keyboard path for every important setting.

## Future work

The optional profile may grow to include document search, speech tools, and
small local helpers. Each addition needs a clear privacy statement, a resource
budget, a package boundary, and a removal path before it becomes part of a
release.
