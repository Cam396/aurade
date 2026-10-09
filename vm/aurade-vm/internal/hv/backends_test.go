package hv

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func has(args []string, want ...string) bool {
	joined := "\x00" + strings.Join(args, "\x00") + "\x00"
	return strings.Contains(joined, "\x00"+strings.Join(want, "\x00")+"\x00")
}

func TestQEMUArgs(t *testing.T) {
	dir := t.TempDir()
	s := Spec{Name: "aurade", Dir: dir, ISO: "/iso/aurade.iso", MemoryMB: 6144, CPUs: 4, Accel3D: true}
	q := &QEMU{goos: "linux"}
	t.Setenv("AURADE_VM_DISPLAY", "")
	args := q.Args(s, "/fw/code.fd")
	for _, want := range [][]string{
		{"-machine", "q35,accel=kvm"}, {"-m", "6144"}, {"-smp", "4"},
		{"-device", "virtio-blk-pci,drive=hd0,bootindex=1"}, {"-device", "ide-cd,drive=cd0,bus=ide.0,bootindex=2"},
		{"-device", "virtio-vga-gl,edid=on,xres=1920,yres=1080"},
		{"-display", "gtk,zoom-to-fit=on,gl=on"},
		{"-drive", "file=/iso/aurade.iso,media=cdrom,if=none,id=cd0,readonly=on"},
	} {
		if !has(args, want...) {
			t.Errorf("missing %v in %v", want, args)
		}
	}
	if strings.Contains(strings.Join(args, " "), AnswersFile) {
		t.Error("answers drive with no answers file")
	}
	os.WriteFile(filepath.Join(dir, AnswersFile), []byte("x"), 0o600)
	if !strings.Contains(strings.Join(q.Args(s, "/fw/code.fd"), " "), AnswersFile) {
		t.Error("the answers file is not attached")
	}
	if err := q.Finish(context.Background(), s); err != nil || fileExists(filepath.Join(dir, AnswersFile)) {
		t.Fatalf("finish: %v", err)
	}
	mac := (&QEMU{goos: "darwin"}).Args(s, "/fw")
	if !has(mac, "-machine", "q35,accel=hvf") || !has(mac, "-display", "cocoa") {
		t.Errorf("mac args %v", mac)
	}
}

func TestQEMUExplainsWhatIsMissing(t *testing.T) {
	none := func(string) string { return "" }
	for _, c := range []struct {
		q    *QEMU
		want string
	}{
		{&QEMU{goos: "windows", lookup: none}, "Windows"},
		{&QEMU{goos: "darwin", goarch: "arm64", lookup: none}, "Apple Silicon"},
		{&QEMU{goos: "linux", goarch: "amd64", lookup: none}, "not installed"},
	} {
		if d := c.q.Detect(context.Background()); d.Available || !strings.Contains(d.Why, c.want) {
			t.Errorf("%+v: %+v", c.q, d)
		}
	}
}

func TestLibvirtInstallArgs(t *testing.T) {
	l := &Libvirt{uri: "qemu:///session"}
	s := Spec{Name: "a", Dir: "/vms/a", ISO: "/iso/x.iso", AnswersISO: "/vms/a/" + AnswersFile, MemoryMB: 4096, CPUs: 2, DiskGB: 40}
	args := l.InstallArgs(s)
	for _, want := range [][]string{
		{"--connect", "qemu:///session"}, {"--boot", "uefi,firmware.feature0.name=secure-boot,firmware.feature0.enabled=no,firmware.feature1.name=enrolled-keys,firmware.feature1.enabled=no"}, {"--import"},
		{"--disk", "path=/vms/a/a.qcow2,size=40,format=qcow2,bus=virtio,boot.order=1"},
		{"--disk", "path=/iso/x.iso,device=cdrom,bus=sata,readonly=on,boot.order=2"},
		{"--disk", "path=/vms/a/" + AnswersFile + ",device=cdrom,bus=sata,readonly=on"},
	} {
		if !has(args, want...) {
			t.Errorf("missing %v", want)
		}
	}
	list := " Type   Device   Target   Source\n------------------------------------\n file   disk     vda      /vms/a/a.qcow2\n file   cdrom    sda      /iso/x.iso\n file   cdrom    sdb      /vms/a/" + AnswersFile + "\n"
	if blkTarget(list, "/vms/a/"+AnswersFile) != "sdb" || blkTarget(list, "/nope") != "" {
		t.Error("blkTarget")
	}
}

