//! What the Details tab shows beyond what the filesystem knows.
//!
//! The reference reads this out of the Windows property system, which has a
//! reader for every format the machine has a codec for. There is no such
//! thing here, so this does the two that matter: EXIF, parsed in this file,
//! and everything ffprobe knows about a media file, when ffprobe is installed.
//!
//! EXIF is parsed rather than pulled in as a dependency because it is a small
//! format and a large attack surface. Every offset in it is a number in the
//! file, pointing anywhere the file likes, and a reader that trusts them will
//! read out of bounds on a crafted photograph. So every read here is range
//! checked and returns None instead of panicking, the walk follows a fixed
//! number of directories, and nothing is allocated in proportion to a length
//! the file claims.

use std::path::Path;
use std::process::Command;

use serde::Serialize;

use crate::error::Result;

/// The longest ffprobe gets. It reads a header, so anything slower than this
/// is a file it is going to struggle with anyway.
const PROBE_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(10);

// ------------------------------------------------------------------ photos ---

/// What a photograph says about itself.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Photo {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub width: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub height: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub camera: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub lens: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub software: Option<String>,
    /// When the shutter fired, as `2026-09-08 21:04:11`. EXIF writes colons
    /// where a date has dashes, which no other reader on the desktop expects.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub taken: Option<String>,
    /// 1 to 8. The picture is stored one way up and meant to be shown another,
    /// and a viewer that ignores this shows a third of all phone photographs
    /// on their side.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub orientation: Option<u16>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub exposure: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub aperture: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub iso: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub focal_length: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub artist: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub copyright: Option<String>,
    /// Degrees, north and east positive. Worth showing precisely because a
    /// photograph carrying one is a fact about the person who took it.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub latitude: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub longitude: Option<f64>,
}

impl Photo {
    /// Whether anything was found. An empty set is not worth a tab.
    pub fn is_empty(&self) -> bool {
        *self == Photo::default()
    }
}

/// The largest header this will read. EXIF lives at the front of a file and
/// the whole segment is capped at 64 KB by the JPEG format itself; a TIFF can
/// put its directory anywhere, so this is where the reading stops.
const MAX_HEADER: usize = 4 * 1024 * 1024;

/// Read the EXIF a file carries, if it carries any.
pub fn photo(path: &Path) -> Result<Option<Photo>> {
    let bytes = read_head(path, MAX_HEADER)?;
    Ok(exif_of(&bytes))
}

fn read_head(path: &Path, limit: usize) -> Result<Vec<u8>> {
    use std::io::Read;
    let file = std::fs::File::open(path)
        .map_err(|e| crate::error::Error::io(path.display().to_string(), e))?;
    let mut out = Vec::new();
    file.take(limit as u64)
        .read_to_end(&mut out)
        .map_err(|e| crate::error::Error::io(path.display().to_string(), e))?;
    Ok(out)
}

/// Parse whatever EXIF is in these bytes. Public for the tests, and because a
/// caller that already has the bytes should not have to write them out first.
pub fn exif_of(bytes: &[u8]) -> Option<Photo> {
    let tiff = find_tiff(bytes)?;
    let reader = Tiff::open(tiff)?;
    let mut photo = Photo::default();

    let mut make: Option<String> = None;
    let mut model: Option<String> = None;
    let mut date_time: Option<String> = None;

    let mut exif_ifd = None;
    let mut gps_ifd = None;
    for entry in reader.entries(reader.first_ifd) {
        match entry.tag {
            0x010F => make = reader.text(&entry),
            0x0110 => model = reader.text(&entry),
            0x0112 => photo.orientation = reader.number(&entry).map(|n| n as u16),
            0x0131 => photo.software = reader.text(&entry),
            0x0132 => date_time = reader.text(&entry),
            0x013B => photo.artist = reader.text(&entry),
            0x8298 => photo.copyright = reader.text(&entry),
            0x8769 => exif_ifd = reader.number(&entry).map(|n| n as usize),
            0x8825 => gps_ifd = reader.number(&entry).map(|n| n as usize),
            _ => {}
        }
    }

    let mut taken: Option<String> = None;
    if let Some(at) = exif_ifd {
        for entry in reader.entries(at) {
            match entry.tag {
                0x829A => photo.exposure = reader.rational(&entry).map(as_shutter),
                0x829D => photo.aperture = reader.rational(&entry).map(|v| format!("f/{}", trim(v))),
                0x8827 => photo.iso = reader.number(&entry),
                0x9003 => taken = reader.text(&entry),
                0x920A => {
                    photo.focal_length = reader.rational(&entry).map(|v| format!("{} mm", trim(v)))
                }
                0xA002 => photo.width = reader.number(&entry),
                0xA003 => photo.height = reader.number(&entry),
                0xA434 => photo.lens = reader.text(&entry),
                _ => {}
            }
        }
    }
    //: DateTimeOriginal is when the shutter fired; DateTime is when the file
    //: was last written, which an edit changes. Prefer the first and fall back.
    photo.taken = taken.or(date_time).map(normalise_date);

    if let Some(at) = gps_ifd {
        let (mut lat, mut lat_ref, mut lon, mut lon_ref) = (None, None, None, None);
        for entry in reader.entries(at) {
            match entry.tag {
                0x0001 => lat_ref = reader.text(&entry),
                0x0002 => lat = reader.degrees(&entry),
                0x0003 => lon_ref = reader.text(&entry),
                0x0004 => lon = reader.degrees(&entry),
                _ => {}
            }
        }
        photo.latitude = lat.map(|d| signed(d, lat_ref.as_deref(), "S"));
        photo.longitude = lon.map(|d| signed(d, lon_ref.as_deref(), "W"));
    }

    photo.camera = match (make, model) {
        (Some(make), Some(model)) if model.starts_with(&make) => Some(model),
        (Some(make), Some(model)) => Some(format!("{make} {model}")),
        (make, model) => make.or(model),
    };
    if photo.is_empty() { None } else { Some(photo) }
}

