package hv

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
)

// VMware drives Workstation (Windows, Linux) and Fusion (Intel Macs) through
// vmrun and vmware-vdiskmanager, which both ship with the product.
type VMware struct {
	goos, goarch string
	// lookup finds a tool; replaceable for tests.
	lookup func(name string) string
}

// NewVMware returns the backend for this computer.
func NewVMware() *VMware {
	v := &VMware{goos: runtime.GOOS, goarch: runtime.GOARCH}
	v.lookup = v.findTool
	return v
}

func (v *VMware) ID() string { return "vmware" }

func (v *VMware) Name() string {
	if v.goos == "darwin" {
		return "VMware Fusion"
	}
	return "VMware Workstation"
}

// The NVMe controller below puts the disk here.
func (v *VMware) GuestDisk() string { return "/dev/nvme0n1" }

func (v *VMware) hostType() string {
	if v.goos == "darwin" {
		return "fusion"
	}
	return "ws"
}

func (v *VMware) toolDirs() []string {
	switch v.goos {
	case "windows":
		var dirs []string
		if out, err := exec.Command("reg", "query", `HKLM\SOFTWARE\WOW6432Node\VMware, Inc.\VMware Workstation`, "/v", "InstallPath").Output(); err == nil {
			if m := regexp.MustCompile(`InstallPath\s+REG_SZ\s+(.+)`).FindStringSubmatch(string(out)); m != nil {
				dirs = append(dirs, strings.TrimSpace(m[1]))
			}
		}
		for _, env := range []string{"ProgramFiles(x86)", "ProgramFiles"} {
			if p := os.Getenv(env); p != "" {
				dirs = append(dirs, filepath.Join(p, "VMware", "VMware Workstation"))
			}
		}
		return dirs
	case "darwin":
		return []string{"/Applications/VMware Fusion.app/Contents/Library"}
	default:
		return []string{"/usr/bin", "/usr/local/bin"}
	}
}

func (v *VMware) findTool(name string) string {
	exe := name
	if v.goos == "windows" {
		exe += ".exe"
	}
	for _, d := range v.toolDirs() {
		p := filepath.Join(d, exe)
		if st, err := os.Stat(p); err == nil && !st.IsDir() {
			return p
		}
	}
	if p, err := exec.LookPath(exe); err == nil {
		return p
	}
	return ""
}

var vmrunVersionRe = regexp.MustCompile(`vmrun version (\d+)\.(\d+)`)

func (v *VMware) Detect(ctx context.Context) Detection {
	if v.goos != "windows" && v.goos != "linux" && v.goos != "darwin" {
		return Detection{Foreign: true, Why: "VMware runs on Windows, Linux and Macs."}
	}
	if v.goos == "darwin" && v.goarch == "arm64" {
		return Detection{Why: "VMware Fusion on an Apple Silicon Mac can only run Arm systems, and AuraDE is built for x86_64 PCs."}
	}
	vmrun := v.lookup("vmrun")
	if vmrun == "" {
		return Detection{Why: v.Name() + " is not installed. It is free for personal use from vmware.com."}
	}
	if v.lookup("vmware-vdiskmanager") == "" {
		return Detection{Why: v.Name() + " is installed without vmware-vdiskmanager, which is needed to make the disk."}
	}
	// vmrun with no arguments prints its help, with the version, and exits
	// non-zero, so the output matters and the status does not.
	out, _ := exec.CommandContext(ctx, vmrun).CombinedOutput()
	product, ok := productVersion(string(out))
	if !ok {
		return Detection{Available: true, Version: "unknown version"}
	}
	if product < 16 {
		return Detection{Version: strconv.Itoa(product), Why: fmt.Sprintf("%s %d is too old; AuraDE needs version 16 or newer.", v.Name(), product)}
	}
	return Detection{Available: true, Version: "version " + strconv.Itoa(product)}
}

// productVersion reads the product's major version out of vmrun's banner.
// vmrun numbers itself 1.<product>: Workstation 17 prints "vmrun version
// 1.17.0.25388281". Fusion follows its own numbering, 13 for Fusion 13.
func productVersion(banner string) (int, bool) {
	m := vmrunVersionRe.FindStringSubmatch(banner)
	if m == nil {
		return 0, false
	}
	major, _ := strconv.Atoi(m[1])
	minor, _ := strconv.Atoi(m[2])
	if major == 1 {
		return minor, true
	}
	return major, true
}

