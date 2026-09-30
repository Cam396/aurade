# Try AuraDE in a virtual machine on Windows.
#
#   irm https://raw.githubusercontent.com/Cam396/aurade/main/vm/aurade-vm.ps1 | iex
#
# Run it in PowerShell. Hyper-V needs an administrator PowerShell and the
# Hyper-V feature turned on; VirtualBox needs neither.
#
# The first run downloads the latest release ISO, checks its SHA-256 (and its
# signature when gpg is installed), makes a virtual disk and boots the
# installer. Install onto the virtual disk; every run after that starts the
# installed system. Nothing outside the VM folder is touched.
#
# Settings, all optional, as environment variables set before running it:
#   $env:AURADE_VM_BACKEND   hyperv or virtualbox (default: hyperv when it is
#                            turned on and this is an administrator shell,
#                            otherwise virtualbox)
#   $env:AURADE_VM_DIR       where the ISO and disk live (default ~\AuraDE)
#   $env:AURADE_VM_NAME      the VM's name (default aurade)
#   $env:AURADE_VM_MEMORY    MiB of memory (default 6144, 4096 at least)
#   $env:AURADE_VM_CPUS      virtual CPUs (default 4)
#   $env:AURADE_VM_DISK_GB   disk size (default 40, 30 at least)
#   $env:AURADE_VM_VERSION   a release tag such as v1.1.1 instead of the latest

$ErrorActionPreference = 'Stop'
# Windows PowerShell 5 draws its progress bar so slowly that it throttles a
# large download to a crawl.
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Get-AuraSetting([string]$Name, $Default) {
  $value = [Environment]::GetEnvironmentVariable($Name)
  if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
  return $value
}

function Say([string]$Text) { Write-Host "aurade-vm: $Text" }
function Fail([string]$Text) { throw "aurade-vm: $Text" }

function Invoke-AuraDEVM {
  $repo = 'Cam396/aurade'
  $fingerprint = 'BC390DCF360B2184DBBF008B8B2AB2EFE667CB69'
  $dir = Get-AuraSetting 'AURADE_VM_DIR' (Join-Path $HOME 'AuraDE')
  $name = Get-AuraSetting 'AURADE_VM_NAME' 'aurade'
  $memory = [int](Get-AuraSetting 'AURADE_VM_MEMORY' 6144)
  $cpus = [int](Get-AuraSetting 'AURADE_VM_CPUS' 4)
  $diskGB = [int](Get-AuraSetting 'AURADE_VM_DISK_GB' 40)

  if ($memory -lt 4096) { Fail 'AuraDE needs at least 4096 MiB of memory in the VM' }
  if ($diskGB -lt 30) { Fail 'AuraDE needs a disk of at least 30 GB' }
  if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
    Fail 'AuraDE is built for x86_64 PCs, and emulating one on this machine is too slow to use'
  }

  $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
  $haveHyperV = [bool](Get-Command Get-VM -ErrorAction SilentlyContinue)
  $vbox = Find-VBoxManage

  $backend = Get-AuraSetting 'AURADE_VM_BACKEND' ''
  if (-not $backend) {
    if ($haveHyperV -and $isAdmin) { $backend = 'hyperv' }
    elseif ($vbox) { $backend = 'virtualbox' }
    elseif ($haveHyperV) { Fail 'Hyper-V needs an administrator PowerShell. Open one (right click PowerShell, Run as administrator) and run this again' }
    else {
      Fail ("neither Hyper-V nor VirtualBox is ready. Either turn Hyper-V on (Windows Pro or Enterprise), " +
            "in an administrator PowerShell: Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All, " +
            "then restart; or install VirtualBox from https://www.virtualbox.org")
    }
  }

  New-Item -ItemType Directory -Force -Path $dir | Out-Null

  switch ($backend) {
    'hyperv' {
      if (-not $haveHyperV) { Fail 'Hyper-V is not turned on. In an administrator PowerShell: Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All, then restart' }
      if (-not $isAdmin) { Fail 'Hyper-V needs an administrator PowerShell' }
      Start-HyperV $repo $fingerprint $dir $name $memory $cpus $diskGB
    }
    'virtualbox' {
      if (-not $vbox) { Fail 'VirtualBox is not installed; get it from https://www.virtualbox.org' }
      Start-VirtualBox $vbox $repo $fingerprint $dir $name $memory $cpus $diskGB
    }
    default { Fail "AURADE_VM_BACKEND must be hyperv or virtualbox, not $backend" }
  }
}