/// Where the orientation tag's value sits in these bytes, and what it says.
///
/// An offset rather than a value, so a caller can change it in place. Turning
/// a photograph by rewriting those two bytes keeps everything else the camera
/// recorded and touches not one pixel, which is the difference between
/// rotating a picture and re-encoding it.
pub fn orientation_at(bytes: &[u8]) -> Option<(usize, bool, u16)> {
    let (start, end) = find_tiff_at(bytes)?;
    let reader = Tiff::open(bytes.get(start..end)?)?;
    for entry in reader.entries(reader.first_ifd) {
        //: SHORT, one of them, so the value is in the entry itself and the
        //: first two of its four bytes are the number.
        if entry.tag == 0x0112 && entry.kind == 3 && entry.count == 1 {
            let value = reader.u16_at(entry.at)?;
            return Some((start + entry.at, reader.big_endian, value));
        }
    }
    None
}

/// Write an orientation back over the one already there.
///
/// Only over one that exists: the tag is stored inline in a fixed size entry,
/// so changing it is two bytes, and adding one would mean rebuilding every
/// offset in the directory that follows.
pub fn set_orientation(bytes: &mut [u8], value: u16) -> bool {
    let Some((at, big_endian, _)) = orientation_at(bytes) else { return false };
    let raw = if big_endian { value.to_be_bytes() } else { value.to_le_bytes() };
    let Some(slot) = bytes.get_mut(at..at + 2) else { return false };
    slot.copy_from_slice(&raw);
    true
}

/// Where the TIFF header starts, whatever is wrapped around it.
fn find_tiff(bytes: &[u8]) -> Option<&[u8]> {
    let (start, end) = find_tiff_at(bytes)?;
    bytes.get(start..end)
}

/// The half open range the TIFF block occupies.
///
/// The end matters as much as the start. Inside a JPEG the block is one
/// segment with a declared length, and an entry whose offset points past that
/// length is pointing at the compressed image, not at metadata. Reading it
/// would not be out of bounds, but it would be reporting picture bytes as if
/// the camera had written them there.
fn find_tiff_at(bytes: &[u8]) -> Option<(usize, usize)> {
    //: A TIFF, and everything built on one, is its own header.
    if bytes.starts_with(b"II\x2a\x00") || bytes.starts_with(b"MM\x00\x2a") {
        return Some((0, bytes.len()));
    }
    if !bytes.starts_with(&[0xFF, 0xD8]) {
        return None;
    }
    //: Walk the JPEG's segments to the APP1 that says Exif. Skipping by the
    //: declared length rather than scanning for the string, so that the same
    //: bytes appearing inside the image data are not mistaken for a header.
    let mut at = 2usize;
    loop {
        if at + 4 > bytes.len() || bytes[at] != 0xFF {
            return None;
        }
        let marker = bytes[at + 1];
        //: Start of scan: the compressed image follows and there are no more
        //: segments to read.
        if marker == 0xDA || marker == 0xD9 {
            return None;
        }
        let length = u16::from_be_bytes([bytes[at + 2], bytes[at + 3]]) as usize;
        if length < 2 {
            return None;
        }
        let body = at + 4;
        let end = body.checked_add(length - 2)?;
        if end > bytes.len() {
            return None;
        }
        if marker == 0xE1 && bytes[body..end].starts_with(b"Exif\0\0") {
            return Some((body + 6, end));
        }
        at = end;
    }
}

/// One directory entry, already located but not yet read.
struct Entry {
    tag: u16,
    kind: u16,
    count: u32,
    /// Where the four value bytes are. The value itself when it fits in them,
    /// an offset into the file when it does not.
    at: usize,
}

