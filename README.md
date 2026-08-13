# AuraDE

<p align="center">
  <img src="assets/aurade-logo.png" alt="AuraDE logo" width="450">
</p>

AuraDE is a ChromiumOS Ash-based desktop environment for Arch Linux. It brings
a configurable, local-first ChromeOS-style desktop to ordinary laptops while
keeping the host's Linux kernel, hardware drivers, NetworkManager, PipeWire,
and systemd.

> **Status: pre-alpha source preview.** The source tree is public now so people
> can inspect, build, and contribute. The current unsigned packages and ISO are
> development artifacts, not a supported or stable release. Read
> [RELEASE_STATUS.md](RELEASE_STATUS.md) before installing anything.

Join the project Discord: <https://discord.gg/vkZ7CSMG5>

## What is here

- Ash window management and ChromeOS system UI on generic Linux.
- Wayland/Weston, X11, and direct-DRM build paths.
- Local Linux accounts and a greetd/session-manager integration.
- Files, Terminal, Settings, Diagnostics, audio, power, display, and
  accessibility integrations adapted for Linux hosts.
- NetworkManager through the `org.chromium.flimflam` Shill bridge.
- Optional local AI providers and history embeddings; AI is not installed by
  the base profile.
- Arch package recipes, a reproducible patch series, CI helpers, and an
  installer/recovery toolchain.

AuraDE is not an official Google or ChromiumOS distribution. It does not ship
ChromeOS firmware, a ChromeOS kernel, Verified Boot, Google API credentials, or
Google account authentication. Google web applications, when enabled, run as
browser PWAs in the user's session.

## Repository layout

| Path | Purpose |
| --- | --- |
| `patches/` | Ordered Chromium source patches (`patches/SERIES`) |
| `chromiumos-ash/` | Ash package and Linux session launcher |
| `aurade/` | User-facing base meta-package and commands |
| `aurade-*` | Account, AI, power, host, login, helper, and web packages |
| `shill-nm-adapter/` | NetworkManager-to-Shill D-Bus bridge |
| `ci/` | Patch, package, release, and VM smoke tooling |
| `installer/` | ArchISO profile, installer, and recovery tools |
| `build-aurade.sh` | Low-effort dependency, source, package, ISO, and test orchestrator |
| `AURADE_AUR.md` | AUR package split and upload checklist |
| `OPUS_GUI_TUI_HANDOFF.md` | Finish-gated GUI/TUI installer contract |
| `CITATION.cff` | Machine-readable project metadata and citation record |

The current source snapshot carries 33 ordered Chromium patches and an
11-package Arch set:

`aurade`, `aurade-account-helper`, `aurade-ai`, `aurade-full`,
`aurade-host-bridge`, `aurade-login`, `aurade-power`, `aurade-system-helper`,
`aurade-webapp-shortcuts`, `chromiumos-ash`, and `shill-nm-adapter`.

## Build the small packages

Use an Arch Linux host, container, or validation root with `base-devel`,
`pacman`, `namcap`, `repo-add`, and the package dependencies installed.
For the complete pinned build, release-repository, and ISO workflow, see
[BUILDING.md](BUILDING.md). Maintainer-level CI details are in
[`ci/README.md`](ci/README.md).

```bash
git clone https://github.com/Cam396/aurade.git
cd aurade
export AURADE_WORKDIR="${AURADE_WORKDIR:-$PWD/.aurade-work}"

# Installer and package-source checks; also builds the non-Chromium packages.
AURADE_VERIFY_CHROMIUMOS_ASH=0 ci/arch-package-smoke.sh
```

For the lowest-effort supported build on an Arch x86_64 host:

```bash
./build-aurade.sh --all
```

Use `./build-aurade.sh --plan --all` to inspect the workflow first. ARM64 and
other architectures can run `./build-aurade.sh --source-only --arch aarch64`
to clone Chromium and verify the patch series; binary and ISO production is
not yet claimed for those targets.

For a complete private repository, follow [BUILDING.md](BUILDING.md). After
the validation root and pinned Chromium checkout are ready, the final
orchestration command is:

```bash
sudo env \
  CHROME_SRC="$AURADE_WORKDIR/chromium-bootstrap/src" \
  AURADE_WORKDIR="$AURADE_WORKDIR" \
  ./ci/build-release-candidate.sh
```

The `--reuse-chromium` option is safe only when the exact current
`pkgver-pkgrel` Chromium package has already been built and recorded in the
builder's work directory. The release scripts refuse stale or unexpected
package sets.

## Build ChromiumOS Ash

