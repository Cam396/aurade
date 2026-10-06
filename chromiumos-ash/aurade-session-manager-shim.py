#!/usr/bin/env python3
"""Minimal org.chromium.SessionManager D-Bus shim for AuraDE on Linux."""

import os
import signal

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib


SESSION_MANAGER_SERVICE = "org.chromium.SessionManager"
SESSION_MANAGER_PATH = "/org/chromium/SessionManager"
SESSION_MANAGER_IFACE = "org.chromium.SessionManagerInterface"

# One file per user whose desktop shows its lock screen. The session child
# reads it when the desktop exits: a desktop that went away while locked is
# not started again unlocked. Root owns the files, so the desktop's user
# cannot clear one.
LOCK_STATE_DIR = os.environ.get("AURADE_LOCK_STATE_DIR", "/run/aurade-lock")


class SessionManager(dbus.service.Object):
    def __init__(self):
        self._state = "started"
        self._bus = dbus.SystemBus()
        self._sessions = {}
        self._primary_user = os.environ.get("AURADE_SESSION_USER", "")
        bus_name = dbus.service.BusName(
            SESSION_MANAGER_SERVICE, bus=self._bus
        )
        super().__init__(bus_name, SESSION_MANAGER_PATH)

    @dbus.service.method(SESSION_MANAGER_IFACE, out_signature="s")
    def RetrieveSessionState(self):
        return self._state

    @dbus.service.method(SESSION_MANAGER_IFACE, out_signature="a{ss}")
    def RetrieveActiveSessions(self):
        return self._sessions

    @dbus.service.method(SESSION_MANAGER_IFACE, out_signature="s")
    def RetrievePrimarySession(self):
        return self._primary_user

    def _caller_uid(self, sender):
        return int(self._bus.get_unix_user(sender))

    def _lock_file(self, sender):
        return os.path.join(LOCK_STATE_DIR, str(self._caller_uid(sender)))

    def _set_locked(self, sender, locked):
        path = self._lock_file(sender)
        if locked:
            os.makedirs(LOCK_STATE_DIR, mode=0o755, exist_ok=True)
            with open(path, "w", encoding="ascii") as handle:
                handle.write("locked\n")
        else:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    @dbus.service.method(SESSION_MANAGER_IFACE, in_signature="ss",
                         sender_keyword="sender")
    def StartSession(self, user_email, unique_id, sender=None):
        if sender:
            self._set_locked(sender, False)
        self._state = "started"
        self._primary_user = user_email
        self._sessions[user_email] = unique_id
        self.SessionStateChanged(self._state)

    @dbus.service.method(SESSION_MANAGER_IFACE, in_signature="ssb",
                         sender_keyword="sender")
    def StartSessionEx(self, user_email, unique_id, _chrome_side_key_generation,
                       sender=None):
        self.StartSession(user_email, unique_id, sender=sender)

    @dbus.service.method(SESSION_MANAGER_IFACE, in_signature="s",
                         sender_keyword="sender")
    def EmitStartedUserSession(self, user_email, sender=None):
        if sender:
            self._set_locked(sender, False)
        if user_email:
            self._state = "started"
            self._primary_user = user_email
            self._sessions.setdefault(user_email, "")
            self.SessionStateChanged(self._state)

    @dbus.service.method(SESSION_MANAGER_IFACE)
    def StopSession(self):
        self._state = "stopped"
        self._sessions.clear()
        self.SessionStateChanged(self._state)

    @dbus.service.method(SESSION_MANAGER_IFACE, in_signature="u")
    def StopSessionWithReason(self, _reason):
        self.StopSession()

    @dbus.service.method(SESSION_MANAGER_IFACE, in_signature="s")
    def LoadShillProfile(self, _user_email):
        return

    @dbus.service.method(SESSION_MANAGER_IFACE, in_signature="ay", out_signature="ay")
    def RetrievePolicyEx(self, _descriptor_blob):
        return dbus.ByteArray(b"")

    @dbus.service.method(SESSION_MANAGER_IFACE, in_signature="ayay")
    def StorePolicyEx(self, _descriptor_blob, _policy_blob):
        return

    @dbus.service.method(SESSION_MANAGER_IFACE)
    def EmitLoginPromptVisible(self):
        self.LoginPromptVisible()

    @dbus.service.method(SESSION_MANAGER_IFACE)
    def EmitAshInitialized(self):
        return

    @dbus.service.method(SESSION_MANAGER_IFACE, out_signature="b",
                         sender_keyword="sender")
    def IsScreenLocked(self, sender=None):
        return bool(sender) and os.path.exists(self._lock_file(sender))

    @dbus.service.method(SESSION_MANAGER_IFACE)
    def LockScreen(self):
        return

    @dbus.service.method(SESSION_MANAGER_IFACE, sender_keyword="sender")
    def HandleLockScreenShown(self, sender=None):
        if sender:
            self._set_locked(sender, True)
        self.ScreenIsLocked()

    @dbus.service.method(SESSION_MANAGER_IFACE, sender_keyword="sender")
    def HandleLockScreenDismissed(self, sender=None):
        if sender:
            self._set_locked(sender, False)
        self.ScreenIsUnlocked()

    @dbus.service.method(SESSION_MANAGER_IFACE)
    def EnableChromeTesting(self):
        return

    @dbus.service.signal(SESSION_MANAGER_IFACE, signature="s")
    def SessionStateChanged(self, state):
        pass

    @dbus.service.signal(SESSION_MANAGER_IFACE)
    def LoginPromptVisible(self):
        pass

    @dbus.service.signal(SESSION_MANAGER_IFACE)
    def ScreenIsLocked(self):
        pass

    @dbus.service.signal(SESSION_MANAGER_IFACE)
    def ScreenIsUnlocked(self):
        pass


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    SessionManager()
    loop = GLib.MainLoop()

    def quit_loop(_signum, _frame):
        loop.quit()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, quit_loop)
    loop.run()


if __name__ == "__main__":
    main()
