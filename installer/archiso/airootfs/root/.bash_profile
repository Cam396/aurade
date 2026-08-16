# The live console's login shell.
#
# tty1 is owned by aurade-installer-autostart.service during an installer boot.
# Keeping the login shell plain prevents a second copy from appearing after
# the graphical front end exits. The recovery-console boot entry still lands
# here for manual commands.
[[ -f /etc/bashrc ]] && . /etc/bashrc
