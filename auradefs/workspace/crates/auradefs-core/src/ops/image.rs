//! Turning a picture the right way up.
//!
//! Two things are going on here and they are easy to confuse. A photograph can
//! be stored one way round and carry a note saying which way up it is meant to
//! be shown, and it can simply be stored the way it is meant to be shown. So a
//! turn is done in whichever of those two the file already speaks: rewriting
//! the note when there is one, and moving the pixels when there is not.
//!
//! Rewriting the note is worth the trouble. It is two bytes, it takes no time
//! on a forty megapixel photograph, and it keeps every other thing the camera
//! recorded. Re-encoding a JPEG throws all of that away and loses a little
//! quality every time, so a person who turns a picture four times gets back
//! something visibly worse than they started with.

use std::path::{Path, PathBuf};

use crate::error::{Error, Result};

/// One of the eight ways a picture can sit: some number of quarter turns, and
/// whether it is mirrored.
///
/// EXIF numbers these one to eight in an order that looks arbitrary, so the
/// number is converted to this at the edges and never reasoned about directly.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Facing {
    /// Quarter turns clockwise, 0 to 3, applied after the mirroring.
    pub quarter: u8,
    pub mirrored: bool,
}

impl Facing {
    pub const UPRIGHT: Facing = Facing { quarter: 0, mirrored: false };

    pub fn from_exif(value: u16) -> Option<Facing> {
        Some(match value {
            1 => Facing { quarter: 0, mirrored: false },
            2 => Facing { quarter: 0, mirrored: true },
            3 => Facing { quarter: 2, mirrored: false },
            4 => Facing { quarter: 2, mirrored: true },
            //: Five and seven are the two mirrored diagonals, and this is the
            //: order the decoder applies them in: turn first, then mirror,
            //: which is a mirror first and the opposite turn.
            5 => Facing { quarter: 3, mirrored: true },
            6 => Facing { quarter: 1, mirrored: false },
            7 => Facing { quarter: 1, mirrored: true },
            8 => Facing { quarter: 3, mirrored: false },
            _ => return None,
        })
    }

    pub fn to_exif(self) -> u16 {
        match (self.quarter % 4, self.mirrored) {
            (0, false) => 1,
            (0, true) => 2,
            (2, false) => 3,
            (2, true) => 4,
            (3, true) => 5,
            (1, false) => 6,
            (1, true) => 7,
            _ => 8,
        }
    }

    /// This facing, and then `next` applied to what it produced.
    ///
    /// Mirroring reverses which way a turn goes, which is the whole of the
    /// arithmetic: a quarter turn clockwise seen in a mirror is a quarter turn
    /// the other way.
    pub fn then(self, next: Facing) -> Facing {
        let carried = if next.mirrored { (4 - self.quarter % 4) % 4 } else { self.quarter % 4 };
        Facing {
            quarter: (next.quarter + carried) % 4,
            mirrored: next.mirrored ^ self.mirrored,
        }
    }
}

/// What the user asked for.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Turn {
    Left,
    Right,
    HalfTurn,
    MirrorHorizontal,
    MirrorVertical,
}

impl Turn {
    pub fn facing(self) -> Facing {
        match self {
            Turn::Right => Facing { quarter: 1, mirrored: false },
            Turn::Left => Facing { quarter: 3, mirrored: false },
            Turn::HalfTurn => Facing { quarter: 2, mirrored: false },
            Turn::MirrorHorizontal => Facing { quarter: 0, mirrored: true },
            Turn::MirrorVertical => Facing { quarter: 2, mirrored: true },
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Turn::Left => "left",
            Turn::Right => "right",
            Turn::HalfTurn => "half",
            Turn::MirrorHorizontal => "mirror",
            Turn::MirrorVertical => "flip",
        }
    }

    pub fn from_name(name: &str) -> Option<Turn> {
        match name.trim().to_ascii_lowercase().as_str() {
            "left" | "ccw" | "counterclockwise" => Some(Turn::Left),
            "right" | "cw" | "clockwise" => Some(Turn::Right),
            "half" | "180" => Some(Turn::HalfTurn),
            "mirror" | "fliph" | "horizontal" => Some(Turn::MirrorHorizontal),
            "flip" | "flipv" | "vertical" => Some(Turn::MirrorVertical),
            _ => None,
        }
    }
}