func (v *VMware) vmx(spec Spec) string  { return filepath.Join(spec.Dir, spec.Name+".vmx") }
func (v *VMware) vmdk(spec Spec) string { return filepath.Join(spec.Dir, spec.Name+".vmdk") }

func (v *VMware) Exists(spec Spec) bool {
	_, err := os.Stat(v.vmx(spec))
	return err == nil
}

func (v *VMware) Running(ctx context.Context, spec Spec) bool {
	vmrun := v.lookup("vmrun")
	if vmrun == "" {
		return false
	}
	out, err := run(ctx, vmrun, "-T", v.hostType(), "list")
	if err != nil {
		return false
	}
	return listed(out, v.vmx(spec))
}

// listed finds a .vmx in vmrun's list. Windows paths compare without case.
func listed(list, vmx string) bool {
	want := filepath.Clean(vmx)
	for _, line := range strings.Split(list, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "Total running VMs") {
			continue
		}
		if line == want || strings.EqualFold(line, want) && strings.Contains(want, `\`) {
			return true
		}
	}
	return false
}

func (v *VMware) Create(ctx context.Context, spec Spec, log func(string)) error {
	if log == nil {
		log = func(string) {}
	}
	if v.Exists(spec) {
		return fmt.Errorf("a VM is already at %s", v.vmx(spec))
	}
	if err := os.MkdirAll(spec.Dir, 0o755); err != nil {
		return err
	}
	vdisk := v.lookup("vmware-vdiskmanager")
	if vdisk == "" {
		return errors.New("vmware-vdiskmanager was not found")
	}
	log(fmt.Sprintf("Making a %d GB virtual disk (it only takes the space AuraDE uses)", spec.DiskGB))
	// Growable, in one file. The adapter type only labels the descriptor;
	// the disk is attached to NVMe below.
	if _, err := run(ctx, vdisk, "-c", "-s", strconv.Itoa(spec.DiskGB)+"GB", "-a", "lsilogic", "-t", "0", v.vmdk(spec)); err != nil {
		return err
	}
	log("Writing the VM's settings")
	if err := os.WriteFile(v.vmx(spec), []byte(VMX(spec)), 0o644); err != nil {
		return err
	}
	return nil
}

// VMX renders the configuration. It follows a VM AuraDE is tested on:
// UEFI, NVMe, e1000e on NAT, a USB 3 tablet, and SVGA with 3D, which is what
// makes the desktop usable.
func VMX(spec Spec) string {
	graphicsKB := 2097152
	if spec.MemoryMB >= 8192 {
		graphicsKB = 4194304
	}
	kv := map[string]string{
		".encoding":                      "UTF-8",
		"config.version":                 "8",
		"virtualHW.version":              "19",
		"displayName":                    spec.Name,
		"guestOS":                        "other6xlinux-64",
		"firmware":                       "efi",
		"uefi.secureBoot.enabled":        "FALSE",
		"numvcpus":                       strconv.Itoa(spec.CPUs),
		"cpuid.coresPerSocket":           strconv.Itoa(spec.CPUs),
		"memsize":                        strconv.Itoa(spec.MemoryMB),
		"pciBridge0.present":             "TRUE",
		"pciBridge4.present":             "TRUE",
		"pciBridge4.virtualDev":          "pcieRootPort",
		"pciBridge4.functions":           "8",
		"pciBridge5.present":             "TRUE",
		"pciBridge5.virtualDev":          "pcieRootPort",
		"pciBridge5.functions":           "8",
		"pciBridge6.present":             "TRUE",
		"pciBridge6.virtualDev":          "pcieRootPort",
		"pciBridge6.functions":           "8",
		"pciBridge7.present":             "TRUE",
		"pciBridge7.virtualDev":          "pcieRootPort",
		"pciBridge7.functions":           "8",
		"vmci0.present":                  "TRUE",
		"hpet0.present":                  "TRUE",
		"nvme0.present":                  "TRUE",
		"nvme0:0.present":                "TRUE",
		"nvme0:0.fileName":               spec.Name + ".vmdk",
		"sata0.present":                  "TRUE",
		"sata0:0.present":                "TRUE",
		"sata0:0.deviceType":             "cdrom-image",
		"sata0:0.fileName":               spec.ISO,
		"sata0:0.startConnected":         "TRUE",
		"ethernet0.present":              "TRUE",
		"ethernet0.connectionType":       "nat",
		"ethernet0.virtualDev":           "e1000e",
		"ethernet0.addressType":          "generated",
		"usb.present":                    "TRUE",
		"ehci.present":                   "TRUE",
		"usb_xhci.present":               "TRUE",
		"usb_xhci:4.present":             "TRUE",
		"usb_xhci:4.deviceType":          "hid",
		"usb_xhci:4.port":                "4",
		"usb_xhci:4.parent":              "-1",
		"sound.present":                  "TRUE",
		"sound.autoDetect":               "TRUE",
		"sound.fileName":                 "-1",
		"sound.virtualDev":               "hdaudio",
		"mks.enable3d":                   strings.ToUpper(strconv.FormatBool(spec.Accel3D)),
		"svga.graphicsMemoryKB":          strconv.Itoa(graphicsKB),
		"floppy0.present":                "FALSE",
		"powerType.powerOff":             "soft",
		"powerType.powerOn":              "soft",
		"powerType.suspend":              "soft",
		"powerType.reset":                "soft",
		"tools.syncTime":                 "TRUE",
		"gui.stretchGuestMode":           "fullfill",
		"virtualHW.productCompatibility": "hosted",
		"annotation":                     "AuraDE, made by aurade-vm",
	}
	if spec.AnswersISO != "" {
		kv["sata0:1.present"] = "TRUE"
		kv["sata0:1.deviceType"] = "cdrom-image"
		kv["sata0:1.fileName"] = spec.AnswersISO
		kv["sata0:1.startConnected"] = "TRUE"
	}
	keys := make([]string, 0, len(kv))
	for k := range kv {
		keys = append(keys, k)
	}
	// .encoding has to be the first line; the rest are sorted so the file
	// is the same every time.
	sort.Slice(keys, func(i, j int) bool {
		if keys[i] == ".encoding" || keys[j] == ".encoding" {
			return keys[i] == ".encoding"
		}
		return keys[i] < keys[j]
	})
	var b strings.Builder
	for _, k := range keys {
		fmt.Fprintf(&b, "%s = \"%s\"\n", k, vmxEscape(kv[k]))
	}
	return b.String()
}

// .vmx values are taken literally, backslashes included, except that VMware
// writes a few characters as | and two hex digits.
func vmxEscape(s string) string {
	r := strings.NewReplacer("|", "|7C", `"`, "|22", "#", "|23")
	return r.Replace(s)
}

var vmxHexRe = regexp.MustCompile(`\|([0-9A-Fa-f]{2})`)

func vmxUnescape(s string) string {
	return vmxHexRe.ReplaceAllStringFunc(s, func(m string) string {
		n, _ := strconv.ParseUint(m[1:], 16, 8)
		return string(rune(n))
	})
}

// vmxValue reads the value out of a `key = "value"` line.
func vmxValue(line string) string {
	_, v, ok := strings.Cut(line, "=")
	if !ok {
		return ""
	}
	v = strings.TrimSpace(v)
	v = strings.TrimPrefix(v, `"`)
	v = strings.TrimSuffix(v, `"`)
	return vmxUnescape(v)
}

func (v *VMware) Start(ctx context.Context, spec Spec) error {
	vmrun := v.lookup("vmrun")
	if vmrun == "" {
		return errors.New("vmrun was not found")
	}
	_, err := runLogged(ctx, filepath.Join(spec.Dir, "vmrun.log"), vmrun, "-T", v.hostType(), "start", v.vmx(spec), "gui")
	return err
}

// Finish drops the answers disk from the settings and deletes its file. The
// VM must be off, which it is on the run after the install, before Start.
func (v *VMware) Finish(ctx context.Context, spec Spec) error {
	path := v.vmx(spec)
	b, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	// VMware rewrites the file with Windows line endings on Windows.
	lines := strings.Split(strings.ReplaceAll(strings.TrimRight(string(b), "\r\n"), "\r\n", "\n"), "\n")
	var kept []string
	answers := []string{filepath.Join(spec.Dir, AnswersFile)}
	for _, line := range lines {
		if strings.HasPrefix(line, "sata0:1.") {
			if strings.HasPrefix(line, "sata0:1.fileName") {
				if a := vmxValue(line); a != "" {
					if !filepath.IsAbs(a) && !strings.Contains(a, `:\`) {
						a = filepath.Join(spec.Dir, a)
					}
					answers = append(answers, a)
				}
			}
			continue
		}
		kept = append(kept, line)
	}
	if len(kept) != len(lines) {
		if err := os.WriteFile(path, []byte(strings.Join(kept, "\n")+"\n"), 0o644); err != nil {
			return err
		}
	}
	for _, a := range answers {
		if err := os.Remove(a); err != nil && !os.IsNotExist(err) {
			return err
		}
	}
	return nil
}
