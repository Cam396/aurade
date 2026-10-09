# aurade-vm

Try AuraDE in a virtual machine. `aurade-vm` finds the hypervisors on your
computer, downloads the AuraDE ISO, checks it against the release key, makes
the VM and starts the installer, with your answers already filled in if you
like.

It is one program for Windows, Linux and macOS, with the same screens on each.

## What it does

1. **Where it runs.** It lists the hypervisors it found and says what to
   install for the ones it did not.
2. **How much is set up for you:**
   - **Guided:** answer the installer's questions here (language, keyboard,
     time zone, computer name, username, encryption, filesystem). The installer
     opens with them filled in, asks for your password itself, and still
     confirms the disk before writing anything.
   - **Express:** the same questions plus a password, and nothing more. The
     installer runs by itself, wipes the VM's disk, installs and restarts into
     AuraDE. Encryption is off in Express, because there is no one at the VM to
     type a passphrase on every start.
   - **Just the VM:** the installer asks everything.
3. **Your desktop**, for Guided and Express: the display size, the feature
   set, extra apps (Firefox, Visual Studio Code, Flatpak with Flathub,
   Waydroid, developer tools) and, on Btrfs, a snapshot before every update.
   They go to the installer as its advanced questions, so the apps come from
   the same pinned packages as the rest of the system.
4. **The VM.** Memory, processors, disk and 3D graphics, with sizes suited to
   this computer already picked.
5. **The download.** It resumes if it stops, and is checked against the
   published SHA-256 and the AuraDE release key's signature. An ISO that fails
   either check is deleted.

Run it again after installing and choose **Start**. On that first start it
removes the answers disk from the VM, because the installed system does not
need it.

## Hypervisors

| Hypervisor | Hosts | Tested end to end |
| --- | --- | --- |
| VMware Workstation | Windows, Linux | Yes: Guided and Express installs, with guest tools |
| VMware Fusion | Intel Macs | No |
| QEMU (KVM, or HVF on a Mac) | Linux, Intel Macs | Yes: an Express install with every desktop choice, and the guest agent |
| libvirt, which GNOME Boxes and virt-manager use | Linux | Yes, to the pre-filled installer |
| VirtualBox | Windows, Linux, Intel Macs | No |
| Hyper-V | Windows Pro and Enterprise, as administrator | No |
| Parallels Desktop (Pro or Business) | Intel Macs | No |
| UTM 4.2 or later | Intel Macs | No |

`aurade-vm --hypervisors` lists what it finds on this computer and what is
missing from the rest. A VM is always started again with the hypervisor that
made it; `aurade-vm.json` in its folder records which.

UTM is driven through its AppleScript dictionary, since its `utmctl` command
cannot make a VM. macOS asks once whether your terminal may control UTM.

The installer adds the hypervisor's guest tools on its own when it finds it
is in a VM: open-vm-tools for VMware, the QEMU guest agent for QEMU and
libvirt, VirtualBox's guest service and Hyper-V's daemons. Parallels Tools
are not packaged for Arch, so they come from the Parallels menu.

AuraDE is built for x86_64 PCs. On an Apple Silicon Mac no hypervisor can run
it at a usable speed, and `aurade-vm` says so instead of trying.

## On an Arch computer, without a VM

On a computer that runs Arch Linux, the list of hypervisors ends with **This
Arch computer, beside its desktop**, and `aurade-vm --existing-arch` does the
same without the screens. It follows `docs/existing-arch.md`: it downloads the
release key and refuses it unless it is the pinned one, has pacman trust it,
adds the `[aurade]` repository if it is missing, and runs
`sudo pacman -Syu aurade`, which asks before installing. Nothing is erased,
and AuraDE becomes one more session at the login screen.
`--existing-arch --dry-run` prints the commands and changes nothing.

## How answers reach the installer

The answers go on a small ISO labelled `AURADE_ANS`, attached as a second
optical drive. When the live system starts, `aurade-installer-autostart` copies
`answers.txt` off it and starts the text installer with `--answers`. The file
holds no password or passphrase, and the installer checks every line exactly
as if it had been typed.

For Express the disk also carries `express` and `password.hash`. The password
is hashed here with SHA-512 crypt, the same kind the installer makes itself, so
only the hash ever reaches the VM. The installer then checks before touching
anything that it is running in a VM, that every answer is there, and that the
disk has no partitions or filesystem on it. If any check fails it says why and
goes on as a Guided install instead.

## Getting it

```powershell
irm https://raw.githubusercontent.com/Cam396/aurade/main/vm/aurade-vm/get.ps1 | iex
```

```sh
curl -fsSL https://raw.githubusercontent.com/Cam396/aurade/main/vm/aurade-vm/get.sh | bash
```

Each script downloads the program for this computer, checks it against the
SHA-256 written into the script for that version (and, on Linux and macOS,
the release key's signature over the checksums when gpg is installed), and
starts it. A download that does not match is deleted and never run. Because
the file is fetched by PowerShell or curl rather than a browser, Windows and
macOS do not stop to ask about an unknown download.

`build.sh` with `PIN=1` writes the version and hashes into both scripts.

## Without the screens

```sh
aurade-vm --yes --username alex --hostname alex-vm --memory 8192
```

For Express without the screens, the password comes in on standard input:

```sh
printf '%s\n' "$PASSWORD" | aurade-vm --yes --mode express --password-stdin --username alex
```

The desktop choices have options too: `--display-scale 125`,
`--features plus`, `--apps firefox,flatpak` and `--update-snapshots no`.

`aurade-vm --help` lists every option.

## Updating

`aurade-vm --update` replaces the program with the newest published one. It
reads the version and SHA-256 that `get.sh` and `get.ps1` carry on the main
branch, so an update trusts exactly what a first install does. When the
release has a signed `SHA256SUMS`, the release key's signature is checked
too. A build that fails either check is never used. The welcome screen says
when a newer one is out. New VMs always get the newest AuraDE release unless
`--release` names another. `--iso FILE` uses an ISO you already
have instead of downloading one; that file is not checked.

## Building

```sh
vm/aurade-vm/test.sh                 # tests, and a build for each host
vm/aurade-vm/build.sh 0.1.0          # binaries and SHA256SUMS in vm/aurade-vm/dist
GPGKEY=<fingerprint> vm/aurade-vm/build.sh 0.1.0   # and sign SHA256SUMS
```