/// What a turn did.
#[derive(Debug, Clone, PartialEq)]
pub struct Turned {
    pub path: PathBuf,
    /// True when the picture itself was never decoded: the orientation was
    /// rewritten and not one pixel moved.
    pub lossless: bool,
    /// How it sits now, as EXIF numbers it. One when the pixels were moved,
    /// because then there is nothing left to correct.
    pub orientation: u16,
    pub width: u32,
    pub height: u32,
}

/// The largest picture this will decode. A turn that has to re-encode holds
/// the whole thing in memory twice.
const MAX_DECODE_BYTES: u64 = 128 * 1024 * 1024;

/// Turn a picture, in place.
pub fn turn(path: &Path, turn: Turn) -> Result<Turned> {
    let meta = std::fs::metadata(path).map_err(|e| Error::io(path.display().to_string(), e))?;
    if meta.is_dir() {
        return Err(Error::BadRequest("a folder cannot be turned".into()));
    }
    if let Some(done) = turn_by_note(path, turn)? {
        return Ok(done);
    }
    if meta.len() > MAX_DECODE_BYTES {
        return Err(Error::Unsupported(format!("{} is too large to turn", path.display())));
    }
    turn_by_pixels(path, turn, &meta)
}

/// Rewrite the orientation the file already carries, if it carries one.
fn turn_by_note(path: &Path, turn: Turn) -> Result<Option<Turned>> {
    let mut bytes = std::fs::read(path).map_err(|e| Error::io(path.display().to_string(), e))?;
    let Some((_, _, current)) = crate::media::orientation_at(&bytes) else { return Ok(None) };
    let Some(facing) = Facing::from_exif(current) else { return Ok(None) };
    let wanted = facing.then(turn.facing()).to_exif();
    if !crate::media::set_orientation(&mut bytes, wanted) {
        return Ok(None);
    }
    //: Written whole and moved into place, so an interrupted turn leaves the
    //: photograph as it was rather than half of each.
    let (width, height) = crate::thumbs::dimensions(path).unwrap_or((0, 0));
    replace(path, &bytes)?;
    //: The size on screen is the size after the note is honoured, which is the
    //: other way round for an odd number of quarter turns.
    let (width, height) = if Facing::from_exif(wanted).map(|f| f.quarter % 2 == 1).unwrap_or(false) {
        (height, width)
    } else {
        (width, height)
    };
    Ok(Some(Turned { path: path.to_path_buf(), lossless: true, orientation: wanted, width, height }))
}

/// Move the pixels and write the picture back out.
fn turn_by_pixels(path: &Path, turn: Turn, meta: &std::fs::Metadata) -> Result<Turned> {
    let format = image::ImageFormat::from_path(path)
        .map_err(|_| Error::Unsupported(format!("{} is not a picture", path.display())))?;
    if !format.writing_enabled() {
        return Err(Error::Unsupported(format!(
            "a {} can be read but not written",
            format.extensions_str().first().copied().unwrap_or("picture")
        )));
    }
    let reader = image::ImageReader::open(path)
        .map_err(|e| Error::io(path.display().to_string(), e))?
        .with_guessed_format()
        .map_err(|e| Error::io(path.display().to_string(), e))?;
    let mut decoder = reader
        .into_decoder()
        .map_err(|e| Error::Unsupported(format!("{}: {e}", path.display())))?;
    //: Whatever the file already said about which way up it is, applied first,
    //: so the turn is a turn of what the user is looking at.
    let stored = image::ImageDecoder::orientation(&mut decoder)
        .unwrap_or(image::metadata::Orientation::NoTransforms);
    let mut picture = image::DynamicImage::from_decoder(decoder)
        .map_err(|e| Error::Unsupported(format!("{}: {e}", path.display())))?;
    picture.apply_orientation(stored);
    picture.apply_orientation(as_orientation(turn.facing()));

    let mut encoded = std::io::Cursor::new(Vec::new());
    picture
        .write_to(&mut encoded, format)
        .map_err(|e| Error::Tool { tool: "image".into(), message: e.to_string() })?;
    replace_keeping_mode(path, encoded.get_ref(), meta)?;
    Ok(Turned {
        path: path.to_path_buf(),
        lossless: false,
        //: Upright, and it says so. The pixels are the picture now, and a
        //: leftover note would have every viewer turn it a second time.
        orientation: 1,
        width: picture.width(),
        height: picture.height(),
    })
}

fn as_orientation(facing: Facing) -> image::metadata::Orientation {
    image::metadata::Orientation::from_exif(facing.to_exif() as u8)
        .unwrap_or(image::metadata::Orientation::NoTransforms)
}

