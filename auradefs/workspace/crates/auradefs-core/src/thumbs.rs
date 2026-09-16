//! Thumbnails, in the shared cache every other program on the desktop uses.
//!
//! The freedesktop thumbnail specification is worth following exactly rather
//! than keeping a private cache: a picture folder opened in this file manager
//! and then in an image viewer should not generate every thumbnail twice, and
//! a thumbnail written here has to be one another program will trust.
//!
//! Trust is the whole of it. A cached thumbnail carries the URI and the
//! modification time of what it was made from, and a reader that does not check
//! them will happily show the previous contents of a file that has since
//! changed. So every read validates, and a stale entry is treated as no entry.

use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};

use crate::error::{Error, Result};

/// The sizes the specification defines. Bigger ones exist in the same layout,
/// so adding one later is a variant rather than a redesign.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Size {
    Normal,
    Large,
    XLarge,
    XxLarge,
}

impl Size {
    pub fn pixels(self) -> u32 {
        match self {
            Size::Normal => 128,
            Size::Large => 256,
            Size::XLarge => 512,
            Size::XxLarge => 1024,
        }
    }

    pub fn dir_name(self) -> &'static str {
        match self {
            Size::Normal => "normal",
            Size::Large => "large",
            Size::XLarge => "x-large",
            Size::XxLarge => "xx-large",
        }
    }

    /// The smallest size that can fill a box of `wanted` pixels without being
    /// scaled up, which is how a view picks what to ask for.
    pub fn for_display(wanted: u32) -> Size {
        for size in [Size::Normal, Size::Large, Size::XLarge] {
            if wanted <= size.pixels() {
                return size;
            }
        }
        Size::XxLarge
    }
}

/// What this program calls itself in the failure directory. The specification
/// keeps failures per program, because one program failing to read a format
/// says nothing about another.
const FAIL_OWNER: &str = "auradefs-1";

pub fn cache_home() -> Result<PathBuf> {
    if let Ok(v) = std::env::var("XDG_CACHE_HOME") {
        if !v.is_empty() {
            return Ok(PathBuf::from(v));
        }
    }
    Ok(PathBuf::from(
        std::env::var("HOME").map_err(|_| Error::NotFound("HOME is not set".into()))?,
    )
    .join(".cache"))
}

fn thumb_root() -> Result<PathBuf> {
    Ok(cache_home()?.join("thumbnails"))
}

/// An image's size without decoding it. Every format this reads keeps the
/// dimensions in its header, so this costs a few hundred bytes rather than the
/// whole picture.
pub fn dimensions(path: &Path) -> Option<(u32, u32)> {
    image::ImageReader::open(path).ok()?.with_guessed_format().ok()?.into_dimensions().ok()
}

/// The cache file name for a path: the MD5 of its URI, in hex, with `.png`.
pub fn key(path: &Path) -> String {
    use md5::Digest as _;
    let uri = crate::apps::file_url(path);
    let digest = md5::Md5::digest(uri.as_bytes());
    let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();
    format!("{hex}.png")
}

/// Where a thumbnail for this path and size would live, whether or not it is
/// there.
pub fn cache_path(path: &Path, size: Size) -> Result<PathBuf> {
    Ok(thumb_root()?.join(size.dir_name()).join(key(path)))
}

/// The cached thumbnail, if there is a valid one.
///
/// Valid means it exists, it records the same URI, and it records the source's
/// current modification time. A file edited in place keeps its name and its
/// URI, so the time is the only thing that catches it.
pub fn cached(path: &Path, size: Size) -> Result<Option<PathBuf>> {
    let file = cache_path(path, size)?;
    let Ok(bytes) = std::fs::read(&file) else { return Ok(None) };
    let text = png_text(&bytes);
    let uri = crate::apps::file_url(path);
    if text.iter().find(|(k, _)| k == "Thumb::URI").map(|(_, v)| v.as_str()) != Some(uri.as_str()) {
        return Ok(None);
    }
    let Some(recorded) = text
        .iter()
        .find(|(k, _)| k == "Thumb::MTime")
        .and_then(|(_, v)| v.parse::<i64>().ok())
    else {
        return Ok(None);
    };
    let Ok(stat) = std::fs::metadata(path) else { return Ok(None) };
    use std::os::unix::fs::MetadataExt;
    if stat.mtime() != recorded {
        return Ok(None);
    }
    //: The recorded time has one second of resolution, which is what the
    //: specification stores, so an edit inside the same second would slip
    //: past it. The size is written alongside for exactly that case. It is
    //: optional in the specification, so it is only checked when it is there.
    if let Some(size) = text
        .iter()
        .find(|(k, _)| k == "Thumb::Size")
        .and_then(|(_, v)| v.parse::<u64>().ok())
    {
        if stat.len() != size {
            return Ok(None);
        }
    }
    Ok(Some(file))
}

/// Has making a thumbnail for this file already been tried and failed? The
/// answer stops a grid view from trying again on every scroll.
pub fn failed(path: &Path) -> Result<bool> {
    let file = thumb_root()?.join("fail").join(FAIL_OWNER).join(key(path));
    let Ok(bytes) = std::fs::read(&file) else { return Ok(false) };
    let text = png_text(&bytes);
    let Some(recorded) = text
        .iter()
        .find(|(k, _)| k == "Thumb::MTime")
        .and_then(|(_, v)| v.parse::<i64>().ok())
    else {
        return Ok(false);
    };
    use std::os::unix::fs::MetadataExt;
    let Ok(stat) = std::fs::metadata(path) else { return Ok(false) };
    //: A file that has changed since the failure deserves another try, by the
    //: same two measures the cache itself uses.
    if stat.mtime() != recorded {
        return Ok(false);
    }
    if let Some(size) = text
        .iter()
        .find(|(k, _)| k == "Thumb::Size")
        .and_then(|(_, v)| v.parse::<u64>().ok())
    {
        if stat.len() != size {
            return Ok(false);
        }
    }
    Ok(true)
}

