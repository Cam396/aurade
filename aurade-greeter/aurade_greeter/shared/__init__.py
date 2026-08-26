"""The installer's design system, carried into the greeter unchanged.

These files are copies. `tests/shared_test.py` asserts every one of them is
byte for byte identical to its original under `installer/lib/aurade_gui/`, so
the two cannot drift apart quietly. That test failing means somebody changed
one side and not the other, and the fix is to copy again rather than to edit
here.

Copies rather than a shared package because the installer lives only on the
installation media and the greeter lives only on the installed system, so
there is no moment when both are present and one could depend on the other.
Extracting a real shared package is worth doing once a third thing needs
these, and not before.

The greeter uses `tokens` for the Material 3 roles, `brand` for the aurora and
the mark, `a11y` for the announcements a screen reader needs, and `status` for
the clock, the battery and the network, which the installer already reads from
`/sys` and `/proc` with no toolkit involved.
"""
