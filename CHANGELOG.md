# Changelog

Notable changes to AuraDE, newest first. Versions match the GitHub releases.

## 1.1.3, unreleased

### Changed
- Setup starts the display name with your Linux account's full name, and an
  empty name field shows your login name.
- The display size preview in setup shows Files, Chromium and Settings, apps
  that are on the machine, instead of Photos, Camera and A4.
- The installer shows how much of the package download has arrived.

### Fixed
- The erase confirmation field in the graphical installer shows one focus
  ring instead of two.
- The login screen says "Welcome" to an account signing in for the first
  time, and "Welcome back" only after that.
- The text installer's done screen stays up until you press a key: enter
  restarts, esc leaves to the console. Before, it closed at once and nobody
  saw that the install had finished.

## 1.1.2, 2026-10-01

### Added
- AuraDE installs onto an Arch system you already use, as one more session at your login screen next to Plasma, GNOME or whatever else is there. The steps are in [docs/existing-arch.md](docs/existing-arch.md), and `sudo pacman -Rns aurade` takes it back out.
- One command to try AuraDE in a virtual machine on Linux, macOS and Windows.
- A hardware report form for telling us what works on your machine.

### Changed
- Setup and system messages say "computer" instead of "Chromebook".
- About says updates come from pacman, shows Arch Linux where it showed Crostini, and no longer lists What's new or Firmware updates, which pointed at Google's services.
- Setup says you sign in with your Linux account's password.
- My Images lists the AuraDE wallpapers.
- The text installer fills a large screen and picks a font size to match it.
- The installer's wallpaper card fits its column, and the encryption page says each thing once.
- On a display with no render node, the installer draws in software and warns instead of refusing to install.

### Fixed
- Installing `aurade` on its own now brings the Files service with it. Before, Files opened on an empty Home.
- Files says when its file service is not running and how to start it, instead of showing an empty folder.
- Only one AuraDE session shows at the login screen. The developer sessions of the shell are hidden.
- The network bridge starts as soon as it is installed, so setup on a wired connection no longer asks for Wi-Fi before the first reboot.
- Files: Set as Desktop sets the wallpaper, submenus open, rows that do not apply stay hidden, and a full folder no longer says it is empty.
- Files: a narrow window keeps every toolbar button in reach and floats the details pane over the list.

## 1.1.1, 2026-09-29

### Updating from 1.0.0 or 1.1.0
Machines installed from 1.0.0 or 1.1.0 only read the copy of the AuraDE repository on their own disk, so they never see an update. Paste this once in a terminal; it adds the online repository ahead of that copy and updates. Pasting it again changes nothing.

```sh
grep -q Cam396/aurade /etc/pacman.d/aurade-mirrorlist || sudo sed -i '1i Server = https://github.com/Cam396/aurade/releases/download/repo-x86_64' /etc/pacman.d/aurade-mirrorlist; sudo pacman -Syu
```

### Changed
- New installs follow the published AuraDE repository, so `sudo pacman -Syu` brings AuraDE updates as well as Arch ones. The copy on the disk stays as a fallback for machines without a network.
- First login no longer waits on Google services a local account cannot reach. The language, interest and perks steps are skipped, which removes several seconds of loading screen.
- The first setup screen says "Welcome to AuraDE".
- The Memory Saver tip says "Make AuraDE faster".

### Fixed
- Signing out no longer crashes the desktop in the background. The browser used to be stopped at the same moment as the session's message bus, and up to half of all sign outs left a crash report behind. It now finishes quitting first.
- Installing some AuraDE packages from the online repository failed with "invalid or corrupted package". The repository was repaired on 2026-09-29, and every release now checks that what is served matches its database.

### Removed
- Browse as Guest. On AuraDE a guest session would run as the owner's Linux account, with the owner's files.

## 1.1.0, 2026-09-28

### Added
- Wi-Fi setup in the text installer: scan, join, hidden networks, WPA3 Personal and Enhanced Open, and a Saved Wi-Fi page to reconnect or forget networks. Networks joined in the installer carry into the installed system.

### Changed
- First-run setup offers only the local account. The Google sign-in and device enrollment options are gone, because they cannot work without Google's services.
- A local account's first login goes from the account form straight to display size and theme. There is no separate device password, no Gemini or AI introduction, and no Explore window afterwards.
- New installs sign in through the graphical login screen instead of the text one. If the graphical screen fails to start three times in a row, the text login takes over for that boot, so there is always a way in.

### Fixed
- The "Google API keys are missing" warnings no longer appear, on the setup screen or in the browser.
- The keyboard and time zone lists in the text installer open on their defaults (`us` and `UTC`).

## 1.0.0 "Alpenglow", ISO refreshed 2026-09-23

### Changed
- The installer checks the machine's real memory before it downloads anything. When memory is short, it downloads the base system straight onto the new disk after formatting instead of holding it in memory. The confirm screen says so, because a network drop on that path leaves an unfinished install.
- The Arch base moved to the 2026-09-15 snapshot.
- The ISO and its SBOM are signed with the release key.

## 1.0.0 "Alpenglow", 2026-09-23

First stable release.

### Added
- The Ash desktop shell (Chromium 156.0.8060.0) on Arch Linux, with the Files app on a live local daemon.
- Graphical and text installers, with plain or LUKS encrypted installs.
- A signed package repository. `aurade-full` installs the whole desktop.
- The desktop and login screen draw in software when there is no usable GPU, including virtual machines.
- A long-term release signing key: `BC390DCF360B2184DBBF008B8B2AB2EFE667CB69`.

### Fixed
- A GPU that keeps failing drops the desktop to software rendering instead of taking it down.
- Installed systems get working Arch mirrors, and pacman's cache has the right permissions for updates.
- A wrong password on the graphical login screen no longer leaves it stuck.