/// Read the tEXt chunks out of a PNG. Only tEXt, because that is what the
/// specification uses, and a hand rolled reader for one chunk type is smaller
/// and more predictable than a decode of the whole image.
fn png_text(bytes: &[u8]) -> Vec<(String, String)> {
    const MAGIC: &[u8] = b"\x89PNG\r\n\x1a\n";
    let mut out = Vec::new();
    if bytes.len() < MAGIC.len() || &bytes[..MAGIC.len()] != MAGIC {
        return out;
    }
    let mut at = MAGIC.len();
    while at + 8 <= bytes.len() {
        let length = u32::from_be_bytes([bytes[at], bytes[at + 1], bytes[at + 2], bytes[at + 3]]) as usize;
        let kind = &bytes[at + 4..at + 8];
        let start = at + 8;
        let end = match start.checked_add(length) {
            Some(e) if e <= bytes.len() => e,
            _ => break,
        };
        if kind == b"tEXt" {
            let body = &bytes[start..end];
            if let Some(split) = body.iter().position(|b| *b == 0) {
                out.push((
                    String::from_utf8_lossy(&body[..split]).into_owned(),
                    String::from_utf8_lossy(&body[split + 1..]).into_owned(),
                ));
            }
        }
        if kind == b"IEND" {
            break;
        }
        //: length, type, data, then the four byte checksum.
        at = end + 4;
    }
    out
}

/// The largest file worth opening for this. Past it a thumbnail costs more
/// than the row it decorates, and a folder of raw camera files would stall the
/// scroll it was meant to help.
pub const MAX_SOURCE_BYTES: u64 = 40 * 1024 * 1024;

/// The longest either converter gets. A malformed file that makes poppler or
/// ffmpeg sit there is a hung request otherwise, and in a service this small
/// one stuck worker is felt immediately.
const TOOL_TIMEOUT: Duration = Duration::from_secs(12);

/// What has to happen before there is a picture to scale down.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    /// The file is already an image.
    Image,
    /// Page one has to be rendered first.
    Pdf,
    /// A frame has to be pulled out first.
    Video,
    /// The cover inside the tag is the picture, when there is one.
    Audio,
}

impl Kind {
    pub fn name(self) -> &'static str {
        match self {
            Kind::Image => "image",
            Kind::Pdf => "pdf",
            Kind::Video => "video",
            Kind::Audio => "audio",
        }
    }

    /// What kind of thumbnail a name asks for, if any at all.
    ///
    /// The extension rather than the content, because the answer is needed
    /// before the file is opened: no thumbnail is the normal answer for most
    /// files, and it should cost a string comparison rather than a read.
    pub fn of_path(path: &Path) -> Option<Kind> {
        let ext = path.extension()?.to_str()?.to_ascii_lowercase();
        const IMAGE: &[&str] =
            &["png", "jpg", "jpeg", "gif", "bmp", "webp", "tiff", "tif", "ico", "avif"];
        const VIDEO: &[&str] =
            &["mp4", "mkv", "mov", "webm", "avi", "m4v", "mpg", "mpeg", "ogv"];
        if ext == "pdf" {
            return Some(Kind::Pdf);
        }
        if IMAGE.contains(&ext.as_str()) {
            return Some(Kind::Image);
        }
        if VIDEO.contains(&ext.as_str()) {
            return Some(Kind::Video);
        }
        //: The cover module's list rather than a second copy of it, so a
        //: format that gains a cover writer gains a thumbnail with it.
        if crate::cover::is_sound(path) {
            return Some(Kind::Audio);
        }
        None
    }
}

/// A directory holding one converted frame, removed when this goes out of
/// scope. The converters write files rather than to a pipe, so there has to be
/// somewhere for them to write, and it has to go away on every path out of
/// here including the ones that failed.
struct Staged {
    dir: PathBuf,
    png: PathBuf,
}

impl Drop for Staged {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

impl Staged {
    /// Turn a PDF or a video into a PNG, which the rest of this can then treat
    /// as any other image.
    fn render(path: &Path, kind: Kind) -> Result<Staged> {
        if kind == Kind::Audio {
            return Staged::cover(path);
        }
        let (tool, stem) = match kind {
            Kind::Pdf => ("pdftoppm", "page"),
            Kind::Video => ("ffmpeg", "frame"),
            Kind::Image => return Err(Error::BadRequest("an image needs no converter".into())),
            Kind::Audio => unreachable!("a cover was taken above"),
        };
        let found = crate::apps::which(tool)
            .ok_or_else(|| Error::Tool { tool: tool.into(), message: "not installed".into() })?;

        //: Built before the command so that every early return below has the
        //: directory already under a guard.
        let mut staged = Staged { dir: staging_dir()?, png: PathBuf::new() };

        let mut cmd = Command::new(&found);
        cmd.current_dir(&staged.dir);
        match kind {
            //: One page, at the resolution a screen shows it at, so poppler is
            //: never asked to rasterise a poster at print size.
            Kind::Pdf => {
                cmd.args(["-png", "-f", "1", "-l", "1", "-r", "72"]).arg(path).arg(stem);
            }
            //: A second in, because the first frame of a great many videos is
            //: black, and a wall of black thumbnails is worse than none.
            Kind::Video => {
                cmd.args(["-nostdin", "-loglevel", "error", "-ss", "1", "-i"])
                    .arg(path)
                    .args(["-frames:v", "1", "-f", "image2", "frame.png"]);
            }
            Kind::Image | Kind::Audio => unreachable!("neither reaches a converter"),
        }
        cmd.stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null());

