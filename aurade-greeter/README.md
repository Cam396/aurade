# aurade-greeter

The graphical greeter for AuraDE, drawn with the installer's design system.

The parts that decide anything have no toolkit in them and can be driven to
their ends by a test on a machine with no display: `protocol.py` holds the
whole greetd conversation, `accounts.py` holds the rule for who counts as a
person, `sessions.py` holds the session picker. `app.py` is the part that
draws.

`aurade_greeter/shared/` carries copies of the installer's tokens, brand
drawing, accessibility helpers, status readings and generated stylesheets.
They are copies because the installer exists only on the installation media
and the greeter exists only on the installed system, so neither can import the
other. `tests/shared_test.py` asserts every one is byte for byte identical to
its original, so they cannot drift apart quietly. If that test fails, copy the
file again rather than editing the copy.

## Running the tests

    ./run-tests.sh

The window test needs a compositor and starts a headless weston. It skips
loudly rather than failing when there is not one, and says so in its own line,
so a run with no runtime coverage cannot be mistaken for a run with it.

## Turning it on

This package does not switch the greeter. `aurade.toml.example` is the greetd
configuration that uses it, and copying it over `/etc/greetd/aurade.toml` is a
deliberate act. Keep `greetd-tuigreet` installed: it is the way in when the
graphical greeter will not start.
