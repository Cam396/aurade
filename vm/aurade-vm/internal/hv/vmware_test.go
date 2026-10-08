package hv

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestVMXHasWhatAuraDENeeds(t *testing.T) {
	spec := Spec{Name: "aurade", Dir: "/x", ISO: `C:\AuraDE\aurade.iso`, AnswersISO: "answers.iso", MemoryMB: 6144, CPUs: 4, DiskGB: 40, Accel3D: true}
	vmx := VMX(spec)
	if !strings.HasPrefix(vmx, ".encoding = \"UTF-8\"\n") {
		t.Fatal(".encoding is not the first line")
	}
	for _, want := range []string{
		`firmware = "efi"`, `nvme0:0.fileName = "aurade.vmdk"`, `memsize = "6144"`, `numvcpus = "4"`,
		`mks.enable3d = "TRUE"`, `sata0:0.fileName = "C:\\AuraDE\\aurade.iso"`, `sata0:1.fileName = "answers.iso"`,
		`uefi.secureBoot.enabled = "FALSE"`,
	} {
		if !strings.Contains(vmx, want+"\n") {
			t.Errorf("missing %s", want)
		}
	}
	if strings.Contains(VMX(Spec{Name: "a", MemoryMB: 4096, CPUs: 2}), "sata0:1") {
		t.Error("an answers drive with no answers disk")
	}
}

func TestFinishDropsTheAnswersDisk(t *testing.T) {
	dir := t.TempDir()
	spec := Spec{Name: "aurade", Dir: dir, ISO: "aurade.iso", AnswersISO: filepath.Join(dir, "answers.iso"), MemoryMB: 4096, CPUs: 2}
	os.WriteFile(spec.AnswersISO, []byte("x"), 0o600)
	v := &VMware{goos: "linux"}
	os.WriteFile(v.vmx(spec), []byte(VMX(spec)), 0o644)
	if err := v.Finish(context.Background(), spec); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(v.vmx(spec))
	if strings.Contains(string(b), "sata0:1") || !strings.Contains(string(b), "sata0:0.fileName") {
		t.Fatalf("finish left the wrong drives:\n%s", b)
	}
	if _, err := os.Stat(spec.AnswersISO); !os.IsNotExist(err) {
		t.Fatal("the answers disk was not deleted")
	}
	// Twice is harmless.
	if err := v.Finish(context.Background(), spec); err != nil {
		t.Fatal(err)
	}
}

func TestAppleSiliconIsExplained(t *testing.T) {
	v := &VMware{goos: "darwin", goarch: "arm64", lookup: func(string) string { return "/x" }}
	d := v.Detect(context.Background())
	if d.Available || !strings.Contains(d.Why, "Apple Silicon") {
		t.Fatalf("%+v", d)
	}
	if v.Name() != "VMware Fusion" || v.hostType() != "fusion" {
		t.Fatal("a Mac is not Fusion")
	}
}

func TestMissingVMwareSaysWhereToGetIt(t *testing.T) {
	v := &VMware{goos: "windows", goarch: "amd64", lookup: func(string) string { return "" }}
	d := v.Detect(context.Background())
	if d.Available || !strings.Contains(d.Why, "not installed") {
		t.Fatalf("%+v", d)
	}
}

func TestProductVersion(t *testing.T) {
	for banner, want := range map[string]int{
		"\nvmrun version 1.17.0.25388281\n": 17,
		"vmrun version 1.16.2 build-1":      16,
		"vmrun version 13.5.0":              13,
	} {
		if got, ok := productVersion(banner); !ok || got != want {
			t.Errorf("%q: got %d want %d", banner, got, want)
		}
	}
	if _, ok := productVersion("nothing"); ok {
		t.Error("parsed a version out of nothing")
	}
}
