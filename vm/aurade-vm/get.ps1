# Get aurade-vm on Windows and start it.
#
#   irm https://raw.githubusercontent.com/Cam396/aurade/main/vm/aurade-vm/get.ps1 | iex
#
# It downloads the aurade-vm program for this PC, checks it against the
# SHA-256 written into this script for that version, and runs it. A file
# PowerShell downloads is not marked as coming from the internet the way a
# browser download is, so Windows does not stop to ask about it; the check
# against the hash below is what makes that safe. A file that does not match
# is deleted and never run.
#
# Settings, all optional, as environment variables:
#   AURADE_VM_ARGS      options for aurade-vm, for example "--release v1.1.2"
#   AURADE_VM_BIN_DIR   where the program is kept (default %LOCALAPPDATA%\AuraDE\bin)
#   AURADE_VM_BASE_URL  where to download from (for testing a build)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# >>> pins (written by build.sh; do not edit by hand)
$Version = '0.0.0'
$Pins = @{
  'windows-amd64' = ''
  'windows-arm64' = ''
}
# <<< pins

function Say($text) { Write-Host "aurade-vm: $text" }
function Fail($text) { Write-Host "aurade-vm: $text" -ForegroundColor Red; throw "aurade-vm: $text" }

try {
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

$arch = switch ($env:PROCESSOR_ARCHITECTURE) {
  'AMD64' { 'amd64' }
  'ARM64' { 'arm64' }
  default { Fail "this PC is $($env:PROCESSOR_ARCHITECTURE); aurade-vm runs on 64-bit Windows" }
}
$target = "windows-$arch"
$want = $Pins[$target]
if (-not $want) { Fail "no aurade-vm build is published for $target yet" }

$binDir = if ($env:AURADE_VM_BIN_DIR) { $env:AURADE_VM_BIN_DIR } else { Join-Path $env:LOCALAPPDATA 'AuraDE\bin' }
$exe = Join-Path $binDir 'aurade-vm.exe'
$name = "aurade-vm-$Version-$target.exe"
$base = if ($env:AURADE_VM_BASE_URL) { $env:AURADE_VM_BASE_URL.TrimEnd('/') } else { "https://github.com/Cam396/aurade/releases/download/aurade-vm-v$Version" }

function HashOf($path) { (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant() }

if ((Test-Path -LiteralPath $exe) -and ((HashOf $exe) -eq $want)) {
  Say "aurade-vm $Version is already here"
} else {
  New-Item -ItemType Directory -Force -Path $binDir | Out-Null
  Remove-Item -Force -ErrorAction SilentlyContinue -LiteralPath $exe
  $part = "$exe.part"
  Say "downloading aurade-vm $Version"
  Invoke-WebRequest -UseBasicParsing -Uri "$base/$name" -OutFile $part
  $got = HashOf $part
  if ($got -ne $want) {
    Remove-Item -Force -LiteralPath $part
    Fail "the download does not match the SHA-256 this script expects, so it was deleted. Expected $want, got $got."
  }
  Move-Item -Force -LiteralPath $part -Destination $exe
  Say "checked: SHA-256 $want"
}

$argv = @()
if ($env:AURADE_VM_ARGS) { $argv = @($env:AURADE_VM_ARGS -split '\s+' | Where-Object { $_ }) }
# An array after a native command is passed as separate arguments.
& $exe $argv
