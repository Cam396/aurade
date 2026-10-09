package tui

import (
	"context"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/answers"
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/Cam396/aurade/vm/aurade-vm/internal/hv"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/plan"
)

type stubHV struct{ ok bool }

func (s stubHV) ID() string   { return "stub" }
func (s stubHV) Name() string { return "Stub Hypervisor" }
func (s stubHV) Detect(context.Context) hv.Detection {
	if s.ok {
		return hv.Detection{Available: true, Version: "1.0"}
	}
	return hv.Detection{Why: "Stub is not installed."}
}
func (s stubHV) GuestDisk() string                                   { return "/dev/vda" }
func (s stubHV) Running(context.Context, hv.Spec) bool               { return false }
func (s stubHV) Exists(hv.Spec) bool                                 { return false }
func (s stubHV) Create(context.Context, hv.Spec, func(string)) error { return nil }
func (s stubHV) Start(context.Context, hv.Spec) error                { return nil }
func (s stubHV) Finish(context.Context, hv.Spec) error               { return nil }

func press(m tea.Model, keys ...string) tea.Model {
	for _, k := range keys {
		var msg tea.KeyMsg
		switch k {
		case "enter":
			msg = tea.KeyMsg{Type: tea.KeyEnter}
		case "esc":
			msg = tea.KeyMsg{Type: tea.KeyEsc}
		case "down":
			msg = tea.KeyMsg{Type: tea.KeyDown}
		case "up":
			msg = tea.KeyMsg{Type: tea.KeyUp}
		case "right":
			msg = tea.KeyMsg{Type: tea.KeyRight}
		case "ctrl+u":
			msg = tea.KeyMsg{Type: tea.KeyCtrlU}
		default:
			msg = tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune(k)}
		}
		m, _ = m.Update(msg)
	}
	return m
}

func newTest(t *testing.T, ok bool) tea.Model {
	t.Helper()
	m := New(Options{BaseDir: t.TempDir(), LocalISO: "/x.iso"})
	var tm tea.Model = m
	tm, _ = tm.Update(detectMsg{{stubHV{true}, stubHV{true}.Detect(nil)}, {stubHV{ok}, stubHV{ok}.Detect(nil)}})
	return tm
}

func TestGuidedWalkThrough(t *testing.T) {
	m := newTest(t, false)
	if !strings.Contains(m.View(), "Make a new AuraDE VM") {
		t.Fatal("welcome screen")
	}
	m = press(m, "enter")
	v := m.View()
	if !strings.Contains(v, "Stub Hypervisor") || !strings.Contains(v, "ready") || !strings.Contains(v, "Stub is not installed.") {
		t.Fatalf("hypervisor screen:\n%s", v)
	}
	m = press(m, "enter")
	if !strings.Contains(m.View(), "Guided") || !strings.Contains(m.View(), "Express") {
		t.Fatal("mode screen")
	}
	m = press(m, "enter")
	if m.(Model).screen != sQuestions {
		t.Fatal("guided did not lead to the questions")
	}
	// Move to the computer name and make it bad.
	m = press(m, "down", "down", "down", "ctrl+u", "localhost", "enter")
	if !strings.Contains(m.View(), "cannot call itself localhost") {
		t.Fatalf("a bad hostname was not explained:\n%s", m.View())
	}
	m = press(m, "ctrl+u", "box", "enter")
	// Username: fill it in, then go through the two choices.
	m = press(m, "ctrl+u", "me", "enter", "enter", "right", "enter")
	if m.(Model).screen != sDesktop {
		t.Fatalf("questions did not finish, at screen %d:\n%s", m.(Model).screen, m.View())
	}
	// The desktop: 150%, Firefox, and the rest as they are.
	m = press(m, "right", "right", "right", "enter", "enter", "right", "enter", "enter", "enter", "enter", "enter", "enter")
	if m.(Model).screen != sMachine {
		t.Fatalf("desktop did not finish, at screen %d:\n%s", m.(Model).screen, m.View())
	}
	m = press(m, "enter", "enter", "enter", "enter", "enter")
	if m.(Model).screen != sReview {
		t.Fatalf("machine form did not finish:\n%s", m.View())
	}
	v = m.View()
	for _, want := range []string{"me on box", "encrypted", "your own ISO, not checked", "Stub Hypervisor", "150% size", "firefox", "a snapshot before every update"} {
		if !strings.Contains(v, want) {
			t.Errorf("review is missing %q:\n%s", want, v)
		}
	}
	p := m.(Model).buildPlan()
	if p.Mode != plan.Guided || p.Answers.Encrypt != "yes" || p.Answers.Hostname != "box" || p.Spec.MemoryMB < 4096 {
		t.Fatalf("plan %+v", p)
	}
	if a := p.Answers; a.DisplayScale != "150" || a.Apps != "firefox" || a.Profile != "auto" || a.AutoSnapshots != "yes" {
		t.Fatalf("desktop answers %+v", a)
	}
	if err := p.Answers.Validate(); err != nil {
		t.Fatal(err)
	}
	// Back from the machine reaches the desktop, with the choices kept.
	m = press(m, "esc", "esc")
	back := m.(Model)
	if back.screen != sDesktop || back.desktop.get("app:firefox") != "yes" {
		t.Fatalf("esc from the machine did not keep the desktop:\n%s", m.View())
	}
}

