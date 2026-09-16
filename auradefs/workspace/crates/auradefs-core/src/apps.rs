//! Which programs exist, which one opens a file, and starting it.
//!
//! Everything here is the freedesktop desktop entry and mime apps specs read
//! directly. That matters for a file manager: Open With has to show the same
//! list the rest of the desktop shows, and Set as default has to be the change
//! every other program then honours, not a private preference.
//!
//! A launched program is detached deliberately. The file manager is a long
//! lived service; a text editor started from it must not die when it restarts,
//! and must not leave a zombie behind either.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use crate::error::{Error, Result};
use crate::mime::{config_dirs, data_dirs, xdg_config_home};

/// One `.desktop` file, reduced to what a file manager uses.
#[derive(Debug, Clone, Default)]
pub struct DesktopEntry {
    /// The desktop id: the path under `applications/` with separators turned
    /// into dashes, which is what every association file refers to.
    pub id: String,
    pub path: PathBuf,
    pub name: String,
    pub generic_name: Option<String>,
    pub comment: Option<String>,
    pub icon: Option<String>,
    pub exec: Option<String>,
    pub try_exec: Option<String>,
    pub path_dir: Option<PathBuf>,
    pub terminal: bool,
    pub no_display: bool,
    pub hidden: bool,
    pub mime_types: Vec<String>,
    pub categories: Vec<String>,
    pub keywords: Vec<String>,
    /// Extra verbs the program declares, as (action id, name, exec).
    pub actions: Vec<DesktopAction>,
}

#[derive(Debug, Clone, Default)]
pub struct DesktopAction {
    pub id: String,
    pub name: String,
    pub exec: Option<String>,
    pub icon: Option<String>,
}

impl DesktopEntry {
    /// Read one desktop file. `id` is what the caller derived from its
    /// location, because the file itself does not carry it.
    pub fn parse(path: &Path, id: &str, text: &str) -> Option<DesktopEntry> {
        let groups = parse_groups(text);
        let main = groups.get("Desktop Entry")?;
        if main.get("Type").map(|t| t != "Application").unwrap_or(false) {
            return None;
        }
        let mut entry = DesktopEntry {
            id: id.to_string(),
            path: path.to_path_buf(),
            name: main.get("Name").cloned().unwrap_or_else(|| id.to_string()),
            generic_name: main.get("GenericName").cloned(),
            comment: main.get("Comment").cloned(),
            icon: main.get("Icon").cloned(),
            exec: main.get("Exec").cloned(),
            try_exec: main.get("TryExec").cloned(),
            path_dir: main.get("Path").map(PathBuf::from),
            terminal: main.get("Terminal").map(|v| v == "true").unwrap_or(false),
            no_display: main.get("NoDisplay").map(|v| v == "true").unwrap_or(false),
            hidden: main.get("Hidden").map(|v| v == "true").unwrap_or(false),
            mime_types: split_list(main.get("MimeType")),
            categories: split_list(main.get("Categories")),
            keywords: split_list(main.get("Keywords")),
            actions: Vec::new(),
        };
        for id in split_list(main.get("Actions")) {
            if let Some(g) = groups.get(&format!("Desktop Action {id}")) {
                entry.actions.push(DesktopAction {
                    name: g.get("Name").cloned().unwrap_or_else(|| id.clone()),
                    exec: g.get("Exec").cloned(),
                    icon: g.get("Icon").cloned(),
                    id,
                });
            }
        }
        Some(entry)
    }

    /// Would this entry actually run? `TryExec` naming a program that is not
    /// installed is the spec's way of saying no, and showing it in Open With
    /// would offer a menu row that does nothing.
    pub fn is_runnable(&self) -> bool {
        if self.hidden || self.exec.is_none() {
            return false;
        }
        match &self.try_exec {
            Some(t) => which(t).is_some(),
            None => true,
        }
    }

    /// The argv to run, with the field codes filled in.
    pub fn command(&self, paths: &[PathBuf]) -> Result<Vec<String>> {
        let exec = self
            .exec
            .as_deref()
            .ok_or_else(|| Error::BadRequest(format!("{} has no Exec line", self.id)))?;
        expand(exec, paths, self)
    }

    /// The argv for one of the extra verbs the program declares.
    pub fn action_command(&self, action_id: &str, paths: &[PathBuf]) -> Result<Vec<String>> {
        let action = self
            .actions
            .iter()
            .find(|a| a.id == action_id)
            .ok_or_else(|| Error::NotFound(format!("{}: action {action_id}", self.id)))?;
        let exec = action
            .exec
            .as_deref()
            .ok_or_else(|| Error::BadRequest(format!("{action_id} has no Exec line")))?;
        expand(exec, paths, self)
    }
}

fn split_list(value: Option<&String>) -> Vec<String> {
    value
        .map(|v| {
            v.split(';')
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default()
}

/// A desktop file is an ini file with one wrinkle: localised keys, written
/// `Name[de]`. The unlocalised key is what a service wants, so the bracketed
/// forms are dropped rather than merged.
fn parse_groups(text: &str) -> HashMap<String, HashMap<String, String>> {
    let mut groups: HashMap<String, HashMap<String, String>> = HashMap::new();
    let mut current = String::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some(name) = line.strip_prefix('[').and_then(|l| l.strip_suffix(']')) {
            current = name.to_string();
            groups.entry(current.clone()).or_default();
            continue;
        }
        let Some((key, value)) = line.split_once('=') else { continue };
        let key = key.trim();
        if key.contains('[') {
            continue;
        }
        groups
            .entry(current.clone())
            .or_default()
            .insert(key.to_string(), unescape(value.trim()));
    }
    groups
}

/// The desktop entry escapes, which are not the shell's.
fn unescape(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    let mut chars = value.chars();
    while let Some(c) = chars.next() {
        if c != '\\' {
            out.push(c);
            continue;
        }
        match chars.next() {
            Some('s') => out.push(' '),
            Some('n') => out.push('\n'),
            Some('t') => out.push('\t'),
            Some('r') => out.push('\r'),
            Some('\\') => out.push('\\'),
            Some(other) => {
                out.push('\\');
                out.push(other);
            }
            None => out.push('\\'),
        }
    }
    out
}

/// Split an `Exec` line the way the spec says: whitespace separates arguments,
/// double quotes group them, and inside quotes a backslash escapes the four
/// characters that would otherwise be special.
pub fn split_exec(exec: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut token = String::new();
    let mut in_quotes = false;
    let mut has_token = false;
    let mut chars = exec.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '"' => {
                in_quotes = !in_quotes;
                has_token = true;
            }
            '\\' if in_quotes => {
                if let Some(next) = chars.next() {
                    if matches!(next, '"' | '`' | '$' | '\\') {
                        token.push(next);
                    } else {
                        token.push('\\');
                        token.push(next);
                    }
                }
            }
            c if c.is_whitespace() && !in_quotes => {
                if has_token || !token.is_empty() {
                    out.push(std::mem::take(&mut token));
                    has_token = false;
                }
            }
            c => {
                token.push(c);
                has_token = true;
            }
        }
    }
    if has_token || !token.is_empty() {
        out.push(token);
    }
    out
}