Chromium is intentionally not vendored in this repository. A clean build
downloads tens of gigabytes and can take hours:

```bash
ci/bootstrap-chromium-src.sh \
  --revision "$(cat pins/chromium.sha)" \
  --target "$AURADE_WORKDIR/chromium-bootstrap" \
  --run --verify-series
```

After the source gate passes, run the pinned release entry point described in
[BUILDING.md](BUILDING.md). Do not use `build-chromeos-ash.sh` with a
`CHROME_SRC` variable; that legacy helper reads `CHROMIUMOS_DIR` instead.

The patch series is always applied in the order listed by `patches/SERIES`.
Before spending build time, run the no-build integrity gate:

```bash
CHROME_SRC=/path/to/chromium-bootstrap/src \
  ci/verify-patch-series.sh --expect-tree-match
```

Before tagging or attaching artifacts, run the read-only public leak gate:

```bash
ci/public-release-leak-gate.sh
```

Do not put a Chromium checkout, `chroot/`, `out/`, package cache, VM image, or
build logs into this repository. The root `.gitignore` is intentionally
defensive.

## Installing a development package set

There is no supported public binary repository yet. If you receive a matching,
unsigned development repository from a maintainer, verify its `SHA256SUMS`,
import its separately supplied signing key when present, and install the base
profile first:

```bash
sudo pacman -U aurade-account-helper-*.pkg.tar.* \
  aurade-system-helper-*.pkg.tar.* shill-nm-adapter-*.pkg.tar.* \
  aurade-power-*.pkg.tar.* aurade-host-bridge-*.pkg.tar.* \
  aurade-login-*.pkg.tar.* aurade-webapp-shortcuts-*.pkg.tar.* \
  aurade-*.pkg.tar.* chromiumos-ash-*.pkg.tar.*
sudo systemctl enable --now NetworkManager
aurade-session
```

Do not use an unsigned artifact on a machine containing data you cannot
restore. The installer and recovery documentation are development tooling
until the repository is signed and a real laptop has passed the hardware
matrix.

## Prepare the AUR packages

The next publication target is the Arch User Repository after the current
pre-alpha feedback cycle. Generate one self-contained upload directory per
package with:

```bash
export AURADE_WORKDIR="$PWD/.aurade-work"
export AURADE_AUR_OUTPUT="$AURADE_WORKDIR/aur-bundles"
ci/export-aur-bundles.sh
```

The exporter includes the ten small packages and an x86_64
`chromiumos-ash-bin` wrapper for the current unsigned development payload.
It intentionally does not copy Chromium checkouts, ISO/package archives,
private documents, VM credentials, or build logs. See [AURADE_AUR.md](AURADE_AUR.md)
for the per-package `makepkg`, `.SRCINFO`, `namcap`, and upload sequence. AUR
publication is not a stable-release or ARM-support claim.

## Testing and reporting

The live VM path uses VMware and `vmrun`; QEMU is not the project validation
target. Start the VM through the host's `vmrun` operations, then use
`ci/vm-smoke.sh` for package/session/Files/audio/accessibility checks. Physical
qualification procedures for the Dell Latitude 3180 and HP G3/G4 EE are in
[AURADE_HARDWARE_TEST_PACKET.md](AURADE_HARDWARE_TEST_PACKET.md).
The copy-paste VM test matrix and failure-report format are in
[TESTING.md](TESTING.md). Common build and VM failures are collected in
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

Please include the exact package versions, SHA-256 values, hardware model,
and relevant `journalctl`/`coredumpctl` evidence in an issue. Never paste
passwords, API keys, private repository URLs, or an unredacted hardware report.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [HACKING.md](HACKING.md) before
changing the patch series. Keep AuraDE adaptations labeled with
`// AuraDE compatibility:`; reserve `// HACK(AuraDE):` for deliberately
temporary workarounds. Every patch must apply with strict whitespace checking,
and `.SRCINFO` must be regenerated from its `PKGBUILD`.

For community setup, channels, roles, and moderation guidance, see
[COMMUNITY.md](COMMUNITY.md). The starter server name is **AuraDE Community**.

## License and upstream notices

AuraDE-authored packaging, helpers, scripts, and documentation are released
under the BSD 3-Clause License in [LICENSE](LICENSE). ChromiumOS/Ash-derived
files and third-party components retain their upstream notices; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and the `LICENSE` file inside
each package directory.

## Security

Do not report a vulnerability in a public issue. Use the repository's private
security-advisory flow at
<https://github.com/Cam396/aurade/security/advisories/new>. See
[SECURITY.md](SECURITY.md) for scope and supported-version policy.
