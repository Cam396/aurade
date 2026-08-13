"""Graphical renderer for the AuraDE installer.

Three modules, split along one line: whether the code needs a display.

``bridge``  talks to ``aurade-installer-gui-bridge``, which is the shell model
            holding the question manifest, the validators, the journal readers
            and the engine invocation.
``flow``    is the page order, the wording, and the rule about which button
            goes where. No GTK import, so it is testable without a display.
``app``     is the GTK4/libadwaita widget layer, and is the only module that
            imports ``gi``.

The split is not decoration. This project has already shipped an installer
prompt that hung at its own keyboard validation while a syntax check and a
source grep both passed, so the parts that decide what happens are kept where
a test can drive them on a machine with no graphics at all.
"""

__all__ = ["bridge", "flow"]
