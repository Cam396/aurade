//! Where an application's icon is, found the way Ash finds it for the
//! launcher, so Open with and the shelf show the same picture for the same
//! program: the pixmaps directories, then hicolor, Adwaita and gnome under
//! each icon root, and a search of the roots when none of those has it.
//!
//! Only what a page can draw is returned. Ash reads an XPM itself; a browser
//! cannot, so an application whose only icon is one gets none here and the
//! page draws its generic one.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{Duration, Instant};

/// Bigger than any application icon worth showing; a larger file is
/// something else with an icon's name.
const MAX_ICON_BYTES: u64 = 512 * 1024;

/// How long a name that found nothing stays unfound, so an application
/// installed since gets its icon without a restart.
const MISS_LIFETIME: Duration = Duration::from_secs(60);

const THEMES: &[&str] = &["hicolor", "Adwaita", "gnome"];

/// Ash's directories, with the sizes a dialog row draws best first and the
/// largest last, because the picture travels inside the answer.
const SUBDIRS: &[&str] = &[
    "scalable/apps",
    "48x48/apps",
    "64x64/apps",
    "32x32/apps",
    "96x96/apps",
    "128x128/apps",
    "256x256/apps",
    "24x24/apps",
    "16x16/apps",
    "512x512/apps",
    "symbolic/apps",
];

fn cache() -> &'static Mutex<HashMap<String, (Option<PathBuf>, Instant)>> {
    static CACHE: std::sync::OnceLock<Mutex<HashMap<String, (Option<PathBuf>, Instant)>>> =
        std::sync::OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

/// The file for the desktop entry's `Icon=` value, if there is one a page
/// can show.
pub fn find(icon: &str) -> Option<PathBuf> {
    if icon.is_empty() {
        return None;
    }
    if let Some((found, when)) = cache().lock().unwrap_or_else(|e| e.into_inner()).get(icon) {
        if found.is_some() || when.elapsed() < MISS_LIFETIME {
            return found.clone();
        }
    }
    let found = look_up(icon);
    cache()
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .insert(icon.to_string(), (found.clone(), Instant::now()));
    found
}

/// The type a page is told the picture is.
pub fn mime_of(path: &Path) -> &'static str {
    match path.extension().and_then(|e| e.to_str()) {
        Some("svg") => "image/svg+xml",
        _ => "image/png",
    }
}

fn drawable(path: &Path) -> bool {
    matches!(path.extension().and_then(|e| e.to_str()), Some("svg" | "png"))
        && std::fs::metadata(path)
            .map(|m| m.is_file() && m.len() <= MAX_ICON_BYTES)
            .unwrap_or(false)
}

fn file_names(icon: &str) -> Vec<String> {
    let path = Path::new(icon);
    match path.extension().and_then(|e| e.to_str()) {
        Some("svg" | "png") => {
            path.file_name().map(|n| vec![n.to_string_lossy().to_string()]).unwrap_or_default()
        }
        _ => vec![format!("{icon}.svg"), format!("{icon}.png")],
    }
}

fn icon_roots() -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Some(home) = std::env::var_os("HOME").filter(|h| !h.is_empty()) {
        roots.push(Path::new(&home).join(".local/share/icons"));
        roots.push(Path::new(&home).join(".icons"));
    }
    roots.push(PathBuf::from("/usr/local/share/icons"));
    roots.push(PathBuf::from("/usr/share/icons"));
    roots
}

fn look_up(icon: &str) -> Option<PathBuf> {
    let as_path = Path::new(icon);
    if as_path.is_absolute() {
        return drawable(as_path).then(|| as_path.to_path_buf());
    }
    //: A name, never a path into somewhere else.
    if icon.contains('/') {
        return None;
    }
    let names = file_names(icon);
    let roots = icon_roots();
    let mut dirs = vec![
        PathBuf::from("/usr/local/share/pixmaps"),
        PathBuf::from("/usr/share/pixmaps"),
    ];
    for root in &roots {
        for theme in THEMES {
            dirs.extend(SUBDIRS.iter().map(|sub| root.join(theme).join(sub)));
        }
    }
    for dir in &dirs {
        for name in &names {
            let path = dir.join(name);
            if drawable(&path) {
                return Some(path);
            }
        }
    }
    //: Then anywhere under the roots, as Ash does, for an application that
    //: put its icon in another theme only.
    for root in &roots {
        if let Some(found) = search(root, &names, 0) {
            return Some(found);
        }
    }
    None
}

fn search(dir: &Path, names: &[String], depth: usize) -> Option<PathBuf> {
    //: Themes are four levels deep at most: theme, size, context, file.
    if depth > 4 {
        return None;
    }
    let mut subdirs = Vec::new();
    for entry in std::fs::read_dir(dir).ok()?.flatten() {
        let Ok(kind) = entry.file_type() else { continue };
        let name = entry.file_name();
        if kind.is_dir() {
            subdirs.push(entry.path());
        } else if names.iter().any(|n| name == n.as_str()) && drawable(&entry.path()) {
            return Some(entry.path());
        }
    }
    subdirs.sort();
    subdirs.into_iter().find_map(|sub| search(&sub, names, depth + 1))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_name_is_looked_for_as_svg_then_png_and_a_file_name_as_itself() {
        assert_eq!(file_names("org.kde.kate"), ["org.kde.kate.svg", "org.kde.kate.png"]);
        assert_eq!(file_names("firefox.png"), ["firefox.png"]);
        //: An XPM is a name like any other here, since nothing can draw one.
        assert_eq!(file_names("xterm-color_48x48.xpm"), [
            "xterm-color_48x48.xpm.svg",
            "xterm-color_48x48.xpm.png"
        ]);
    }

    #[test]
    fn a_path_into_somewhere_else_finds_nothing() {
        assert_eq!(look_up("../../etc/passwd"), None);
        assert_eq!(look_up(""), None);
        assert_eq!(find(""), None);
    }

    #[test]
    fn an_absolute_path_is_used_only_when_it_is_a_picture() {
        let dir = std::env::temp_dir().join(format!("appicons-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let png = dir.join("app.png");
        let xpm = dir.join("app.xpm");
        std::fs::write(&png, b"\x89PNG\r\n\x1a\n").unwrap();
        std::fs::write(&xpm, b"/* XPM */").unwrap();
        assert_eq!(look_up(&png.display().to_string()), Some(png.clone()));
        assert_eq!(look_up(&xpm.display().to_string()), None);
        assert_eq!(mime_of(&png), "image/png");
        assert_eq!(mime_of(Path::new("/x/app.svg")), "image/svg+xml");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_theme_is_searched_when_the_usual_places_do_not_have_it() {
        let root = std::env::temp_dir().join(format!("appicons-root-{}", std::process::id()));
        let deep = root.join("breeze/apps/48");
        std::fs::create_dir_all(&deep).unwrap();
        std::fs::write(deep.join("org.example.app.svg"), b"<svg/>").unwrap();
        let names = file_names("org.example.app");
        assert_eq!(search(&root, &names, 0), Some(deep.join("org.example.app.svg")));
        assert_eq!(search(&root, &file_names("org.example.none"), 0), None);
        let _ = std::fs::remove_dir_all(&root);
    }
}
