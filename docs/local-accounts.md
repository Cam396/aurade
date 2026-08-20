# AuraDE Local Accounts

## V1 implemented path

- AuraDE packages launch ChromiumOS Ash with `--aurade-enable-local-accounts`.
- The User Creation screen shows a fourth `Local account` card after Google,
  child, and enterprise options.
- The local setup screen records non-secret local profile metadata in:
  `${XDG_CONFIG_HOME:-~/.config}/aurade/profile.json`.
- The launcher stores ChromiumOS Ash state in:
  `${XDG_DATA_HOME:-~/.local/share}/aurade/chromiumos-ash`.
- A one-time launcher migration moves the old
  `${XDG_DATA_HOME:-~/.local/share}/chromiumos-ash` directory to the new XDG
  AuraDE path when the new path does not already exist.
- Local session start uses a regular ChromeOS user context backed by the Linux
  username as `username@local.aurade` with `AUTH_FLOW_OFFLINE`.
- `aurade-account-helper` provides the privileged/security boundary for PAM
  verification and password change operations. Passwords are read from stdin,
  never argv.
- Headless Wayland CI smoke can pass renderer flags through
  `AURADE_CHROME_EXTRA_FLAGS`, for example
  `--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader`.
  Normal graphical sessions should use the default GPU path.

## V2: local user creation

AuraDE should add a separate user creation flow only after the greeter/session
boundary is stable.

Required behavior:

- Create real Linux users through a privileged helper, not from Chromium WebUI.
- Create the home directory with the distro default skeleton and ownership.
- Set the Linux password through PAM or `passwd`-equivalent APIs.
- Write display metadata to AuraDE config first, then mirror to AccountsService
  when available.
- Warn clearly that the password is the real Linux account password.
- Do not create users from inside an already-authenticated user's desktop
  without an explicit polkit/admin authorization step.

## V2: AuraDE greeter

The temporary v1 target remains display-manager launched. A native AuraDE
greeter needs its own security review before beta:

- Run a minimal greeter as a dedicated unprivileged user.
- Authenticate target Linux users through PAM.
- Start the selected user session through systemd-logind or an equivalent
  session manager API.
- Never pass passwords over argv, environment variables, logs, or Chromium
  extension APIs.
- Keep EULA/legal/consent screens in the packaged first-run path.
- Support offline local sign-in after required legal screens.

## Google account track

Google sign-in remains a parallel track. Missing OAuth/API configuration must
show a polished blocker or setup note; release packages must not use fake OAuth
tokens.