function Find-VBoxManage {
  $cmd = Get-Command VBoxManage.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  foreach ($root in @($env:VBOX_MSI_INSTALL_PATH, $env:VBOX_INSTALL_PATH, "$env:ProgramFiles\Oracle\VirtualBox")) {
    if ($root -and (Test-Path (Join-Path $root 'VBoxManage.exe'))) { return (Join-Path $root 'VBoxManage.exe') }
  }
  return $null
}

# --- the ISO ---------------------------------------------------------------------

function Get-AuraDEIso([string]$Repo, [string]$Fingerprint, [string]$Dir) {
  $tag = Get-AuraSetting 'AURADE_VM_VERSION' ''
  if (-not $tag) {
    $tag = (Invoke-RestMethod -UseBasicParsing "https://api.github.com/repos/$Repo/releases/latest").tag_name
  }
  if ($tag -notmatch '^v\d+\.\d+\.\d+$') { Fail "could not work out the latest release (got '$tag')" }
  $base = "https://github.com/$Repo/releases/download/$tag"
  $file = "aurade-$tag-x86_64.iso"
  $iso = Join-Path $Dir $file
  if (Test-Path "$iso.checked") {
    Say "using $file, already downloaded and checked"
    return $iso
  }

  Say "downloading AuraDE $tag (about 1.7 GB) into $Dir"
  $part = "$iso.part"
  $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
  if ($curl) {
    # Windows 10 and later ship curl.exe, which resumes a broken download.
    & $curl.Source -fL -# --retry 3 -C - -o $part "$base/$file"
    if ($LASTEXITCODE -ne 0) { Fail 'the download failed; run this again to resume it' }
  } else {
    Invoke-WebRequest -UseBasicParsing -Uri "$base/$file" -OutFile $part
  }

  $want = ((Invoke-WebRequest -UseBasicParsing -Uri "$base/$file.sha256").Content -split '\s+')[0].ToLower()
  $got = (Get-FileHash -Algorithm SHA256 -Path $part).Hash.ToLower()
  if ($got -ne $want) {
    Remove-Item -Force $part
    Fail 'the download does not match its published SHA-256; run this again to retry'
  }
  Move-Item -Force $part $iso

  $gpg = Get-Command gpg.exe -ErrorAction SilentlyContinue
  if ($gpg) {
    $gnupg = Join-Path ([IO.Path]::GetTempPath()) ("aurade-gpg-" + [Guid]::NewGuid())
    New-Item -ItemType Directory -Path $gnupg | Out-Null
    try {
      Invoke-WebRequest -UseBasicParsing -Uri "$base/aurade-repository.asc" -OutFile (Join-Path $gnupg 'key.asc')
      Invoke-WebRequest -UseBasicParsing -Uri "$base/$file.sig" -OutFile "$iso.sig"
      & $gpg.Source --homedir $gnupg --batch --quiet --import (Join-Path $gnupg 'key.asc') 2>$null
      $status = & $gpg.Source --homedir $gnupg --batch --status-fd 1 --verify "$iso.sig" $iso 2>$null
    } finally {
      Remove-Item -Recurse -Force $gnupg -ErrorAction SilentlyContinue
    }
    if (-not ($status -match "VALIDSIG $Fingerprint ")) { Fail "the ISO is not signed by the AuraDE release key $Fingerprint" }
    Say 'checked: SHA-256 and the release key''s signature'
  } else {
    Say 'checked: SHA-256 (install Gpg4win to check the signature as well)'
  }
  New-Item -ItemType File -Force -Path "$iso.checked" | Out-Null
  return $iso
}

