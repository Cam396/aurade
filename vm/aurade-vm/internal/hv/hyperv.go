package hv

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

// HyperV drives Hyper-V on Windows Pro and Enterprise through its PowerShell
// module, which needs an administrator.
type HyperV struct {
	goos string
	ps   func(ctx context.Context, script string) (string, error)
}

// NewHyperV returns the backend for this computer.
func NewHyperV() *HyperV {
	return &HyperV{goos: runtime.GOOS, ps: powershell}
}

func powershell(ctx context.Context, script string) (string, error) {
	exe := "powershell.exe"
	if root := os.Getenv("SystemRoot"); root != "" {
		exe = filepath.Join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	}
	out, err := exec.CommandContext(ctx, exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
		"-Command", "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; "+script).CombinedOutput()
	s := strings.TrimSpace(strings.ReplaceAll(string(out), "\r", ""))
	if err != nil {
		if s == "" {
			s = err.Error()
		}
		return s, fmt.Errorf("Hyper-V: %s", firstLine(s))
	}
	return s, nil
}

// psq quotes a value for PowerShell: single quotes, with ' doubled.
func psq(s string) string { return "'" + strings.ReplaceAll(s, "'", "''") + "'" }

func (h *HyperV) ID() string        { return "hyperv" }
func (h *HyperV) Name() string      { return "Hyper-V" }
func (h *HyperV) GuestDisk() string { return "/dev/sda" }

const hypervProbe = `$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$mod = [bool](Get-Command Get-VM -ErrorAction SilentlyContinue)
$ver = ''
if ($mod) { try { $ver = (Get-VMHost).Name + ' ' + (Get-Item "$env:SystemRoot\System32\vmms.exe").VersionInfo.ProductVersion } catch { } }
"admin=$admin"; "module=$mod"; "version=$ver"`

func (h *HyperV) Detect(ctx context.Context) Detection {
	if h.goos != "windows" {
		return Detection{Foreign: true, Why: "Hyper-V runs on Windows."}
	}
	out, err := h.ps(ctx, hypervProbe)
	if err != nil {
		return Detection{Why: "PowerShell could not be asked about Hyper-V: " + firstLine(out)}
	}
	kv := map[string]string{}
	for _, line := range strings.Split(out, "\n") {
		if k, v, ok := strings.Cut(strings.TrimSpace(line), "="); ok {
			kv[k] = v
		}
	}
	switch {
	case kv["module"] != "True":
		return Detection{Why: "Hyper-V is not turned on. On Windows Pro or Enterprise, in an administrator PowerShell: Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All, then restart."}
	case kv["admin"] != "True":
		return Detection{Why: "Hyper-V needs an administrator. Run aurade-vm from a terminal opened with Run as administrator."}
	}
	return Detection{Available: true, Version: strings.TrimSpace(kv["version"])}
}

func (h *HyperV) Exists(s Spec) bool {
	_, err := h.ps(context.Background(), "Get-VM -Name "+psq(s.Name)+" | Out-Null")
	return err == nil
}

func (h *HyperV) Running(ctx context.Context, s Spec) bool {
	out, err := h.ps(ctx, "(Get-VM -Name "+psq(s.Name)+").State")
	return err == nil && strings.TrimSpace(out) == "Running"
}

// CreateScript makes a generation 2 VM (UEFI) with Secure Boot off, the disk
// first in the boot order and the installer after it.
func (h *HyperV) CreateScript(s Spec) string {
	var b strings.Builder
	fmt.Fprintf(&b, "$switch = Get-VMSwitch -Name 'Default Switch' -ErrorAction SilentlyContinue\n")
	fmt.Fprintf(&b, "if (-not $switch) { $switch = Get-VMSwitch | Where-Object SwitchType -eq 'External' | Select-Object -First 1 }\n")
	fmt.Fprintf(&b, "if (-not $switch) { throw 'Hyper-V has no Default Switch and no external switch for the network' }\n")
	fmt.Fprintf(&b, "$vm = New-VM -Name %s -Generation 2 -MemoryStartupBytes %dMB -NewVHDPath %s -NewVHDSizeBytes %dGB -SwitchName $switch.Name -Path %s\n",
		psq(s.Name), s.MemoryMB, psq(filepath.Join(s.Dir, s.Name+".vhdx")), s.DiskGB, psq(filepath.Dir(s.Dir)))
	fmt.Fprintf(&b, "Set-VM -VM $vm -ProcessorCount %d -StaticMemory -AutomaticCheckpointsEnabled $false\n", s.CPUs)
	fmt.Fprintf(&b, "Set-VMFirmware -VM $vm -EnableSecureBoot Off\n")
	fmt.Fprintf(&b, "$dvd = Add-VMDvdDrive -VM $vm -Path %s -Passthru\n", psq(s.ISO))
	if s.AnswersISO != "" {
		fmt.Fprintf(&b, "Add-VMDvdDrive -VM $vm -Path %s\n", psq(s.AnswersISO))
	}
	fmt.Fprintf(&b, "Set-VMFirmware -VM $vm -BootOrder (Get-VMHardDiskDrive -VM $vm), $dvd\n")
	fmt.Fprintf(&b, "Set-VMVideo -VM $vm -ResolutionType Single -HorizontalResolution 1920 -VerticalResolution 1080 -ErrorAction SilentlyContinue\n")
	return b.String()
}

func (h *HyperV) Create(ctx context.Context, s Spec, log func(string)) error {
	if log == nil {
		log = func(string) {}
	}
	if h.Exists(s) {
		return fmt.Errorf("Hyper-V already has a VM called %s", s.Name)
	}
	log(fmt.Sprintf("Making a generation 2 VM with a %d GB disk", s.DiskGB))
	_, err := h.ps(ctx, h.CreateScript(s))
	return err
}

func (h *HyperV) Start(ctx context.Context, s Spec) error {
	if _, err := h.ps(ctx, "$vm = Get-VM -Name "+psq(s.Name)+"; if ($vm.State -ne 'Running') { Start-VM -VM $vm }; Start-Process vmconnect.exe -ArgumentList 'localhost', "+psq(s.Name)); err != nil {
		return err
	}
	return nil
}

func (h *HyperV) Finish(ctx context.Context, s Spec) error {
	answers := filepath.Join(s.Dir, AnswersFile)
	if !fileExists(answers) {
		return nil
	}
	if _, err := h.ps(ctx, "Get-VMDvdDrive -VMName "+psq(s.Name)+" | Where-Object Path -eq "+psq(answers)+" | Remove-VMDvdDrive"); err != nil {
		return err
	}
	if err := os.Remove(answers); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}
