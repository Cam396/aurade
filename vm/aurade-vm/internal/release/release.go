// Package release finds an AuraDE release, downloads its ISO, and checks it
// against the published SHA-256 and the release key's signature.
package release

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
	"strings"
	"time"

	"github.com/ProtonMail/go-crypto/openpgp"
)

const (
	// Repo is where releases are published.
	Repo = "Cam396/aurade"
	// Fingerprint is the AuraDE release key. A signature from any other key
	// is refused, whatever key the release page offers.
	Fingerprint = "BC390DCF360B2184DBBF008B8B2AB2EFE667CB69"
)

var tagRe = regexp.MustCompile(`^v[0-9]+\.[0-9]+\.[0-9]+$`)

// Client talks to GitHub. Base is replaceable for tests.
type Client struct {
	HTTP *http.Client
	Base string // https://github.com
}

// New returns a client for github.com.
func New() *Client {
	return &Client{HTTP: &http.Client{Timeout: 0}, Base: "https://github.com"}
}

// Latest works out the newest release tag. The latest release page redirects
// to its tag, which avoids the API and its rate limit.
func (c *Client) Latest(ctx context.Context) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodHead, c.Base+"/"+Repo+"/releases/latest", nil)
	if err != nil {
		return "", err
	}
	hc := *c.HTTP
	hc.Timeout = 30 * time.Second
	resp, err := hc.Do(req)
	if err != nil {
		return "", fmt.Errorf("could not reach GitHub to find the latest release: %w", err)
	}
	resp.Body.Close()
	tag := resp.Request.URL.Path
	tag = tag[strings.LastIndex(tag, "/")+1:]
	if !tagRe.MatchString(tag) {
		return "", fmt.Errorf("could not work out the latest release (got %q)", tag)
	}
	return tag, nil
}

// ISOName is the published ISO file name for a tag.
func ISOName(tag string) string { return "aurade-" + tag + "-x86_64.iso" }

func (c *Client) assetURL(tag, name string) string {
	return c.Base + "/" + Repo + "/releases/download/" + tag + "/" + name
}

func (c *Client) small(ctx context.Context, url string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	hc := *c.HTTP
	hc.Timeout = 60 * time.Second
	resp, err := hc.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("%s: %s", url, resp.Status)
	}
	return io.ReadAll(io.LimitReader(resp.Body, 1<<20))
}

// Progress is called as the download moves. Total is -1 when unknown.
type Progress func(done, total int64)

// Fetch downloads the ISO for tag into dir, resuming a partial download, and
// checks it. It returns the ISO's path. A stamp file next to the ISO records
// that it was checked, so a second run starts straight away.
func (c *Client) Fetch(ctx context.Context, tag, dir string, progress Progress) (string, Verified, error) {
	name := ISOName(tag)
	iso := filepath.Join(dir, name)
	stamp := iso + ".checked"
	if b, err := os.ReadFile(stamp); err == nil {
		return iso, Verified(strings.TrimSpace(string(b))), nil
	}
	sumFile, err := c.small(ctx, c.assetURL(tag, name+".sha256"))
	if err != nil {
		return "", "", fmt.Errorf("could not get the ISO's published SHA-256: %w", err)
	}
	want := strings.Fields(string(sumFile))
	if len(want) == 0 || len(want[0]) != 64 {
		return "", "", errors.New("the published SHA-256 file is malformed")
	}
	part := iso + ".part"
	if err := c.download(ctx, c.assetURL(tag, name), part, progress); err != nil {
		return "", "", err
	}
	got, err := sha256File(part)
	if err != nil {
		return "", "", err
	}
	if got != strings.ToLower(want[0]) {
		os.Remove(part)
		return "", "", errors.New("the download does not match its published SHA-256; run this again to retry")
	}
	if err := os.Rename(part, iso); err != nil {
		return "", "", err
	}
	v := VerifiedSHA
	sig, errSig := c.small(ctx, c.assetURL(tag, name+".sig"))
	key, errKey := c.small(ctx, c.assetURL(tag, "aurade-repository.asc"))
	if errSig != nil || errKey != nil {
		return "", "", errors.New("the release's signature or key could not be downloaded, so the ISO cannot be trusted")
	}
	if err := VerifySignature(iso, sig, key); err != nil {
		os.Remove(iso)
		return "", "", err
	}
	v = VerifiedSignature
	_ = os.WriteFile(stamp, []byte(string(v)+"\n"), 0o644)
	return iso, v, nil
}

