package answers

import (
	"encoding/binary"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"
)

// Label is the volume name the live image looks for. It has to match
// AURADE_ANSWERS_DEVICE in aurade-installer-autostart.
const Label = "AURADE_ANS"

const sector = 2048

// File is one file on the answers disk. Name is how Linux shows it: lower
// case, at most 30 characters, letters, digits, dots and underscores.
type File struct {
	Name    string
	Content []byte
}

// WriteISO writes a minimal ISO 9660 image holding the files. Every
// hypervisor can attach an ISO as a second optical drive, so this one format
// covers all of them.
func WriteISO(path string, files ...File) error {
	img := BuildISO(time.Now().UTC(), files...)
	if err := os.WriteFile(path, img, 0o600); err != nil {
		return fmt.Errorf("writing the answers disk: %w", err)
	}
	return nil
}

// BuildISO lays the image out as: system area (0-15), primary volume
// descriptor (16), terminator (17), the two path tables (18, 19), the root
// directory (20) and the files, each from a sector of its own, after it.
//
// Names are stored upper case with the ";1" version, which Linux shows in
// lower case without it; a name with no dot is stored with a trailing one,
// which Linux drops again.
func BuildISO(now time.Time, files ...File) []byte {
	const (
		pvdAt, termAt, lPathAt, mPathAt, rootAt, fileAt = 16, 17, 18, 19, 20, 21
	)
	sort.Slice(files, func(i, j int) bool { return isoName(files[i].Name) < isoName(files[j].Name) })
	extents := make([]int, len(files))
	next := fileAt
	for i, f := range files {
		extents[i] = next
		n := (len(f.Content) + sector - 1) / sector
		if n == 0 {
			n = 1
		}
		next += n
	}
	total := next
	img := make([]byte, total*sector)

	both32 := func(b []byte, v uint32) {
		binary.LittleEndian.PutUint32(b[0:4], v)
		binary.BigEndian.PutUint32(b[4:8], v)
	}
	both16 := func(b []byte, v uint16) {
		binary.LittleEndian.PutUint16(b[0:2], v)
		binary.BigEndian.PutUint16(b[2:4], v)
	}
	pad := func(b []byte, s string) {
		for i := range b {
			b[i] = ' '
		}
		copy(b, s)
	}
	recDate := []byte{byte(now.Year() - 1900), byte(now.Month()), byte(now.Day()),
		byte(now.Hour()), byte(now.Minute()), byte(now.Second()), 0}
	decDate := []byte(now.Format("20060102150405") + "00\x00")
	noDate := []byte("0000000000000000\x00")

	dirRecord := func(name []byte, extent, size uint32, dir bool) []byte {
		n := 33 + len(name)
		if n%2 == 1 {
			n++
		}
		r := make([]byte, n)
		r[0] = byte(n)
		both32(r[2:10], extent)
		both32(r[10:18], size)
		copy(r[18:25], recDate)
		if dir {
			r[25] = 2
		}
		both16(r[28:32], 1)
		r[32] = byte(len(name))
		copy(r[33:], name)
		return r
	}

	// Primary volume descriptor.
	p := img[pvdAt*sector : (pvdAt+1)*sector]
	p[0] = 1
	copy(p[1:6], "CD001")
	p[6] = 1
	pad(p[8:40], "")
	pad(p[40:72], Label)
	both32(p[80:88], uint32(total))
	both16(p[120:124], 1)
	both16(p[124:128], 1)
	both16(p[128:132], sector)
	both32(p[132:140], 10)
	binary.LittleEndian.PutUint32(p[140:144], lPathAt)
	binary.BigEndian.PutUint32(p[148:152], mPathAt)
	copy(p[156:190], dirRecord([]byte{0}, rootAt, sector, true))
	pad(p[190:318], "")
	pad(p[318:446], "")
	pad(p[446:574], "")
	pad(p[574:702], "AURADE-VM")
	pad(p[702:739], "")
	pad(p[739:776], "")
	pad(p[776:813], "")
	copy(p[813:830], decDate)
	copy(p[830:847], decDate)
	copy(p[847:864], noDate)
	copy(p[864:881], noDate)
	p[881] = 1

	// Set terminator.
	t := img[termAt*sector:]
	t[0] = 255
	copy(t[1:6], "CD001")
	t[6] = 1

	// Path tables: one entry, the root.
	l := img[lPathAt*sector:]
	l[0] = 1
	binary.LittleEndian.PutUint32(l[2:6], rootAt)
	binary.LittleEndian.PutUint16(l[6:8], 1)
	m := img[mPathAt*sector:]
	m[0] = 1
	binary.BigEndian.PutUint32(m[2:6], rootAt)
	binary.BigEndian.PutUint16(m[6:8], 1)

	// Root directory: itself, its parent (itself again), and the files, in
	// name order as the standard asks.
	records := [][]byte{dirRecord([]byte{0}, rootAt, sector, true), dirRecord([]byte{1}, rootAt, sector, true)}
	for i, f := range files {
		records = append(records, dirRecord([]byte(isoName(f.Name)), uint32(extents[i]), uint32(len(f.Content)), false))
	}
	off := rootAt * sector
	for _, r := range records {
		copy(img[off:], r)
		off += len(r)
	}
	for i, f := range files {
		copy(img[extents[i]*sector:], f.Content)
	}
	return img
}

func isoName(name string) string {
	n := strings.ToUpper(name)
	if !strings.Contains(n, ".") {
		n += "."
	}
	return n + ";1"
}
