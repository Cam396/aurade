//! Split archives: one archive written as numbered parts, read back as one.
//!
//! 7z's multi volume form is a plain byte split. `thing.7z.001`, `thing.7z.002`
//! and the rest concatenate back to exactly the bytes a single `thing.7z` would
//! have held, so the parts can be made by cutting the finished archive up and
//! read by stitching it back together, with nothing decoded either way.
//!
//! That is also why this is offered for 7z and for nothing else. A spanned zip
//! is not a byte split: each part carries its own header and the central
//! directory records which disk an entry starts on, so cutting a finished zip
//! into pieces produces files that no reader will open. Offering the box for
//! zip and quietly writing something unreadable would be worse than not
//! offering it.

use std::fs::{self, File};
use std::io::{self, BufReader, BufWriter, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

use crate::error::{Error, Result};

/// The smallest part this will write.
///
/// Not a matter of taste. The size is a divisor, so a small enough one turns a
/// modest archive into thousands of files, each with its own inode and its own
/// line in the folder. Every named size below sits far above this; the floor is
/// what answers a caller that works one out for itself.
pub const SMALLEST_PART: u64 = 64 * 1024;

/// How many digits a part number carries. 7z pads to three and then lets the
/// number grow, so part 1000 is `.1000` rather than an error or a wrap.
const DIGITS: usize = 3;

const MB: u64 = 1024 * 1024;

/// How large each part may be, or that there are to be no parts.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct Split(Option<u64>);

impl Split {
    /// One whole archive.
    pub const NONE: Split = Split(None);

    /// The sizes the compress dialog offers: the name a request uses, what to
    /// show a person, and how many bytes it is.
    ///
    /// The odd looking ones are media capacities, which is most of the reason
    /// to split an archive at all: a 4092 MB part is what fits on a FAT32
    /// stick, and a 4480 MB one is what fits on a DVD.
    pub const ALL: [(&'static str, &'static str, Option<u64>); 12] = [
        ("none", "Do not split", None),
        ("10m", "10 MB", Some(10 * MB)),
        ("100m", "100 MB", Some(100 * MB)),
        ("650m", "CD, 650 MB", Some(650 * MB)),
        ("700m", "CD, 700 MB", Some(700 * MB)),
        ("1024m", "1 GB", Some(1024 * MB)),
        ("2048m", "2 GB", Some(2048 * MB)),
        ("4092m", "FAT32, 4092 MB", Some(4092 * MB)),
        ("4480m", "DVD, 4480 MB", Some(4480 * MB)),
        ("5120m", "5 GB", Some(5120 * MB)),
        ("8128m", "DVD DL, 8128 MB", Some(8128 * MB)),
        ("23040m", "Blu-ray, 23040 MB", Some(23040 * MB)),
    ];

    /// One of the named sizes, or nothing. An unknown name is not silently a
    /// whole archive: the caller asked for something and deserves the 400.
    pub fn from_name(name: &str) -> Option<Split> {
        let wanted = name.trim().to_ascii_lowercase();
        Split::ALL.iter().find(|(n, _, _)| *n == wanted).map(|(_, _, bytes)| Split(*bytes))
    }

    /// A size the caller worked out itself, checked against the floor.
    pub fn of_bytes(bytes: u64) -> Result<Split> {
        if bytes < SMALLEST_PART {
            return Err(Error::BadRequest(format!(
                "a part of {bytes} bytes is under the {SMALLEST_PART} byte minimum"
            )));
        }
        Ok(Split(Some(bytes)))
    }

    pub fn bytes(self) -> Option<u64> {
        self.0
    }

    pub fn wanted(self) -> bool {
        self.0.is_some()
    }
}

// ------------------------------------------------------------------ names ---

/// The name of one part: `thing.7z` and 1 give `thing.7z.001`.
pub fn part_name(archive: &Path, index: usize) -> PathBuf {
    let mut name = archive.as_os_str().to_os_string();
    name.push(format!(".{index:03}"));
    PathBuf::from(name)
}

/// The archive a numbered part belongs to, and which part it is.
///
/// Only a run of three or more digits counts, so `notes.2024` and
/// `photo.7z.bak` are left alone. Part zero is refused: 7z counts from one, and
/// a `.000` in a folder is something else.
pub fn numbered(path: &Path) -> Option<(PathBuf, usize)> {
    let name = path.file_name()?.to_str()?;
    let (base, digits) = name.rsplit_once('.')?;
    if base.is_empty() || digits.len() < DIGITS || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let index: usize = digits.parse().ok()?;
    if index == 0 {
        return None;
    }
    Some((path.with_file_name(base), index))
}

/// Every part of the set `any_part` belongs to, in order.
///
/// The set has to be complete to be read at all. A 7z keeps its header at the
/// end, so a missing part is not a shorter archive, it is an unreadable one;
/// the hole is named rather than read past, because "part 2 of thing.7z is not
/// here" is something a person can act on and a decode error is not.
pub fn parts_of(any_part: &Path) -> Result<Vec<PathBuf>> {
    let Some((archive, _)) = numbered(any_part) else {
        return Err(Error::BadRequest(format!(
            "{} is not a numbered part of an archive",
            any_part.display()
        )));
    };
    let dir = match archive.parent() {
        Some(p) if !p.as_os_str().is_empty() => p.to_path_buf(),
        _ => PathBuf::from("."),
    };
    let stem = archive.file_name().unwrap_or_default().to_os_string();

    let mut found: Vec<(usize, PathBuf)> = Vec::new();
    for entry in
        fs::read_dir(&dir).map_err(|e| Error::io(dir.display().to_string(), e))?.flatten()
    {
        //: A directory called `thing.7z.002` is not part two of anything.
        if !entry.file_type().map(|t| t.is_file()).unwrap_or(false) {
            continue;
        }
        let path = entry.path();
        if let Some((base, index)) = numbered(&path) {
            if base.file_name().unwrap_or_default() == stem {
                found.push((index, path));
            }
        }
    }
    found.sort_by_key(|(index, _)| *index);

    if found.is_empty() {
        return Err(Error::NotFound(part_name(&archive, 1).display().to_string()));
    }
    for (wanted, (index, _)) in (1usize..).zip(found.iter()) {
        if *index != wanted {
            return Err(Error::NotFound(part_name(&archive, wanted).display().to_string()));
        }
    }
    Ok(found.into_iter().map(|(_, path)| path).collect())
}

// ---------------------------------------------------------------- writing ---

/// Cut a finished archive into numbered parts and remove the whole one.
///
/// Every part is named before any is written, so a set that would land on top
/// of files already there is refused with the archive still in one piece. A
/// failure part way through takes the parts it wrote with it, for the same
/// reason: half a set is not an archive and cannot be opened as one.
pub fn split_file(archive: &Path, part: u64) -> Result<Vec<PathBuf>> {
    if part < SMALLEST_PART {
        return Err(Error::BadRequest(format!(
            "a part of {part} bytes is under the {SMALLEST_PART} byte minimum"
        )));
    }
    let total = fs::metadata(archive)
        .map_err(|e| Error::io(archive.display().to_string(), e))?
        .len();
    //: An archive that fits inside one part still becomes `.001`, which is
    //: what 7z itself writes and what keeps the name of a set predictable
    //: whether or not the guess about its size turned out to be right.
    let count = total.div_ceil(part).max(1);
    let names: Vec<PathBuf> =
        (1..=count as usize).map(|index| part_name(archive, index)).collect();
    for name in &names {
        if name.symlink_metadata().is_ok() {
            return Err(Error::Exists(name.display().to_string()));
        }
    }

    let written = write_parts(archive, part, &names);
    if let Err(e) = written {
        for name in &names {
            let _ = fs::remove_file(name);
        }
        return Err(e);
    }
    fs::remove_file(archive).map_err(|e| Error::io(archive.display().to_string(), e))?;
    Ok(names)
}

fn write_parts(archive: &Path, part: u64, names: &[PathBuf]) -> Result<()> {
    let file = File::open(archive).map_err(|e| Error::io(archive.display().to_string(), e))?;
    let mut source = BufReader::new(file);
    for name in names {
        let mut sink = BufWriter::new(
            File::create(name).map_err(|e| Error::io(name.display().to_string(), e))?,
        );
        let mut window = (&mut source).take(part);
        io::copy(&mut window, &mut sink)
            .map_err(|e| Error::io(name.display().to_string(), e))?;
        sink.flush().map_err(|e| Error::io(name.display().to_string(), e))?;
    }
    Ok(())
}

// ---------------------------------------------------------------- reading ---

/// The parts of a split archive, read as though they were one file.
///
/// This is a `Read + Seek` over the set, which is what a 7z reader needs: the
/// header is at the end, so the first thing it does is seek there. Stitching
/// the parts into a temporary file first would work as well and would want as
/// much free space again as the archive takes, which for the sizes people
/// split archives at is the whole point of not doing it.
#[derive(Debug)]
pub struct Volumes {
    parts: Vec<(PathBuf, u64)>,
    total: u64,
    pos: u64,
    open: Option<(usize, File)>,
}

impl Volumes {
    /// Open the whole set that `any_part` belongs to.
    pub fn open(any_part: &Path) -> Result<Volumes> {
        let names = parts_of(any_part)?;
        let mut parts = Vec::with_capacity(names.len());
        let mut total = 0;
        for name in names {
            let len = fs::metadata(&name)
                .map_err(|e| Error::io(name.display().to_string(), e))?
                .len();
            total += len;
            parts.push((name, len));
        }
        Ok(Volumes { parts, total, pos: 0, open: None })
    }

    /// How many bytes the set holds together.
    pub fn len(&self) -> u64 {
        self.total
    }

    pub fn is_empty(&self) -> bool {
        self.total == 0
    }

    /// How many files it took.
    pub fn parts(&self) -> usize {
        self.parts.len()
    }

    /// Which part a position lands in, and how far into it, or nothing when it
    /// is at or past the end.
    fn locate(&self, pos: u64) -> Option<(usize, u64)> {
        let mut start = 0;
        for (index, (_, len)) in self.parts.iter().enumerate() {
            if pos < start + len {
                return Some((index, pos - start));
            }
            start += len;
        }
        None
    }
}

impl Read for Volumes {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        if buf.is_empty() {
            return Ok(0);
        }
        let Some((index, offset)) = self.locate(self.pos) else { return Ok(0) };
        let reopen = match &self.open {
            Some((open, _)) => *open != index,
            None => true,
        };
        if reopen {
            self.open = Some((index, File::open(&self.parts[index].0)?));
        }
        //: Held to the length this part had when the set was opened. A part
        //: that grew under us is not more archive, and reading the extra would
        //: put bytes in the middle of the stream that were never there.
        let room = (self.parts[index].1 - offset).min(buf.len() as u64) as usize;
        let (_, file) = self.open.as_mut().expect("just opened");
        file.seek(SeekFrom::Start(offset))?;
        let read = file.read(&mut buf[..room])?;
        if read == 0 {
            //: Nothing to read where there should have been something: the
            //: part shrank while the archive was being read. Saying so beats
            //: handing back a stream that looks complete and is not.
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                format!("{} is shorter than it was", self.parts[index].0.display()),
            ));
        }
        self.pos += read as u64;
        Ok(read)
    }
}

