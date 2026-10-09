package plan

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/Cam396/aurade/vm/aurade-vm/internal/answers"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/hv"
)

type fakeHV struct {
	created, started, finished int
	running, failStart         bool
	spec                       hv.Spec
}

func (f *fakeHV) ID() string                            { return "fake" }
func (f *fakeHV) Name() string                          { return "Fake" }
func (f *fakeHV) Detect(context.Context) hv.Detection   { return hv.Detection{Available: true} }
func (f *fakeHV) GuestDisk() string                     { return "/dev/vda" }
func (f *fakeHV) Exists(s hv.Spec) bool                 { return f.created > 0 }
func (f *fakeHV) Running(context.Context, hv.Spec) bool { return f.running }
func (f *fakeHV) Start(context.Context, hv.Spec) error {
	f.started++
	if f.failStart {
		return fmt.Errorf("would not start")
	}
	return nil
}
func (f *fakeHV) Finish(context.Context, hv.Spec) error {
	f.finished++
	return nil
}
func (f *fakeHV) Create(_ context.Context, s hv.Spec, _ func(string)) error {
	f.created++
	f.spec = s
	return nil
}

func TestGuidedWritesAnswersNamingTheGuestDisk(t *testing.T) {
	base := t.TempDir()
	iso := filepath.Join(base, "local.iso")
	os.WriteFile(iso, []byte("x"), 0o600)
	f := &fakeHV{}
	p := &Plan{Backend: f, Mode: Guided, BaseDir: base, LocalISO: iso,
		Spec:    hv.Spec{Name: "aurade", MemoryMB: 4096, CPUs: 2, DiskGB: 30},
		Answers: answers.Answers{Hostname: "box", Username: "me"}}
	var steps []string
	if err := p.Run(context.Background(), func(e Event) {
		if e.Step != "" {
			steps = append(steps, e.Step)
		}
	}); err != nil {
		t.Fatal(err)
	}
	if f.created != 1 || f.started != 1 {
		t.Fatalf("created %d started %d", f.created, f.started)
	}
	if f.spec.ISO != iso || f.spec.AnswersISO == "" {
		t.Fatalf("spec %+v", f.spec)
	}
	img, _ := os.ReadFile(f.spec.AnswersISO)
	if !strings.Contains(string(img), "target=/dev/vda\n") || !strings.Contains(string(img), "hostname=box\n") {
		t.Fatal("the answers disk does not name the guest disk and the answers")
	}
	// The next run starts the same VM and tidies the answers disk away.
	if err := p.Run(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if f.created != 1 || f.started != 2 || f.finished != 1 {
		t.Fatalf("second run: created %d started %d finished %d", f.created, f.started, f.finished)
	}
	if len(steps) == 0 {
		t.Fatal("no steps reported")
	}
	// While it runs, its settings are left alone.
	f.running = true
	if err := p.Run(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if f.finished != 1 || f.started != 3 {
		t.Fatalf("running VM: started %d finished %d", f.started, f.finished)
	}
}

func TestBadAnswersStopBeforeAnythingIsMade(t *testing.T) {
	base := t.TempDir()
	f := &fakeHV{}
	p := &Plan{Backend: f, Mode: Guided, BaseDir: base, LocalISO: "/nonexistent",
		Spec: hv.Spec{Name: "aurade"}, Answers: answers.Answers{Hostname: "localhost"}}
	if err := p.Run(context.Background(), nil); err == nil || f.created != 0 {
		t.Fatalf("err=%v created=%d", err, f.created)
	}
}

func TestPlainWritesNoAnswers(t *testing.T) {
	base := t.TempDir()
	iso := filepath.Join(base, "local.iso")
	os.WriteFile(iso, []byte("x"), 0o600)
	f := &fakeHV{}
	p := &Plan{Backend: f, Mode: Plain, BaseDir: base, LocalISO: iso, Spec: hv.Spec{Name: "aurade"}}
	if err := p.Run(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if f.spec.AnswersISO != "" {
		t.Fatal("plain mode attached answers")
	}
}

// A first start that fails leaves the answers for the next try.
func TestFailedFirstStartKeepsTheAnswers(t *testing.T) {
	base := t.TempDir()
	iso := filepath.Join(base, "local.iso")
	os.WriteFile(iso, []byte("x"), 0o600)
	f := &fakeHV{failStart: true}
	p := &Plan{Backend: f, Mode: Guided, BaseDir: base, LocalISO: iso,
		Spec: hv.Spec{Name: "aurade", MemoryMB: 4096, CPUs: 2, DiskGB: 30}, Answers: answers.Answers{Hostname: "box"}}
	if err := p.Run(context.Background(), nil); err == nil {
		t.Fatal("a failed start was not reported")
	}
	f.failStart = false
	p2 := &Plan{Backend: f, BaseDir: base, Spec: hv.Spec{Name: "aurade"}}
	if err := p2.Run(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if f.finished != 0 {
		t.Fatal("the answers were tidied away before the VM had ever started")
	}
	p3 := &Plan{Backend: f, BaseDir: base, Spec: hv.Spec{Name: "aurade"}}
	if err := p3.Run(context.Background(), nil); err != nil || f.finished != 1 {
		t.Fatalf("after a start, the next run should tidy up: %v %d", err, f.finished)
	}
}

func TestExpressCarriesTheHashAndNeverEncrypts(t *testing.T) {
	base := t.TempDir()
	iso := filepath.Join(base, "local.iso")
	os.WriteFile(iso, []byte("x"), 0o600)
	f := &fakeHV{}
	p := &Plan{Backend: f, Mode: Express, BaseDir: base, LocalISO: iso, PasswordHash: "$6$salt$hash",
		Spec:    hv.Spec{Name: "aurade", MemoryMB: 4096, CPUs: 2, DiskGB: 30},
		Answers: answers.Answers{Hostname: "box", Username: "me", Encrypt: "yes"}}
	if err := p.Run(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	img, _ := os.ReadFile(f.spec.AnswersISO)
	for _, want := range []string{"PASSWORD.HASH;1", "EXPRESS.;1", "$6$salt$hash\n", "encrypt=no\n"} {
		if !strings.Contains(string(img), want) {
			t.Errorf("the express disk lacks %q", want)
		}
	}
	for _, bad := range []*Plan{
		{Backend: &fakeHV{}, Mode: Express, BaseDir: t.TempDir(), LocalISO: iso, PasswordHash: "$6$x$y", Spec: hv.Spec{Name: "a"}},
		{Backend: &fakeHV{}, Mode: Express, BaseDir: t.TempDir(), LocalISO: iso, Answers: answers.Answers{Username: "me"}, Spec: hv.Spec{Name: "a"}},
	} {
		if err := bad.Run(context.Background(), nil); err == nil {
			t.Error("an express install with no username or no password was made")
		}
	}
}

// Older releases downloaded here are removed once a newer one is checked,
// unless a VM still starts from one. An ISO this tool did not download, which
// has no stamp, is never touched.
func TestOldISOsGoUnlessAVMUsesThem(t *testing.T) {
	base := t.TempDir()
	put := func(name string, stamp bool) string {
		p := filepath.Join(base, name)
		os.WriteFile(p, []byte("iso"), 0o644)
		if stamp {
			os.WriteFile(p+".checked", []byte("sha256+signature\n"), 0o644)
		}
		return p
	}
	current := put("aurade-v1.2.0-x86_64.iso", true)
	unused := put("aurade-v1.1.1-x86_64.iso", true)
	os.WriteFile(unused+".part", []byte("half"), 0o644)
	used := put("aurade-v1.1.2-x86_64.iso", true)
	legacy := put("aurade-v1.0.0-x86_64.iso", true)
	handPlaced := put("aurade-v0.9.0-x86_64.iso", false)

	// A VM with a record that starts from v1.1.2, and an early VMware VM with
	// no record whose .vmx names v1.0.0 in other case.
	os.MkdirAll(filepath.Join(base, "a"), 0o755)
	if err := hv.WriteRecord(hv.Record{Backend: "qemu", Spec: hv.Spec{Name: "a", Dir: filepath.Join(base, "a"), ISO: used, MemoryMB: 4096}}); err != nil {
		t.Fatal(err)
	}
	os.MkdirAll(filepath.Join(base, "old"), 0o755)
	os.WriteFile(filepath.Join(base, "old", "old.vmx"), []byte(`ide1:0.fileName = "D:\VMs\AURADE-V1.0.0-X86_64.ISO"`+"\n"), 0o644)

	var logs []string
	p := &Plan{BaseDir: base}
	p.tidyOldISOs(current, func(e Event) { logs = append(logs, e.Log) })

	gone := func(p string) bool { _, err := os.Stat(p); return os.IsNotExist(err) }
	if !gone(unused) || !gone(unused+".checked") || !gone(unused+".part") {
		t.Error("an older release no VM uses was kept")
	}
	for _, keep := range []string{current, current + ".checked", used, legacy, handPlaced} {
		if gone(keep) {
			t.Errorf("%s was removed", filepath.Base(keep))
		}
	}
	if len(logs) != 1 || !strings.Contains(logs[0], "aurade-v1.1.1-x86_64.iso") {
		t.Errorf("the removal was not reported once: %q", logs)
	}

	// A VM folder whose .vmx cannot be read keeps everything. A folder by
	// that name cannot be read as a file, even by root.
	again := put("aurade-v1.1.1-x86_64.iso", true)
	os.MkdirAll(filepath.Join(base, "broken", "broken.vmx"), 0o755)
	p.tidyOldISOs(current, func(Event) {})
	if gone(again) {
		t.Error("an ISO was removed while a VM's settings could not be read")
	}
}
