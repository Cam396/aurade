"""The AuraDE greeter.

Everything that decides anything lives in a module with no toolkit in it, so
the sign in conversation, the account rules and the session rules can all be
driven to their ends by a test on a machine with no display.

`a11y.py`, `brand.py`, `status.py`, `tokens.py` and the five `theme-*.css`
files are **copies of the installer's**, carried across unchanged.
`tests/shared_test.py` asserts every one is byte for byte identical to its
original under `installer/lib/aurade_gui/`, so they cannot drift apart
quietly. That test failing means somebody changed one side and not the other,
and the fix is to copy again rather than to edit the copy here.

They are copies rather than a shared package because the installer exists only
on the installation media and the greeter exists only on the installed system,
so there is no moment when both are present and one could depend on the other.
They sit in this directory rather than a `shared/` one below it because
makepkg resolves every local source to its basename, so a package with a
subdirectory in it cannot be built at all.
"""
