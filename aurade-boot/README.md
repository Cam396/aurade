# aurade-boot

The AuraDE boot screen, and the disk unlock in it. A plymouth theme, plus an
initramfs hook that adds what the theme needs and does not carry.

On an encrypted install this is the first thing AuraDE shows: one of the
wallpaper photographs, the mark, and a field for the disk passphrase, in the
greeter's type and colours. A wrong passphrase shakes the field and says so;
Caps Lock is pointed out before it costs a try; the keyboard layout is named
in the corner whenever it is not plain US. On a machine without encryption it
is the mark on a photograph while the system starts.

## How it is put together

Plymouth's script plugin can place an image, fade it and move it. It cannot
lay out type in more than one weight, cannot blur, and scales images by
sampling single points, so small type scaled at boot comes out jagged.

So `tools/build-assets.py` draws everything ahead of time, at eight sizes
from 0.75x to 3x of a 1080 line screen. The script picks the size nearest
the screen and places the drawn pieces without scaling them. The only things
scaled at boot are the photograph and the shade over it, which are soft
anyway.

The drawn pieces are kept as one archive, `aurade-boot-drawn.tar`. The
generator writes the same bytes for the same pictures, so a rebuild that
changed nothing shows no change. The layout numbers live in the generator,
which writes them into the script's generated block.

The photographs are the wallpaper package's. The theme links to them by
slot, and the `aurade-boot` initramfs hook copies a few of them into the
image, a different few at each rebuild. It also drops the drawn sizes that
no connected screen would use. Together that keeps the image a few megabytes
larger rather than twenty.

## Enabling it

- `HOOKS` in `/etc/mkinitcpio.conf` gains `plymouth aurade-boot` after
  `sd-vconsole` and before `block`, so the screen is up before
  `sd-encrypt` asks.
- `/etc/plymouth/plymouthd.conf` names the theme and fixes the device scale
  at 1. The theme does its own scaling, and plymouth's would double it on a
  high density panel:

      [Daemon]
      Theme=aurade-boot
      DeviceScale=1

- The kernel command line gains `splash`. Without it plymouth stays in text.
- `/etc/vconsole.conf` carries `XKBLAYOUT`, and `XKBVARIANT` if there is one.
  Plymouth reads keys through the XKB layout and ignores `KEYMAP`, so a
  console keymap alone would mean a passphrase typed on a US layout.

The AuraDE installer does all four on an encrypted install.

## Changing it

    python3 aurade-boot/tools/build-assets.py
    python3 aurade-boot/tools/build-assets.py --no-build --mock /tmp/m.png --photo 1 --state ready --size 2560x1440

The first draws and packs everything; the second composes a screen from the
drawn pieces with the script's own layout, without booting anything. States
are `boot`, `focus`, `ready`, `error`, `idle` and `starting`.

To see the real thing on a running system, with the greeter stopped:

    plymouthd --mode=boot --kernel-command-line="quiet splash"
    plymouth show-splash
    plymouth ask-for-password --prompt="Please enter passphrase for disk Test (test):"
    plymouth quit