/// Fill in the field codes. The list codes (`%F`, `%U`) turn one argument into
/// as many as there are files; the single codes take the first file and the
/// caller is expected to have launched once per file already.
fn expand(exec: &str, paths: &[PathBuf], entry: &DesktopEntry) -> Result<Vec<String>> {
    let mut out = Vec::new();
    for token in split_exec(exec) {
        match token.as_str() {
            "%F" | "%U" => {
                for p in paths {
                    out.push(if token == "%U" {
                        file_url(p)
                    } else {
                        p.display().to_string()
                    });
                }
                continue;
            }
            "%i" => {
                //: One field code that expands to two arguments, or to none.
                if let Some(icon) = &entry.icon {
                    out.push("--icon".into());
                    out.push(icon.clone());
                }
                continue;
            }
            _ => {}
        }
        let first = paths.first();
        let mut value = token.clone();
        if value.contains("%f") {
            value = value.replace(
                "%f",
                &first.map(|p| p.display().to_string()).unwrap_or_default(),
            );
        }
        if value.contains("%u") {
            value = value.replace("%u", &first.map(|p| file_url(p)).unwrap_or_default());
        }
        value = value
            .replace("%c", &entry.name)
            .replace("%k", &entry.path.display().to_string());
        //: The deprecated codes are dropped rather than passed through, so an
        //: old desktop file does not hand a literal "%d" to the program.
        for dead in ["%d", "%D", "%n", "%N", "%v", "%m"] {
            value = value.replace(dead, "");
        }
        value = value.replace("%%", "%");
        if value.is_empty() && token.starts_with('%') {
            continue;
        }
        out.push(value);
    }
    if out.is_empty() {
        return Err(Error::BadRequest(format!("{}: empty Exec line", entry.id)));
    }
    Ok(out)
}

/// `file:///home/cam/a b.txt`, percent encoded the way a URL has to be.
pub fn file_url(path: &Path) -> String {
    let mut out = String::from("file://");
    for byte in path.display().to_string().bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' | b'/' => {
                out.push(byte as char)
            }
            other => out.push_str(&format!("%{other:02X}")),
        }
    }
    out
}

/// Find a program on `PATH`, or accept an absolute path that is executable.
pub fn which(program: &str) -> Option<PathBuf> {
    let candidate = Path::new(program);
    if candidate.is_absolute() {
        return is_executable(candidate).then(|| candidate.to_path_buf());
    }
    let path = std::env::var("PATH").ok()?;
    path.split(':')
        .filter(|d| !d.is_empty())
        .map(|d| Path::new(d).join(program))
        .find(|p| is_executable(p))
}

