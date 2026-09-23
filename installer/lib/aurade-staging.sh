#!/usr/bin/env bash
# Pick a safe place for the package cache before the target disk is changed.

aurade_meminfo_bytes() {
  local field=$1 path=${AURADE_MEMINFO:-/proc/meminfo} kib
  kib=$(awk -v name="$field:" '$1 == name {print $2; exit}' "$path" 2>/dev/null || true)
  [[ $kib =~ ^[0-9]+$ ]] || return 1
  printf '%s' "$((kib * 1024))"
}

aurade_workspace_capacity_bytes() {
  local path=$1 free_kib free_bytes fs_type mem_available swap_free memory_bytes
  if [[ ${AURADE_WORKSPACE_FREE_BYTES:-} =~ ^[0-9]+$ ]]; then
    free_bytes=$AURADE_WORKSPACE_FREE_BYTES
  else
    free_kib=$(df -Pk -- "$path" 2>/dev/null | awk 'NR == 2 {print $4; exit}')
    [[ $free_kib =~ ^[0-9]+$ ]] || return 1
    free_bytes=$((free_kib * 1024))
  fi

  fs_type=${AURADE_WORKSPACE_FS_TYPE:-$(stat -f -c %T -- "$path" 2>/dev/null || true)}
  case $fs_type in
    tmpfs|ramfs|overlay|overlayfs)
      mem_available=$(aurade_meminfo_bytes MemAvailable || printf '0')
      swap_free=$(aurade_meminfo_bytes SwapFree || printf '0')
      memory_bytes=$((mem_available + swap_free))
      (( memory_bytes < free_bytes )) && free_bytes=$memory_bytes
      ;;
  esac
  printf '%s' "$free_bytes"
}

aurade_select_package_staging() {
  local requested=$1 package_bytes=$2 path=$3 reserve available needed
  reserve=${AURADE_STAGING_MEMORY_RESERVE_BYTES:-805306368}
  [[ $package_bytes =~ ^[0-9]+$ && $reserve =~ ^[0-9]+$ ]] || return 2
  needed=$((package_bytes + reserve))
  case $requested in
    target) printf 'target'; return 0 ;;
    workspace|auto) ;;
    *) return 2 ;;
  esac
  available=$(aurade_workspace_capacity_bytes "$path") || return 1
  if [[ $requested == workspace ]]; then
    (( available >= needed )) || return 1
    printf 'workspace'
  elif (( available >= needed )); then
    printf 'workspace'
  else
    printf 'target'
  fi
}
