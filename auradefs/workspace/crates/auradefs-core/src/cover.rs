//! The album cover inside a sound file.
//!
//! The reference hands this to TagLib#: the picture list on the file's tag
//! is replaced with the chosen image, or emptied, and the file is saved.
//! lofty is the same idea on this side. It reads and writes the tags that
//! carry pictures in the formats a music folder holds: ID3v2 in MP3, WAV and
//! AIFF, Vorbis comments in FLAC, Ogg and Opus, the ilst atoms in MP4 and
//! M4A, and APE tags in Monkey's Audio, WavPack and Musepack. A container
//! none of those fit, WMA or MKV or WebM, is refused with its name rather
//! than rewritten blind.
//!
//! The write goes through a copy. lofty rewrites a file in place, moving the
//! audio along to make room for a bigger tag, and a crash in the middle of
//! that is a truncated album. So the tag is written into a copy beside the
//! original and the copy is renamed over it: everyone else sees the old file
//! or the new one. The copy carries the original's mode and its extended
//! attributes, because the tags and the comment this file manager keeps live
//! in those and a cover change must not lose them.

use std::fs::{File, OpenOptions};
use std::path::Path;

use lofty::config::WriteOptions;
use lofty::file::{AudioFile, TaggedFile, TaggedFileExt};
use lofty::picture::{Picture, PictureType};
use lofty::tag::{Tag, TagType};

use crate::error::{Error, Result};

/// The names whose contents can carry a cover, by extension: the containers
/// lofty writes. Read for a list before anything is opened, so it has to be
/// a string comparison. `oga` is here although lofty does not map the
/// extension: the reader below looks at the bytes, and an .oga is Ogg with
/// Vorbis, Opus or FLAC inside, all three of which it reads.
pub const CARRIERS: &[&str] = &[
    "mp3", "mp2", "flac", "ogg", "oga", "opus", "spx", "m4a", "m4b", "m4p", "m4r", "mp4", "m4v",
    "3gp", "wav", "wave", "aiff", "aif", "aifc", "ape", "wv", "mpc", "aac",
];

/// The sound formats among them, for the thumbnailer: a video's picture is a
/// frame pulled out of it, and a sound file's is its cover.
pub const SOUND: &[&str] = &[
    "mp3", "mp2", "flac", "ogg", "oga", "opus", "spx", "m4a", "m4b", "m4p", "m4r", "wav", "wave",
    "aiff", "aif", "aifc", "ape", "wv", "mpc", "aac",
];

/// The largest picture worth embedding. A cover is a few hundred kilobytes;
/// past this it is a photograph that was picked by mistake, and it would be
/// copied into every player's memory whenever the track is queued. The
/// number sits under FLAC's limit, a metadata block of 16 MiB less one byte
/// with the picture's own header inside it, which is the tightest of the
/// containers: what passes this check is a picture every one of them takes.
pub const MAX_COVER_BYTES: u64 = 15 * 1024 * 1024;

fn extension(path: &Path) -> Option<String> {
    Some(path.extension()?.to_str()?.to_ascii_lowercase())
}

/// Whether the name says the file can hold a cover at all.
pub fn can_carry(path: &Path) -> bool {
    extension(path).is_some_and(|ext| CARRIERS.contains(&ext.as_str()))
}

/// Whether the name says the file is sound rather than video.
pub fn is_sound(path: &Path) -> bool {
    extension(path).is_some_and(|ext| SOUND.contains(&ext.as_str()))
}

/// The picture a file carries.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Cover {
    /// What the tag says the bytes are, or what the bytes say when the tag
    /// did not.
    pub mime: String,
    pub bytes: Vec<u8>,
    /// Whether the tag calls it the front cover, as against some other
    /// picture that was the best there was.
    pub front: bool,
}

fn leaf(path: &Path) -> String {
    path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default()
}

fn io(path: &Path, e: std::io::Error) -> Error {
    Error::io(path.display().to_string(), e)
}

