// Package update replaces aurade-vm with a newer published build.
//
// It trusts exactly what a first install trusts. get.sh and get.ps1 on the
// main branch carry the current version and a SHA-256 for every build, written
// there by build.sh, and a download that does not match its pin is deleted
// unrun, as the one-line installers do. When the release also has a signed
// SHA256SUMS, the release key's signature over it is checked too, and a bad
// one stops the update.
package update

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/Cam396/aurade/vm/aurade-vm/internal/release"
)

// Sources are where the pins and the builds come from. Replaceable for tests.
type Sources struct {
	Scripts  string // the folder holding get.sh and get.ps1
	Releases string // the folder holding one folder per release tag
	Key      string // the release key, armored
	HTTP     *http.Client
}

// Default is the published AuraDE repository.
func Default() Sources {
	return Sources{
		Scripts:  "https://raw.githubusercontent.com/" + release.Repo + "/main/vm/aurade-vm",
		Releases: "https://github.com/" + release.Repo + "/releases/download",
		Key:      "https://github.com/" + release.Repo + "/raw/main/pins/aurade-release.gpg",
		HTTP:     &http.Client{Timeout: 5 * time.Minute},
	}
}

// Pin is the newest published build for one computer.
type Pin struct {
	Version string
	SHA256  string // empty when nothing is published for this computer
}

var (
	shVersionRe = regexp.MustCompile(`(?m)^VERSION=([0-9]+\.[0-9]+\.[0-9]+)$`)
	psVersionRe = regexp.MustCompile(`(?m)^\$Version = '([0-9]+\.[0-9]+\.[0-9]+)'$`)
	hexRe       = regexp.MustCompile(`^[0-9a-f]{64}$`)
)

// ParsePins reads the pins block of get.sh or get.ps1 for goos/goarch.
func ParsePins(script []byte, goos, goarch string) (Pin, error) {
	s := string(script)
	var p Pin
	if goos == "windows" {
		m := psVersionRe.FindStringSubmatch(s)
		if m == nil {
			return p, errors.New("get.ps1 has no version")
		}
		p.Version = m[1]
		re := regexp.MustCompile(`(?m)^\s*'windows-` + regexp.QuoteMeta(goarch) + `' = '([0-9a-f]*)'$`)
		if m := re.FindStringSubmatch(s); m != nil {
			p.SHA256 = m[1]
		}
	} else {
		m := shVersionRe.FindStringSubmatch(s)
		if m == nil {
			return p, errors.New("get.sh has no version")
		}
		p.Version = m[1]
		re := regexp.MustCompile(`(?m)^PIN_` + regexp.QuoteMeta(goos) + `_` + regexp.QuoteMeta(goarch) + `=([0-9a-f]*)$`)
		if m := re.FindStringSubmatch(s); m != nil {
			p.SHA256 = m[1]
		}
	}
	if p.SHA256 != "" && !hexRe.MatchString(p.SHA256) {
		return p, errors.New("the published pin is not a SHA-256")
	}
	return p, nil
}

// Newer reports whether version a is newer than b. Anything that is not
// x.y.z, such as a development build's "dev", is never newer and never older.
func Newer(a, b string) bool {
	pa, oka := semver(a)
	pb, okb := semver(b)
	if !oka || !okb {
		return false
	}
	for i := range pa {
		if pa[i] != pb[i] {
			return pa[i] > pb[i]
		}
	}
	return false
}

func semver(v string) ([3]int, bool) {
	var out [3]int
	parts := strings.Split(strings.TrimPrefix(v, "v"), ".")
	if len(parts) != 3 {
		return out, false
	}
	for i, p := range parts {
		n, err := strconv.Atoi(p)
		if err != nil || n < 0 {
			return out, false
		}
		out[i] = n
	}
	return out, true
}

// BuildName is the published file name of a build.
func BuildName(version, goos, goarch string) string {
	name := "aurade-vm-" + version + "-" + goos + "-" + goarch
	if goos == "windows" {
		name += ".exe"
	}
	return name
}

func (s Sources) get(ctx context.Context, url string, limit int64) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	resp, err := s.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("%s: %s", url, resp.Status)
	}
	b, err := io.ReadAll(io.LimitReader(resp.Body, limit+1))
	if err != nil {
		return nil, err
	}
	if int64(len(b)) > limit {
		return nil, fmt.Errorf("%s is larger than expected", url)
	}
	return b, nil
}