fn is_executable(path: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    std::fs::metadata(path)
        .map(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
        .unwrap_or(false)
}

// ------------------------------------------------------------- the registry ---

/// Every installed application, plus the association files that say which one
/// opens what.
#[derive(Debug, Default)]
pub struct Registry {
    entries: BTreeMap<String, DesktopEntry>,
    /// mime type to desktop ids, in the order the association files gave them.
    added: HashMap<String, Vec<String>>,
    removed: HashMap<String, HashSet<String>>,
    defaults: HashMap<String, Vec<String>>,
    /// From each `mimeinfo.cache`, which is what a package manager writes.
    cached: HashMap<String, Vec<String>>,
}

impl Registry {
    /// Scan the XDG data path. Earlier directories win, which is what makes a
    /// desktop file in the home directory override the system one.
    pub fn load() -> Self {
        let mut reg = Registry::default();
        for dir in data_dirs() {
            let apps = dir.join("applications");
            reg.scan_applications(&apps, &apps);
            reg.read_mimeinfo_cache(&apps.join("mimeinfo.cache"));
        }
        //: mimeapps.list is read most specific first and the first answer for a
        //: type wins, so config comes before data.
        let mut lists: Vec<PathBuf> = config_dirs()
            .into_iter()
            .map(|d| d.join("mimeapps.list"))
            .collect();
        lists.extend(data_dirs().into_iter().map(|d| d.join("applications/mimeapps.list")));
        for list in lists {
            reg.read_mimeapps(&list);
        }
        reg
    }

    fn scan_applications(&mut self, base: &Path, dir: &Path) {
        let Ok(read) = std::fs::read_dir(dir) else { return };
        for entry in read.flatten() {
            let path = entry.path();
            if path.is_dir() {
                self.scan_applications(base, &path);
                continue;
            }
            if path.extension().map(|e| e != "desktop").unwrap_or(true) {
                continue;
            }
            let id = path
                .strip_prefix(base)
                .unwrap_or(&path)
                .to_string_lossy()
                .replace('/', "-");
            //: An id already present came from an earlier, more specific
            //: directory and stays.
            if self.entries.contains_key(&id) {
                continue;
            }
            let Ok(text) = std::fs::read_to_string(&path) else { continue };
            if let Some(parsed) = DesktopEntry::parse(&path, &id, &text) {
                self.entries.insert(id, parsed);
            }
        }
    }

    fn read_mimeinfo_cache(&mut self, path: &Path) {
        let Ok(text) = std::fs::read_to_string(path) else { return };
        for (mime, ids) in parse_mime_section(&text, "MIME Cache") {
            self.cached.entry(mime).or_default().extend(ids);
        }
    }

    fn read_mimeapps(&mut self, path: &Path) {
        let Ok(text) = std::fs::read_to_string(path) else { return };
        for (mime, ids) in parse_mime_section(&text, "Default Applications") {
            self.defaults.entry(mime).or_default().extend(ids);
        }
        for (mime, ids) in parse_mime_section(&text, "Added Associations") {
            self.added.entry(mime).or_default().extend(ids);
        }
        for (mime, ids) in parse_mime_section(&text, "Removed Associations") {
            self.removed.entry(mime).or_default().extend(ids);
        }
    }

    pub fn get(&self, id: &str) -> Option<&DesktopEntry> {
        self.entries.get(id)
    }

    /// Everything installed, for the full Open With list and for search.
    pub fn all(&self) -> impl Iterator<Item = &DesktopEntry> {
        self.entries.values()
    }

    /// The one that opens this type, if anything does.
    pub fn default_for(&self, mime: &str) -> Option<&DesktopEntry> {
        for id in self.defaults.get(mime)? {
            if self.is_removed(mime, id) {
                continue;
            }
            if let Some(entry) = self.entries.get(id) {
                if entry.is_runnable() {
                    return Some(entry);
                }
            }
        }
        None
    }

    fn is_removed(&self, mime: &str, id: &str) -> bool {
        self.removed.get(mime).map(|s| s.contains(id)).unwrap_or(false)
    }

    /// Everything that handles this type, the default first. `also` is the
    /// type's ancestry, so a `text/x-python` file still offers every text
    /// editor.
    pub fn handlers_for(&self, mime: &str, also: &[String]) -> Vec<&DesktopEntry> {
        let types: Vec<&str> =
            std::iter::once(mime).chain(also.iter().map(String::as_str)).collect();
        let mut seen: HashSet<String> = HashSet::new();
        let mut order: Vec<String> = Vec::new();

        //: The default first, then the explicit associations, then the package
        //: manager's cache, then anything that merely declares the type. Each
        //: pass runs over the whole ancestry before the next begins, so an
        //: application associated with the exact type outranks one that only
        //: handles its parent.
        let sources: [&HashMap<String, Vec<String>>; 3] =
            [&self.defaults, &self.added, &self.cached];
        for source in sources {
            for t in &types {
                for id in source.get(*t).into_iter().flatten() {
                    if self.is_removed(t, id) || !seen.insert(id.clone()) {
                        continue;
                    }
                    order.push(id.clone());
                }
            }
        }
        for t in &types {
            for (id, entry) in &self.entries {
                if !entry.mime_types.iter().any(|m| m == t) {
                    continue;
                }
                if self.is_removed(t, id) || !seen.insert(id.clone()) {
                    continue;
                }
                order.push(id.clone());
            }
        }

        order
            .iter()
            .filter_map(|id| self.entries.get(id))
            .filter(|e| e.is_runnable() && !e.no_display)
            .collect()
    }

    /// Make `id` the default for `mime`, by writing the user's own
    /// `mimeapps.list`. Every other program on the desktop reads the same
    /// file, so this is a system wide change and not a private one.
    pub fn set_default(&mut self, mime: &str, id: &str) -> Result<PathBuf> {
        if !self.entries.contains_key(id) {
            return Err(Error::NotFound(format!("no application {id}")));
        }
        let dir = xdg_config_home()
            .ok_or_else(|| Error::BadRequest("no HOME, so no place to record this".into()))?;
        std::fs::create_dir_all(&dir).map_err(|e| Error::io(dir.display().to_string(), e))?;
        let path = dir.join("mimeapps.list");
        let text = std::fs::read_to_string(&path).unwrap_or_default();
        let updated = upsert_default(&text, mime, id);
        write_atomically(&path, updated.as_bytes())?;
        self.defaults.insert(mime.to_string(), vec![id.to_string()]);
        //: Setting a default also has to undo a previous removal of the same
        //: pair, or the entry we just chose would be filtered straight out.
        if let Some(set) = self.removed.get_mut(mime) {
            set.remove(id);
        }
        Ok(path)
    }
}

fn parse_mime_section(text: &str, section: &str) -> Vec<(String, Vec<String>)> {
    let mut out = Vec::new();
    let mut inside = false;
    for line in text.lines() {
        let line = line.trim();
        if line.starts_with('[') {
            inside = line == format!("[{section}]");
            continue;
        }
        if !inside || line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some((mime, ids)) = line.split_once('=') {
            out.push((
                mime.trim().to_string(),
                ids.split(';')
                    .map(str::trim)
                    .filter(|s| !s.is_empty())
                    .map(str::to_string)
                    .collect(),
            ));
        }
    }
    out
}

/// Set `mime=id` under `[Default Applications]`, creating the section if the
/// file does not have one and leaving every other line exactly as it was. A
/// mimeapps.list holds the user's choices for every type on the system, so
/// rewriting it wholesale would throw away answers this call was not asked
/// about.
fn upsert_default(text: &str, mime: &str, id: &str) -> String {
    let mut lines: Vec<String> = text.lines().map(str::to_string).collect();
    let header = "[Default Applications]";
    let start = lines.iter().position(|l| l.trim() == header);
    match start {
        Some(start) => {
            let end = lines[start + 1..]
                .iter()
                .position(|l| l.trim_start().starts_with('['))
                .map(|k| start + 1 + k)
                .unwrap_or(lines.len());
            let existing = lines[start + 1..end]
                .iter()
                .position(|l| l.split_once('=').map(|(k, _)| k.trim() == mime).unwrap_or(false))
                .map(|k| start + 1 + k);
            match existing {
                Some(at) => lines[at] = format!("{mime}={id}"),
                None => lines.insert(end, format!("{mime}={id}")),
            }
        }
        None => {
            if !lines.is_empty() && !lines.last().map(|l| l.is_empty()).unwrap_or(true) {
                lines.push(String::new());
            }
            lines.push(header.to_string());
            lines.push(format!("{mime}={id}"));
        }
    }
    let mut out = lines.join("\n");
    out.push('\n');
    out
}

/// Write through a temporary file and rename, so a crash or a full disk leaves
/// the old file rather than half of the new one.
fn write_atomically(path: &Path, bytes: &[u8]) -> Result<()> {
    let tmp = path.with_extension(format!("tmp{}", std::process::id()));
    {
        let mut file = std::fs::File::create(&tmp)
            .map_err(|e| Error::io(tmp.display().to_string(), e))?;
        file.write_all(bytes).map_err(|e| Error::io(tmp.display().to_string(), e))?;
        file.sync_all().map_err(|e| Error::io(tmp.display().to_string(), e))?;
    }
    std::fs::rename(&tmp, path).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        Error::io(path.display().to_string(), e)
    })
}