func TestVirtualBoxSteps(t *testing.T) {
	v := &VirtualBox{}
	s := Spec{Name: "a", Dir: "/vms/a", ISO: "/iso/x.iso", AnswersISO: "/vms/a/" + AnswersFile, MemoryMB: 4096, CPUs: 2, DiskGB: 40}
	steps := v.Steps(s)
	if !has(steps[0], "--basefolder", "/vms") || !has(steps[1], "--firmware", "efi") || !has(steps[2], "--size", "40960") {
		t.Errorf("steps %v", steps)
	}
	last := steps[len(steps)-1]
	if !has(last, "--port", "2") || !has(last, "--medium", "/vms/a/"+AnswersFile) {
		t.Errorf("answers step %v", last)
	}
	if len(v.Steps(Spec{Name: "a", Dir: "/vms/a"})) != len(steps)-1 {
		t.Error("an answers drive with no answers disk")
	}
}

func TestHyperVScriptQuotes(t *testing.T) {
	h := &HyperV{}
	s := Spec{Name: "it's", Dir: `C:\VMs\it's`, ISO: `C:\iso\x.iso`, AnswersISO: `C:\VMs\it's\` + AnswersFile, MemoryMB: 4096, CPUs: 2, DiskGB: 40}
	sc := h.CreateScript(s)
	for _, want := range []string{"-Name 'it''s' -Generation 2", "-MemoryStartupBytes 4096MB", "-NewVHDSizeBytes 40GB",
		"-EnableSecureBoot Off", `Add-VMDvdDrive -VM $vm -Path 'C:\VMs\it''s\` + AnswersFile + `'`} {
		if !strings.Contains(sc, want) {
			t.Errorf("missing %q in\n%s", want, sc)
		}
	}
}

func TestHyperVDetectReadsTheProbe(t *testing.T) {
	for out, want := range map[string]string{
		"admin=False\nmodule=False\nversion=": "not turned on",
		"admin=False\nmodule=True\nversion=":  "administrator",
	} {
		h := &HyperV{goos: "windows", ps: func(context.Context, string) (string, error) { return out, nil }}
		if d := h.Detect(context.Background()); d.Available || !strings.Contains(d.Why, want) {
			t.Errorf("%q: %+v", out, d)
		}
	}
	h := &HyperV{goos: "windows", ps: func(context.Context, string) (string, error) {
		return "admin=True\nmodule=True\nversion=HOST 10.0", nil
	}}
	if !h.Detect(context.Background()).Available {
		t.Error("ready Hyper-V not available")
	}
}

func TestParallels(t *testing.T) {
	p := &Parallels{goos: "darwin", goarch: "arm64", lookup: func(string) string { return "/x" }}
	if d := p.Detect(context.Background()); d.Available || !strings.Contains(d.Why, "Apple Silicon") {
		t.Errorf("%+v", d)
	}
	s := Spec{Name: "a", Dir: "/vms/a", ISO: "/iso/x.iso", AnswersISO: "/vms/a/" + AnswersFile, MemoryMB: 4096, CPUs: 2, DiskGB: 40}
	steps := (&Parallels{}).Steps(s)
	if !has(steps[0], "--dst", "/vms") || !has(steps[len(steps)-1], "--device-bootorder", "hdd0 cdrom0") {
		t.Errorf("steps %v", steps)
	}
	info := "Hardware:\n  hdd0 (+) sata:0 image='/vms/a/a.hdd' 40960Mb\n  cdrom0 (+) sata:1 image='/iso/x.iso'\n  cdrom1 (+) sata:2 image='/vms/a/" + AnswersFile + "'\n"
	if prlDevice(info, "/vms/a/"+AnswersFile) != "cdrom1" {
		t.Error("prlDevice")
	}
}

func TestRecordsRoundTrip(t *testing.T) {
	base := t.TempDir()
	dir := filepath.Join(base, "one")
	os.MkdirAll(dir, 0o755)
	if err := WriteRecord(Record{Backend: "qemu", Spec: Spec{Name: "one", Dir: dir, MemoryMB: 4096}}); err != nil {
		t.Fatal(err)
	}
	old := filepath.Join(base, "old")
	os.MkdirAll(old, 0o755)
	os.WriteFile(filepath.Join(old, "old.vmx"), nil, 0o644)
	os.MkdirAll(filepath.Join(base, "empty"), 0o755)
	rs := Existing(base)
	if len(rs) != 2 || rs[0].Spec.Name != "old" || rs[0].Backend != "vmware" || rs[1].Backend != "qemu" || rs[1].Spec.MemoryMB != 4096 {
		t.Fatalf("%+v", rs)
	}
}