/// Read what lofty makes of the bytes. The bytes rather than the name: a
/// track called .oga could be any of three formats, and a file that was
/// renamed by hand is still what it is.
fn open(path: &Path) -> Result<TaggedFile> {
    let mut file = File::open(path).map_err(|e| io(path, e))?;
    lofty::read_from(&mut file).map_err(|e| {
        if e.is_unknown_format() {
            Error::Unsupported(format!("{} is not a sound file this can read", leaf(path)))
        } else {
            Error::Unsupported(format!("{}: {e}", leaf(path)))
        }
    })
}

/// The cover, if there is one: the front cover when the tag names one, else
/// the first picture of any kind, which is what a player shows too.
pub fn read(path: &Path) -> Result<Option<Cover>> {
    if !can_carry(path) {
        return Ok(None);
    }
    Ok(pick(&open(path)?))
}

fn pick(tagged: &TaggedFile) -> Option<Cover> {
    let mut other = None;
    for tag in tagged.tags() {
        //: An MP4 covr atom has no picture type, so the one picture an M4A
        //: carries is its cover by definition rather than by label.
        let unlabelled = tag.tag_type() == TagType::Mp4Ilst;
        for picture in tag.pictures() {
            if picture.data().is_empty() {
                continue;
            }
            let cover = Cover {
                mime: mime_of(picture),
                bytes: picture.data().to_vec(),
                front: unlabelled || picture.pic_type() == PictureType::CoverFront,
            };
            if cover.front {
                return Some(cover);
            }
            if other.is_none() {
                other = Some(cover);
            }
        }
    }
    other
}

/// The tag's word for the picture's format, and when the tag has none, the
/// bytes' own: a PNG and a JPEG both announce themselves in their first
/// bytes, and a tag written by a careless program leaves the field empty.
fn mime_of(picture: &Picture) -> String {
    if let Some(mime) = picture.mime_type() {
        let text = mime.as_str();
        if !text.is_empty() {
            return text.to_string();
        }
    }
    sniff(picture.data()).to_string()
}

pub fn sniff(bytes: &[u8]) -> &'static str {
    if bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        "image/png"
    } else if bytes.starts_with(b"\xff\xd8\xff") {
        "image/jpeg"
    } else if bytes.starts_with(b"GIF8") {
        "image/gif"
    } else if bytes.starts_with(b"BM") {
        "image/bmp"
    } else if bytes.starts_with(b"RIFF") && bytes.get(8..12) == Some(b"WEBP") {
        "image/webp"
    } else {
        "application/octet-stream"
    }
}

/// Make `image` the file's cover, in place of every picture it carried.
///
/// The picker offers bitmaps, JPEGs and PNGs, the three the reference's
/// filter lists, and lofty reads those plus GIF and TIFF from the bytes. A
/// file that is none of them is refused before the track is touched.
pub fn change(path: &Path, image: &Path) -> Result<()> {
    let meta = std::fs::metadata(image).map_err(|e| io(image, e))?;
    if meta.is_dir() {
        return Err(Error::BadRequest(format!("{} is a folder, not a picture", leaf(image))));
    }
    if meta.len() > MAX_COVER_BYTES {
        return Err(Error::BadRequest(format!(
            "{} is too large for a cover ({} bytes; the limit is {})",
            leaf(image),
            meta.len(),
            MAX_COVER_BYTES
        )));
    }
    let mut file = File::open(image).map_err(|e| io(image, e))?;
    let mut picture = Picture::from_reader(&mut file).map_err(|_| {
        Error::BadRequest(format!("{} is not a picture that can be embedded", leaf(image)))
    })?;
    picture.set_pic_type(PictureType::CoverFront);
    //: The picture's own name, the way TagLib# fills the description in,
    //: so a tag editor opened later says where the cover came from.
    picture.set_description(Some(leaf(image)));
    apply(path, Some(picture)).map(|_| ())
}

/// Strip every picture from the file. Returns whether there was one: a file
/// that had none is left exactly as it was, modification time included.
pub fn remove(path: &Path) -> Result<bool> {
    apply(path, None)
}