// -------------------------------------------------------------- launching ---

/// How to start something.
#[derive(Debug, Clone, Default)]
pub struct Launch {
    pub argv: Vec<String>,
    pub cwd: Option<PathBuf>,
    /// Run inside a terminal emulator, for a `Terminal=true` entry or for the
    /// Run in terminal verb.
    pub in_terminal: bool,
    /// Ask for the administrator's authority first. This is `pkexec`, which
    /// prompts through polkit; there is no path here that runs anything as
    /// root without that prompt.
    pub as_admin: bool,
    /// Keep the terminal open after the program exits, so its output can be
    /// read. Only meaningful with `in_terminal`.
    pub hold: bool,
}

impl Launch {
    pub fn new(argv: Vec<String>) -> Self {
        Launch { argv, ..Default::default() }
    }
}

/// Terminal emulators worth trying, in the order a desktop would. The `-e`
/// spelling differs, so each carries its own.
const TERMINALS: &[(&str, &[&str])] = &[
    ("aurade-terminal", &["-e"]),
    ("foot", &["-e"]),
    ("alacritty", &["-e"]),
    ("kitty", &["--"]),
    ("wezterm", &["start", "--"]),
    ("gnome-terminal", &["--"]),
    ("konsole", &["-e"]),
    ("xfce4-terminal", &["-x"]),
    ("xterm", &["-e"]),
];

/// The terminal to use, honouring `$TERMINAL` first.
pub fn terminal() -> Option<(PathBuf, Vec<String>)> {
    if let Ok(name) = std::env::var("TERMINAL") {
        if let Some(path) = which(&name) {
            let args = TERMINALS
                .iter()
                .find(|(n, _)| *n == name)
                .map(|(_, a)| a.iter().map(|s| s.to_string()).collect())
                .unwrap_or_else(|| vec!["-e".to_string()]);
            return Some((path, args));
        }
    }
    for (name, args) in TERMINALS {
        if let Some(path) = which(name) {
            return Some((path, args.iter().map(|s| s.to_string()).collect()));
        }
    }
    None
}

/// Start it, detached, and do not wait for it.
///
/// The child is `setsid --fork`, which forks and exits at once. That gives the
/// program its own session, so it survives this service restarting, and gives
/// us a direct child that exits immediately, so there is no zombie to reap
/// later.
pub fn spawn(launch: &Launch) -> Result<()> {
    if launch.argv.is_empty() {
        return Err(Error::BadRequest("nothing to run".into()));
    }
    let mut argv = launch.argv.clone();

    if launch.as_admin {
        let pkexec = which("pkexec").ok_or_else(|| {
            Error::NotFound("pkexec is not installed, so there is no way to ask for authority".into())
        })?;
        //: --keep-cwd matters: without it pkexec runs in / and a relative path
        //: in the argv would mean something else.
        let mut with = vec![pkexec.display().to_string(), "--keep-cwd".into()];
        with.append(&mut argv);
        argv = with;
    }

    if launch.in_terminal {
        let (term, sep) = terminal()
            .ok_or_else(|| Error::NotFound("no terminal emulator is installed".into()))?;
        let mut with = vec![term.display().to_string()];
        with.extend(sep);
        if launch.hold {
            //: Holding the window open is not a flag every emulator has, so it
            //: is done with a shell that waits rather than with an option that
            //: may not exist.
            with.push("/bin/sh".into());
            with.push("-c".into());
            with.push(format!(
                "{}; printf '\\n[done, press enter]'; read _",
                shell_quote(&argv)
            ));
        } else {
            with.append(&mut argv);
        }
        argv = with;
    }

    let program = argv.remove(0);
    let mut command = match which("setsid") {
        Some(setsid) => {
            let mut c = Command::new(setsid);
            c.arg("--fork").arg("--").arg(&program).args(&argv);
            c
        }
        None => {
            //: Without util-linux the program still starts, it just stays a
            //: child of this process.
            let mut c = Command::new(&program);
            c.args(&argv);
            c
        }
    };
    if let Some(cwd) = &launch.cwd {
        command.current_dir(cwd);
    }
    command.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    let mut child = command
        .spawn()
        .map_err(|e| Error::io(format!("starting {program}"), e))?;
    //: setsid has already forked and is about to exit, so this returns at once.
    let _ = child.wait();
    Ok(())
}

/// Quote an argv for a `sh -c` string. Single quotes with the one escape that
/// works inside them, because anything else is a way to get an argument
/// interpreted as syntax.
pub fn shell_quote(argv: &[String]) -> String {
    argv.iter()
        .map(|a| format!("'{}'", a.replace('\'', "'\\''")))
        .collect::<Vec<_>>()
        .join(" ")
}

