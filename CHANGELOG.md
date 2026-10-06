# Changelog

Notable changes to AuraDE, newest first. Versions match the GitHub releases.

## 1.1.3, unreleased

### Added
- Encrypted installs ask for the disk passphrase on a graphical unlock
  screen, in the keyboard layout chosen in the installer. It stays sharp on a
  4K screen, even one connected after installing.
- Linux applications fit in:
  - KDE, GTK and Qt apps take the desktop's light or dark mode, accent colour,
    fonts and icons, and follow them when they change.
  - Opening and saving files happens in AuraDE Files, and "Show in folder"
    opens it.
  - Their tray icons show in the status area on every monitor, with their
    menus.
  - Music and video players show in the media controls, with artwork, seeking
    and the media keys. Starting one pauses the others, as on a Chromebook.
  - Unread counts and other badges show on their shelf and launcher icons.
  - X11 apps work, and every app shows the desktop's cursors.
  - App info shows an app's package, version and size.
- Apps install from the launcher: search for one that is not installed and
  install it from there.
- Every monitor is its own display, each with its own scale and resolution,
  set in Settings, and a monitor can be turned.
- Lock locks: the lock screen asks for your account password and stays
  locked. The power menu has Sleep, and the computer wakes up locked.
- A hardware package, aurade-hardware, on every install. Its pieces switch
  themselves on only on the machines that need them:
  - On an encrypted install, the built-in keyboard of a Surface laptop, or of
    a 2015 to 2017 MacBook or MacBook Pro, works at the disk unlock prompt.
    Before, nobody could type the passphrase on them.
  - Intel Macs get fan control. Without it their fans stayed at their
    slowest while the machine heated up.
- Broadcom Wi-Fi that only works with Broadcom's own driver, as in most Intel
  Macs, gets that driver, built for the installed kernel. Other Broadcom chips
  keep the open one.
- The installer has Wi-Fi on most Intel Macs: it carries Broadcom's driver for
  the chips the open drivers cannot run, and uses it only on those.
- The installer says what it found: on a Surface, that the touchscreen and pen
  need a kernel AuraDE does not install; on a Mac with Apple's T2 chip, that
  the built-in keyboard, trackpad and Wi-Fi do too; on a Chromebook, that its
  speakers and microphone may need a fix made for that model, and where it is.

### Changed
- Text on standard resolution monitors is drawn with subpixels, so it is
  sharper, unless your font settings say otherwise.
- Linux app windows have the same frame as the desktop's own.
- Sound devices go by their short names in the volume menu, instead of long
  hardware descriptions.
- The volume bubble only shows when somebody changes the volume, not at every
  start of the desktop.
- Files: double click and Enter open a file, Open with lists the apps that
  can, thumbnails replace the icons, the path starts at Home, and Back,
  Forward and Up move through real folders.
- Setup starts the display name with your Linux account's full name, and an
  empty name field shows your login name.
- The display size preview in setup shows Files, Chromium and Settings, apps
  that are on the machine, instead of Photos, Camera and A4.
- The installer shows how much of the package download has arrived.

### Fixed
- The graphical installer typed in a US layout whatever keyboard was picked.
  On an encrypted install that set a passphrase nobody could type again at
  the unlock prompt. The layout chosen is now the one used, in the installer,
  at the unlock prompt and at the login screen.
- Choosing a display size of 150, 175, 250 or 300 percent in Settings no
  longer makes the desktop crash at every start.
- On a computer without a GPU, switching desks and turning a monitor no
  longer crash the desktop.
- Tooltips stay on the screen.
- The login screen no longer says Password twice under the password field.
- Removing or updating a Linux app asks for your password when it needs one,
  uninstalling asks first instead of crashing the desktop, and a failed
  uninstall says why.
- Linux apps: a new window takes focus, a window that asks to be tiny opens
  at a usable size, every window finds its shelf icon, Qt apps show the right
  colours, and old style icons show.
- Google web apps show their logos instead of a letter, and preinstalled web
  apps whose icons went missing install again.
- Wi-Fi works on Surfaces. Their Marvell Wi-Fi firmware is on the installer
  and on installed systems: Arch stopped including it by default, and without
  it the Surface Laptop 1 and 2, Pro 4 to 6 and Book 1 and 2 had no Wi-Fi at
  all, whatever the kernel.
- The installer has sound firmware for recent Intel laptops, so speech mode
  is no longer silent on them.
- With no working Wi-Fi, the installer suggests USB tethering from a phone,
  and iPhones can be trusted for tethering from the installer.
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