fn apply(path: &Path, picture: Option<Picture>) -> Result<bool> {
    if !can_carry(path) {
        return Err(Error::Unsupported(format!("{} cannot carry a cover", leaf(path))));
    }
    let mut tagged = open(path)?;
    let had = tagged.tags().iter().any(|tag| !tag.pictures().is_empty());
    if picture.is_none() && !had {
        return Ok(false);
    }
    //: Every tag loses its pictures, not just the one the new cover goes
    //: into. An MP3 can carry an APE tag beside its ID3v2, and a player that
    //: reads the APE one first would keep showing the cover that was removed.
    let types: Vec<TagType> = tagged.tags().iter().map(|tag| tag.tag_type()).collect();
    for tag_type in types {
        if let Some(tag) = tagged.tag_mut(tag_type) {
            while !tag.pictures().is_empty() {
                tag.remove_picture(0);
            }
        }
    }
    if let Some(picture) = picture {
        //: Into the format's own tag, made if the file had none: a bare FLAC
        //: gets a Vorbis comment block, a bare MP3 an ID3v2 tag.
        let primary = tagged.primary_tag_type();
        if tagged.tag(primary).is_none() {
            tagged.insert_tag(Tag::new(primary));
        }
        tagged.tag_mut(primary).expect("inserted above").push_picture(picture);
    }
    write_beside(path, &tagged)?;
    Ok(had)
}