/// Open these paths with a named application.
pub fn open_with(reg: &Registry, id: &str, paths: &[PathBuf]) -> Result<()> {
    let entry = reg
        .get(id)
        .ok_or_else(|| Error::NotFound(format!("no application {id}")))?;
    let argv = entry.command(paths)?;
    spawn(&Launch {
        argv,
        cwd: paths.first().and_then(|p| p.parent().map(Path::to_path_buf)),
        in_terminal: entry.terminal,
        ..Default::default()
    })
}

/// Open a terminal at a directory. This is Files' Open in Terminal, and the
/// analogue of its Open in Windows Terminal.
pub fn open_terminal(dir: &Path) -> Result<()> {
    let (term, _) = terminal()
        .ok_or_else(|| Error::NotFound("no terminal emulator is installed".into()))?;
    spawn(&Launch {
        argv: vec![term.display().to_string()],
        cwd: Some(dir.to_path_buf()),
        ..Default::default()
    })
}

/// Files' Run as administrator. Never a silent escalation: pkexec puts the
/// polkit prompt in front of it, and a refusal there is the end of it.
pub fn run_as_admin(path: &Path, args: &[String]) -> Result<()> {
    let mut argv = vec![path.display().to_string()];
    argv.extend(args.iter().cloned());
    spawn(&Launch {
        argv,
        cwd: path.parent().map(Path::to_path_buf),
        as_admin: true,
        ..Default::default()
    })
}

/// Files' Run with PowerShell, in the form this system actually has: run the
/// script in a terminal that stays open long enough to read what it said.
pub fn run_in_terminal(path: &Path, args: &[String]) -> Result<()> {
    let mut argv = vec![path.display().to_string()];
    argv.extend(args.iter().cloned());
    spawn(&Launch {
        argv,
        cwd: path.parent().map(Path::to_path_buf),
        in_terminal: true,
        hold: true,
        ..Default::default()
    })
}

// ------------------------------------------------------- the applications ---

/// Where a pinned folder's desktop entry goes: the per user applications
/// directory every launcher on this system already reads, which is the same
/// place `Registry::load` finds the rest of them.
fn applications_dir() -> Result<PathBuf> {
    Ok(crate::mime::xdg_data_home()
        .ok_or_else(|| Error::BadRequest("no HOME, so no place to record this".into()))?
        .join("applications"))
}

