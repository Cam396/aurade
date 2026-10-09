package hv

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
)

// RecordFile sits in each VM's folder and says which hypervisor made it, so a
// later run starts it with the same one.
const RecordFile = "aurade-vm.json"

// Record is what is kept about a VM between runs.
type Record struct {
	Backend string `json:"backend"`
	Spec    Spec   `json:"spec"`
	// Started is set once the VM has been started; until then the answers
	// disk has not been read, and a later run keeps it.
	Started bool `json:"started"`
}

// WriteRecord saves r in the VM's folder.
func WriteRecord(r Record) error {
	b, err := json.MarshalIndent(r, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(r.Spec.Dir, RecordFile), append(b, '\n'), 0o644)
}

// Existing lists the VMs made in base, newest record format first. A folder
// with a .vmx and no record was made by an early build, which only knew
// VMware.
func Existing(base string) []Record {
	entries, err := os.ReadDir(base)
	if err != nil {
		return nil
	}
	var out []Record
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		dir := filepath.Join(base, e.Name())
		if b, err := os.ReadFile(filepath.Join(dir, RecordFile)); err == nil {
			var r Record
			if json.Unmarshal(b, &r) == nil && r.Backend != "" {
				r.Spec.Dir = dir
				if r.Spec.Name == "" {
					r.Spec.Name = e.Name()
				}
				out = append(out, r)
				continue
			}
		}
		if _, err := os.Stat(filepath.Join(dir, e.Name()+".vmx")); err == nil {
			out = append(out, Record{Backend: "vmware", Spec: Spec{Name: e.Name(), Dir: dir}})
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Spec.Name < out[j].Spec.Name })
	return out
}