fn replace(path: &Path, bytes: &[u8]) -> Result<()> {
    let meta = std::fs::metadata(path).map_err(|e| Error::io(path.display().to_string(), e))?;
    replace_keeping_mode(path, bytes, &meta)
}

/// Write beside the original and rename over it, with the permissions the
/// original had. A rename is one step for everyone else looking at the folder:
/// they see the old picture or the new one, never a truncated file.
fn replace_keeping_mode(path: &Path, bytes: &[u8], meta: &std::fs::Metadata) -> Result<()> {
    use std::io::Write;
    use std::os::unix::fs::{MetadataExt, PermissionsExt};
    let dir = path.parent().unwrap_or(Path::new("."));
    let name = path.file_name().unwrap_or_default().to_string_lossy().into_owned();
    let temp = dir.join(format!(".{name}.turning-{}", std::process::id()));

    let write = || -> std::io::Result<()> {
        let mut file = std::fs::File::create(&temp)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        std::fs::set_permissions(&temp, std::fs::Permissions::from_mode(meta.mode() & 0o7777))
    };
    if let Err(e) = write() {
        let _ = std::fs::remove_file(&temp);
        return Err(Error::io(temp.display().to_string(), e));
    }
    std::fs::rename(&temp, path).map_err(|e| {
        let _ = std::fs::remove_file(&temp);
        Error::io(path.display().to_string(), e)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(tag: &str) -> PathBuf {
        let base = std::env::temp_dir().join(format!("auradefs-turn-{tag}"));
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(&base).unwrap();
        base
    }

    /// A picture with no symmetry at all, so every one of the eight facings
    /// produces different pixels and none of them can pass for another.
    fn lopsided() -> image::RgbImage {
        image::RgbImage::from_fn(4, 6, |x, y| {
            image::Rgb([(x * 60) as u8, (y * 40) as u8, ((x + 1) * (y + 1) * 7) as u8])
        })
    }

    #[test]
    fn the_eight_facings_are_the_eight_the_decoder_knows() {
        for value in 1..=8u16 {
            let facing = Facing::from_exif(value).unwrap();
            assert_eq!(facing.to_exif(), value, "exif {value} did not survive the round trip");
        }
        assert_eq!(Facing::from_exif(0), None);
        assert_eq!(Facing::from_exif(9), None);
        assert_eq!(Facing::UPRIGHT.to_exif(), 1);
    }

    #[test]
    fn composing_two_facings_is_doing_them_one_after_the_other() {
        //: The arithmetic is checked against the decoder rather than against
        //: itself: for every starting facing and every turn, composing and
        //: then applying has to give the same pixels as applying and then
        //: applying. A wrong sign in the mirror case shows up here and
        //: nowhere else.
        let raw = image::DynamicImage::ImageRgb8(lopsided());
        for first in 1..=8u16 {
            let first = Facing::from_exif(first).unwrap();
            for turn in [
                Turn::Left,
                Turn::Right,
                Turn::HalfTurn,
                Turn::MirrorHorizontal,
                Turn::MirrorVertical,
            ] {
                let mut one = raw.clone();
                one.apply_orientation(as_orientation(first));
                one.apply_orientation(as_orientation(turn.facing()));

                let mut two = raw.clone();
                two.apply_orientation(as_orientation(first.then(turn.facing())));

                assert_eq!(
                    one.to_rgb8().into_raw(),
                    two.to_rgb8().into_raw(),
                    "{first:?} then {turn:?} composed wrong"
                );
            }
        }
    }

    #[test]
    fn four_right_turns_come_back_to_where_they_started() {
        for start in 1..=8u16 {
            let mut facing = Facing::from_exif(start).unwrap();
            for _ in 0..4 {
                facing = facing.then(Turn::Right.facing());
            }
            assert_eq!(facing.to_exif(), start);
        }
        //: And a mirror twice is no mirror at all.
        let facing = Facing::UPRIGHT
            .then(Turn::MirrorHorizontal.facing())
            .then(Turn::MirrorHorizontal.facing());
        assert_eq!(facing, Facing::UPRIGHT);
        //: Left undoes right.
        assert_eq!(
            Facing::UPRIGHT.then(Turn::Right.facing()).then(Turn::Left.facing()),
            Facing::UPRIGHT
        );
    }

    #[test]
    fn a_turn_name_is_the_one_the_menu_uses() {
        for turn in [
            Turn::Left,
            Turn::Right,
            Turn::HalfTurn,
            Turn::MirrorHorizontal,
            Turn::MirrorVertical,
        ] {
            assert_eq!(Turn::from_name(turn.name()), Some(turn));
        }
        assert_eq!(Turn::from_name("CW"), Some(Turn::Right));
        assert_eq!(Turn::from_name(" 180 "), Some(Turn::HalfTurn));
        assert_eq!(Turn::from_name("sideways"), None);
    }

    #[test]
    fn a_png_is_turned_by_moving_its_pixels() {
        let base = scratch("png");
        let file = base.join("shot.png");
        lopsided().save(&file).unwrap();
        let before = image::open(&file).unwrap();

        let done = turn(&file, Turn::Right).unwrap();
        assert!(!done.lossless, "a png has no note to rewrite");
        assert_eq!((done.width, done.height), (6, 4), "the sides did not swap");
        assert_eq!(done.orientation, 1);

        let after = image::open(&file).unwrap();
        let mut expected = before.clone();
        expected.apply_orientation(image::metadata::Orientation::Rotate90);
        assert_eq!(after.to_rgb8().into_raw(), expected.to_rgb8().into_raw());

        //: And four of them is the picture it started as, which a turn that
        //: quietly did nothing would also pass, so the check above is the one
        //: that matters and this is the one that catches a drift.
        for _ in 0..3 {
            turn(&file, Turn::Right).unwrap();
        }
        assert_eq!(
            image::open(&file).unwrap().to_rgb8().into_raw(),
            before.to_rgb8().into_raw()
        );
    }

    /// A JPEG carrying one EXIF entry: which way up it is. Built rather than
    /// checked in, so the test can say exactly what is in the file.
    fn jpeg_facing(dir: &Path, name: &str, orientation: u16) -> PathBuf {
        let mut tiff = b"II\x2a\x00".to_vec();
        tiff.extend_from_slice(&8u32.to_le_bytes()); // the first directory
        tiff.extend_from_slice(&1u16.to_le_bytes()); // one entry in it
        tiff.extend_from_slice(&0x0112u16.to_le_bytes()); // orientation
        tiff.extend_from_slice(&3u16.to_le_bytes()); // SHORT
        tiff.extend_from_slice(&1u32.to_le_bytes()); // one of them
        tiff.extend_from_slice(&orientation.to_le_bytes());
        tiff.extend_from_slice(&[0, 0]); // the entry's four value bytes
        tiff.extend_from_slice(&0u32.to_le_bytes()); // no directory after this

        let mut body = b"Exif\0\0".to_vec();
        body.extend_from_slice(&tiff);
        let mut segment = vec![0xFF, 0xE1];
        segment.extend_from_slice(&((body.len() + 2) as u16).to_be_bytes());
        segment.extend_from_slice(&body);

        let mut encoded = std::io::Cursor::new(Vec::new());
        image::DynamicImage::ImageRgb8(lopsided())
            .write_to(&mut encoded, image::ImageFormat::Jpeg)
            .unwrap();
        let encoded = encoded.into_inner();
        //: Straight after the start of image marker, which is where an
        //: application segment belongs.
        let mut out = encoded[..2].to_vec();
        out.extend_from_slice(&segment);
        out.extend_from_slice(&encoded[2..]);

        let path = dir.join(name);
        std::fs::write(&path, &out).unwrap();
        path
    }

    #[test]
    fn a_photograph_that_says_which_way_up_it_is_turned_without_being_decoded() {
        let base = scratch("jpeg");
        let file = jpeg_facing(&base, "photo.jpg", 1);
        let before = std::fs::read(&file).unwrap();

        let done = turn(&file, Turn::Right).unwrap();
        assert!(done.lossless, "a photograph with an orientation was re-encoded");
        assert_eq!(done.orientation, 6, "a quarter turn clockwise is exif 6");
        //: Four by six upright, six by four on its side.
        assert_eq!((done.width, done.height), (6, 4));

        let after = std::fs::read(&file).unwrap();
        assert_eq!(after.len(), before.len(), "the file changed size, so it was rewritten");
        let differing = before.iter().zip(&after).filter(|(a, b)| a != b).count();
        assert_eq!(differing, 1, "{differing} bytes changed, not the one that says which way up");

        //: And the decoder agrees about what it now says, which is the whole
        //: point: a note only counts if the thing that reads pictures reads it.
        let mut decoder = image::ImageReader::open(&file)
            .unwrap()
            .with_guessed_format()
            .unwrap()
            .into_decoder()
            .unwrap();
        assert_eq!(
            image::ImageDecoder::orientation(&mut decoder).unwrap(),
            image::metadata::Orientation::Rotate90
        );
    }

    #[test]
    fn turning_a_photograph_all_the_way_round_leaves_the_file_it_started_as() {
        let base = scratch("jpeg-round");
        //: Starting from six rather than one, because a picture already on its
        //: side is the case that composition gets wrong.
        let file = jpeg_facing(&base, "photo.jpg", 6);
        let before = std::fs::read(&file).unwrap();
        for _ in 0..4 {
            assert!(turn(&file, Turn::Left).unwrap().lossless);
        }
        assert_eq!(std::fs::read(&file).unwrap(), before, "four turns did not come back");

        //: A mirror and a mirror back, likewise.
        turn(&file, Turn::MirrorHorizontal).unwrap();
        assert_ne!(std::fs::read(&file).unwrap(), before);
        turn(&file, Turn::MirrorHorizontal).unwrap();
        assert_eq!(std::fs::read(&file).unwrap(), before);
    }

    #[test]
    fn a_thumbnail_made_before_a_turn_is_not_the_one_shown_after_it() {
        let base = scratch("cache");
        std::fs::create_dir_all(base.join("cache")).unwrap();
        let file = jpeg_facing(&base, "photo.jpg", 1);

        static LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
        let _guard = LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let before_var = std::env::var("XDG_CACHE_HOME").ok();
        unsafe { std::env::set_var("XDG_CACHE_HOME", base.join("cache")) };

        let first = crate::thumbs::thumbnail(&file, crate::thumbs::Size::Normal).unwrap().unwrap();
        let before = image::open(&first).unwrap();
        //: A turn changes the file, so the cached thumbnail is stale. It is
        //: the modification time that says so, and it must actually move.
        std::thread::sleep(std::time::Duration::from_millis(1100));
        turn(&file, Turn::Right).unwrap();
        let second = crate::thumbs::thumbnail(&file, crate::thumbs::Size::Normal).unwrap().unwrap();
        let after = image::open(&second).unwrap();

        unsafe {
            match before_var {
                Some(v) => std::env::set_var("XDG_CACHE_HOME", v),
                None => std::env::remove_var("XDG_CACHE_HOME"),
            }
        }
        //: The pixels, not the file. A thumbnail carries the source's
        //: modification time inside it, so comparing the two files byte for
        //: byte says only that the time moved, which it did whether or not the
        //: picture is now shown the right way up.
        assert_ne!(
            (before.width(), before.height()),
            (after.width(), after.height()),
            "the turned photograph came back the same shape, so the note was not read"
        );
        assert_ne!(
            before.to_rgb8().into_raw(),
            after.to_rgb8().into_raw(),
            "the turned photograph kept its old picture"
        );
    }

    #[test]
    fn a_folder_and_a_file_that_is_not_a_picture_are_refused() {
        let base = scratch("refuse");
        let err = turn(&base, Turn::Left).unwrap_err();
        assert_eq!(err.code(), "bad-request");

        let text = base.join("notes.txt");
        std::fs::write(&text, b"not a picture").unwrap();
        let err = turn(&text, Turn::Left).unwrap_err();
        assert_eq!(err.code(), "unsupported", "got {err:?}");
        //: And it is still there, unchanged.
        assert_eq!(std::fs::read(&text).unwrap(), b"not a picture");

        let missing = base.join("gone.png");
        assert_eq!(turn(&missing, Turn::Left).unwrap_err().code(), "not-found");
    }

    #[test]
    fn the_permissions_survive_a_turn() {
        use std::os::unix::fs::PermissionsExt;
        let base = scratch("mode");
        let file = base.join("shot.png");
        lopsided().save(&file).unwrap();
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o640)).unwrap();
        turn(&file, Turn::HalfTurn).unwrap();
        let mode = std::fs::metadata(&file).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o640, "the turned picture came back with different permissions");
        //: And nothing was left beside it.
        let leftovers: Vec<_> = std::fs::read_dir(&base)
            .unwrap()
            .flatten()
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .filter(|n| n != "shot.png")
            .collect();
        assert!(leftovers.is_empty(), "left behind {leftovers:?}");
    }
}
