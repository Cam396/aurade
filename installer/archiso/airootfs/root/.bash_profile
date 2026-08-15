# The live console's login shell.
#
# tty1 is the one the boot menu lands on, and the only one where starting an
# installer over the top of someone is not a surprise: a second console reached
# with Alt+F2, or a session over the serial port, belongs to whoever went
# looking for it.
#
# The installer replaces this shell rather than running under it, so quitting
# the installer ends the login and agetty offers a fresh one. Nothing is
# started twice, and Ctrl+C during a question gets you a prompt.
[[ -f /etc/bashrc ]] && . /etc/bashrc

if [[ $- == *i* && $(tty) == /dev/tty1 && -x /usr/local/sbin/aurade-installer-autostart ]]; then
  /usr/local/sbin/aurade-installer-autostart
fi