// Superseded lists the release ISOs in dir other than keep that Fetch
// downloaded and checked, which is what its stamp beside each one says. An
// ISO put there any other way has no stamp and is never listed.
func Superseded(dir, keep string) []string {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	var out []string
	for _, e := range entries {
		name := e.Name()
		if e.IsDir() || !strings.HasPrefix(name, "aurade-") || !strings.HasSuffix(name, "-x86_64.iso") {
			continue
		}
		iso := filepath.Join(dir, name)
		if iso == keep {
			continue
		}
		if _, err := os.Stat(iso + ".checked"); err != nil {
			continue
		}
		out = append(out, iso)
	}
	return out
}

// Verified says how much was checked.
type Verified string

const (
	VerifiedSHA       Verified = "sha256"
	VerifiedSignature Verified = "sha256+signature"
	VerifiedLocal     Verified = "local file, not checked"
)

func (c *Client) download(ctx context.Context, url, part string, progress Progress) error {
	var have int64
	if st, err := os.Stat(part); err == nil {
		have = st.Size()
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	if have > 0 {
		req.Header.Set("Range", fmt.Sprintf("bytes=%d-", have))
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return fmt.Errorf("download failed: %w", err)
	}
	defer resp.Body.Close()
	flags := os.O_CREATE | os.O_WRONLY
	switch resp.StatusCode {
	case http.StatusPartialContent:
		flags |= os.O_APPEND
	case http.StatusOK:
		have = 0
		flags |= os.O_TRUNC
	case http.StatusRequestedRangeNotSatisfiable:
		return nil // already complete; the checksum decides
	default:
		return fmt.Errorf("download failed: %s", resp.Status)
	}
	total := int64(-1)
	if resp.ContentLength >= 0 {
		total = have + resp.ContentLength
	}
	f, err := os.OpenFile(part, flags, 0o644)
	if err != nil {
		return err
	}
	defer f.Close()
	buf := make([]byte, 1<<20)
	done := have
	last := time.Time{}
	for {
		n, rerr := resp.Body.Read(buf)
		if n > 0 {
			if _, err := f.Write(buf[:n]); err != nil {
				return err
			}
			done += int64(n)
			if progress != nil && time.Since(last) > 100*time.Millisecond {
				progress(done, total)
				last = time.Now()
			}
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			return fmt.Errorf("download interrupted (run again to resume): %w", rerr)
		}
	}
	if progress != nil {
		progress(done, total)
	}
	return nil
}

func sha256File(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// VerifySignature checks a detached signature on file, made by the key with
// the pinned fingerprint. The key file may hold other keys; only the pinned
// one is used.
func VerifySignature(file string, sig, armoredKey []byte) error {
	ring, err := openpgp.ReadArmoredKeyRing(bytes.NewReader(armoredKey))
	if err != nil {
		return fmt.Errorf("the release key could not be read: %w", err)
	}
	var pinned openpgp.EntityList
	for _, e := range ring {
		if strings.EqualFold(hex.EncodeToString(e.PrimaryKey.Fingerprint), Fingerprint) {
			pinned = append(pinned, e)
		}
	}
	if len(pinned) == 0 {
		return fmt.Errorf("the release page does not offer the AuraDE release key %s", Fingerprint)
	}
	f, err := os.Open(file)
	if err != nil {
		return err
	}
	defer f.Close()
	check := openpgp.CheckDetachedSignature
	if bytes.HasPrefix(bytes.TrimSpace(sig), []byte("-----BEGIN")) {
		check = openpgp.CheckArmoredDetachedSignature
	}
	if _, err := check(pinned, f, bytes.NewReader(sig), nil); err != nil {
		return fmt.Errorf("the ISO is not signed by the AuraDE release key %s", Fingerprint)
	}
	return nil
}
