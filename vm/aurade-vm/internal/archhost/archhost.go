// Package archhost installs AuraDE beside the desktop of an Arch Linux
// computer, with no virtual machine: the steps of docs/existing-arch.md, done
// for the person and shown as they run.
//
// Nothing is erased. AuraDE becomes one more session at the login screen,
// and pacman asks before it installs anything.
package archhost

import (
	"bufio"
	"bytes"
	"context"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"time"

	"github.com/ProtonMail/go-crypto/openpgp"

	"github.com/Cam396/aurade/vm/aurade-vm/internal/release"
)

const (
	// KeyURL is the release key, as the doc fetches it.
	KeyURL = "https://raw.githubusercontent.com/" + release.Repo + "/main/pins/aurade-release.gpg"
	// RepoServer is the published AuraDE repository.
	RepoServer = "https://github.com/" + release.Repo + "/releases/download/repo-x86_64"
)

// IsArch reports whether os-release names Arch Linux itself. Derivatives are
// left out: the doc was proven on Arch, and their pacman.conf and keyring
// differ in ways it does not cover.
func IsArch(osRelease string) bool {
	for _, line := range strings.Split(osRelease, "\n") {
		if strings.TrimSpace(line) == "ID=arch" || strings.TrimSpace(line) == `ID="arch"` {
			return true
		}
	}
	return false
}

// Detect reads this computer's os-release.
func Detect() bool {
	b, err := os.ReadFile("/etc/os-release")
	return err == nil && IsArch(string(b))
}

// HasRepo reports whether pacman.conf already has an [aurade] section.
func HasRepo(pacmanConf string) bool {
	sc := bufio.NewScanner(strings.NewReader(pacmanConf))
	for sc.Scan() {
		if strings.TrimSpace(sc.Text()) == "[aurade]" {
			return true
		}
	}
	return false
}

// RepoBlock is what is added to pacman.conf.
const RepoBlock = "\n[aurade]\nServer = " + RepoServer + "\n"

// CheckKey makes sure the armored key holds the pinned release key, so a
// changed file on the way here is refused before pacman is asked to trust it.
func CheckKey(armored []byte) error {
	ring, err := openpgp.ReadArmoredKeyRing(bytes.NewReader(armored))
	if err != nil {
		ring, err = openpgp.ReadKeyRing(bytes.NewReader(armored))
		if err != nil {
			return fmt.Errorf("the release key could not be read: %w", err)
		}
	}
	for _, e := range ring {
		if strings.EqualFold(hex.EncodeToString(e.PrimaryKey.Fingerprint), release.Fingerprint) {
			return nil
		}
	}
	return fmt.Errorf("the downloaded key is not the AuraDE release key %s", release.Fingerprint)
}

// Step is one command, with what it is for.
type Step struct {
	Why   string
	Args  []string
	Stdin string // fed to the command, for the pacman.conf lines
}

// Steps are the commands for the doc's steps 1 and 2. keyFile is the checked
// key on disk. sudo is prepended unless this already runs as root.
func Steps(keyFile string, pacmanConf string, root, noConfirm bool) []Step {
	sudo := func(args ...string) []string {
		if root {
			return args
		}
		return append([]string{"sudo"}, args...)
	}
	steps := []Step{
		{Why: "Trust the AuraDE release key", Args: sudo("pacman-key", "--add", keyFile)},
		{Why: "Sign it locally, so pacman accepts AuraDE's packages", Args: sudo("pacman-key", "--lsign-key", release.Fingerprint)},
	}
	if !HasRepo(pacmanConf) {
		steps = append(steps, Step{Why: "Add the AuraDE repository to /etc/pacman.conf", Args: sudo("tee", "-a", "/etc/pacman.conf"), Stdin: RepoBlock})
	}
	install := sudo("pacman", "-Syu", "aurade")
	if noConfirm {
		install = append(install, "--noconfirm")
	}
	return append(steps, Step{Why: "Update Arch and install AuraDE (about 300 MiB to download)", Args: install})
}

// Options control Run.
type Options struct {
	DryRun     bool // print the commands instead of running them
	NoConfirm  bool // let pacman go ahead without asking
	Out        io.Writer
	HTTP       *http.Client
	KeyURL     string
	PacmanConf string
}

// Run does the doc's steps. The commands run attached to this terminal, so
// sudo and pacman ask their own questions.
func Run(ctx context.Context, o Options) error {
	if o.Out == nil {
		o.Out = os.Stdout
	}
	if o.HTTP == nil {
		o.HTTP = &http.Client{Timeout: time.Minute}
	}
	if o.KeyURL == "" {
		o.KeyURL = KeyURL
	}
	if o.PacmanConf == "" {
		o.PacmanConf = "/etc/pacman.conf"
	}
	say := func(f string, a ...any) { fmt.Fprintf(o.Out, "==> "+f+"\n", a...) }

	say("Downloading the AuraDE release key")
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, o.KeyURL, nil)
	if err != nil {
		return err
	}
	resp, err := o.HTTP.Do(req)
	if err != nil {
		return fmt.Errorf("could not download the release key: %w", err)
	}
	key, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	resp.Body.Close()
	if err != nil {
		return err
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("could not download the release key: %s", resp.Status)
	}
	if err := CheckKey(key); err != nil {
		return err
	}
	say("It is the release key, %s", release.Fingerprint)
	f, err := os.CreateTemp("", "aurade-release-*.gpg")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err := f.Write(key); err != nil {
		f.Close()
		return err
	}
	f.Close()

	conf, err := os.ReadFile(o.PacmanConf)
	if err != nil {
		return fmt.Errorf("could not read %s: %w", o.PacmanConf, err)
	}
	if HasRepo(string(conf)) {
		say("%s already has the AuraDE repository", o.PacmanConf)
	}
	for _, st := range Steps(f.Name(), string(conf), os.Geteuid() == 0, o.NoConfirm) {
		say("%s", st.Why)
		fmt.Fprintf(o.Out, "    %s\n", strings.Join(st.Args, " "))
		if o.DryRun {
			continue
		}
		cmd := exec.CommandContext(ctx, st.Args[0], st.Args[1:]...)
		cmd.Stdout, cmd.Stderr = o.Out, os.Stderr
		if st.Stdin != "" {
			cmd.Stdin = strings.NewReader(st.Stdin)
		} else {
			cmd.Stdin = os.Stdin
		}
		if err := cmd.Run(); err != nil {
			return fmt.Errorf("%s did not finish (%w). Nothing after it was run", strings.Join(st.Args, " "), err)
		}
	}
	if o.DryRun {
		say("Nothing was changed: that was a dry run")
		return nil
	}
	fmt.Fprint(o.Out, "\nAuraDE is installed beside your desktop. Sign out, choose the AuraDE\n"+
		"session at your login screen, and sign in as yourself. To go back, sign\n"+
		"out and choose your old session. sudo pacman -Rns aurade removes it.\n")
	return nil
}
