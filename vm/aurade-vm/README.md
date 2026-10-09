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
   - **Just the VM:** the installer asks everything.
3. **The VM.** Memory, processors, disk and 3D graphics, with sizes suited to
   this computer already picked.
4. **The download.** It resumes if it stops, and is checked against the
   published SHA-256 and the AuraDE release key's signature. An ISO that fails
   either check is deleted.

Run it again after installing and choose **Start**. On that first start it
removes the answers disk from the VM, because the installed system does not
need it.

## Hypervisors

| Hypervisor | Hosts | Status |
| --- | --- | --- |
| VMware Workstation | Windows, Linux | Ready |
| VMware Fusion | Intel Macs | Ready |
| QEMU, libvirt, VirtualBox, Hyper-V | | Planned (the scripts beside this folder cover them today) |
| UTM, GNOME Boxes, Parallels | | Planned |

AuraDE is built for x86_64 PCs. On an Apple Silicon Mac no hypervisor can run
it at a usable speed, and `aurade-vm` says so instead of trying.

## How answers reach the installer

The answers go on a small ISO labelled `AURADE_ANS`, attached as a second
optical drive. When the live system starts, `aurade-installer-autostart` copies
`answers.txt` off it and starts the text installer with `--answers`. The file
holds no password or passphrase, and the installer checks every line exactly
as if it had been typed.

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

`aurade-vm --help` lists every option. `--iso FILE` uses an ISO you already
have instead of downloading one; that file is not checked.

## Building

```sh
vm/aurade-vm/test.sh                 # tests, and a build for each host
vm/aurade-vm/build.sh 0.1.0          # binaries and SHA256SUMS in vm/aurade-vm/dist
GPGKEY=<fingerprint> vm/aurade-vm/build.sh 0.1.0   # and sign SHA256SUMS
```