// Without Btrfs there is nothing to snapshot, so the question is not asked
// and the answer is no.
func TestNoSnapshotsWithoutBtrfs(t *testing.T) {
	f := desktopForm(false)
	if f.get("auto_snapshots") != "" {
		t.Fatal("the snapshot question was asked without Btrfs")
	}
	m := Model{desktop: f, desktopReady: true}
	a := answers.Answers{Filesystem: "ext4"}
	m.desktopAnswers(&a)
	if a.AutoSnapshots != "no" || a.Apps != "" || a.DisplayScale != "auto" {
		t.Fatalf("%+v", a)
	}
	if err := a.Validate(); err != nil {
		t.Fatal(err)
	}
}

func TestEscGoesBack(t *testing.T) {
	m := press(newTest(t, true), "enter", "enter", "enter", "esc")
	if m.(Model).screen != sMode {
		t.Fatal("esc from the questions did not go back to the mode")
	}
}

func TestExpressAsksForAPasswordAndNoEncryption(t *testing.T) {
	m := press(newTest(t, true), "enter", "enter", "down", "enter")
	if m.(Model).screen != sQuestions {
		t.Fatal("express did not lead to the questions")
	}
	v := m.View()
	if !strings.Contains(v, "Password again") || strings.Contains(v, "Encrypt") {
		t.Fatalf("express questions:\n%s", v)
	}
	// locale, keymap, timezone, hostname: keep; username, then two passwords
	// that differ, which must be refused.
	m = press(m, "enter", "enter", "enter", "enter", "ctrl+u", "me", "enter", " pw ", "enter", "other", "enter")
	if !strings.Contains(m.View(), "not the same") {
		t.Fatalf("different passwords were accepted:\n%s", m.View())
	}
	if strings.Contains(m.View(), " pw ") {
		t.Fatal("the password was shown")
	}
	m = press(m, "ctrl+u", " pw ", "enter", "enter")
	if m.(Model).screen != sDesktop {
		t.Fatalf("express questions did not finish:\n%s", m.View())
	}
	m = press(m, "enter", "enter", "enter", "enter", "enter", "enter", "enter", "enter")
	if m.(Model).screen != sMachine {
		t.Fatalf("express questions did not finish:\n%s", m.View())
	}
	mm := m.(Model)
	if got := mm.questions.get("password"); got != " pw " {
		t.Fatalf("the password was changed on the way: %q", got)
	}
	p := m.(Model).buildPlan()
	if p.Mode != plan.Express || p.Answers.Encrypt != "no" || p.Answers.Username != "me" {
		t.Fatalf("plan %+v", p)
	}
}

// A newer aurade-vm is mentioned on the welcome screen, and nothing is said
// when there is none.
func TestWelcomeMentionsANewerVersion(t *testing.T) {
	m := newTest(t, false)
	if strings.Contains(m.View(), "--update") {
		t.Fatal("an update was mentioned with none published")
	}
	next, _ := m.Update(updateMsg("9.9.9"))
	if !strings.Contains(next.View(), "aurade-vm 9.9.9 is out") {
		t.Fatalf("the newer version is not mentioned:\n%s", next.View())
	}
}

// On Arch the list ends with this computer itself, which explains the steps
// and hands over to the terminal; elsewhere it is not offered.
func TestExistingArchIsOfferedOnArch(t *testing.T) {
	if strings.Contains(press(newTest(t, true), "enter").View(), "This Arch computer") {
		t.Fatal("offered on a computer that is not Arch")
	}
	var m tea.Model = New(Options{BaseDir: t.TempDir(), LocalISO: "/x.iso", Arch: true})
	m, _ = m.Update(detectMsg{{stubHV{true}, stubHV{true}.Detect(nil)}})
	m = press(m, "enter")
	if !strings.Contains(m.View(), "This Arch computer, beside its desktop") {
		t.Fatalf("not offered on Arch:\n%s", m.View())
	}
	m = press(m, "down", "down", "enter")
	if m.(Model).screen != sArch || !strings.Contains(m.View(), "Nothing is erased") {
		t.Fatalf("arch screen:\n%s", m.View())
	}
	m = press(m, "esc")
	if m.(Model).screen != sHypervisor {
		t.Fatal("esc did not go back")
	}
	next, cmd := press(m, "enter").Update(tea.KeyMsg{Type: tea.KeyEnter})
	if !next.(Model).result.ExistingArch || cmd == nil {
		t.Fatal("going ahead did not hand over to the terminal")
	}
}
