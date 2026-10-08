package tui

import (
	"context"
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
	if !strings.Contains(m.View(), "Guided") || !strings.Contains(m.View(), "coming soon") {
		t.Fatal("mode screen")
	}
	// Express is not ready: Enter on it stays put.
	m = press(m, "down", "enter")
	if m.(Model).screen != sMode {
		t.Fatal("an unready mode was accepted")
	}
	m = press(m, "up", "enter")
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
	m = press(m, "ctrl+u", "me", "enter", "right", "enter", "enter")
	if m.(Model).screen != sMachine {
		t.Fatalf("questions did not finish, at screen %d:\n%s", m.(Model).screen, m.View())
	}
	m = press(m, "enter", "enter", "enter", "enter", "enter")
	if m.(Model).screen != sReview {
		t.Fatalf("machine form did not finish:\n%s", m.View())
	}
	v = m.View()
	for _, want := range []string{"me on box", "encrypted", "your own ISO, not checked", "Stub Hypervisor"} {
		if !strings.Contains(v, want) {
			t.Errorf("review is missing %q:\n%s", want, v)
		}
	}
	p := m.(Model).buildPlan()
	if p.Mode != plan.Guided || p.Answers.Encrypt != "yes" || p.Answers.Hostname != "box" || p.Spec.MemoryMB < 4096 {
		t.Fatalf("plan %+v", p)
	}
}

func TestEscGoesBack(t *testing.T) {
	m := press(newTest(t, true), "enter", "enter", "enter", "esc")
	if m.(Model).screen != sMode {
		t.Fatal("esc from the questions did not go back to the mode")
	}
}
