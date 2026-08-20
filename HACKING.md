# Hacking on AuraDE

AuraDE adapts the Ash desktop to ordinary Linux rather than reproducing the
whole ChromeOS device stack. Most changes are small compatibility layers:
session state, display startup, local accounts, networking, packaging, and the
installer.

## Find the right layer

- Put user-facing behavior in the AuraDE package or session wrapper when it
  does not need Chromium changes.
- Keep Chromium changes in an ordered patch under patches/.
- Keep NetworkManager integration in shill-nm-adapter/.
- Keep destructive installation logic in the installer engine, not in a UI.

## Patch conventions

Use // AuraDE compatibility: for a deliberate long-lived adaptation. Use
// HACK(AuraDE): only for a temporary workaround with a removal condition.
Keep comments focused on why the upstream assumption does not hold on Linux.

Before opening a change:

~~~bash
git diff --check
ci/source-integrity-gate.sh
~~~

For Chromium work, verify the exact source tree with:

~~~bash
CHROME_SRC=/path/to/chromium/src ci/verify-patch-series.sh --expect-tree-match
~~~

## Runtime debugging

Reproduce on a disposable session, capture the smallest useful log excerpt,
and distinguish a source hypothesis from a runtime result. Do not add a broad
disable or a fake service to make a test green. If a change affects login,
network, graphics, or power, add a focused regression test and run the full
installer and package gates before claiming it is complete.
