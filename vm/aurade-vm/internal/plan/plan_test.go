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