impl Seek for Volumes {
    fn seek(&mut self, from: SeekFrom) -> io::Result<u64> {
        //: Through i128 because every one of these can overflow: a seek to
        //: u64::MAX, or a negative offset from a position near zero. Past the
        //: end is allowed, as it is on a real file, and reads there give 0.
        let target: i128 = match from {
            SeekFrom::Start(n) => n as i128,
            SeekFrom::End(n) => self.total as i128 + n as i128,
            SeekFrom::Current(n) => self.pos as i128 + n as i128,
        };
        if target < 0 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "a seek to before the start of the archive",
            ));
        }
        self.pos = target.min(u64::MAX as i128) as u64;
        Ok(self.pos)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "auradefs-volume-{tag}-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn write(path: &Path, bytes: &[u8]) {
        let mut f = File::create(path).unwrap();
        f.write_all(bytes).unwrap();
    }

    /// A run whose every byte says where it is, so a stitch that loses or
    /// repeats a stretch shows up as a wrong value rather than a wrong length.
    fn counted(len: usize) -> Vec<u8> {
        (0..len).map(|i| (i % 251) as u8).collect()
    }

    #[test]
    fn the_named_sizes_are_the_ones_the_dialog_offers() {
        assert_eq!(Split::ALL.len(), 12);
        assert_eq!(Split::from_name("none").unwrap().bytes(), None);
        assert_eq!(Split::from_name("10m").unwrap().bytes(), Some(10 * 1024 * 1024));
        assert_eq!(Split::from_name("4092m").unwrap().bytes(), Some(4092 * 1024 * 1024));
        assert_eq!(Split::from_name("23040m").unwrap().bytes(), Some(23040 * 1024 * 1024));
        //: Case and stray spaces come from a form field, not from an attack.
        assert_eq!(Split::from_name(" 700M ").unwrap().bytes(), Some(700 * 1024 * 1024));
        assert!(Split::from_name("dvd").is_none());
        assert!(Split::from_name("").is_none());
    }

    #[test]
    fn a_part_under_the_floor_is_refused() {
        assert!(Split::of_bytes(SMALLEST_PART - 1).is_err());
        assert!(Split::of_bytes(0).is_err());
        assert_eq!(Split::of_bytes(SMALLEST_PART).unwrap().bytes(), Some(SMALLEST_PART));
    }

    #[test]
    fn a_part_number_is_three_digits_counted_from_one() {
        assert_eq!(part_name(Path::new("/a/thing.7z"), 1), Path::new("/a/thing.7z.001"));
        assert_eq!(part_name(Path::new("/a/thing.7z"), 42), Path::new("/a/thing.7z.042"));
        //: Past 999 the number grows rather than wrapping.
        assert_eq!(part_name(Path::new("/a/thing.7z"), 1000), Path::new("/a/thing.7z.1000"));
    }

    #[test]
    fn only_a_numbered_part_reads_as_one() {
        let (base, index) = numbered(Path::new("/a/thing.7z.007")).unwrap();
        assert_eq!(base, Path::new("/a/thing.7z"));
        assert_eq!(index, 7);
        //: Two digits is a year or a version, not a part.
        assert!(numbered(Path::new("/a/notes.99")).is_none());
        assert!(numbered(Path::new("/a/photo.7z.bak")).is_none());
        assert!(numbered(Path::new("/a/thing.7z")).is_none());
        //: 7z counts from one, so a `.000` beside a set is a different file.
        assert!(numbered(Path::new("/a/thing.7z.000")).is_none());
    }

    #[test]
    fn splitting_writes_numbered_parts_and_removes_the_whole_one() {
        let dir = scratch("write");
        let whole = dir.join("thing.7z");
        write(&whole, &counted(200_000));

        let parts = split_file(&whole, SMALLEST_PART).unwrap();
        assert_eq!(parts.len(), 4, "200000 bytes at 65536 is four parts");
        assert!(!whole.exists(), "the whole archive is gone once it is in parts");
        for part in &parts[..3] {
            assert_eq!(fs::metadata(part).unwrap().len(), SMALLEST_PART);
        }
        let last = fs::metadata(&parts[3]).unwrap().len();
        assert_eq!(last, 200_000 - 3 * SMALLEST_PART);
        assert_eq!(parts[0], dir.join("thing.7z.001"));
        assert_eq!(parts[3], dir.join("thing.7z.004"));
    }

    #[test]
    fn an_archive_that_fits_in_one_part_still_becomes_a_set() {
        let dir = scratch("one");
        let whole = dir.join("small.7z");
        write(&whole, &counted(1000));
        let parts = split_file(&whole, SMALLEST_PART).unwrap();
        assert_eq!(parts, vec![dir.join("small.7z.001")]);
        assert!(!whole.exists());
    }

    #[test]
    fn a_split_that_would_land_on_a_file_is_refused_with_nothing_written() {
        let dir = scratch("clash");
        let whole = dir.join("thing.7z");
        write(&whole, &counted(200_000));
        write(&dir.join("thing.7z.003"), b"someone else's file");

        let refused = split_file(&whole, SMALLEST_PART).unwrap_err();
        assert!(matches!(refused, Error::Exists(_)), "got {refused:?}");
        assert!(whole.exists(), "the archive is still whole");
        assert!(!dir.join("thing.7z.001").exists(), "and nothing was written first");
        assert_eq!(fs::read(dir.join("thing.7z.003")).unwrap(), b"someone else's file");
    }

    #[test]
    fn a_part_under_the_floor_is_refused_by_the_writer_too() {
        let dir = scratch("floor");
        let whole = dir.join("thing.7z");
        write(&whole, &counted(200_000));
        assert!(split_file(&whole, 512).is_err());
        assert!(whole.exists());
    }

    #[test]
    fn the_parts_read_back_as_the_bytes_they_were_cut_from() {
        let dir = scratch("read");
        let whole = dir.join("thing.7z");
        let original = counted(200_000);
        write(&whole, &original);
        split_file(&whole, SMALLEST_PART).unwrap();

        let mut set = Volumes::open(&dir.join("thing.7z.001")).unwrap();
        assert_eq!(set.parts(), 4);
        assert_eq!(set.len(), 200_000);
        let mut back = Vec::new();
        set.read_to_end(&mut back).unwrap();
        assert_eq!(back, original);
    }

    #[test]
    fn any_part_names_the_whole_set() {
        let dir = scratch("any");
        let whole = dir.join("thing.7z");
        write(&whole, &counted(200_000));
        split_file(&whole, SMALLEST_PART).unwrap();
        //: The caller opens whichever one they clicked on, which need not be
        //: the first.
        let set = Volumes::open(&dir.join("thing.7z.003")).unwrap();
        assert_eq!(set.parts(), 4);
        assert_eq!(set.len(), 200_000);
    }

    #[test]
    fn a_seek_lands_in_the_right_part() {
        let dir = scratch("seek");
        let whole = dir.join("thing.7z");
        let original = counted(200_000);
        write(&whole, &original);
        split_file(&whole, SMALLEST_PART).unwrap();
        let mut set = Volumes::open(&dir.join("thing.7z.001")).unwrap();

        //: The end, which is where a 7z reader looks first.
        set.seek(SeekFrom::End(-16)).unwrap();
        let mut tail = Vec::new();
        set.read_to_end(&mut tail).unwrap();
        assert_eq!(tail, original[original.len() - 16..]);

        //: Straddling a boundary, which is the case a single file never
        //: exercises: eight bytes ending in part one and eight beginning in
        //: part two.
        set.seek(SeekFrom::Start(SMALLEST_PART - 8)).unwrap();
        let mut across = [0u8; 16];
        set.read_exact(&mut across).unwrap();
        let at = (SMALLEST_PART - 8) as usize;
        assert_eq!(&across[..], &original[at..at + 16]);

        //: And past the end reads nothing rather than failing.
        set.seek(SeekFrom::Start(500_000)).unwrap();
        assert_eq!(set.read(&mut across).unwrap(), 0);
        assert!(set.seek(SeekFrom::Start(0)).is_ok());
        assert!(set.seek(SeekFrom::Current(-1)).is_err());
    }

    #[test]
    fn a_part_that_grows_under_the_reader_does_not_bleed_into_the_stream() {
        //: Deliberately not a power of two. `read_to_end` doubles what it asks
        //: for, so against a 64 KiB part it lands exactly on the boundary and
        //: never asks for a byte past it: the test would then be measuring the
        //: buffer growth rather than the clamp, and passed either way.
        const PART: u64 = SMALLEST_PART + 1000;
        let dir = scratch("grow");
        let whole = dir.join("thing.7z");
        let original = counted(200_000);
        write(&whole, &original);
        split_file(&whole, PART).unwrap();

        //: Opened first, so the lengths are the ones recorded, and then part
        //: one gains four kilobytes it did not have.
        let mut set = Volumes::open(&dir.join("thing.7z.001")).unwrap();
        let mut first = fs::OpenOptions::new()
            .append(true)
            .open(dir.join("thing.7z.001"))
            .unwrap();
        first.write_all(&[0xAA; 4096]).unwrap();
        first.flush().unwrap();
        drop(first);

        //: Straight across the seam, which is the read that has to be held to
        //: where the part ended when the set was opened. Without that, the
        //: eight bytes after the seam come from what was appended rather than
        //: from part two.
        set.seek(SeekFrom::Start(PART - 8)).unwrap();
        let mut across = [0u8; 16];
        set.read_exact(&mut across).unwrap();
        let at = (PART - 8) as usize;
        assert_eq!(&across[..], &original[at..at + 16], "the seam read the wrong bytes");

        //: And the whole of it is still the archive it was. Appended bytes are
        //: not more archive: reading them would put four kilobytes of
        //: something else into the middle of the stream and push the real
        //: bytes there out of the way.
        set.seek(SeekFrom::Start(0)).unwrap();
        let mut back = Vec::new();
        set.read_to_end(&mut back).unwrap();
        assert_eq!(back.len(), 200_000, "the set changed length under the reader");
        assert_eq!(
            back.iter().zip(original.iter()).position(|(a, b)| a != b),
            None,
            "the stream differs from what was split"
        );
    }

    #[test]
    fn a_missing_part_is_named_rather_than_read_past() {
        let dir = scratch("hole");
        let whole = dir.join("thing.7z");
        write(&whole, &counted(200_000));
        split_file(&whole, SMALLEST_PART).unwrap();
        fs::remove_file(dir.join("thing.7z.002")).unwrap();

        let refused = Volumes::open(&dir.join("thing.7z.001")).unwrap_err();
        match refused {
            Error::NotFound(named) => assert!(
                named.ends_with("thing.7z.002"),
                "the error names the part that is missing, got {named}"
            ),
            other => panic!("expected the missing part to be named, got {other:?}"),
        }
    }

    #[test]
    fn a_directory_beside_the_set_is_not_a_part() {
        let dir = scratch("dir");
        let whole = dir.join("thing.7z");
        write(&whole, &counted(100_000));
        split_file(&whole, SMALLEST_PART).unwrap();
        fs::create_dir(dir.join("thing.7z.003")).unwrap();
        let set = Volumes::open(&dir.join("thing.7z.001")).unwrap();
        assert_eq!(set.parts(), 2);
    }

    #[test]
    fn a_path_that_is_not_a_part_is_refused() {
        let dir = scratch("notpart");
        let refused = parts_of(&dir.join("thing.7z")).unwrap_err();
        assert!(matches!(refused, Error::BadRequest(_)), "got {refused:?}");
    }
}
