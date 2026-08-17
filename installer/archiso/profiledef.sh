#!/usr/bin/env bash
# shellcheck disable=SC2034 # mkarchiso sources this declarative profile.

iso_name="aurade"
iso_label="AURADE_INSTALL"
iso_publisher="AuraDE Contributors"
iso_application="AuraDE reproducible installer and recovery environment"
iso_version="1"
install_dir="arch"
buildmodes=('iso')
bootmodes=('uefi.systemd-boot')
arch="x86_64"
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
airootfs_image_tool_options=(-comp zstd -Xcompression-level 10 -b 1M)
file_permissions=(
  ["/etc/shadow"]=0:0:400
  ["/usr/local/sbin/aurade-install"]=0:0:755
  ["/usr/local/sbin/aurade-secure-boot-sign"]=0:0:755
  ["/usr/local/share/aurade/90-aurade-secure-boot.hook"]=0:0:644
  ["/usr/local/sbin/aurade-installer-tui"]=0:0:755
  ["/usr/local/sbin/aurade-installer-gui"]=0:0:755
  ["/usr/local/sbin/aurade-installer-gui-bridge"]=0:0:755
  ["/usr/local/sbin/aurade-installer-start"]=0:0:755
  ["/usr/local/sbin/aurade-installer-autostart"]=0:0:755
  ["/etc/systemd/system/aurade-installer-autostart.service"]=0:0:644
  ["/etc/systemd/system/aurade-installer-serial.service"]=0:0:644
  ["/root/.bash_profile"]=0:0:644
  ["/usr/local/sbin/aurade-recovery"]=0:0:755
  ["/usr/local/sbin/aurade-hardware-qualify"]=0:0:755
  ["/usr/local/sbin/aurade-install-failure"]=0:0:755
  ["/usr/local/sbin/aurade-network-diagnostics"]=0:0:755
  ["/usr/local/sbin/aurade-refresh-mirrors"]=0:0:755
  ["/usr/local/lib/aurade/aurade-validate.sh"]=0:0:644
  ["/usr/local/lib/aurade/aurade-journal.sh"]=0:0:644
  ["/usr/local/lib/aurade/aurade-questions.sh"]=0:0:644
  ["/usr/local/lib/aurade/aurade-tui.sh"]=0:0:644
  ["/usr/local/lib/aurade/aurade-copy.sh"]=0:0:644
  ["/usr/local/lib/aurade/aurade-wait.sh"]=0:0:644
  ["/usr/local/lib/aurade/aurade-tips"]=0:0:644
  ["/usr/local/lib/aurade/aurade-probe.sh"]=0:0:644
  ["/usr/local/lib/aurade/aurade-renderers.sh"]=0:0:644
  ["/usr/local/lib/aurade/aurade_gui/__init__.py"]=0:0:644
  ["/usr/local/lib/aurade/aurade_gui/a11y.py"]=0:0:644
  ["/usr/local/lib/aurade/aurade_gui/bridge.py"]=0:0:644
  ["/usr/local/lib/aurade/aurade_gui/flow.py"]=0:0:644
  ["/usr/local/lib/aurade/aurade_gui/app.py"]=0:0:644
  ["/usr/local/lib/aurade/aurade_gui/brand.py"]=0:0:644
  ["/usr/local/lib/aurade/aurade_gui/locales.py"]=0:0:644
  ["/usr/local/lib/aurade/aurade_gui/stage.py"]=0:0:644
  ["/usr/local/lib/aurade/aurade_gui/tokens.py"]=0:0:644
  ["/usr/local/lib/aurade/aurade_gui/wait.py"]=0:0:644
  ["/usr/local/lib/aurade/aurade_gui/theme.css"]=0:0:644
  ["/usr/local/lib/aurade/aurade_gui/theme-dark.css"]=0:0:644
  ["/usr/local/lib/aurade/aurade_gui/theme-hc.css"]=0:0:644
  ["/usr/local/lib/aurade/aurade_gui/theme-dark-hc.css"]=0:0:644
  ["/usr/local/lib/aurade/aurade_gui/theme-oled.css"]=0:0:644
  ["/usr/local/share/aurade/aurade-mark.png"]=0:0:644
  ["/usr/local/share/aurade/aurade-wordmark.png"]=0:0:644
  # The wallpapers themselves are deliberately not listed one by one. There
  # are twenty eight of them, `build-iso.sh` stages every one at 0644 from the
  # manifest, and a hand written list of twenty eight file names is a list
  # that is wrong the first time somebody adds a twenty ninth photograph. The
  # stage test checks the mode of what actually landed instead.
  ["/usr/local/share/aurade/wallpapers/manifest.tsv"]=0:0:644
  # The boot screen. The theme is five files and all five are read by a daemon
  # running as root before there is a user, so they are listed one by one:
  # unlike the wallpapers this is a fixed set that does not grow, and a boot
  # screen that silently fails to load is a boot that falls back to scrolling
  # kernel messages, which nobody files a bug about.
  ["/etc/plymouth/plymouthd.conf"]=0:0:644
  ["/usr/share/plymouth/themes/aurade/aurade.plymouth"]=0:0:644
  ["/usr/share/plymouth/themes/aurade/aurade.script"]=0:0:644
  ["/usr/share/plymouth/themes/aurade/dot.png"]=0:0:644
  ["/usr/share/plymouth/themes/aurade/aurade-mark.png"]=0:0:644
  ["/usr/share/plymouth/themes/aurade/aurade-wordmark.png"]=0:0:644
)
