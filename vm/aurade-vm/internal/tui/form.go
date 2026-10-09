package tui

import (
	"strings"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
)

type fieldKind int

const (
	textField fieldKind = iota
	choiceField
)

// field is one question on a form screen. Text fields are typed; choice
// fields cycle with the arrow keys, which is quicker than typing "btrfs".
type field struct {
	key      string
	label    string
	help     string
	kind     fieldKind
	input    textinput.Model
	choices  []string
	labels   []string // what to show for each choice, if not the choice itself
	idx      int
	validate func(string) error
	err      string
	hidden   bool
}

func newText(key, label, help, value string, validate func(string) error) *field {
	in := textinput.New()
	in.SetValue(value)
	in.CharLimit = 64
	in.Prompt = ""
	return &field{key: key, label: label, help: help, kind: textField, input: in, validate: validate}
}

// secret hides what is typed.
func (f *field) secret() {
	f.input.EchoMode = textinput.EchoPassword
	f.input.EchoCharacter = '•'
	f.input.CharLimit = 256
	f.hidden = true
}

func newChoice(key, label, help string, choices, labels []string, current string) *field {
	f := &field{key: key, label: label, help: help, kind: choiceField, choices: choices, labels: labels}
	for i, c := range choices {
		if c == current {
			f.idx = i
		}
	}
	return f
}

func (f *field) value() string {
	if f.kind == choiceField {
		return f.choices[f.idx]
	}
	if f.hidden {
		// A password is exactly what was typed, spaces and all.
		return f.input.Value()
	}
	return strings.TrimSpace(f.input.Value())
}

func (f *field) shown() string {
	if f.kind == choiceField {
		if f.labels != nil {
			return f.labels[f.idx]
		}
		return f.choices[f.idx]
	}
	if f.hidden {
		return strings.Repeat("•", len([]rune(f.input.Value())))
	}
	return f.input.Value()
}

func (f *field) check() bool {
	f.err = ""
	if f.validate != nil {
		if err := f.validate(f.value()); err != nil {
			// The shared checks name their field ("time zone: ..."); here the
			// label is right above, so only the reason is shown.
			msg := err.Error()
			if i := strings.Index(msg, ": "); i >= 0 && i < 20 {
				msg = msg[i+2:]
			}
			f.err = msg
			return false
		}
	}
	return true
}

// form is a list of fields with one focused.
type form struct {
	fields []*field
	focus  int
}

func (fm *form) get(key string) string {
	for _, f := range fm.fields {
		if f.key == key {
			return f.value()
		}
	}
	return ""
}

func (fm *form) setFocus(i int) {
	if len(fm.fields) == 0 {
		return
	}
	if i < 0 {
		i = len(fm.fields) - 1
	}
	if i >= len(fm.fields) {
		i = 0
	}
	for j, f := range fm.fields {
		if f.kind == textField {
			if j == i {
				f.input.Focus()
			} else {
				f.input.Blur()
			}
		}
	}
	fm.focus = i
}

// valid checks every field and moves to the first bad one.
func (fm *form) valid() bool {
	first := -1
	for i, f := range fm.fields {
		if !f.check() && first < 0 {
			first = i
		}
	}
	if first >= 0 {
		fm.setFocus(first)
		return false
	}
	return true
}

// update handles movement and editing. It reports whether Enter was pressed
// on the last field, which is how a form is finished.
func (fm *form) update(msg tea.Msg) (tea.Cmd, bool) {
	f := fm.fields[fm.focus]
	if k, ok := msg.(tea.KeyMsg); ok {
		switch k.String() {
		case "up", "shift+tab":
			f.check()
			fm.setFocus(fm.focus - 1)
			return nil, false
		case "down", "tab":
			f.check()
			fm.setFocus(fm.focus + 1)
			return nil, false
		case "enter":
			if !f.check() {
				return nil, false
			}
			if fm.focus == len(fm.fields)-1 {
				return nil, true
			}
			fm.setFocus(fm.focus + 1)
			return nil, false
		case "left", "h":
			if f.kind == choiceField {
				f.idx = (f.idx - 1 + len(f.choices)) % len(f.choices)
				return nil, false
			}
		case "right", "l", " ":
			if f.kind == choiceField {
				f.idx = (f.idx + 1) % len(f.choices)
				return nil, false
			}
		}
	}
	if f.kind == textField {
		var cmd tea.Cmd
		f.input, cmd = f.input.Update(msg)
		f.err = ""
		return cmd, false
	}
	return nil, false
}
