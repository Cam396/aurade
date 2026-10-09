// Package plan is what aurade-vm does once the questions are answered: get
// the ISO, write the answers disk, make the VM and start it. The TUI and the
// non-interactive mode both run it, so they cannot drift apart.
package plan

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

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
	// Express installs from the answers with nothing asked in the VM, then
	// restarts into AuraDE. The installer only does this in a VM, on a blank
	// disk, and falls back to Guided if anything is missing.
	Express Mode = "express"
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
	// PasswordHash is the account's crypt(3) hash, for Express. The
	// password itself never reaches the plan.
	PasswordHash string
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
	// A VM made earlier keeps its own settings; only the name was asked for.
	// One with no record is from an early build that recorded nothing, and
	// had always been started.
	rec := hv.Record{Backend: p.Backend.ID(), Started: true}
	for _, r := range hv.Existing(p.BaseDir) {
		if r.Spec.Name == p.Spec.Name && r.Backend == p.Backend.ID() && r.Spec.MemoryMB > 0 {
			p.Spec, rec = r.Spec, r
		}
	}
	if p.Backend.Exists(p.Spec) {
		if p.Backend.Running(ctx, p.Spec) {
			emit(Event{Step: "Your AuraDE VM is already running"})
			return p.Backend.Start(ctx, p.Spec)
		}
		emit(Event{Step: "Starting the AuraDE VM you already have"})
		if rec.Started {
			if err := p.Backend.Finish(ctx, p.Spec); err != nil {
				return fmt.Errorf("tidying up after the install: %w", err)
			}
		}
		if err := p.Backend.Start(ctx, p.Spec); err != nil {
			return err
		}
		return p.markStarted(rec)
	}
	switch p.Mode {
	case Guided, Express:
		if err := p.Answers.Validate(); err != nil {
			return err
		}
	}
	if p.Mode == Express {
		switch {
		case p.Answers.Username == "":
			return fmt.Errorf("an express install needs a username")
		case p.PasswordHash == "":
			return fmt.Errorf("an express install needs a password")
		}
		// A passphrase cannot be typed into an install nobody watches.
		p.Answers.Encrypt = "no"
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
		p.tidyOldISOs(iso, emit)
	}

	if err := os.MkdirAll(p.Spec.Dir, 0o755); err != nil {
		return err
	}
	if p.Mode == Guided || p.Mode == Express {
		emit(Event{Step: "Writing your answers for the installer"})
		p.Answers.Target = p.Backend.GuestDisk()
		path := filepath.Join(p.Spec.Dir, hv.AnswersFile)
		files := []answers.File{{Name: "answers.txt", Content: p.Answers.File()}}
		if p.Mode == Express {
			files = append(files, answers.File{Name: "express"},
				answers.File{Name: "password.hash", Content: []byte(p.PasswordHash + "\n")})
		}
		if err := answers.WriteISO(path, files...); err != nil {
			return err
		}
		p.Spec.AnswersISO = path
	}
	emit(Event{Step: "Making the VM in " + p.Backend.Name()})
	if err := p.Backend.Create(ctx, p.Spec, func(s string) { emit(Event{Log: s}) }); err != nil {
		return err
	}
	if err := hv.WriteRecord(hv.Record{Backend: p.Backend.ID(), Spec: p.Spec}); err != nil {
		return err
	}
	emit(Event{Step: "Starting the VM"})
	if err := p.Backend.Start(ctx, p.Spec); err != nil {
		return err
	}
	return p.markStarted(hv.Record{Backend: p.Backend.ID(), Spec: p.Spec})
}

// tidyOldISOs removes the releases downloaded here before this one, nearly
// 2 GB each, once this one has been checked. One that a VM here still starts
// from is kept, and so is any ISO this tool did not download itself.
func (p *Plan) tidyOldISOs(current string, emit func(Event)) {
	vms := hv.Existing(p.BaseDir)
	for _, old := range release.Superseded(p.BaseDir, current) {
		if isoInUse(vms, old) {
			continue
		}
		var size int64
		if fi, err := os.Stat(old); err == nil {
			size = fi.Size()
		}
		if err := os.Remove(old); err != nil {
			continue
		}
		os.Remove(old + ".checked")
		os.Remove(old + ".part")
		emit(Event{Log: fmt.Sprintf("Removed %s (%.1f GB), an older AuraDE that no VM here starts from",
			filepath.Base(old), float64(size)/1e9)})
	}
}

// isoInUse reports whether any of the VMs starts from iso. The name is what
// is compared, ignoring case, so a doubt keeps the file. A VM from an early
// build recorded nothing, so its .vmx is read, and one that cannot be read
// keeps every ISO.
func isoInUse(vms []hv.Record, iso string) bool {
	name := filepath.Base(iso)
	for _, r := range vms {
		if r.Spec.ISO != "" {
			if strings.EqualFold(filepath.Base(r.Spec.ISO), name) {
				return true
			}
			continue
		}
		b, err := os.ReadFile(filepath.Join(r.Spec.Dir, r.Spec.Name+".vmx"))
		if err != nil || bytes.Contains(bytes.ToLower(b), []byte(strings.ToLower(name))) {
			return true
		}
	}
	return false
}

func (p *Plan) markStarted(r hv.Record) error {
	if r.Started || r.Spec.Dir == "" {
		return nil
	}
	r.Started = true
	return hv.WriteRecord(r)
}