/// Write the tagged file into a copy beside the original and rename it over.
fn write_beside(path: &Path, tagged: &TaggedFile) -> Result<()> {
    use std::os::unix::fs::{MetadataExt, PermissionsExt};
    let meta = std::fs::metadata(path).map_err(|e| io(path, e))?;
    let dir = path.parent().unwrap_or(Path::new("."));
    let temp = dir.join(format!(".{}.cover-{}", leaf(path), std::process::id()));
    let result = (|| -> Result<()> {
        std::fs::copy(path, &temp).map_err(|e| io(&temp, e))?;
        //: What this file manager keeps on the file itself: its tags, its
        //: comment, where a download came from. Carried one by one, and one
        //: the destination refuses is skipped rather than fatal, because a
        //: security label a plain user cannot set is not theirs to lose.
        for name in crate::xattr::list(path).unwrap_or_default() {
            if let Ok(Some(value)) = crate::xattr::get(path, &name) {
                let _ = crate::xattr::set(&temp, &name, &value);
            }
        }
        let mut file =
            OpenOptions::new().read(true).write(true).open(&temp).map_err(|e| io(&temp, e))?;
        tagged.save_to(&mut file, WriteOptions::default()).map_err(|e| Error::Io {
            context: format!("writing the cover into {}", leaf(path)),
            source: std::io::Error::other(e.to_string()),
        })?;
        file.sync_all().map_err(|e| io(&temp, e))?;
        std::fs::set_permissions(&temp, std::fs::Permissions::from_mode(meta.mode() & 0o7777))
            .map_err(|e| io(&temp, e))?;
        std::fs::rename(&temp, path).map_err(|e| io(path, e))
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temp);
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use std::process::Command;

    fn scratch(tag: &str) -> PathBuf {
        let base = std::env::temp_dir().join(format!("auradefs-cover-{tag}"));
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(&base).unwrap();
        base
    }

    /// Half a second of silence in the container `name` asks for, through
    /// ffmpeg. The tests are about what happens around the codec, not the
    /// codec, and ffmpeg writes every container lofty reads.
    fn track(dir: &Path, name: &str) -> Option<PathBuf> {
        let ffmpeg = crate::apps::which("ffmpeg")?;
        let out = dir.join(name);
        let status = Command::new(ffmpeg)
            .args(["-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "0.5"])
            .arg(&out)
            .status()
            .ok()?;
        status.success().then_some(out)
    }

    fn png(dir: &Path, name: &str, colour: [u8; 3]) -> PathBuf {
        let out = dir.join(name);
        image::RgbImage::from_pixel(6, 4, image::Rgb(colour)).save(&out).unwrap();
        out
    }

    #[test]
    fn the_name_says_what_can_hold_a_cover_and_what_is_sound() {
        let carry = |name: &str| can_carry(Path::new(name));
        let sound = |name: &str| is_sound(Path::new(name));
        assert!(carry("track.MP3") && sound("track.MP3"), "case is not the point");
        assert!(carry("track.flac") && sound("track.flac"));
        assert!(carry("track.oga") && sound("track.oga"));
        assert!(carry("clip.mp4") && !sound("clip.mp4"), "a video's picture is a frame");
        assert!(carry("clip.m4v") && !sound("clip.m4v"));
        assert!(!carry("clip.mkv"), "no tag lofty writes lives in Matroska");
        assert!(!carry("song.wma"), "ASF is not written either");
        assert!(!carry("notes.txt") && !sound("notes.txt"));
        assert!(!carry("mp3"), "a name that is the word is not the extension");
    }

    #[test]
    fn the_bytes_say_what_a_tag_forgot_to() {
        assert_eq!(sniff(b"\x89PNG\r\n\x1a\n...."), "image/png");
        assert_eq!(sniff(b"\xff\xd8\xff\xe0...."), "image/jpeg");
        assert_eq!(sniff(b"GIF89a"), "image/gif");
        assert_eq!(sniff(b"BM......"), "image/bmp");
        assert_eq!(sniff(b"RIFF....WEBP"), "image/webp");
        assert_eq!(sniff(b"hello"), "application/octet-stream");
        assert_eq!(sniff(b""), "application/octet-stream");
    }

    #[test]
    fn a_cover_goes_in_comes_back_and_comes_out_in_every_container() {
        let dir = scratch("round-trip");
        let art = png(&dir, "art.png", [200, 30, 30]);
        let art_bytes = std::fs::read(&art).unwrap();
        let mut tried = 0;
        for name in ["silence.mp3", "silence.flac", "silence.ogg", "silence.m4a", "silence.wav", "silence.opus"] {
            let Some(file) = track(&dir, name) else { continue };
            tried += 1;
            assert_eq!(read(&file).unwrap(), None, "{name} starts with no cover");
            //: Nothing to remove is nothing written: the same bytes and the
            //: same modification time, not a rewrite that happens to agree.
            let untouched = std::fs::read(&file).unwrap();
            let stamp = std::fs::metadata(&file).unwrap().modified().unwrap();
            assert!(!remove(&file).unwrap(), "{name}: nothing to remove yet");
            assert_eq!(std::fs::read(&file).unwrap(), untouched, "{name}: not rewritten");
            assert_eq!(std::fs::metadata(&file).unwrap().modified().unwrap(), stamp, "{name}: not touched");

            change(&file, &art).unwrap();
            let cover = read(&file).unwrap().unwrap_or_else(|| panic!("{name} lost the cover"));
            assert_eq!(cover.bytes, art_bytes, "{name}: the bytes come back untouched");
            assert_eq!(cover.mime, "image/png", "{name}");
            assert!(cover.front, "{name}: it is the front cover");

            //: Still a track: the audio survived the rewrite.
            assert!(crate::media::media(&file).map(|m| m.is_some()).unwrap_or(true), "{name} still probes as media");

            assert!(remove(&file).unwrap(), "{name}: there was one to remove");
            assert_eq!(read(&file).unwrap(), None, "{name}: and now there is not");
        }
        assert!(tried > 0, "ffmpeg is needed to make the fixtures");
    }

    #[test]
    fn a_second_cover_replaces_the_first_rather_than_joining_it() {
        let dir = scratch("replace");
        let Some(file) = track(&dir, "silence.mp3") else { return };
        let red = png(&dir, "red.png", [200, 0, 0]);
        let blue = png(&dir, "blue.png", [0, 0, 200]);
        change(&file, &red).unwrap();
        change(&file, &blue).unwrap();
        let tagged = open(&file).unwrap();
        let pictures: usize = tagged.tags().iter().map(|t| t.pictures().len()).sum();
        assert_eq!(pictures, 1, "one cover, the latest");
        assert_eq!(read(&file).unwrap().unwrap().bytes, std::fs::read(&blue).unwrap());
    }

    #[test]
    fn the_file_keeps_its_mode_and_its_attributes_across_the_rewrite() {
        use std::os::unix::fs::PermissionsExt;
        let dir = scratch("keep");
        let Some(file) = track(&dir, "silence.flac") else { return };
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o640)).unwrap();
        //: A tag and a comment, the two things this file manager writes on a
        //: file, when the filesystem takes attributes at all.
        let tagged = crate::xattr::set_tags(&file, &["Blue".to_string()]).is_ok();
        let art = png(&dir, "art.png", [1, 2, 3]);
        change(&file, &art).unwrap();
        let mode = std::fs::metadata(&file).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o640, "the mode survived");
        if tagged {
            assert_eq!(crate::xattr::tags(&file).unwrap(), vec!["Blue".to_string()], "the tag survived");
        }
        //: And nothing was left beside it.
        let leftovers: Vec<_> = std::fs::read_dir(&dir)
            .unwrap()
            .filter_map(|e| e.ok())
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .filter(|n| n.contains(".cover-"))
            .collect();
        assert!(leftovers.is_empty(), "temporary copies left behind: {leftovers:?}");
    }

    #[test]
    fn what_is_not_a_picture_is_refused_before_the_track_is_touched() {
        let dir = scratch("refuse");
        let Some(file) = track(&dir, "silence.mp3") else { return };
        let before = std::fs::read(&file).unwrap();
        let text = dir.join("notes.txt");
        std::fs::write(&text, b"this is not a picture at all").unwrap();
        let err = change(&file, &text).unwrap_err();
        assert!(matches!(err, Error::BadRequest(_)), "{err}");
        assert_eq!(std::fs::read(&file).unwrap(), before, "the track is as it was");
        let err = change(&file, &dir).unwrap_err();
        assert!(matches!(err, Error::BadRequest(_)), "a folder: {err}");
        assert!(err.to_string().contains("folder"), "said for what it is: {err}");
        let missing = change(&file, &dir.join("nowhere.png")).unwrap_err();
        assert!(matches!(missing, Error::NotFound(_)), "{missing}");
        //: One byte over the limit is refused by size, before the bytes are
        //: looked at, and the limit is quoted.
        let huge = dir.join("huge.png");
        let mut bytes = b"\x89PNG\r\n\x1a\n".to_vec();
        bytes.resize(MAX_COVER_BYTES as usize + 1, 0);
        std::fs::write(&huge, &bytes).unwrap();
        let err = change(&file, &huge).unwrap_err();
        assert!(matches!(err, Error::BadRequest(_)), "{err}");
        assert!(err.to_string().contains(&MAX_COVER_BYTES.to_string()), "{err}");
        assert_eq!(std::fs::read(&file).unwrap(), before, "the track is still as it was");
    }

    #[test]
    fn a_carrier_by_its_bytes_but_not_by_its_name_is_left_alone() {
        //: The name is the contract the list view and the page work from. A
        //: file called .dat that happens to hold an MP3 gets no cover written
        //: into it, and none read out of it, because nothing would show it.
        let dir = scratch("by-name");
        let Some(file) = track(&dir, "silence.mp3") else { return };
        let odd = dir.join("song.dat");
        std::fs::copy(&file, &odd).unwrap();
        let before = std::fs::read(&odd).unwrap();
        let art = png(&dir, "art.png", [3, 3, 3]);
        let err = change(&odd, &art).unwrap_err();
        assert!(matches!(err, Error::Unsupported(_)), "{err}");
        assert!(err.to_string().contains("song.dat"), "{err}");
        assert_eq!(std::fs::read(&odd).unwrap(), before, "not written");
        assert_eq!(read(&odd).unwrap(), None);
    }

    #[test]
    fn a_write_that_fails_leaves_the_track_and_no_copy_behind() {
        //: A picture the container refuses: FLAC's block cannot hold one
        //: over 16 MiB less its header, and lofty says so from inside the
        //: save, after the copy was made. The copy must go and the original
        //: must not have moved.
        let dir = scratch("failed-write");
        let Some(file) = track(&dir, "silence.flac") else { return };
        let before = std::fs::read(&file).unwrap();
        let mut bytes = b"\x89PNG\r\n\x1a\n".to_vec();
        bytes.resize(16 * 1024 * 1024 + 64, 0);
        let picture = Picture::unchecked(bytes)
            .pic_type(PictureType::CoverFront)
            .mime_type(lofty::picture::MimeType::Png)
            .build();
        let mut tagged = open(&file).unwrap();
        let primary = tagged.primary_tag_type();
        tagged.insert_tag(Tag::new(primary));
        tagged.tag_mut(primary).unwrap().push_picture(picture);
        let err = write_beside(&file, &tagged).unwrap_err();
        assert!(matches!(err, Error::Io { .. }), "{err}");
        assert!(err.to_string().contains("silence.flac"), "{err}");
        assert_eq!(std::fs::read(&file).unwrap(), before, "the original is as it was");
        let leftovers: Vec<_> = std::fs::read_dir(&dir)
            .unwrap()
            .filter_map(|e| e.ok())
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .filter(|n| n.contains(".cover-"))
            .collect();
        assert!(leftovers.is_empty(), "left behind: {leftovers:?}");
    }

    #[test]
    fn a_container_lofty_cannot_write_is_refused_by_name() {
        let dir = scratch("container");
        let art = png(&dir, "art.png", [9, 9, 9]);
        let mkv = dir.join("clip.mkv");
        std::fs::write(&mkv, b"\x1a\x45\xdf\xa3 not really matroska").unwrap();
        let err = change(&mkv, &art).unwrap_err();
        assert!(matches!(err, Error::Unsupported(_)), "{err}");
        assert_eq!(read(&mkv).unwrap(), None, "and reading one asks nothing of the bytes");
        //: The name says sound but the bytes do not.
        let fake = dir.join("fake.mp3");
        std::fs::write(&fake, b"plain text with an mp3 name").unwrap();
        let err = change(&fake, &art).unwrap_err();
        assert!(matches!(err, Error::Unsupported(_)), "{err}");
    }

    #[test]
    fn the_first_picture_stands_in_when_no_front_cover_is_named() {
        let dir = scratch("fallback");
        let Some(file) = track(&dir, "silence.flac") else { return };
        let art = png(&dir, "back.png", [7, 7, 7]);
        let mut picture = Picture::from_reader(&mut File::open(&art).unwrap()).unwrap();
        picture.set_pic_type(PictureType::CoverBack);
        let mut tagged = open(&file).unwrap();
        let primary = tagged.primary_tag_type();
        tagged.insert_tag(Tag::new(primary));
        tagged.tag_mut(primary).unwrap().push_picture(picture);
        write_beside(&file, &tagged).unwrap();
        let cover = read(&file).unwrap().expect("the back cover is better than nothing");
        assert!(!cover.front);
        assert_eq!(cover.bytes, std::fs::read(&art).unwrap());

        //: A front cover behind it in the list is still the one to show.
        let front_art = png(&dir, "front.png", [200, 200, 0]);
        let mut front = Picture::from_reader(&mut File::open(&front_art).unwrap()).unwrap();
        front.set_pic_type(PictureType::CoverFront);
        let mut tagged = open(&file).unwrap();
        tagged.tag_mut(primary).unwrap().push_picture(front);
        assert_eq!(tagged.tag(primary).unwrap().pictures().len(), 2, "both are kept");
        assert_eq!(tagged.tag(primary).unwrap().pictures()[0].pic_type(), PictureType::CoverBack);
        write_beside(&file, &tagged).unwrap();
        let cover = read(&file).unwrap().unwrap();
        assert!(cover.front, "the front cover wins whatever the order");
        assert_eq!(cover.bytes, std::fs::read(&front_art).unwrap());
    }
}