        if !run_bounded(cmd, TOOL_TIMEOUT) {
            return Err(Error::Tool { tool: tool.into(), message: "did not finish".into() });
        }
        //: The exit status is deliberately not consulted. Both tools report a
        //: failure over files they nonetheless managed to draw, and the
        //: question here is whether there is a picture, not whether the tool
        //: was happy about it.
        let png = png_named(&staged.dir, stem)
            .ok_or_else(|| Error::Tool { tool: tool.into(), message: "produced no image".into() })?;
        staged.png = png;
        Ok(staged)
    }

    /// The picture inside a sound file's tag, written out where the decoder
    /// below can open it. No converter runs: the cover is already an image,
    /// in whatever format the tag stored, and the decoder reads the bytes to
    /// tell which.
    fn cover(path: &Path) -> Result<Staged> {
        let found = crate::cover::read(path)?.ok_or_else(|| {
            Error::Unsupported(format!(
                "{} has no cover",
                path.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default()
            ))
        })?;
        let mut staged = Staged { dir: staging_dir()?, png: PathBuf::new() };
        let out = staged.dir.join("cover");
        std::fs::write(&out, &found.bytes).map_err(|e| Error::io(out.display().to_string(), e))?;
        staged.png = out;
        Ok(staged)
    }
}

/// Run a converter, killing it if it outstays the deadline. True means it
/// exited on its own, whatever it exited with.
fn run_bounded(mut cmd: Command, limit: Duration) -> bool {
    let Ok(mut child) = cmd.spawn() else { return false };
    let deadline = Instant::now() + limit;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return true,
            Ok(None) => {}
            Err(_) => return false,
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            //: Reaped, not merely signalled. One zombie per malformed file adds
            //: up in a process that stays running for the life of the session.
            let _ = child.wait();
            return false;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

/// The PNG a converter left behind. Found rather than predicted, because the
/// tools disagree about the name: pdftoppm appends the page number to the stem
/// it was handed.
fn png_named(dir: &Path, stem: &str) -> Option<PathBuf> {
    let mut names: Vec<std::ffi::OsString> = std::fs::read_dir(dir)
        .ok()?
        .filter_map(|e| e.ok())
        .map(|e| e.file_name())
        .filter(|name| {
            let name = name.to_string_lossy();
            name.starts_with(stem) && name.to_ascii_lowercase().ends_with(".png")
        })
        .collect();
    //: Sorted so that a multi page render, if one ever slips through, gives
    //: page one rather than whichever the directory happened to list first.
    names.sort();
    Some(dir.join(names.first()?))
}

/// A directory of our own to convert into. Created rather than reused, so a
/// converter never writes into something that was already sitting there under
/// that name.
fn staging_dir() -> Result<PathBuf> {
    use std::os::unix::fs::DirBuilderExt;
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let base = std::env::temp_dir();
    let mut last: Option<std::io::Error> = None;
    for _ in 0..8 {
        let n = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let dir = base.join(format!("auradefs-thumb-{}-{nanos}-{n}", std::process::id()));
        //: create fails if the name is taken, which is the point: the converter
        //: writes into a directory this process made, at a mode only this user
        //: can read.
        match std::fs::DirBuilder::new().mode(0o700).create(&dir) {
            Ok(()) => return Ok(dir),
            Err(e) => last = Some(e),
        }
    }
    Err(Error::Tool {
        tool: "staging".into(),
        message: last.map(|e| e.to_string()).unwrap_or_else(|| "no directory".into()),
    })
}

/// Make a thumbnail and put it in the cache, returning where it went.
///
/// An image is decoded directly. A PDF and a video are not images, so a
/// converter turns one into a picture first and everything past that point is
/// identical: one cache entry, keyed on the original file, whatever it was.
pub fn generate(path: &Path, size: Size) -> Result<PathBuf> {
    use std::os::unix::fs::MetadataExt;
    let stat = std::fs::metadata(path).map_err(|e| Error::io(path.display().to_string(), e))?;
    if stat.is_dir() {
        return Err(Error::BadRequest("a folder has no thumbnail".into()));
    }
    if stat.len() > MAX_SOURCE_BYTES {
        return Err(Error::Unsupported(format!(
            "{} is too large to thumbnail",
            path.display()
        )));
    }

    let staged = match Kind::of_path(path).unwrap_or(Kind::Image) {
        Kind::Image => None,
        //: A sound file with no cover is the ordinary case, and one worth
        //: remembering: the failure entry carries the file's time and size,
        //: so a cover added later is seen and a folder of untagged tracks is
        //: not reopened on every scroll.
        Kind::Audio => match Staged::render(path, Kind::Audio) {
            Ok(staged) => Some(staged),
            Err(Error::Unsupported(why)) => {
                let _ = mark_failed(path, stat.mtime());
                return Err(Error::Unsupported(why));
            }
            Err(e) => return Err(e),
        },
        other => Some(Staged::render(path, other)?),
    };
    let source: &Path = staged.as_ref().map(|s| s.png.as_path()).unwrap_or(path);

    let decoded = image::ImageReader::open(source)
        .map_err(|e| Error::io(source.display().to_string(), e))?
        .with_guessed_format()
        .map_err(|e| Error::io(source.display().to_string(), e))?
        .into_decoder()
        .and_then(|mut decoder| {
            //: A phone stores its photographs one way round and writes down
            //: which way up they are meant to be shown. Ignoring that note
            //: puts about a third of a camera roll on its side, and it is what
            //: makes turning a picture by rewriting the note look like it did
            //: nothing at all.
            let facing = image::ImageDecoder::orientation(&mut decoder)
                .unwrap_or(image::metadata::Orientation::NoTransforms);
            let mut picture = image::DynamicImage::from_decoder(decoder)?;
            picture.apply_orientation(facing);
            Ok(picture)
        });
    let decoded = match decoded {
        Ok(d) => d,
        Err(e) => {
            //: Record the failure so the next scroll past this row does not
            //: pay for the same decode again.
            let _ = mark_failed(path, stat.mtime());
            return Err(Error::Unsupported(format!(
                "{}: {e}",
                path.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default()
            )));
        }
    };

    let edge = size.pixels();
    //: Never scaled up. A sixteen pixel icon made into a 256 pixel thumbnail
    //: is a blurred sixteen pixel icon, and the view can enlarge it itself if
    //: it wants to.
    let small = if decoded.width() <= edge && decoded.height() <= edge {
        decoded
    } else {
        image::DynamicImage::ImageRgba8(image::imageops::thumbnail(
            &decoded.to_rgba8(),
            fit(decoded.width(), decoded.height(), edge).0,
            fit(decoded.width(), decoded.height(), edge).1,
        ))
    };

    let out = cache_path(path, size)?;
    write_png(
        &out,
        &small.to_rgba8(),
        &[
            ("Thumb::URI".into(), crate::apps::file_url(path)),
            ("Thumb::MTime".into(), stat.mtime().to_string()),
            ("Thumb::Size".into(), stat.len().to_string()),
        ],
    )?;
    Ok(out)
}

/// The size that fits inside a square of `edge`, keeping the proportions and
/// never going below one pixel.
fn fit(width: u32, height: u32, edge: u32) -> (u32, u32) {
    if width == 0 || height == 0 {
        return (1, 1);
    }
    if width >= height {
        let h = (height as u64 * edge as u64 / width as u64).max(1) as u32;
        (edge, h)
    } else {
        let w = (width as u64 * edge as u64 / height as u64).max(1) as u32;
        (w, edge)
    }
}

/// Note that this file cannot be thumbnailed.
pub fn mark_failed(path: &Path, mtime: i64) -> Result<PathBuf> {
    let size = std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);
    let out = thumb_root()?.join("fail").join(FAIL_OWNER).join(key(path));
    //: A one pixel transparent image. The specification wants a valid PNG here
    //: rather than an empty file, so that a reader can find the metadata.
    let pixel = image::RgbaImage::from_pixel(1, 1, image::Rgba([0, 0, 0, 0]));
    write_png(
        &out,
        &pixel,
        &[
            ("Thumb::URI".into(), crate::apps::file_url(path)),
            ("Thumb::MTime".into(), mtime.to_string()),
            ("Thumb::Size".into(), size.to_string()),
        ],
    )?;
    Ok(out)
}