# --- Hyper-V -----------------------------------------------------------------------

function Start-HyperV($Repo, $Fingerprint, $Dir, $Name, $Memory, $Cpus, $DiskGB) {
  $vm = Get-VM -Name $Name -ErrorAction SilentlyContinue
  if (-not $vm) {
    $iso = Get-AuraDEIso $Repo $Fingerprint $Dir
    $disk = Join-Path $Dir "$Name.vhdx"
    # The Default Switch gives the VM internet through the host, the way a
    # user network does in QEMU. It exists on Windows 10 1709 and later.
    $switch = Get-VMSwitch -Name 'Default Switch' -ErrorAction SilentlyContinue
    if (-not $switch) { $switch = Get-VMSwitch | Where-Object SwitchType -eq 'External' | Select-Object -First 1 }
    if (-not $switch) { Fail 'Hyper-V has no Default Switch and no external switch for the VM''s network' }

    Say "creating the Hyper-V VM $Name"
    $vm = New-VM -Name $Name -Generation 2 -MemoryStartupBytes ([int64]$Memory * 1MB) `
      -NewVHDPath $disk -NewVHDSizeBytes ([int64]$DiskGB * 1GB) -SwitchName $switch.Name -Path $Dir
    Set-VM -VM $vm -ProcessorCount $Cpus -StaticMemory -AutomaticCheckpointsEnabled $false
    # The installer and the installed system boot through their own signed
    # chain only once a key is enrolled, so Secure Boot starts off.
    Set-VMFirmware -VM $vm -EnableSecureBoot Off
    $dvd = Add-VMDvdDrive -VM $vm -Path $iso -Passthru
    $hdd = Get-VMHardDiskDrive -VM $vm
    # The disk first: empty, the firmware falls through to the installer,
    # and once AuraDE is installed it boots straight into it.
    Set-VMFirmware -VM $vm -BootOrder $hdd, $dvd
    Set-VMVideo -VM $vm -ResolutionType Single -HorizontalResolution 1920 -VerticalResolution 1080 -ErrorAction SilentlyContinue
    Say "choose the virtual disk in the installer; after it finishes, the VM boots AuraDE"
  } else {
    Say "starting the existing Hyper-V VM $Name"
  }
  if ($vm.State -ne 'Running') { Start-VM -VM $vm }
  Start-Process vmconnect.exe -ArgumentList 'localhost', $Name
}

# --- VirtualBox --------------------------------------------------------------------

function Start-VirtualBox($VBox, $Repo, $Fingerprint, $Dir, $Name, $Memory, $Cpus, $DiskGB) {
  & $VBox showvminfo $Name *> $null
  if ($LASTEXITCODE -eq 0) {
    Say "starting the existing VirtualBox VM $Name"
    & $VBox startvm $Name
    return
  }
  $iso = Get-AuraDEIso $Repo $Fingerprint $Dir
  $disk = Join-Path $Dir "$Name.vdi"
  Say "creating the VirtualBox VM $Name"
  function VB { & $VBox @args; if ($LASTEXITCODE -ne 0) { Fail "VBoxManage $($args -join ' ') failed" } }
  VB createvm --name $Name --ostype ArchLinux_64 --register --basefolder $Dir
  VB modifyvm $Name --memory $Memory --cpus $Cpus --firmware efi --graphicscontroller vmsvga --vram 128 `
    --nic1 nat --mouse usbtablet --usbxhci on --boot1 disk --boot2 dvd
  VB createmedium disk --filename $disk --size ($DiskGB * 1024)
  VB storagectl $Name --name SATA --add sata --portcount 2
  VB storageattach $Name --storagectl SATA --port 0 --type hdd --medium $disk
  VB storageattach $Name --storagectl SATA --port 1 --type dvddrive --medium $iso
  Say "choose the virtual disk in the installer; after it finishes, the VM boots AuraDE"
  VB startvm $Name
}

Invoke-AuraDEVM
