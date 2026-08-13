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
  ["/usr/local/sbin/aurade-installer"]=0:0:755
  ["/usr/local/sbin/aurade-recovery"]=0:0:755
  ["/usr/local/sbin/aurade-hardware-qualify"]=0:0:755
  ["/usr/local/sbin/aurade-refresh-mirrors"]=0:0:755
  ["/usr/local/lib/aurade/aurade-validate.sh"]=0:0:644
)
