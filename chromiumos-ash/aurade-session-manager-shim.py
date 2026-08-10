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


class SessionManager(dbus.service.Object):
    def __init__(self):
        self._state = "started"
        self._sessions = {}
        self._primary_user = os.environ.get("AURADE_SESSION_USER", "")
        bus_name = dbus.service.BusName(
            SESSION_MANAGER_SERVICE, bus=dbus.SystemBus()
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

    @dbus.service.method(SESSION_MANAGER_IFACE, in_signature="ss")
    def StartSession(self, user_email, unique_id):
        self._state = "started"
        self._primary_user = user_email
        self._sessions[user_email] = unique_id
        self.SessionStateChanged(self._state)

    @dbus.service.method(SESSION_MANAGER_IFACE, in_signature="ssb")
    def StartSessionEx(self, user_email, unique_id, _chrome_side_key_generation):
        self.StartSession(user_email, unique_id)

    @dbus.service.method(SESSION_MANAGER_IFACE, in_signature="s")
    def EmitStartedUserSession(self, user_email):
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

    @dbus.service.method(SESSION_MANAGER_IFACE, out_signature="b")
    def IsScreenLocked(self):
        return False

    @dbus.service.method(SESSION_MANAGER_IFACE)
    def LockScreen(self):
        return

    @dbus.service.method(SESSION_MANAGER_IFACE)
    def HandleLockScreenShown(self):
        return

    @dbus.service.method(SESSION_MANAGER_IFACE)
    def HandleLockScreenDismissed(self):
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
