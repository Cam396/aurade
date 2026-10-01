# AuraDE on an Arch system you already use

AuraDE installs next to the desktop you have. Your login screen keeps working,
and AuraDE becomes one more session to pick there. Nothing is erased, and you
can go back to your old desktop at the next login.

This was tested on a fresh Arch install with KDE Plasma, SDDM and
NetworkManager.

## 1. Trust the release key

The packages are signed. The key is not on the public keyservers, so take it
from this repository and check its fingerprint before trusting it:

```sh
curl -fsSLo aurade-release.gpg https://raw.githubusercontent.com/Cam396/aurade/main/pins/aurade-release.gpg
gpg --show-keys aurade-release.gpg
```

The fingerprint must read `BC390DCF360B2184DBBF008B8B2AB2EFE667CB69`. Then:

```sh
sudo pacman-key --add aurade-release.gpg
sudo pacman-key --lsign-key BC390DCF360B2184DBBF008B8B2AB2EFE667CB69
```

## 2. Add the repository and install

```sh
printf '\n[aurade]\nServer = https://github.com/Cam396/aurade/releases/download/repo-x86_64\n' | sudo tee -a /etc/pacman.conf
sudo pacman -Syu aurade
```

This is about 300 MiB to download and 730 MiB installed. From then on,
`sudo pacman -Syu` updates AuraDE together with the rest of Arch.

## 3. Sign in to AuraDE

Sign out. At your login screen, choose the **AuraDE** session and sign in as
yourself. The first time, AuraDE asks a few setup questions and then opens its
desktop. Your files are the ones in your home folder.

To go back, sign out and choose your old session.

## What changes on your system

- A logind drop-in, `/etc/systemd/logind.conf.d/60-aurade-laptop.conf`,
  writes down systemd's own defaults for the lid switch. It does not change
  how your current desktop handles the lid.
- New system users and groups for the greeter, seat access and colour
  management.
- `greetd` is installed but not enabled. Your login screen stays as it is.
- The Files service, `auradefs`, runs only inside an AuraDE session.
- `aurade-powerd`, which tells AuraDE about suspend and resume, is installed
  but not enabled. Enable it if you want it:

  ```sh
  sudo systemctl enable --now aurade-powerd
  ```

## Removing it

```sh
sudo pacman -Rns aurade
```

Then delete the `[aurade]` lines from `/etc/pacman.conf`. AuraDE's own settings
live in `~/.local/share/aurade` and can be deleted too.