/// Write a PNG with the metadata chunks, through a temporary file so a reader
/// never sees a half written thumbnail.
///
/// The cache holds thumbnails of files the user may not want anyone else to
/// see, so the directory is theirs alone and so is the file. The specification
/// requires exactly this.
fn write_png(out: &Path, image: &image::RgbaImage, text: &[(String, String)]) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let dir = out
        .parent()
        .ok_or_else(|| Error::BadRequest("no directory for the thumbnail".into()))?;
    std::fs::create_dir_all(dir).map_err(|e| Error::io(dir.display().to_string(), e))?;
    let _ = std::fs::set_permissions(dir, std::fs::Permissions::from_mode(0o700));

    let tmp = out.with_extension(format!("tmp{}", std::process::id()));
    {
        let file = std::fs::File::create(&tmp).map_err(|e| Error::io(tmp.display().to_string(), e))?;
        let _ = file.set_permissions(std::fs::Permissions::from_mode(0o600));
        let mut writer = std::io::BufWriter::new(file);
        let mut encoder = png::Encoder::new(&mut writer, image.width(), image.height());
        encoder.set_color(png::ColorType::Rgba);
        encoder.set_depth(png::BitDepth::Eight);
        for (key, value) in text {
            encoder
                .add_text_chunk(key.clone(), value.clone())
                .map_err(|e| Error::Tool { tool: "png".into(), message: e.to_string() })?;
        }
        let mut png_writer = encoder
            .write_header()
            .map_err(|e| Error::Tool { tool: "png".into(), message: e.to_string() })?;
        png_writer
            .write_image_data(image.as_raw())
            .map_err(|e| Error::Tool { tool: "png".into(), message: e.to_string() })?;
        png_writer
            .finish()
            .map_err(|e| Error::Tool { tool: "png".into(), message: e.to_string() })?;
        writer.flush().map_err(|e| Error::io(tmp.display().to_string(), e))?;
    }
    std::fs::rename(&tmp, out).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        Error::io(out.display().to_string(), e)
    })
}