struct Tiff<'a> {
    bytes: &'a [u8],
    big_endian: bool,
    first_ifd: usize,
}

impl<'a> Tiff<'a> {
    fn open(bytes: &'a [u8]) -> Option<Tiff<'a>> {
        let big_endian = match bytes.get(..2)? {
            b"MM" => true,
            b"II" => false,
            _ => return None,
        };
        let reader = Tiff { bytes, big_endian, first_ifd: 0 };
        if reader.u16_at(2)? != 42 {
            return None;
        }
        let first_ifd = reader.u32_at(4)? as usize;
        Some(Tiff { first_ifd, ..reader })
    }

    fn u16_at(&self, at: usize) -> Option<u16> {
        let raw: [u8; 2] = self.bytes.get(at..at + 2)?.try_into().ok()?;
        Some(if self.big_endian { u16::from_be_bytes(raw) } else { u16::from_le_bytes(raw) })
    }

    fn u32_at(&self, at: usize) -> Option<u32> {
        let raw: [u8; 4] = self.bytes.get(at..at + 4)?.try_into().ok()?;
        Some(if self.big_endian { u32::from_be_bytes(raw) } else { u32::from_le_bytes(raw) })
    }

    /// The entries of one directory.
    ///
    /// Collected rather than returned lazily so the borrow ends here, and
    /// capped so that a count of four billion costs nothing: the vector grows
    /// as entries are read, never to the size the file asked for.
    fn entries(&self, at: usize) -> Vec<Entry> {
        const MAX_ENTRIES: usize = 512;
        let mut out = Vec::new();
        let Some(count) = self.u16_at(at) else { return out };
        for i in 0..(count as usize).min(MAX_ENTRIES) {
            let base = match at.checked_add(2 + i * 12) {
                Some(base) => base,
                None => break,
            };
            let (Some(tag), Some(kind), Some(count)) =
                (self.u16_at(base), self.u16_at(base + 2), self.u32_at(base + 4))
            else {
                break;
            };
            out.push(Entry { tag, kind, count, at: base + 8 });
        }
        out
    }

    /// Where an entry's bytes actually are, and how many there are.
    fn value(&self, entry: &Entry) -> Option<(usize, usize)> {
        let unit = match entry.kind {
            1 | 2 | 6 | 7 => 1,
            3 | 8 => 2,
            4 | 9 | 11 => 4,
            5 | 10 | 12 => 8,
            _ => return None,
        };
        let size = (entry.count as usize).checked_mul(unit)?;
        if size <= 4 {
            return Some((entry.at, size));
        }
        let at = self.u32_at(entry.at)? as usize;
        //: The one check that matters: the offset is a number in the file and
        //: points wherever the file says. Everything past here reads inside
        //: the slice or not at all.
        if at.checked_add(size)? > self.bytes.len() {
            return None;
        }
        Some((at, size))
    }

    fn text(&self, entry: &Entry) -> Option<String> {
        if entry.kind != 2 {
            return None;
        }
        let (at, size) = self.value(entry)?;
        let raw = self.bytes.get(at..at + size)?;
        let raw = raw.split(|b| *b == 0).next().unwrap_or(raw);
        let text = String::from_utf8_lossy(raw).trim().to_string();
        if text.is_empty() { None } else { Some(text) }
    }

    /// A single whole number, whichever width it was stored at.
    fn number(&self, entry: &Entry) -> Option<u32> {
        match entry.kind {
            3 => self.u16_at(self.value(entry)?.0).map(u32::from),
            4 => self.u32_at(self.value(entry)?.0),
            1 => self.bytes.get(self.value(entry)?.0).copied().map(u32::from),
            _ => None,
        }
    }

    fn rational(&self, entry: &Entry) -> Option<(u32, u32)> {
        if entry.kind != 5 && entry.kind != 10 {
            return None;
        }
        let (at, _) = self.value(entry)?;
        let top = self.u32_at(at)?;
        let bottom = self.u32_at(at + 4)?;
        if bottom == 0 { None } else { Some((top, bottom)) }
    }

    /// Three rationals, degrees then minutes then seconds, as one number.
    fn degrees(&self, entry: &Entry) -> Option<f64> {
        if entry.kind != 5 || entry.count < 3 {
            return None;
        }
        let (at, _) = self.value(entry)?;
        let mut total = 0.0;
        for (i, scale) in [1.0, 60.0, 3600.0].into_iter().enumerate() {
            let top = self.u32_at(at + i * 8)? as f64;
            let bottom = self.u32_at(at + i * 8 + 4)? as f64;
            if bottom == 0.0 {
                return None;
            }
            total += top / bottom / scale;
        }
        Some(total)
    }
}

/// A shutter speed the way a camera shows it: a fraction under a second, and
/// a plain number of seconds over one.
fn as_shutter((top, bottom): (u32, u32)) -> String {
    if top == 0 {
        return "0 s".into();
    }
    let value = top as f64 / bottom as f64;
    if value >= 1.0 {
        return format!("{} s", trim((top, bottom)));
    }
    format!("1/{}", (1.0 / value).round() as u64)
}

/// A rational as the shortest true decimal: 2.8 rather than 2.80, 50 rather
/// than 50.0.
fn trim((top, bottom): (u32, u32)) -> String {
    let value = top as f64 / bottom as f64;
    if (value - value.round()).abs() < 0.0005 {
        return format!("{}", value.round() as i64);
    }
    format!("{value:.1}")
}

fn normalise_date(raw: String) -> String {
    //: EXIF writes 2026:09:08 21:04:11, with colons where a date has dashes.
    //: Only the first two are the date; the rest are the time.
    let mut out = raw;
    for _ in 0..2 {
        if let Some(at) = out.find(':') {
            if at < 10 {
                out.replace_range(at..at + 1, "-");
            }
        }
    }
    out
}

fn signed(degrees: f64, reference: Option<&str>, negative: &str) -> f64 {
    if reference.map(|r| r.eq_ignore_ascii_case(negative)).unwrap_or(false) {
        -degrees
    } else {
        degrees
    }
}

// ------------------------------------------------------------------- media ---

/// What a video or a sound file says about itself.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Media {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bitrate: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub width: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub height: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub video_codec: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub audio_codec: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub frame_rate: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub channels: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sample_rate: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub artist: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub album: Option<String>,
}