// Latest reads the newest published build for this computer.
func (s Sources) Latest(ctx context.Context) (Pin, error) {
	script := "get.sh"
	if runtime.GOOS == "windows" {
		script = "get.ps1"
	}
	b, err := s.get(ctx, s.Scripts+"/"+script, 1<<20)
	if err != nil {
		return Pin{}, fmt.Errorf("could not find out the newest aurade-vm: %w", err)
	}
	return ParsePins(b, runtime.GOOS, runtime.GOARCH)
}

// Result says what Apply did.
type Result struct {
	From, To string
	Signed   bool // the release key's signature was checked too
}

// Apply downloads pin's build, checks it, and puts it where exe is. The old
// program is moved aside rather than overwritten, because Windows will not
// replace a running program's file but will rename it.
func (s Sources) Apply(ctx context.Context, current string, pin Pin, exe string) (Result, error) {
	r := Result{From: current, To: pin.Version}
	if pin.SHA256 == "" {
		return r, fmt.Errorf("no aurade-vm %s is published for %s-%s", pin.Version, runtime.GOOS, runtime.GOARCH)
	}
	name := BuildName(pin.Version, runtime.GOOS, runtime.GOARCH)
	base := s.Releases + "/aurade-vm-v" + pin.Version
	body, err := s.get(ctx, base+"/"+name, 256<<20)
	if err != nil {
		return r, fmt.Errorf("could not download aurade-vm %s: %w", pin.Version, err)
	}
	sum := sha256.Sum256(body)
	got := hex.EncodeToString(sum[:])
	if got != pin.SHA256 {
		return r, fmt.Errorf("the download does not match the SHA-256 published for it (expected %s, got %s), so it was not used", pin.SHA256, got)
	}
	// The signature, when the release has one.
	if sums, err := s.get(ctx, base+"/SHA256SUMS", 1<<20); err == nil {
		if sig, err := s.get(ctx, base+"/SHA256SUMS.sig", 1<<20); err == nil {
			key, err := s.get(ctx, s.Key, 1<<20)
			if err != nil {
				return r, fmt.Errorf("the release key could not be downloaded to check the signature: %w", err)
			}
			if err := verifySums(sums, sig, key, got, name); err != nil {
				return r, err
			}
			r.Signed = true
		}
	}
	return r, Replace(exe, body)
}

func verifySums(sums, sig, key []byte, sha, name string) error {
	tmp, err := os.CreateTemp("", "aurade-vm-sums-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err := tmp.Write(sums); err != nil {
		tmp.Close()
		return err
	}
	tmp.Close()
	if err := release.VerifySignature(tmp.Name(), sig, key); err != nil {
		return fmt.Errorf("the checksums are not signed by the AuraDE release key, so the update was not used")
	}
	if !bytes.Contains(sums, []byte(sha+"  "+name+"\n")) {
		return fmt.Errorf("the signed checksums do not list this build, so the update was not used")
	}
	return nil
}

// Replace puts body where exe is, keeping the old program as exe.old until the
// next start cleans it up.
func Replace(exe string, body []byte) error {
	dir := filepath.Dir(exe)
	tmp, err := os.CreateTemp(dir, ".aurade-vm-new-*")
	if err != nil {
		return fmt.Errorf("could not write next to %s: %w", exe, err)
	}
	if _, err := tmp.Write(body); err != nil {
		tmp.Close()
		os.Remove(tmp.Name())
		return err
	}
	tmp.Close()
	if err := os.Chmod(tmp.Name(), 0o755); err != nil {
		os.Remove(tmp.Name())
		return err
	}
	old := exe + ".old"
	os.Remove(old)
	if err := os.Rename(exe, old); err != nil {
		os.Remove(tmp.Name())
		return fmt.Errorf("could not move the running aurade-vm aside: %w", err)
	}
	if err := os.Rename(tmp.Name(), exe); err != nil {
		// Put the old one back, so there is still a program to run.
		os.Rename(old, exe)
		os.Remove(tmp.Name())
		return err
	}
	return nil
}

// Cleanup removes what a previous update moved aside. On Windows that file
// could not be deleted while it was running.
func Cleanup(exe string) { os.Remove(exe + ".old") }