/// Get a thumbnail, making one if the cache does not have a valid one. This is
/// the call a view makes; everything else here exists to serve it.
pub fn thumbnail(path: &Path, size: Size) -> Result<Option<PathBuf>> {
    if let Some(found) = cached(path, size)? {
        return Ok(Some(found));
    }
    if failed(path)? {
        return Ok(None);
    }
    match generate(path, size) {
        Ok(made) => Ok(Some(made)),
        Err(Error::Unsupported(_)) => Ok(None),
        Err(e) => Err(e),
    }
}

/// Remove every cached thumbnail for a path, at every size. Used when a file is
/// deleted, and by the Clear thumbnail cache action.
pub fn forget(path: &Path) -> Result<()> {
    let name = key(path);
    let root = thumb_root()?;
    for size in [Size::Normal, Size::Large, Size::XLarge, Size::XxLarge] {
        let _ = std::fs::remove_file(root.join(size.dir_name()).join(&name));
    }
    let _ = std::fs::remove_file(root.join("fail").join(FAIL_OWNER).join(&name));
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(tag: &str) -> PathBuf {
        let base = std::env::temp_dir().join(format!("auradefs-thumbs-{tag}"));
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(base.join("cache")).unwrap();
        std::fs::create_dir_all(base.join("files")).unwrap();
        base
    }

    /// A PDF small enough to sit in a test, valid enough for poppler: one page
    /// of a blue rectangle on white, at 200 by 100 points.
    fn mini_pdf() -> Vec<u8> {
        let body = b"0 0 1 rg 10 10 180 80 re f";
        let objects: Vec<Vec<u8>> = vec![
            b"<</Type/Catalog/Pages 2 0 R>>".to_vec(),
            b"<</Type/Pages/Kids[3 0 R]/Count 1>>".to_vec(),
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R>>".to_vec(),
            format!("<</Length {}>>\nstream\n", body.len())
                .into_bytes()
                .into_iter()
                .chain(body.iter().copied())
                .chain(b"\nendstream".iter().copied())
                .collect(),
        ];
        let mut out = b"%PDF-1.4\n".to_vec();
        let mut offsets = Vec::new();
        for (n, object) in objects.iter().enumerate() {
            offsets.push(out.len());
            out.extend_from_slice(format!("{} 0 obj\n", n + 1).as_bytes());
            out.extend_from_slice(object);
            out.extend_from_slice(b"\nendobj\n");
        }
        let xref = out.len();
        out.extend_from_slice(format!("xref\n0 {}\n", objects.len() + 1).as_bytes());
        out.extend_from_slice(b"0000000000 65535 f \n");
        for offset in &offsets {
            out.extend_from_slice(format!("{offset:010} 00000 n \n").as_bytes());
        }
        out.extend_from_slice(
            format!(
                "trailer\n<</Size {}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n",
                objects.len() + 1
            )
            .as_bytes(),
        );
        out
    }

    #[test]
    fn an_extension_says_what_has_to_happen_before_there_is_a_picture() {
        let kind = |name: &str| Kind::of_path(Path::new(name));
        assert_eq!(kind("holiday.JPG"), Some(Kind::Image), "the case is not the point");
        assert_eq!(kind("scan.png"), Some(Kind::Image));
        assert_eq!(kind("report.pdf"), Some(Kind::Pdf));
        assert_eq!(kind("clip.mp4"), Some(Kind::Video));
        assert_eq!(kind("clip.mkv"), Some(Kind::Video));
        assert_eq!(kind("track.mp3"), Some(Kind::Audio));
        assert_eq!(kind("track.FLAC"), Some(Kind::Audio));
        assert_eq!(kind("track.oga"), Some(Kind::Audio));
        assert_eq!(kind("clip.m4v"), Some(Kind::Video), "a video's picture is a frame, not its cover");
        //: The three that must not be pictures, because a thumbnail request
        //: for one of them is the common case and has to be cheap.
        assert_eq!(kind("notes.txt"), None);
        assert_eq!(kind("archive.tar.gz"), None);
        assert_eq!(kind("Makefile"), None);
        //: A name that only contains the word is not the extension.
        assert_eq!(kind("pdf"), None);
        assert_eq!(kind("mp4.notes"), None);
        assert_eq!(Kind::Pdf.name(), "pdf");
        assert_eq!(Kind::Video.name(), "video");
        assert_eq!(Kind::Image.name(), "image");
        assert_eq!(Kind::Audio.name(), "audio");
    }

    #[test]
    fn a_converter_that_never_finishes_is_killed_rather_than_waited_on() {
        let Some(sleep) = crate::apps::which("sleep") else { return };
        let mut cmd = Command::new(sleep);
        cmd.arg("30");
        cmd.stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null());
        let started = Instant::now();
        assert!(!run_bounded(cmd, Duration::from_millis(200)), "a killed run is not a success");
        let took = started.elapsed();
        assert!(took < Duration::from_secs(5), "waited {took:?}, so it was not killed");
    }

    #[test]
    fn a_converter_that_exits_badly_still_counts_as_finished() {
        //: Both tools report failure over files they nonetheless drew, so what
        //: is being asked here is whether it stopped, not whether it was happy.
        let Some(shell) = crate::apps::which("sh") else { return };
        let mut cmd = Command::new(shell);
        cmd.args(["-c", "exit 3"]);
        assert!(run_bounded(cmd, Duration::from_secs(5)));
    }

    #[test]
    fn the_page_number_pdftoppm_appends_does_not_hide_the_file() {
        let base = scratch("named");
        let dir = base.join("files");
        std::fs::write(dir.join("page-1.png"), b"x").unwrap();
        std::fs::write(dir.join("page-2.png"), b"x").unwrap();
        std::fs::write(dir.join("page.log"), b"x").unwrap();
        assert_eq!(png_named(&dir, "page"), Some(dir.join("page-1.png")), "page one, in order");
        assert_eq!(png_named(&dir, "frame"), None, "a stem that made nothing");

        let empty = base.join("empty");
        std::fs::create_dir_all(&empty).unwrap();
        assert_eq!(png_named(&empty, "page"), None);
        assert_eq!(png_named(&base.join("gone"), "page"), None, "a missing directory is not a panic");
    }

    #[test]
    fn a_staging_directory_is_ours_alone_and_does_not_outlive_the_render() {
        let one = staging_dir().unwrap();
        let two = staging_dir().unwrap();
        assert_ne!(one, two, "two renders at once must not share a directory");
        use std::os::unix::fs::PermissionsExt;
        let mode = std::fs::metadata(&one).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o700, "the frame is readable by this user and nobody else");

        let kept = one.clone();
        {
            let staged = Staged { dir: one, png: PathBuf::new() };
            std::fs::write(staged.dir.join("frame.png"), b"x").unwrap();
            assert!(kept.exists());
        }
        assert!(!kept.exists(), "the frame outlived the render");
        let _ = std::fs::remove_dir_all(&two);
    }

    #[test]
    fn a_pdf_is_thumbnailed_from_its_first_page() {
        if crate::apps::which("pdftoppm").is_none() {
            return;
        }
        let base = scratch("pdf");
        let file = base.join("files").join("doc.pdf");
        std::fs::write(&file, mini_pdf()).unwrap();
        let made = with_cache(&base, || thumbnail(&file, Size::Normal)).unwrap();
        let made = made.expect("a PDF with a converter present gets a thumbnail");
        let picture = image::open(&made).unwrap();
        assert!(picture.width() <= 128 && picture.height() <= 128, "not scaled down");

        //: The page really was rendered, not merely a blank of the right size.
        //: The rectangle is blue and covers the middle of a 200 by 100 page.
        let rgb = picture.to_rgb8();
        let middle = rgb.get_pixel(rgb.width() / 2, rgb.height() / 2);
        assert!(middle[2] > 150 && middle[0] < 90, "middle pixel is {middle:?}, not the rectangle");

        //: Cached against the PDF itself, so the next scroll past the row does
        //: not run poppler again.
        let again = with_cache(&base, || cached(&file, Size::Normal)).unwrap();
        assert_eq!(again, Some(made));
    }

    #[test]
    fn a_video_is_thumbnailed_from_a_frame_a_second_in() {
        let Some(ffmpeg) = crate::apps::which("ffmpeg") else { return };
        let base = scratch("video");
        let file = base.join("files").join("clip.mp4");
        let made = Command::new(ffmpeg)
            .args(["-nostdin", "-loglevel", "error", "-f", "lavfi", "-i"])
            .arg("testsrc=size=320x240:rate=10:duration=2")
            .args(["-pix_fmt", "yuv420p", "-y"])
            .arg(&file)
            .status();
        if !matches!(made, Ok(status) if status.success()) {
            return;
        }
        let thumb = with_cache(&base, || thumbnail(&file, Size::Normal)).unwrap();
        let thumb = thumb.expect("a video with ffmpeg present gets a thumbnail");
        let picture = image::open(&thumb).unwrap();
        assert!(picture.width() <= 128 && picture.height() <= 128);
        //: A frame, not a black rectangle: the test pattern is bright, and a
        //: seek that landed nowhere would give a uniform image.
        let rgb = picture.to_rgb8();
        let bright = rgb.pixels().filter(|p| p[0] as u16 + p[1] as u16 + p[2] as u16 > 240).count();
        assert!(bright > 32, "only {bright} lit pixels, so the frame is blank");
    }

    #[test]
    fn a_sound_file_is_pictured_by_its_cover_and_forgotten_without_one() {
        let base = scratch("cover");
        let Some(ffmpeg) = crate::apps::which("ffmpeg") else { return };
        let file = base.join("files").join("silence.mp3");
        let made = std::process::Command::new(ffmpeg)
            .args(["-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "0.5"])
            .arg(&file)
            .status();
        if !matches!(made, Ok(status) if status.success()) {
            return;
        }
        //: No cover: no thumbnail, and a failure entry so the next scroll
        //: past the row does not open the file again.
        let none = with_cache(&base, || thumbnail(&file, Size::Normal)).unwrap();
        assert!(none.is_none(), "a track with no cover has no picture");
        assert!(with_cache(&base, || failed(&file)).unwrap(), "and the miss is remembered");

        //: A cover, added a moment later. The file's time and size change
        //: with it, which is what lets the failure entry go stale.
        let art = base.join("files").join("art.png");
        let mut img = image::RgbImage::new(40, 30);
        for (x, _, pixel) in img.enumerate_pixels_mut() {
            *pixel = image::Rgb([250, (x * 6) as u8, 20]);
        }
        img.save(&art).unwrap();
        crate::cover::change(&file, &art).unwrap();
        let thumb = with_cache(&base, || thumbnail(&file, Size::Normal)).unwrap();
        let thumb = thumb.expect("a track with a cover gets a thumbnail");
        let picture = image::open(&thumb).unwrap().to_rgb8();
        assert_eq!((picture.width(), picture.height()), (40, 30), "small art is not scaled up");
        let red = picture.pixels().filter(|p| p[0] > 200 && p[2] < 60).count();
        assert_eq!(red, 40 * 30, "the picture is the cover, not a frame or a glyph");
        assert!(!with_cache(&base, || failed(&file)).unwrap(), "the stale miss no longer counts");
    }

    #[test]
    fn a_file_that_is_not_an_image_is_never_handed_to_a_converter() {
        let base = scratch("noconv");
        let file = base.join("files").join("notes.txt");
        std::fs::write(&file, b"not a picture").unwrap();
        //: An unknown extension falls through to the decoder, which refuses it.
        //: What must not happen is poppler or ffmpeg being run over it.
        let out = with_cache(&base, || thumbnail(&file, Size::Normal)).unwrap();
        assert!(out.is_none());
        let Err(err) = Staged::render(&file, Kind::Image) else {
            panic!("an image was handed to a converter");
        };
        assert_eq!(err.code(), "bad-request");
    }

    /// Point the cache at a scratch directory for one test. These run one at a
    /// time because the variable is process wide.
    fn with_cache<T>(base: &Path, body: impl FnOnce() -> T) -> T {
        static LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
        let _guard = LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let before = std::env::var("XDG_CACHE_HOME").ok();
        unsafe { std::env::set_var("XDG_CACHE_HOME", base.join("cache")) };
        let out = body();
        unsafe {
            match before {
                Some(v) => std::env::set_var("XDG_CACHE_HOME", v),
                None => std::env::remove_var("XDG_CACHE_HOME"),
            }
        }
        out
    }

    fn sample(path: &Path, w: u32, h: u32) {
        let mut img = image::RgbaImage::new(w, h);
        for (x, y, pixel) in img.enumerate_pixels_mut() {
            *pixel = image::Rgba([(x % 256) as u8, (y % 256) as u8, 128, 255]);
        }
        img.save(path).unwrap();
    }

    #[test]
    fn the_cache_name_is_the_md5_of_the_uri() {
        //: The URI from the specification's own example. The digest is of the
        //: URI and not of the path, which is the part that has to match what
        //: every other program computes.
        assert_eq!(
            key(Path::new("/home/jens/photo/me.png")),
            "d40775e596682f2a16d1b834c221c0a2.png"
        );
        assert_eq!(
            key(Path::new("/home/cam/a b.png")),
            key(Path::new("/home/cam/a b.png")),
        );
        assert!(key(Path::new("/a")).ends_with(".png"));
        assert_ne!(key(Path::new("/a")), key(Path::new("/b")));
    }

    #[test]
    fn an_images_size_is_read_from_its_header() {
        let base = scratch("dimensions");
        let source = base.join("files/picture.png");
        sample(&source, 321, 123);
        assert_eq!(dimensions(&source), Some((321, 123)));
        let not_an_image = base.join("files/notes.txt");
        std::fs::write(&not_an_image, b"not a picture").unwrap();
        assert_eq!(dimensions(&not_an_image), None);
        assert_eq!(dimensions(&base.join("files/missing.png")), None);
    }

    #[test]
    fn a_size_is_chosen_without_scaling_anything_up() {
        assert_eq!(Size::for_display(64), Size::Normal);
        assert_eq!(Size::for_display(128), Size::Normal);
        assert_eq!(Size::for_display(129), Size::Large);
        assert_eq!(Size::for_display(500), Size::XLarge);
        //: Bigger than any defined size, so the largest one and no scaling up
        //: beyond it.
        assert_eq!(Size::for_display(600), Size::XxLarge);
        assert_eq!(Size::for_display(4000), Size::XxLarge);
    }

    #[test]
    fn fitting_keeps_the_proportions_and_never_reaches_zero() {
        assert_eq!(fit(1000, 500, 128), (128, 64));
        assert_eq!(fit(500, 1000, 128), (64, 128));
        assert_eq!(fit(1000, 1000, 128), (128, 128));
        //: An extremely wide image would round its height to nothing, and an
        //: image with a zero dimension is not one.
        assert_eq!(fit(10_000, 3, 128).1, 1);
        assert_eq!(fit(0, 0, 128), (1, 1));
    }

    #[test]
    fn a_generated_thumbnail_is_cached_validated_and_reused() {
        let base = scratch("roundtrip");
        let source = base.join("files/picture.png");
        sample(&source, 400, 200);

        with_cache(&base, || {
            assert_eq!(cached(&source, Size::Normal).unwrap(), None);
            let made = generate(&source, Size::Normal).unwrap();
            assert!(made.exists());

            let found = cached(&source, Size::Normal).unwrap().unwrap();
            assert_eq!(found, made);

            let decoded = image::open(&found).unwrap();
            assert_eq!((decoded.width(), decoded.height()), (128, 64));

            let text = png_text(&std::fs::read(&found).unwrap());
            assert!(text.iter().any(|(k, _)| k == "Thumb::URI"));
            assert!(text.iter().any(|(k, _)| k == "Thumb::MTime"));
        });
    }

    #[test]
    fn a_file_edited_in_place_invalidates_its_thumbnail() {
        let base = scratch("stale");
        let source = base.join("files/picture.png");
        sample(&source, 100, 100);

        with_cache(&base, || {
            generate(&source, Size::Normal).unwrap();
            assert!(cached(&source, Size::Normal).unwrap().is_some());

            //: Same name, same URI, different contents. Only the recorded time
            //: catches this, which is the whole reason it is recorded.
            std::thread::sleep(std::time::Duration::from_millis(10));
            sample(&source, 100, 100);
            let when = std::time::SystemTime::now() + std::time::Duration::from_secs(60);
            std::fs::File::options()
                .write(true)
                .open(&source)
                .unwrap()
                .set_times(std::fs::FileTimes::new().set_modified(when))
                .unwrap();

            assert_eq!(
                cached(&source, Size::Normal).unwrap(),
                None,
                "a stale thumbnail was treated as valid"
            );
        });
    }

    #[test]
    fn a_thumbnail_belonging_to_another_file_is_not_used() {
        let base = scratch("wrong-uri");
        let source = base.join("files/picture.png");
        let other = base.join("files/other.png");
        sample(&source, 60, 60);
        sample(&other, 60, 60);

        with_cache(&base, || {
            generate(&source, Size::Normal).unwrap();
            //: Put the first file's thumbnail where the second's would be
            //: looked for. Only the recorded URI tells them apart.
            let from = cache_path(&source, Size::Normal).unwrap();
            let to = cache_path(&other, Size::Normal).unwrap();
            std::fs::copy(&from, &to).unwrap();
            assert_eq!(cached(&other, Size::Normal).unwrap(), None);
        });
    }

    #[test]
    fn a_small_image_is_never_enlarged() {
        let base = scratch("small");
        let source = base.join("files/icon.png");
        sample(&source, 32, 16);
        with_cache(&base, || {
            let made = generate(&source, Size::Large).unwrap();
            let decoded = image::open(&made).unwrap();
            assert_eq!((decoded.width(), decoded.height()), (32, 16));
        });
    }

    #[test]
    fn something_that_is_not_an_image_fails_once_and_is_remembered() {
        let base = scratch("fail");
        let source = base.join("files/notes.txt");
        std::fs::write(&source, b"this is not a picture").unwrap();

        with_cache(&base, || {
            assert!(!failed(&source).unwrap());
            let err = generate(&source, Size::Normal).unwrap_err();
            assert!(matches!(err, Error::Unsupported(_)), "got {err:?}");
            assert!(failed(&source).unwrap(), "the failure was not recorded");
            //: And the convenience call answers with nothing rather than an
            //: error, because a row with no thumbnail is a normal row.
            assert_eq!(thumbnail(&source, Size::Normal).unwrap(), None);
        });
    }

    #[test]
    fn a_changed_file_is_worth_trying_again() {
        let base = scratch("retry");
        let source = base.join("files/maybe.png");
        std::fs::write(&source, b"not yet a picture").unwrap();
        with_cache(&base, || {
            let _ = generate(&source, Size::Normal);
            assert!(failed(&source).unwrap());
            sample(&source, 40, 40);
            //: Second resolution means a rewrite inside the same second looks
            //: unchanged by time alone; the size is what catches it here, and
            //: moving the time proves the other half.
            assert!(!failed(&source).unwrap(), "the size change was not noticed");
            let when = std::time::SystemTime::now() + std::time::Duration::from_secs(60);
            std::fs::File::options()
                .write(true)
                .open(&source)
                .unwrap()
                .set_times(std::fs::FileTimes::new().set_modified(when))
                .unwrap();
            assert!(!failed(&source).unwrap(), "the old failure still applied");
            assert!(thumbnail(&source, Size::Normal).unwrap().is_some());
        });
    }

    #[test]
    fn the_cache_is_readable_only_by_its_owner() {
        use std::os::unix::fs::PermissionsExt;
        let base = scratch("modes");
        let source = base.join("files/private.png");
        sample(&source, 50, 50);
        with_cache(&base, || {
            let made = generate(&source, Size::Normal).unwrap();
            let file = std::fs::metadata(&made).unwrap().permissions().mode() & 0o777;
            let dir = std::fs::metadata(made.parent().unwrap()).unwrap().permissions().mode() & 0o777;
            assert_eq!(file, 0o600, "a thumbnail was readable by others");
            assert_eq!(dir, 0o700, "the thumbnail directory was readable by others");
        });
    }

    #[test]
    fn forgetting_removes_every_size_and_the_failure_record() {
        let base = scratch("forget");
        let source = base.join("files/picture.png");
        sample(&source, 300, 300);
        with_cache(&base, || {
            generate(&source, Size::Normal).unwrap();
            generate(&source, Size::Large).unwrap();
            mark_failed(&source, 0).unwrap();
            forget(&source).unwrap();
            assert!(!cache_path(&source, Size::Normal).unwrap().exists());
            assert!(!cache_path(&source, Size::Large).unwrap().exists());
            assert!(!failed(&source).unwrap());
        });
    }

    #[test]
    fn the_text_reader_walks_chunks_rather_than_guessing_at_offsets() {
        //: Not a PNG at all.
        assert!(png_text(b"just some bytes").is_empty());
        //: A truncated chunk length must not read past the end.
        let mut broken = b"\x89PNG\r\n\x1a\n".to_vec();
        broken.extend_from_slice(&[0xff, 0xff, 0xff, 0xff]);
        broken.extend_from_slice(b"tEXt");
        assert!(png_text(&broken).is_empty());
    }
}