impl Media {
    pub fn is_empty(&self) -> bool {
        *self == Media::default()
    }
}

/// Whether ffprobe is installed. The Details tab asks so it can leave the rows
/// out rather than show a set of empty ones.
pub fn can_probe() -> bool {
    crate::apps::which("ffprobe").is_some()
}

/// Whether the name says this is worth asking ffprobe about.
///
/// The name decides, not ffprobe, because ffprobe guesses hard: handed a text
/// file it finds the ansi demuxer, reports a 640 by 400 video stream at 25
/// frames a second, and is not wrong so much as answering a question nobody
/// asked. So a file is probed when it claims to be media and not otherwise.
pub fn is_media(path: &Path) -> bool {
    //: The video half is the thumbnailer's list rather than a second copy of
    //: it, so a format added there is probed here without anyone remembering.
    if crate::thumbs::Kind::of_path(path) == Some(crate::thumbs::Kind::Video) {
        return true;
    }
    let Some(ext) = path.extension().and_then(|e| e.to_str()) else { return false };
    const AUDIO: &[&str] = &[
        "mp3", "flac", "wav", "ogg", "oga", "opus", "m4a", "m4b", "aac", "wma", "aiff", "aif",
        "ape", "wv", "mka", "ac3", "dts", "amr", "mid", "midi",
    ];
    AUDIO.contains(&ext.to_ascii_lowercase().as_str())
}

/// Everything ffprobe knows about a file, or nothing when it is not installed,
/// not media, or nothing it recognises.
pub fn media(path: &Path) -> Result<Option<Media>> {
    if !is_media(path) {
        return Ok(None);
    }
    let Some(tool) = crate::apps::which("ffprobe") else { return Ok(None) };
    let mut command = Command::new(tool);
    command
        .args([
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-i",
        ])
        .arg(path)
        .stdin(std::process::Stdio::null());
    let Some(out) = run_bounded(command, PROBE_TIMEOUT) else { return Ok(None) };
    Ok(from_probe(&out))
}

/// Parse ffprobe's JSON. Separate from running it so the shape can be tested
/// without a media file and without the tool.
pub fn from_probe(json: &[u8]) -> Option<Media> {
    let root: serde_json::Value = serde_json::from_slice(json).ok()?;
    let mut media = Media::default();

    let format = root.get("format");
    if let Some(format) = format {
        media.duration = format.get("duration").and_then(text_number);
        media.bitrate = format.get("bit_rate").and_then(text_number).map(|v| v as u64);
        if let Some(tags) = format.get("tags") {
            media.title = tag(tags, "title");
            media.artist = tag(tags, "artist").or_else(|| tag(tags, "album_artist"));
            media.album = tag(tags, "album");
        }
    }

    for stream in root.get("streams").and_then(|s| s.as_array()).into_iter().flatten() {
        match stream.get("codec_type").and_then(|v| v.as_str()) {
            Some("video") => {
                //: The first video stream wins. A file with two is a file with
                //: a cover image in it, and the cover is not the video.
                if media.video_codec.is_some() {
                    continue;
                }
                media.video_codec =
                    stream.get("codec_name").and_then(|v| v.as_str()).map(str::to_string);
                media.width = stream.get("width").and_then(|v| v.as_u64()).map(|v| v as u32);
                media.height = stream.get("height").and_then(|v| v.as_u64()).map(|v| v as u32);
                media.frame_rate =
                    stream.get("avg_frame_rate").and_then(|v| v.as_str()).and_then(ratio);
            }
            Some("audio") => {
                if media.audio_codec.is_some() {
                    continue;
                }
                media.audio_codec =
                    stream.get("codec_name").and_then(|v| v.as_str()).map(str::to_string);
                media.channels = stream.get("channels").and_then(|v| v.as_u64()).map(|v| v as u32);
                media.sample_rate = stream.get("sample_rate").and_then(text_number).map(|v| v as u32);
            }
            _ => {}
        }
    }
    if media.is_empty() { None } else { Some(media) }
}

