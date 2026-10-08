// Package plan is what aurade-vm does once the questions are answered: get
// the ISO, write the answers disk, make the VM and start it. The TUI and the
// non-interactive mode both run it, so they cannot drift apart.
package plan

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/Cam396/aurade/vm/aurade-vm/internal/answers"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/hv"
	"github.com/Cam396/aurade/vm/aurade-vm/internal/release"
)

// Mode is how much the tool sets up before the installer starts.
type Mode string

const (
	// Guided fills the installer's questions in; the person still confirms.
	Guided Mode = "guided"
	// Plain only makes the VM; the installer asks everything.
	Plain Mode = "plain"
)

// Plan is everything needed to make and start one VM.
type Plan struct {
	Backend  hv.Backend
	Spec     hv.Spec // ISO is filled in by Run
	Answers  answers.Answers
	Mode     Mode
	BaseDir  string // where ISOs are kept; VMs go in BaseDir/<name>
	Tag      string // a release such as v1.1.2, or "" for the latest
	LocalISO string // use this ISO instead of downloading one
}

// Event reports progress to whoever is watching.
type Event struct {
	Step     string // a new step started
	Log      string // a line worth showing
	Done     int64  // download progress
	Total    int64
	Verified release.Verified
}

// VMDir is where the VM's own files go.
func VMDir(base, name string) string { return filepath.Join(base, name) }

// Run does it. Existing VMs are started rather than replaced.
func (p *Plan) Run(ctx context.Context, emit func(Event)) error {
	if emit == nil {
		emit = func(Event) {}
	}
	p.Spec.Dir = VMDir(p.BaseDir, p.Spec.Name)
	if p.Backend.Exists(p.Spec) {
		emit(Event{Step: "Starting the AuraDE VM you already have"})
		if err := p.Backend.Finish(ctx, p.Spec); err != nil {
			return fmt.Errorf("tidying up after the install: %w", err)
		}
		return p.Backend.Start(ctx, p.Spec)
	}
	if p.Mode == Guided {
		if err := p.Answers.Validate(); err != nil {
			return err
		}
	}
	if err := os.MkdirAll(p.BaseDir, 0o755); err != nil {
		return err
	}

	if p.LocalISO != "" {
		emit(Event{Step: "Using the ISO you gave", Verified: release.VerifiedLocal})
		abs, err := filepath.Abs(p.LocalISO)
		if err != nil {
			return err
		}
		if _, err := os.Stat(abs); err != nil {
			return fmt.Errorf("the ISO %s: %w", p.LocalISO, err)
		}
		p.Spec.ISO = abs
	} else {
		c := release.New()
		tag := p.Tag
		if tag == "" {
			emit(Event{Step: "Finding the latest AuraDE release"})
			var err error
			if tag, err = c.Latest(ctx); err != nil {
				return err
			}
		}
		emit(Event{Step: "Downloading AuraDE " + tag, Log: "Into " + p.BaseDir})
		iso, v, err := c.Fetch(ctx, tag, p.BaseDir, func(done, total int64) {
			emit(Event{Done: done, Total: total})
		})
		if err != nil {
			return err
		}
		emit(Event{Log: "Checked: the published SHA-256 and the AuraDE release key's signature", Verified: v})
		p.Spec.ISO = iso
	}

	if err := os.MkdirAll(p.Spec.Dir, 0o755); err != nil {
		return err
	}
	if p.Mode == Guided {
		emit(Event{Step: "Writing your answers for the installer"})
		p.Answers.Target = p.Backend.GuestDisk()
		path := filepath.Join(p.Spec.Dir, "aurade-answers.iso")
		if err := answers.WriteISO(path, p.Answers.File()); err != nil {
			return err
		}
		p.Spec.AnswersISO = path
	}
	emit(Event{Step: "Making the VM in " + p.Backend.Name()})
	if err := p.Backend.Create(ctx, p.Spec, func(s string) { emit(Event{Log: s}) }); err != nil {
		return err
	}
	emit(Event{Step: "Starting the VM"})
	return p.Backend.Start(ctx, p.Spec)
}