/// The file name a pinned folder gets.
///
/// Derived from the path rather than the folder's name, so two folders called
/// `notes` do not write over one another, and so unpinning can find the entry
/// again without keeping a list of its own beside the directory.
fn pin_file(path: &Path) -> String {
    //: FNV-1a. Not a security hash: this only has to be stable across runs
    //: and different for different paths, and being short keeps the file name
    //: readable in a directory listing.
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in path.as_os_str().as_encoded_bytes() {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("aurade-place-{hash:016x}.desktop")
}

/// Where a folder's entry is, pinned or not.
pub fn pin_path(path: &Path) -> Result<PathBuf> {
    Ok(applications_dir()?.join(pin_file(path)))
}

/// Whether this folder is in the applications list.
pub fn pinned(path: &Path) -> bool {
    pin_path(path).map(|p| p.is_file()).unwrap_or(false)
}

/// Whether this folder has an entry in a particular directory.
pub fn pinned_in(dir: &Path, path: &Path) -> bool {
    dir.join(pin_file(path)).is_file()
}

/// Put a folder in the applications list, which is what this desktop has in
/// place of Windows' Start menu.
///
/// A desktop entry rather than anything of our own, because the launcher, the
/// search and any other shell on this machine all read that directory
/// already; a private list would show up in exactly one place.
pub fn pin(path: &Path) -> Result<PathBuf> {
    pin_into(&applications_dir()?, path)
}

/// The whole of pinning except where the entry goes.
///
/// Split out because where it goes comes from the environment, which is
/// process wide: a test that pointed the environment somewhere of its own
/// would fight every other test in this crate that does the same, and the
/// part worth testing is the entry, not the directory.
pub fn pin_into(dir: &Path, path: &Path) -> Result<PathBuf> {
    if !path.is_dir() {
        return Err(Error::BadRequest(format!(
            "{} is not a folder, and only a folder is pinned this way",
            path.display()
        )));
    }
    //: A newline in a folder's name would end the `Exec` line and let the
    //: rest of the name invent keys of its own, which is a folder deciding
    //: what the launcher runs. Taking the character out would pin a different
    //: folder than the one asked for without saying so, so this refuses.
    if path.as_os_str().as_encoded_bytes().iter().any(|b| *b < 0x20 || *b == 0x7f) {
        return Err(Error::BadRequest(format!(
            "{} has a control character in its name, which cannot be written \
             into a desktop entry",
            path.display()
        )));
    }
    let name = path
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .filter(|n| !n.is_empty())
        .unwrap_or_else(|| path.display().to_string());
    std::fs::create_dir_all(dir).map_err(|e| Error::io(dir.display().to_string(), e))?;
    let file = dir.join(pin_file(path));

    //: Written out a line at a time rather than as one wrapped literal: a
    //: desktop entry key has to start the line, and a continuation in the
    //: source that leaves the indentation in the string produces a file every
    //: parser rejects.
    let mut entry = String::from("[Desktop Entry]\n");
    for (key, value) in [
        ("Type", "Application".to_string()),
        ("Version", "1.0".to_string()),
        ("Name", desktop_value(&name)),
        ("Comment", desktop_value(&format!("Open {}", path.display()))),
        //: `xdg-open` rather than a file manager named here. Which program
        //: opens a folder is the person's setting, and writing our own name
        //: into the entry would quietly override it.
        ("Exec", format!("xdg-open {}", exec_argument(path))),
        ("Icon", "folder".to_string()),
        ("Terminal", "false".to_string()),
        ("Categories", "Utility;Core;".to_string()),
        //: What unpin and the page both read to tell one of these from an
        //: application that happens to live in the same directory.
        ("X-Aurade-Place", desktop_value(&path.display().to_string())),
    ] {
        entry.push_str(&format!("{key}={value}\n"));
    }
    write_atomically(&file, entry.as_bytes())?;
    Ok(file)
}

/// Take a folder back out of the applications list.
pub fn unpin(path: &Path) -> Result<PathBuf> {
    unpin_from(&applications_dir()?, path)
}

/// Take a folder out of a particular applications directory.
pub fn unpin_from(dir: &Path, path: &Path) -> Result<PathBuf> {
    let file = dir.join(pin_file(path));
    if !file.is_file() {
        return Err(Error::NotFound(format!("{} is not pinned", path.display())));
    }
    std::fs::remove_file(&file).map_err(|e| Error::io(file.display().to_string(), e))?;
    Ok(file)
}

/// A value safe to write on the right of a desktop entry key.
///
/// A newline would end the line and let the rest of the string invent keys of
/// its own, which for a value that comes from a folder's name means a folder
/// can write its own `Exec=`.
fn desktop_value(value: &str) -> String {
    value.replace(['\n', '\r'], " ").trim().to_string()
}

/// A path as one argument of an `Exec` line.
///
/// The desktop entry spec reserves the quote characters and the backslash
/// inside a quoted argument, so a folder called `it"s` has to be escaped
/// rather than pasted in.
fn exec_argument(path: &Path) -> String {
    let text = path.display().to_string();
    let mut out = String::with_capacity(text.len() + 2);
    out.push('"');
    for c in text.chars() {
        //: The four the spec names, plus the backslash that escapes them.
        if matches!(c, '"' | '`' | '$' | '\\') {
            out.push('\\');
        }
        //: A percent is doubled: a lone one starts a field code, and `%f`
        //: in a folder's name would be replaced by the launcher.
        if c == '%' {
            out.push('%');
        }
        out.push(c);
    }
    out.push('"');
    out
}

// ------------------------------------------------------------ PowerShell ----

/// PowerShell as this system has it. Files' Run with PowerShell, and it is a
/// real program here rather than a stand in: Microsoft ships `pwsh` for Linux.
pub const POWERSHELL: &str = "pwsh";

/// Whether PowerShell is installed.
pub fn have_powershell() -> bool {
    which(POWERSHELL).is_some()
}

/// Run a script with PowerShell, in a terminal that stays open afterwards.
///
/// `-File` and not `-Command`: the script's path is one argument to the
/// interpreter and is never part of a string it parses, so a file whose name
/// contains a quote or a semicolon is a file name and not more script.
pub fn run_with_powershell(path: &Path) -> Result<()> {
    let shell = which(POWERSHELL)
        .ok_or_else(|| Error::NotFound(format!("{POWERSHELL} is not installed")))?;
    if !path.is_file() {
        return Err(Error::NotFound(path.display().to_string()));
    }
    spawn(&Launch {
        argv: vec![
            shell.display().to_string(),
            "-NoLogo".into(),
            "-File".into(),
            path.display().to_string(),
        ],
        cwd: path.parent().map(Path::to_path_buf),
        in_terminal: true,
        hold: true,
        ..Default::default()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = r#"
[Desktop Entry]
Type=Application
Name=Text Editor
Name[de]=Texteditor
GenericName=Editor
Comment=Edit\stext\sfiles
Icon=accessories-text-editor
Exec=gedit %U
Terminal=false
MimeType=text/plain;text/x-python;
Categories=Utility;TextEditor;
Actions=new-window;

[Desktop Action new-window]
Name=New Window
Exec=gedit --new-window
"#;

    #[test]
    fn a_desktop_file_reads_the_way_the_spec_says() {
        let entry = DesktopEntry::parse(Path::new("/a/gedit.desktop"), "gedit.desktop", SAMPLE).unwrap();
        assert_eq!(entry.name, "Text Editor", "a localised key overwrote the plain one");
        assert_eq!(entry.comment.as_deref(), Some("Edit text files"));
        assert_eq!(entry.mime_types, ["text/plain", "text/x-python"]);
        assert_eq!(entry.categories, ["Utility", "TextEditor"]);
        assert!(!entry.terminal);
        assert_eq!(entry.actions.len(), 1);
        assert_eq!(entry.actions[0].name, "New Window");
    }

    #[test]
    fn a_non_application_entry_is_not_something_to_launch() {
        let text = "[Desktop Entry]\nType=Directory\nName=Games\n";
        assert!(DesktopEntry::parse(Path::new("/a/x.directory"), "x", text).is_none());
    }

    #[test]
    fn exec_splitting_follows_the_quoting_rules() {
        assert_eq!(split_exec("gedit %U"), ["gedit", "%U"]);
        assert_eq!(
            split_exec(r#""/opt/my app/bin" --flag "a b""#),
            ["/opt/my app/bin", "--flag", "a b"]
        );
        assert_eq!(split_exec(r#"prog "say \"hi\"""#), ["prog", r#"say "hi""#]);
        assert_eq!(split_exec("prog   spaced    out"), ["prog", "spaced", "out"]);
        //: An empty quoted argument is an argument.
        assert_eq!(split_exec(r#"prog "" x"#), ["prog", "", "x"]);
    }

    #[test]
    fn a_list_field_code_becomes_one_argument_per_file() {
        let entry = DesktopEntry::parse(Path::new("/a/g.desktop"), "g.desktop", SAMPLE).unwrap();
        let paths = vec![PathBuf::from("/home/cam/a b.txt"), PathBuf::from("/home/cam/c.txt")];
        assert_eq!(
            entry.command(&paths).unwrap(),
            [
                "gedit",
                "file:///home/cam/a%20b.txt",
                "file:///home/cam/c.txt"
            ]
        );
    }

    #[test]
    fn a_single_field_code_takes_the_first_file_and_keeps_its_token() {
        let text = "[Desktop Entry]\nType=Application\nName=V\nIcon=vi\nExec=viewer --file=%f %i\n";
        let entry = DesktopEntry::parse(Path::new("/a/v.desktop"), "v.desktop", text).unwrap();
        assert_eq!(
            entry.command(&[PathBuf::from("/tmp/one"), PathBuf::from("/tmp/two")]).unwrap(),
            ["viewer", "--file=/tmp/one", "--icon", "vi"]
        );
    }

    #[test]
    fn the_deprecated_field_codes_are_dropped_rather_than_passed_on() {
        let text = "[Desktop Entry]\nType=Application\nName=V\nExec=old %d %n %f\n";
        let entry = DesktopEntry::parse(Path::new("/a/o.desktop"), "o.desktop", text).unwrap();
        assert_eq!(entry.command(&[PathBuf::from("/tmp/x")]).unwrap(), ["old", "/tmp/x"]);
    }

    #[test]
    fn a_url_is_encoded_where_it_has_to_be() {
        assert_eq!(file_url(Path::new("/a/b c.txt")), "file:///a/b%20c.txt");
        assert_eq!(file_url(Path::new("/a/#1.txt")), "file:///a/%231.txt");
        assert_eq!(file_url(Path::new("/a/plain.txt")), "file:///a/plain.txt");
    }

    #[test]
    fn shell_quoting_survives_a_name_full_of_syntax() {
        let argv = vec!["/bin/sh".to_string(), "it's; rm -rf /".to_string()];
        assert_eq!(shell_quote(&argv), r#"'/bin/sh' 'it'\''s; rm -rf /'"#);
    }

    #[test]
    fn setting_a_default_keeps_every_other_line() {
        let before = "[Added Associations]\ntext/plain=vim.desktop;\n\n[Default Applications]\nimage/png=eog.desktop\ntext/plain=vim.desktop\n";
        let after = upsert_default(before, "text/plain", "gedit.desktop");
        assert!(after.contains("image/png=eog.desktop"), "another type was lost");
        assert!(after.contains("[Added Associations]\ntext/plain=vim.desktop;"), "another section was lost");
        assert!(after.contains("text/plain=gedit.desktop"));
        assert_eq!(after.matches("text/plain=").count(), 2, "one per section");
    }

    #[test]
    fn setting_a_default_creates_the_section_when_there_is_none() {
        let after = upsert_default("[Added Associations]\ntext/plain=vim.desktop;\n", "text/plain", "gedit.desktop");
        assert!(after.contains("[Default Applications]\ntext/plain=gedit.desktop"));
        let empty = upsert_default("", "text/plain", "gedit.desktop");
        assert_eq!(empty, "[Default Applications]\ntext/plain=gedit.desktop\n");
    }

    #[test]
    fn a_new_type_joins_the_section_rather_than_the_end_of_the_file() {
        let before = "[Default Applications]\nimage/png=eog.desktop\n\n[Added Associations]\nx=y.desktop\n";
        let after = upsert_default(before, "text/plain", "gedit.desktop");
        let at_default = after.find("text/plain=gedit.desktop").unwrap();
        let at_added = after.find("[Added Associations]").unwrap();
        assert!(at_default < at_added, "it landed in the wrong section:\n{after}");
    }

    #[test]
    fn an_entry_whose_program_is_missing_is_not_offered() {
        let text = "[Desktop Entry]\nType=Application\nName=Ghost\nTryExec=/nowhere/ghost\nExec=ghost %f\n";
        let entry = DesktopEntry::parse(Path::new("/a/g.desktop"), "g.desktop", text).unwrap();
        assert!(!entry.is_runnable());
        let text = "[Desktop Entry]\nType=Application\nName=Real\nTryExec=/bin/sh\nExec=sh %f\n";
        let entry = DesktopEntry::parse(Path::new("/a/r.desktop"), "r.desktop", text).unwrap();
        assert!(entry.is_runnable());
    }

    #[test]
    fn a_hidden_entry_is_never_runnable() {
        let text = "[Desktop Entry]\nType=Application\nName=Gone\nHidden=true\nExec=gone\n";
        let entry = DesktopEntry::parse(Path::new("/a/h.desktop"), "h.desktop", text).unwrap();
        assert!(!entry.is_runnable());
    }

    #[test]
    fn the_registry_prefers_the_default_and_then_everything_else() {
        let mut reg = Registry::default();
        for id in ["gedit.desktop", "vim.desktop", "emacs.desktop"] {
            let text = format!(
                "[Desktop Entry]\nType=Application\nName={id}\nExec=/bin/true %f\nMimeType=text/plain;\n"
            );
            reg.entries
                .insert(id.into(), DesktopEntry::parse(Path::new("/a"), id, &text).unwrap());
        }
        reg.defaults.insert("text/plain".into(), vec!["vim.desktop".into()]);
        reg.removed.insert("text/plain".into(), ["emacs.desktop".into()].into());

        assert_eq!(reg.default_for("text/plain").unwrap().id, "vim.desktop");
        let ids: Vec<&str> = reg
            .handlers_for("text/plain", &[])
            .iter()
            .map(|e| e.id.as_str())
            .collect();
        assert_eq!(ids.first(), Some(&"vim.desktop"), "the default was not first");
        assert!(ids.contains(&"gedit.desktop"));
        assert!(!ids.contains(&"emacs.desktop"), "a removed association came back");
    }

    #[test]
    fn a_handler_registered_for_the_parent_type_still_shows_up() {
        let mut reg = Registry::default();
        let text = "[Desktop Entry]\nType=Application\nName=Ed\nExec=/bin/true %f\nMimeType=text/plain;\n";
        reg.entries.insert(
            "ed.desktop".into(),
            DesktopEntry::parse(Path::new("/a"), "ed.desktop", text).unwrap(),
        );
        assert!(reg.handlers_for("text/x-python", &[]).is_empty());
        let ids: Vec<&str> = reg
            .handlers_for("text/x-python", &["text/plain".to_string()])
            .iter()
            .map(|e| e.id.as_str())
            .collect();
        assert_eq!(ids, ["ed.desktop"]);
    }

    #[test]
    fn setting_a_default_that_names_no_application_is_refused() {
        let mut reg = Registry::default();
        let err = reg.set_default("text/plain", "nothing.desktop").unwrap_err();
        assert!(matches!(err, Error::NotFound(_)), "got {err:?}");
    }

    /// A tree of its own, and an applications directory inside it.
    ///
    /// No environment variable: where the entries go is process wide state,
    /// and two of these running at once, or one running beside any other test
    /// in this crate that points XDG_DATA_HOME somewhere, would each write
    /// into the other's directory. `pin_into` takes the directory instead.
    fn own_home(tag: &str) -> (PathBuf, PathBuf) {
        let home = std::env::temp_dir().join(format!("auradefs-apps-{tag}"));
        let _ = std::fs::remove_dir_all(&home);
        let apps = home.join(".local/share/applications");
        std::fs::create_dir_all(&apps).unwrap();
        (home, apps)
    }

    #[test]
    fn a_folder_is_pinned_as_a_desktop_entry_and_unpinned_again() {
        let (home, apps) = own_home("pin");
        let folder = home.join("Notes");
        std::fs::create_dir_all(&folder).unwrap();

        assert!(!pinned_in(&apps, &folder), "it was pinned before anything pinned it");
        let file = pin_into(&apps, &folder).unwrap();
        assert!(pinned_in(&apps, &folder));
        let text = std::fs::read_to_string(&file).unwrap();

        //: Every key starts its own line. An entry written with the source's
        //: indentation still in it parses as nothing at all.
        for line in text.lines().skip(1).filter(|l| !l.is_empty()) {
            assert!(
                !line.starts_with(' ') && line.contains('='),
                "not a key on its own line: {line:?}"
            );
        }
        assert!(text.starts_with("[Desktop Entry]\n"));
        assert!(text.contains("\nType=Application\n"));
        assert!(text.contains("\nName=Notes\n"));
        assert!(
            text.contains(&format!("\nExec=xdg-open \"{}\"\n", folder.display())),
            "the exec line does not open the folder: {text}"
        );

        //: The same folder twice is the same entry, not a second one.
        pin_into(&apps, &folder).unwrap();
        let count = std::fs::read_dir(&apps).unwrap().count();
        assert_eq!(count, 1, "pinning twice left two entries");

        unpin_from(&apps, &folder).unwrap();
        assert!(!pinned_in(&apps, &folder));
        //: And unpinning what is not pinned says so rather than passing.
        assert!(matches!(unpin_from(&apps, &folder), Err(Error::NotFound(_))));
    }

    #[test]
    fn two_folders_of_the_same_name_get_their_own_entries() {
        let (home, apps) = own_home("pin-same-name");
        let one = home.join("a/Notes");
        let two = home.join("b/Notes");
        std::fs::create_dir_all(&one).unwrap();
        std::fs::create_dir_all(&two).unwrap();
        pin_into(&apps, &one).unwrap();
        pin_into(&apps, &two).unwrap();
        assert!(pinned_in(&apps, &one) && pinned_in(&apps, &two));
        assert_ne!(pin_file(&one), pin_file(&two));
        //: Unpinning one leaves the other, which is the whole reason the name
        //: comes from the path and not from the folder's name.
        unpin_from(&apps, &one).unwrap();
        assert!(!pinned_in(&apps, &one));
        assert!(pinned_in(&apps, &two));
    }

    #[test]
    fn a_folder_name_cannot_write_keys_of_its_own_into_the_entry() {
        let (home, apps) = own_home("pin-injection");
        //: A newline in a folder's name would end the Name line and let the
        //: rest invent an Exec, which is a folder deciding what runs.
        let nasty = home.join("evil\nExec=sh -c id\nX=");
        std::fs::create_dir_all(&nasty).unwrap();
        let refused = pin_into(&apps, &nasty);
        assert!(matches!(refused, Err(Error::BadRequest(_))), "got {refused:?}");
        //: And nothing was written, so there is no half an entry left behind
        //: for the launcher to read.
        assert!(!pinned_in(&apps, &nasty));
        assert_eq!(
            std::fs::read_dir(&apps).unwrap().count(),
            0,
            "a refused pin still wrote a file"
        );

        //: And a quote in the name has to stay inside the quoted argument.
        let quoted = home.join("it\"s here");
        std::fs::create_dir_all(&quoted).unwrap();
        let text = std::fs::read_to_string(pin_into(&apps, &quoted).unwrap()).unwrap();
        assert!(text.contains("Exec=xdg-open \"") && text.contains("it\\\"s here\""),
                "the quote was not escaped: {text}");
        //: A percent is a field code the launcher expands, so it is doubled.
        let percent = home.join("100%f");
        std::fs::create_dir_all(&percent).unwrap();
        let text = std::fs::read_to_string(pin_into(&apps, &percent).unwrap()).unwrap();
        assert!(text.contains("100%%f"), "the field code was not escaped: {text}");
    }

    #[test]
    fn only_a_folder_is_pinned_this_way() {
        let (_home, apps) = own_home("pin-file");
        let file = apps.parent().unwrap().join("notes.txt");
        std::fs::write(&file, b"hello").unwrap();
        assert!(matches!(pin_into(&apps, &file), Err(Error::BadRequest(_))));
    }

    #[test]
    fn powershell_is_run_by_file_and_only_when_it_is_installed() {
        //: The one thing worth asserting without PowerShell installed: the
        //: answer is a NotFound naming it, not a panic and not a silent pass.
        if !have_powershell() {
            let asked = run_with_powershell(Path::new("/etc/hostname"));
            assert!(matches!(asked, Err(Error::NotFound(_))), "got {asked:?}");
        }
        assert_eq!(POWERSHELL, "pwsh");
        assert_eq!(have_powershell(), which("pwsh").is_some());
    }
}