/// ffprobe writes numbers as strings in some fields and as numbers in others,
/// and which is which changes between versions.
fn text_number(value: &serde_json::Value) -> Option<f64> {
    value.as_f64().or_else(|| value.as_str()?.parse().ok())
}

/// `30000/1001` is how a frame rate is written. A zero denominator means the
/// stream has no fixed rate, which is not a rate of zero.
fn ratio(raw: &str) -> Option<f64> {
    let (top, bottom) = raw.split_once('/')?;
    let bottom: f64 = bottom.parse().ok()?;
    if bottom == 0.0 {
        return None;
    }
    Some(top.parse::<f64>().ok()? / bottom)
}

fn tag(tags: &serde_json::Value, name: &str) -> Option<String> {
    let found = tags
        .as_object()?
        .iter()
        //: Tag names are whatever the container felt like: TITLE in Matroska,
        //: title in MP4.
        .find(|(key, _)| key.eq_ignore_ascii_case(name))?
        .1
        .as_str()?
        .trim()
        .to_string();
    if found.is_empty() { None } else { Some(found) }
}

/// Run a tool with a deadline, returning its standard output when it finished
/// on its own and said something.
fn run_bounded(mut command: Command, limit: std::time::Duration) -> Option<Vec<u8>> {
    use std::io::Read;
    command.stdout(std::process::Stdio::piped()).stderr(std::process::Stdio::null());
    let mut child = command.spawn().ok()?;
    let deadline = std::time::Instant::now() + limit;
    //: Taken before the wait so the pipe is drained: a tool that fills the
    //: buffer would otherwise block forever waiting for someone to read it,
    //: and the deadline below would be the only thing that ended it.
    let mut stdout = child.stdout.take()?;
    let mut out = Vec::new();
    let reader = std::thread::spawn(move || {
        let _ = stdout.read_to_end(&mut out);
        out
    });
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => {}
            Err(_) => return None,
        }
        if std::time::Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return None;
        }
        std::thread::sleep(std::time::Duration::from_millis(20));
    }
    let out = reader.join().ok()?;
    if out.is_empty() { None } else { Some(out) }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A value as a camera would store it.
    enum Val {
        Ascii(&'static str),
        Short(u16),
        Long(u32),
        Rational(u32, u32),
        Rationals(Vec<(u32, u32)>),
    }

    impl Val {
        fn kind(&self) -> u16 {
            match self {
                Val::Ascii(_) => 2,
                Val::Short(_) => 3,
                Val::Long(_) => 4,
                Val::Rational(..) | Val::Rationals(_) => 5,
            }
        }

        fn count(&self) -> u32 {
            match self {
                Val::Ascii(s) => s.len() as u32 + 1,
                Val::Short(_) | Val::Long(_) | Val::Rational(..) => 1,
                Val::Rationals(v) => v.len() as u32,
            }
        }

        fn bytes(&self) -> Vec<u8> {
            match self {
                Val::Ascii(s) => {
                    let mut out = s.as_bytes().to_vec();
                    out.push(0);
                    out
                }
                Val::Short(v) => v.to_le_bytes().to_vec(),
                Val::Long(v) => v.to_le_bytes().to_vec(),
                Val::Rational(t, b) => {
                    let mut out = t.to_le_bytes().to_vec();
                    out.extend_from_slice(&b.to_le_bytes());
                    out
                }
                Val::Rationals(v) => v
                    .iter()
                    .flat_map(|(t, b)| {
                        let mut out = t.to_le_bytes().to_vec();
                        out.extend_from_slice(&b.to_le_bytes());
                        out
                    })
                    .collect(),
            }
        }
    }

    /// Build a little-endian TIFF block: the thing a camera writes, in
    /// miniature, so the parser is tested against a real layout rather than
    /// against itself.
    fn build_tiff(
        ifd0: Vec<(u16, Val)>,
        exif: Vec<(u16, Val)>,
        gps: Vec<(u16, Val)>,
    ) -> Vec<u8> {
        let block = |n: usize| 2 + 12 * n + 4;
        let n0 = ifd0.len() + usize::from(!exif.is_empty()) + usize::from(!gps.is_empty());
        let ifd0_at = 8usize;
        let exif_at = ifd0_at + block(n0);
        let gps_at = exif_at + if exif.is_empty() { 0 } else { block(exif.len()) };
        let heap_at = gps_at + if gps.is_empty() { 0 } else { block(gps.len()) };

        let mut heap: Vec<u8> = Vec::new();
        let write_ifd = |entries: &[(u16, Val)], extra: &[(u16, u32)], heap: &mut Vec<u8>| {
            let mut out = Vec::new();
            out.extend_from_slice(&((entries.len() + extra.len()) as u16).to_le_bytes());
            for (tag, value) in entries {
                out.extend_from_slice(&tag.to_le_bytes());
                out.extend_from_slice(&value.kind().to_le_bytes());
                out.extend_from_slice(&value.count().to_le_bytes());
                let mut raw = value.bytes();
                if raw.len() <= 4 {
                    raw.resize(4, 0);
                    out.extend_from_slice(&raw);
                } else {
                    out.extend_from_slice(&((heap_at + heap.len()) as u32).to_le_bytes());
                    heap.extend_from_slice(&raw);
                }
            }
            for (tag, at) in extra {
                out.extend_from_slice(&tag.to_le_bytes());
                out.extend_from_slice(&4u16.to_le_bytes());
                out.extend_from_slice(&1u32.to_le_bytes());
                out.extend_from_slice(&at.to_le_bytes());
            }
            out.extend_from_slice(&0u32.to_le_bytes());
            out
        };

        let mut pointers = Vec::new();
        if !exif.is_empty() {
            pointers.push((0x8769u16, exif_at as u32));
        }
        if !gps.is_empty() {
            pointers.push((0x8825u16, gps_at as u32));
        }
        let first = write_ifd(&ifd0, &pointers, &mut heap);
        let second = write_ifd(&exif, &[], &mut heap);
        let third = write_ifd(&gps, &[], &mut heap);

        let mut out = b"II\x2a\x00".to_vec();
        out.extend_from_slice(&(ifd0_at as u32).to_le_bytes());
        out.extend_from_slice(&first);
        if !exif.is_empty() {
            out.extend_from_slice(&second);
        }
        if !gps.is_empty() {
            out.extend_from_slice(&third);
        }
        assert_eq!(out.len(), heap_at, "the layout and the offsets disagree");
        out.extend_from_slice(&heap);
        out
    }

    fn as_jpeg(tiff: &[u8], decoy: bool) -> Vec<u8> {
        let mut out = vec![0xFF, 0xD8];
        if decoy {
            //: An earlier segment whose payload contains the same marker
            //: string. A reader that scans for "Exif\0\0" instead of walking
            //: the segment lengths reads this one and finds rubbish.
            let body = b"JFIF\0Exif\0\0II\x2a\x00\x08\x00\x00\x00rubbish";
            out.extend_from_slice(&[0xFF, 0xE0]);
            out.extend_from_slice(&((body.len() + 2) as u16).to_be_bytes());
            out.extend_from_slice(body);
        }
        let mut body = b"Exif\0\0".to_vec();
        body.extend_from_slice(tiff);
        out.extend_from_slice(&[0xFF, 0xE1]);
        out.extend_from_slice(&((body.len() + 2) as u16).to_be_bytes());
        out.extend_from_slice(&body);
        out.extend_from_slice(&[0xFF, 0xDA]);
        out
    }

    fn a_photograph() -> Vec<u8> {
        build_tiff(
            vec![
                (0x010F, Val::Ascii("Canon")),
                (0x0110, Val::Ascii("Canon EOS 5D")),
                (0x0112, Val::Short(6)),
                (0x0131, Val::Ascii("AuraDE")),
                (0x0132, Val::Ascii("2026:09:08 21:04:11")),
                (0x013B, Val::Ascii("Cameron")),
            ],
            vec![
                (0x829A, Val::Rational(1, 250)),
                (0x829D, Val::Rational(28, 10)),
                (0x8827, Val::Short(400)),
                (0x9003, Val::Ascii("2026:07:04 09:15:00")),
                (0x920A, Val::Rational(50, 1)),
                (0xA002, Val::Long(4096)),
                (0xA003, Val::Long(2731)),
                (0xA434, Val::Ascii("EF50mm f/1.8")),
            ],
            vec![
                (0x0001, Val::Ascii("N")),
                (0x0002, Val::Rationals(vec![(51, 1), (30, 1), (0, 1)])),
                (0x0003, Val::Ascii("W")),
                (0x0004, Val::Rationals(vec![(0, 1), (7, 1), (3000, 100)])),
            ],
        )
    }

    #[test]
    fn a_photograph_reads_back_the_way_a_camera_wrote_it() {
        let photo = exif_of(&as_jpeg(&a_photograph(), false)).expect("no exif found");
        //: The make is dropped when the model already starts with it, because
        //: "Canon Canon EOS 5D" is what the naive join produces and what every
        //: file manager that gets this wrong shows.
        assert_eq!(photo.camera.as_deref(), Some("Canon EOS 5D"));
        assert_eq!(photo.lens.as_deref(), Some("EF50mm f/1.8"));
        assert_eq!(photo.software.as_deref(), Some("AuraDE"));
        assert_eq!(photo.artist.as_deref(), Some("Cameron"));
        assert_eq!(photo.orientation, Some(6));
        assert_eq!(photo.iso, Some(400));
        assert_eq!(photo.width, Some(4096));
        assert_eq!(photo.height, Some(2731));
        assert_eq!(photo.exposure.as_deref(), Some("1/250"));
        assert_eq!(photo.aperture.as_deref(), Some("f/2.8"));
        assert_eq!(photo.focal_length.as_deref(), Some("50 mm"));
        //: DateTimeOriginal, not the file's own DateTime, and with dashes in
        //: the date where EXIF writes colons.
        assert_eq!(photo.taken.as_deref(), Some("2026-07-04 09:15:00"));
        //: 51 degrees 30 minutes north, 0 degrees 7 minutes 30 seconds west.
        assert_eq!(photo.latitude.map(|v| (v * 1000.0).round()), Some(51_500.0));
        assert_eq!(photo.longitude.map(|v| (v * 1000.0).round()), Some(-125.0));
    }

    #[test]
    fn the_exif_block_is_found_by_walking_segments_not_by_looking_for_the_string() {
        let honest = exif_of(&as_jpeg(&a_photograph(), false)).unwrap();
        let with_decoy = exif_of(&as_jpeg(&a_photograph(), true)).unwrap();
        assert_eq!(honest, with_decoy, "an earlier segment was read as the header");
    }

    #[test]
    fn a_tiff_is_its_own_header_and_a_file_with_no_exif_says_so() {
        //: A raw file, not wrapped in anything.
        let photo = exif_of(&a_photograph()).unwrap();
        assert_eq!(photo.camera.as_deref(), Some("Canon EOS 5D"));

        assert_eq!(exif_of(b"not a picture at all"), None);
        assert_eq!(exif_of(&[]), None);
        //: A JPEG with no APP1 in it.
        assert_eq!(exif_of(&[0xFF, 0xD8, 0xFF, 0xDA, 0x00, 0x02]), None);
    }

    #[test]
    fn a_crafted_offset_is_refused_rather_than_read() {
        let good = a_photograph();

        //: The offset of the first directory, pointed past the end.
        let mut wild = good.clone();
        wild[4..8].copy_from_slice(&0xFFFF_FF00u32.to_le_bytes());
        assert_eq!(exif_of(&wild), None, "a directory outside the file was read");

        //: The count of entries in that directory, set to the maximum. The
        //: reader must not allocate for entries that are not there.
        let mut many = good.clone();
        many[8..10].copy_from_slice(&u16::MAX.to_le_bytes());
        let _ = exif_of(&many);

        //: Every truncation of a real file. Any one of these could be the
        //: point where an unchecked read runs off the end.
        for cut in 0..good.len() {
            let _ = exif_of(&good[..cut]);
        }
        //: And every truncation of the JPEG that wraps it.
        let wrapped = as_jpeg(&good, true);
        for cut in 0..wrapped.len() {
            let _ = exif_of(&wrapped[..cut]);
        }

        //: One byte changed, everywhere, one at a time. This is the crafted
        //: file: valid enough to get past the header and wrong after that.
        for at in 0..good.len().min(400) {
            let mut bent = good.clone();
            bent[at] = bent[at].wrapping_add(0x7F);
            let _ = exif_of(&bent);
        }
    }

    #[test]
    fn a_shutter_speed_and_an_aperture_read_the_way_a_camera_shows_them() {
        assert_eq!(as_shutter((1, 250)), "1/250");
        assert_eq!(as_shutter((1, 4)), "1/4");
        //: A long exposure is seconds, not a fraction of one.
        assert_eq!(as_shutter((30, 1)), "30 s");
        assert_eq!(as_shutter((5, 2)), "2.5 s");
        assert_eq!(as_shutter((0, 1)), "0 s");
        assert_eq!(trim((28, 10)), "2.8");
        assert_eq!(trim((50, 1)), "50");
        assert_eq!(trim((16, 10)), "1.6");
        assert_eq!(normalise_date("2026:09:08 21:04:11".into()), "2026-09-08 21:04:11");
        //: A time on its own has no date to fix, and its colons stay.
        assert_eq!(normalise_date("21:04:11".into()), "21-04-11");
    }

    #[test]
    fn a_southern_and_western_photograph_reads_negative() {
        assert_eq!(signed(51.5, Some("N"), "S"), 51.5);
        assert_eq!(signed(51.5, Some("S"), "S"), -51.5);
        assert_eq!(signed(51.5, Some("s"), "S"), -51.5);
        assert_eq!(signed(0.125, Some("W"), "W"), -0.125);
        //: No reference at all is not a reason to guess a hemisphere.
        assert_eq!(signed(51.5, None, "S"), 51.5);
    }

    #[test]
    fn ffprobe_output_becomes_the_rows_the_tab_shows() {
        let json = br#"{
          "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
             "avg_frame_rate": "30000/1001"},
            {"codec_type": "video", "codec_name": "mjpeg", "width": 600, "height": 600,
             "avg_frame_rate": "0/0"},
            {"codec_type": "audio", "codec_name": "aac", "channels": 2,
             "sample_rate": "48000"}
          ],
          "format": {"duration": "12.345000", "bit_rate": "1536000",
                     "tags": {"TITLE": "A Song", "artist": "Someone", "album": "A Record"}}
        }"#;
        let media = from_probe(json).unwrap();
        assert_eq!(media.duration, Some(12.345));
        assert_eq!(media.bitrate, Some(1_536_000));
        //: The first video stream, not the cover art that follows it.
        assert_eq!(media.video_codec.as_deref(), Some("h264"));
        assert_eq!((media.width, media.height), (Some(1920), Some(1080)));
        assert_eq!(media.frame_rate.map(|v| (v * 100.0).round()), Some(2997.0));
        assert_eq!(media.audio_codec.as_deref(), Some("aac"));
        assert_eq!(media.channels, Some(2));
        assert_eq!(media.sample_rate, Some(48_000));
        //: Tag names are cased however the container felt like.
        assert_eq!(media.title.as_deref(), Some("A Song"));
        assert_eq!(media.artist.as_deref(), Some("Someone"));
        assert_eq!(media.album.as_deref(), Some("A Record"));

        //: A rate of 0/0 means the stream has no fixed rate, which is not a
        //: rate of zero and not a division to attempt.
        assert_eq!(ratio("0/0"), None);
        assert_eq!(ratio("25/1"), Some(25.0));
        assert_eq!(ratio("nonsense"), None);

        assert_eq!(from_probe(b"{}"), None, "an empty answer is not a set of rows");
        assert_eq!(from_probe(b"not json"), None);
        assert_eq!(from_probe(br#"{"streams": "not a list"}"#), None);
    }

    #[test]
    fn a_text_file_is_not_offered_to_ffprobe_however_hard_it_guesses() {
        //: Handed a text file, ffprobe finds its ansi demuxer and reports a
        //: 640 by 400 video at 25 frames a second. That answer reached the
        //: Details tab once.
        let dir = std::env::temp_dir().join("auradefs-media-guess");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let text = dir.join("note.txt");
        std::fs::write(&text, "the quiet part out loud
".repeat(400)).unwrap();
        assert!(!is_media(&text));
        assert_eq!(media(&text).unwrap(), None, "a text file came back as a video");

        assert!(is_media(Path::new("a.mp4")) && is_media(Path::new("a.MKV")));
        assert!(is_media(Path::new("a.flac")) && is_media(Path::new("a.mp3")));
        assert!(!is_media(Path::new("a.png")), "a picture is not probed");
        assert!(!is_media(Path::new("Makefile")));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_real_video_is_probed_when_the_tool_is_there() {
        let Some(ffmpeg) = crate::apps::which("ffmpeg") else { return };
        if !can_probe() {
            return;
        }
        let dir = std::env::temp_dir().join("auradefs-media-probe");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let clip = dir.join("clip.mp4");
        let made = Command::new(ffmpeg)
            .args(["-nostdin", "-loglevel", "error", "-f", "lavfi", "-i"])
            .arg("testsrc=size=320x240:rate=10:duration=2")
            .args(["-pix_fmt", "yuv420p", "-y"])
            .arg(&clip)
            .status();
        if !matches!(made, Ok(status) if status.success()) {
            return;
        }
        let media = media(&clip).unwrap().expect("ffprobe said nothing about a video");
        assert_eq!((media.width, media.height), (Some(320), Some(240)));
        assert!(media.duration.unwrap() > 1.5, "duration {:?}", media.duration);
        assert!(media.video_codec.is_some());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_tool_that_never_finishes_does_not_hold_the_request() {
        let Some(sleep) = crate::apps::which("sleep") else { return };
        let mut command = Command::new(sleep);
        command.arg("30");
        let started = std::time::Instant::now();
        assert_eq!(run_bounded(command, std::time::Duration::from_millis(200)), None);
        assert!(started.elapsed() < std::time::Duration::from_secs(5), "it was waited on");
    }
}
