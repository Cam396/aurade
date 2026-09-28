# Changelog

Notable changes to AuraDE, newest first. Versions match the GitHub releases.

## Unreleased

### Added
- Wi-Fi setup in the text installer: scan, join, hidden networks, WPA3 Personal and Enhanced Open, and a Saved Wi-Fi page to reconnect or forget networks. Networks joined in the installer carry into the installed system.

### Changed
- First-run setup offers only the local account. The Google sign-in and device enrollment options are gone, because they cannot work without Google's services.

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
