//! Archives: create, inspect, extract.
//!
//! Eight of the reference's commands are archive commands, and in the
//! prototype all eight were menu rows wired to nothing. The formats a Linux
//! desktop actually meets are zip, 7z and the tar family, so those are what
//! this handles directly rather than shelling out to whatever happens to be
//! installed.
//!
//! The security property that matters here is that an archive is untrusted
//! input. An entry named `../../.bashrc`, or an absolute path, or a symlink
//! pointing out of the destination, all let a crafted archive write anywhere
//! the user can. Every entry goes through [`safe_join`] before a byte is
//! written, and symlink entries are refused outright.

use std::fs::{self, File};
use std::io::{self, BufReader, BufWriter, Read, Seek, SeekFrom, Write};
use std::path::{Component, Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::error::{Error, Result};
use crate::ops::volume::{self, Split, Volumes};

/// The formats this service reads and writes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Format {
    Zip,
    SevenZip,
    Tar,
    TarGz,
    TarXz,
    TarZst,
}

impl Format {
    /// Guess from a file name. Two-part extensions are checked first, because
    /// `.tar.gz` ends in `.gz` and would otherwise read as a bare gzip.
    pub fn from_name(name: &str) -> Option<Format> {
        let lower = name.to_ascii_lowercase();
        for (suffix, format) in [
            (".tar.gz", Format::TarGz),
            (".tgz", Format::TarGz),
            (".tar.xz", Format::TarXz),
            (".txz", Format::TarXz),
            (".tar.zst", Format::TarZst),
            (".tzst", Format::TarZst),
            (".tar", Format::Tar),
            (".zip", Format::Zip),
            (".7z", Format::SevenZip),
        ] {
            if lower.ends_with(suffix) {
                return Some(format);
            }
        }
        None
    }

    /// The extension this service appends when it creates one.
    pub fn extension(self) -> &'static str {
        match self {
            Format::Zip => "zip",
            Format::SevenZip => "7z",
            Format::Tar => "tar",
            Format::TarGz => "tar.gz",
            Format::TarXz => "tar.xz",
            Format::TarZst => "tar.zst",
        }
    }

    /// Whether the format has anywhere to put a password.
    ///
    /// A tar has no encryption of its own and never has had: what the world
    /// calls an encrypted tarball is a tar handed to gpg afterwards, which is
    /// a different operation with different keys. So the answer is no rather
    /// than a password quietly doing nothing.
    pub fn takes_password(self) -> bool {
        matches!(self, Format::Zip | Format::SevenZip)
    }
}

// ---------------------------------------------------------------- options ---

/// How hard to try.
///
/// Files names six steps rather than showing a number, because the number is
/// different for every codec and means nothing to the person choosing. These
/// are those six names; each format maps them onto its own scale below.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Level {
    Ultra,
    High,
    #[default]
    Normal,
    Low,
    Fast,
    /// No compression asked for at all. Worth having for a folder of video or
    /// of already compressed archives, which will not get smaller and would
    /// otherwise be read twice for nothing.
    Store,
}

impl Level {
    pub const ALL: [Level; 6] =
        [Level::Ultra, Level::High, Level::Normal, Level::Low, Level::Fast, Level::Store];

    pub fn name(self) -> &'static str {
        match self {
            Level::Ultra => "ultra",
            Level::High => "high",
            Level::Normal => "normal",
            Level::Low => "low",
            Level::Fast => "fast",
            Level::Store => "store",
        }
    }

    pub fn from_name(name: &str) -> Option<Level> {
        match name.trim().to_ascii_lowercase().as_str() {
            "ultra" => Some(Level::Ultra),
            "high" | "maximum" => Some(Level::High),
            "normal" | "default" => Some(Level::Normal),
            "low" => Some(Level::Low),
            "fast" | "fastest" => Some(Level::Fast),
            "store" | "none" | "copy" => Some(Level::Store),
            _ => None,
        }
    }

    /// Deflate, which zip and gzip both use, runs 0 to 9 and has nothing
    /// beyond 9. Ultra and High therefore land on the same setting: the scale
    /// runs out before the names do, and pretending otherwise would be a
    /// choice that changes nothing.
    fn deflate(self) -> u32 {
        match self {
            Level::Ultra | Level::High => 9,
            Level::Normal => 6,
            Level::Low => 3,
            Level::Fast => 1,
            Level::Store => 0,
        }
    }

    /// zstd runs 1 to 22, and its own default is 3. Nothing here goes near the
    /// top of that range: past about 19 the time grows far faster than the
    /// saving, and this runs while somebody waits.
    fn zstd(self) -> i32 {
        match self {
            Level::Ultra => 19,
            Level::High => 12,
            Level::Normal => 3,
            Level::Low => 2,
            Level::Store | Level::Fast => 1,
        }
    }

    /// xz and lzma2 share a 0 to 9 preset scale, where 9 wants around 700 MB
    /// of memory to compress and 65 MB to decompress. That is a real cost on a
    /// Chromebook, so Ultra stops at 9 and High sits well below it.
    fn lzma(self) -> u32 {
        match self {
            Level::Ultra => 9,
            Level::High => 7,
            Level::Normal => 6,
            Level::Low => 3,
            Level::Fast => 1,
            Level::Store => 0,
        }
    }
}

/// Everything the compress dialog sets besides the format itself.
#[derive(Debug, Clone, Default)]
pub struct Options {
    pub level: Level,
    /// None means no encryption. An empty string is refused rather than read
    /// as None: an empty password box is a mistake, and answering it by
    /// quietly writing a readable archive is the wrong way to be helpful.
    pub password: Option<String>,
    /// Write the archive as numbered parts of at most this size. Only 7z is
    /// split, for the reason spelled out in [`crate::ops::volume`].
    pub split: Split,
    /// The LZMA2 dictionary in bytes, or None for the level's own. Only a 7z
    /// has one to set; the dialog offers 64 KB to 1024 MB.
    pub dictionary: Option<u32>,
    /// The match finder's nice length, which 7-Zip calls the word size, or
    /// None for the level's own. Only a 7z has one; 8 to 273.
    pub word_size: Option<u32>,
    /// How many threads the 7z encoder runs. 0 and 1 both mean one, which
    /// writes one LZMA2 stream; more cut the input into chunks that compress
    /// side by side, each on its own, which is faster and a little larger.
    /// The zip and tar writers here run on one thread whatever this says,
    /// and [`Format::threaded`] says so, so the dialog can grey the box.
    pub threads: u32,
}

/// The LZMA2 dictionary sizes the dialog offers, in bytes, smallest first:
/// the reference's list, 64 KB to 1024 MB.
pub const DICTIONARIES: [u32; 13] = [
    64 << 10,
    256 << 10,
    1 << 20,
    2 << 20,
    4 << 20,
    8 << 20,
    16 << 20,
    32 << 20,
    64 << 20,
    128 << 20,
    256 << 20,
    512 << 20,
    1024 << 20,
];
pub const DICTIONARY_MIN: u32 = DICTIONARIES[0];
pub const DICTIONARY_MAX: u32 = DICTIONARIES[12];
/// The word sizes the dialog offers, which are nice lengths for the match
/// finder; 8 and 273 are the codec's own bounds.
pub const WORD_SIZES: [u32; 7] = [8, 16, 32, 64, 128, 256, 273];
pub const WORD_SIZE_MIN: u32 = WORD_SIZES[0];
pub const WORD_SIZE_MAX: u32 = WORD_SIZES[6];

impl Options {
    pub fn new(level: Level) -> Options {
        Options { level, ..Options::default() }
    }

    /// Check the pair before a byte is written, so a request that cannot be
    /// honoured fails with nothing half made on disk.
    fn check(&self, format: Format) -> Result<()> {
        if self.split.wanted() && format != Format::SevenZip {
            return Err(Error::Unsupported(format!(
                "a .{} is not written in parts",
                format.extension()
            )));
        }
        if (self.dictionary.is_some() || self.word_size.is_some())
            && format != Format::SevenZip
        {
            return Err(Error::Unsupported(format!(
                "a .{} has no dictionary or word size to set",
                format.extension()
            )));
        }
        if let Some(d) = self.dictionary
            && !(DICTIONARY_MIN..=DICTIONARY_MAX).contains(&d)
        {
            return Err(Error::BadRequest(format!(
                "a dictionary is {} to {} bytes, not {d}",
                DICTIONARY_MIN, DICTIONARY_MAX
            )));
        }
        if let Some(w) = self.word_size
            && !(WORD_SIZE_MIN..=WORD_SIZE_MAX).contains(&w)
        {
            return Err(Error::BadRequest(format!(
                "a word size is {WORD_SIZE_MIN} to {WORD_SIZE_MAX}, not {w}"
            )));
        }
        //: A dictionary the machine cannot hold would not fail cleanly: the
        //: allocation is granted and the touch of it is what the kernel
        //: answers, by killing the daemon. Refuse it here, with the numbers.
        if format == Format::SevenZip && self.level != Level::Store {
            let estimate = self.lzma2_estimate();
            if let Some(free) = available_memory()
                && estimate.bytes > free
            {
                return Err(Error::BadRequest(format!(
                    "compressing with a {} dictionary on {} thread{} needs about {} of \
                     memory, and {} is free",
                    human_size(u64::from(estimate.dictionary)),
                    estimate.threads,
                    if estimate.threads == 1 { "" } else { "s" },
                    human_size(estimate.bytes),
                    human_size(free),
                )));
            }
        }
        let Some(password) = &self.password else { return Ok(()) };
        if password.is_empty() {
            return Err(Error::BadRequest("an empty password is not a password".into()));
        }
        if !format.takes_password() {
            return Err(Error::Unsupported(format!(
                "a .{} cannot carry a password",
                format.extension()
            )));
        }
        Ok(())
    }
}

/// One entry as the archive describes itself, before anything is written.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Entry {
    pub name: String,
    pub size: u64,
    pub is_dir: bool,
}

/// Join an archive entry name onto a destination, or refuse.
///
/// This is the whole of zip slip prevention and it is deliberately strict: an
/// absolute path, any `..`, and any Windows drive prefix are refused rather
/// than sanitised, because silently rewriting an entry name produces a file
/// the person did not ask for under a name they did not see.
pub fn safe_join(dest: &Path, name: &str) -> Result<PathBuf> {
    let raw = Path::new(name);
    let mut out = dest.to_path_buf();
    let mut wrote = false;
    for part in raw.components() {
        match part {
            Component::Normal(p) => {
                //: A backslash is a legal byte in a POSIX filename, so an
                //: entry written on Windows can smuggle a separator through a
                //: single component. Refuse rather than split it.
                if p.to_string_lossy().contains('\\') {
                    return Err(Error::BadRequest(format!(
                        "archive entry has a backslash in a component: {name}"
                    )));
                }
                out.push(p);
                wrote = true;
            }
            Component::CurDir => {}
            Component::ParentDir | Component::RootDir | Component::Prefix(_) => {
                return Err(Error::Escapes(name.to_string()));
            }
        }
    }
    if !wrote {
        return Err(Error::BadRequest(format!("archive entry has no name: {name}")));
    }
    Ok(out)
}

fn create_parent(path: &Path) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| Error::io(parent.display().to_string(), e))?;
    }
    Ok(())
}

// ----------------------------------------------------------------- shape --

/// What format a path is, following a numbered part back to the set it is a
/// piece of.
///
/// `thing.7z.001` is a 7z. The number says which piece of it this is, not what
/// kind of file it is, and reading it as an unknown type would leave a person
/// looking at an archive the program says it cannot open.
pub fn format_of(path: &Path) -> Result<Format> {
    let name = path.file_name().unwrap_or_default().to_string_lossy().into_owned();
    if let Some(format) = Format::from_name(&name) {
        return Ok(format);
    }
    let unknown = || Error::BadRequest(format!("unknown archive type: {name}"));
    let (archive, _) = volume::numbered(path).ok_or_else(unknown)?;
    let base = archive.file_name().unwrap_or_default().to_string_lossy().into_owned();
    match Format::from_name(&base) {
        Some(Format::SevenZip) => Ok(Format::SevenZip),
        //: A `.zip.001` is a file someone made with a byte splitter, not a
        //: spanned zip, and stitching it would produce a zip that is missing
        //: the per part headers a spanned one carries. Say so.
        Some(other) => Err(Error::Unsupported(format!(
            "a .{} is not read in parts",
            other.extension()
        ))),
        None => Err(unknown()),
    }
}

/// A 7z that is one file, or the set of parts that stands for one.
///
/// An enum rather than a boxed trait object because the reader is handed to
/// the 7z crate by value, and the crate is generic over `Read + Seek`; two
/// concrete cases behind one name is all that is wanted here.
enum SevenZipSource {
    One(BufReader<File>),
    Many(BufReader<Volumes>),
}

fn seven_zip_source(path: &Path) -> Result<SevenZipSource> {
    if volume::numbered(path).is_some() {
        return Ok(SevenZipSource::Many(BufReader::new(Volumes::open(path)?)));
    }
    let file = File::open(path).map_err(|e| Error::io(path.display().to_string(), e))?;
    Ok(SevenZipSource::One(BufReader::new(file)))
}

impl Read for SevenZipSource {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        match self {
            SevenZipSource::One(r) => r.read(buf),
            SevenZipSource::Many(r) => r.read(buf),
        }
    }
}

impl Seek for SevenZipSource {
    fn seek(&mut self, from: SeekFrom) -> io::Result<u64> {
        match self {
            SevenZipSource::One(r) => r.seek(from),
            SevenZipSource::Many(r) => r.seek(from),
        }
    }
}

// ---------------------------------------------------------------- listing --

/// What is inside, without extracting any of it.
///
/// This is what makes "extract here, smart" a decision rather than a guess:
/// an archive with a single top level directory is already tidy and extracts
/// in place, and one with twenty loose files needs a folder made for it.
/// How the names inside a zip are read when the entry was written without
/// the UTF-8 flag. Such names are bytes in whatever code page the writer had,
/// and there is nothing in the file that says which; the reference offers a
/// list of them in the Extract dialog, and a guess marked "(detected)".
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Names {
    /// UTF-8 where the bytes are valid UTF-8, which most zips written on
    /// anything but Windows are without saying so, and the specification's
    /// own CP437 where they are not. What "system default" comes to here.
    #[default]
    Default,
    /// A code page the user chose.
    Encoding(&'static encoding_rs::Encoding),
}

impl Names {
    /// The dialog's choice, by the label the page sends; empty and "default"
    /// are [`Names::Default`], and a label nothing decodes is refused rather
    /// than quietly read as the default, since the user asked for something.
    pub fn from_label(label: &str) -> Result<Names> {
        let label = label.trim();
        if label.is_empty() || label.eq_ignore_ascii_case("default") {
            return Ok(Names::Default);
        }
        encoding_rs::Encoding::for_label(label.as_bytes())
            .map(Names::Encoding)
            .ok_or_else(|| Error::BadRequest(format!("unknown encoding: {label}")))
    }

    /// The name of one entry under this reading.
    fn zip_name(self, entry: &zip::read::ZipFile<'_>) -> String {
        use zip::HasZipMetadata;
        let raw = entry.name_raw();
        if entry.get_metadata().is_utf8 || raw.is_ascii() {
            return entry.name().to_string();
        }
        match self {
            Names::Default => match std::str::from_utf8(raw) {
                Ok(utf8) => utf8.to_string(),
                Err(_) => entry.name().to_string(),
            },
            Names::Encoding(encoding) => encoding.decode_without_bom_handling(raw).0.into_owned(),
        }
    }
}

/// The encodings the Extract dialog offers, after Default: the reference's
/// list, each by the label the page sends and the name it shows, which are
/// the names .NET gives them.
pub const ENCODINGS: [(&str, &str); 16] = [
    ("utf-8", "Unicode (UTF-8)"),
    ("shift_jis", "Japanese (Shift-JIS)"),
    ("gb18030", "Chinese Simplified (GB18030)"),
    ("big5", "Chinese Traditional (Big5)"),
    ("euc-kr", "Korean"),
    ("windows-1258", "Vietnamese (Windows)"),
    ("windows-874", "Thai (Windows)"),
    ("windows-1256", "Arabic (Windows)"),
    ("windows-1255", "Hebrew (Windows)"),
    ("windows-1254", "Turkish (Windows)"),
    ("windows-1252", "Western European (Windows)"),
    ("windows-1250", "Central European (Windows)"),
    ("windows-1251", "Cyrillic (Windows)"),
    ("windows-1253", "Greek (Windows)"),
    ("windows-1257", "Baltic (Windows)"),
    ("macintosh", "Western European (Mac)"),
];

/// The name the dialog shows for an encoding, from the table above, or the
/// encoding's own name for a guess that is not on it.
pub fn encoding_label(encoding: &'static encoding_rs::Encoding) -> (&'static str, &'static str) {
    let name = encoding.name();
    ENCODINGS
        .iter()
        .copied()
        .find(|(label, _)| {
            encoding_rs::Encoding::for_label(label.as_bytes()).is_some_and(|e| e == encoding)
        })
        .unwrap_or((name, name))
}

/// What a zip says, or fails to say, about its names.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct ZipNames {
    /// Some entry has a name that is neither flagged UTF-8 nor plain ASCII,
    /// so the dialog has an encoding to ask about. The reference's
    /// IsEncodingUndeterminedAsync, entry for entry.
    pub undetermined: bool,
    /// The guess for those names, when the bytes read cleanly as one
    /// encoding; None when they do not and the list stands on its own.
    pub detected: Option<&'static encoding_rs::Encoding>,
}

/// Read the names of a zip and say whether their encoding is in question,
/// with a guess when there is one. Anything but a zip has nothing to ask:
/// 7z and tar name their entries in UTF-8.
pub fn zip_names(path: &Path) -> Result<ZipNames> {
    if format_of(path)? != Format::Zip {
        return Ok(ZipNames::default());
    }
    use zip::HasZipMetadata;
    let file = File::open(path).map_err(|e| Error::io(path.display().to_string(), e))?;
    let mut zip = zip::ZipArchive::new(BufReader::new(file)).map_err(|e| zip_error(path, e))?;
    let mut unflagged: Vec<Vec<u8>> = Vec::new();
    for i in 0..zip.len() {
        let e = zip.by_index_raw(i).map_err(|e| zip_error(path, e))?;
        let raw = e.name_raw();
        if !e.get_metadata().is_utf8 && !raw.is_ascii() {
            unflagged.push(raw.to_vec());
        }
    }
    if unflagged.is_empty() {
        return Ok(ZipNames::default());
    }
    //: The detector reads the names as one text, a line each, the way the
    //: reference feeds its detector; and the guess is kept only when every
    //: name decodes without a replacement character, since a detector always
    //: answers something and a wrong answer offered as "(detected)" is worse
    //: than no answer.
    let mut detector = chardetng::EncodingDetector::new(chardetng::Iso2022JpDetection::Deny);
    let joined = unflagged.join(&b'\n');
    detector.feed(&joined, true);
    let guess = detector.guess(None, chardetng::Utf8Detection::Allow);
    let clean = unflagged.iter().all(|raw| !guess.decode_without_bom_handling(raw).1);
    Ok(ZipNames { undetermined: true, detected: if clean { Some(guess) } else { None } })
}

/// [`list`], reading zip names the chosen way.
pub fn list_with(path: &Path, password: Option<&str>, names: Names) -> Result<Vec<Entry>> {
    match format_of(path)? {
        Format::Zip => {
            let file = File::open(path).map_err(|e| Error::io(path.display().to_string(), e))?;
            let mut zip = zip::ZipArchive::new(BufReader::new(file))
                .map_err(|e| Error::Tool { tool: "zip".into(), message: e.to_string() })?;
            let mut out = Vec::with_capacity(zip.len());
            for i in 0..zip.len() {
                let e = zip.by_index_raw(i).map_err(|e| Error::Tool {
                    tool: "zip".into(),
                    message: e.to_string(),
                })?;
                out.push(Entry {
                    name: names.zip_name(&e),
                    size: e.size(),
                    is_dir: e.is_dir(),
                });
            }
            Ok(out)
        }
        _ => list(path, password),
    }
}

pub fn list(path: &Path, password: Option<&str>) -> Result<Vec<Entry>> {
    match format_of(path)? {
        Format::Zip => {
            let file = File::open(path).map_err(|e| Error::io(path.display().to_string(), e))?;
            let mut zip = zip::ZipArchive::new(BufReader::new(file))
                .map_err(|e| Error::Tool { tool: "zip".into(), message: e.to_string() })?;
            let mut out = Vec::with_capacity(zip.len());
            for i in 0..zip.len() {
                let e = zip.by_index_raw(i).map_err(|e| Error::Tool {
                    tool: "zip".into(),
                    message: e.to_string(),
                })?;
                out.push(Entry {
                    name: Names::Default.zip_name(&e),
                    size: e.size(),
                    is_dir: e.is_dir(),
                });
            }
            Ok(out)
        }
        Format::SevenZip => {
            let mut out = Vec::new();
            //: A 7z can encrypt its header as well as its contents, and then
            //: even the names need the password. Without one this is the
            //: request to read a listing that is not there, which is the
            //: password prompt rather than a failure.
            let reader = sevenz_rust2::ArchiveReader::new(
                seven_zip_source(path)?,
                seven_zip_password(password),
            )
            .map_err(|e| seven_zip_error(path, e))?;
            for e in &reader.archive().files {
                out.push(Entry {
                    name: e.name.clone(),
                    size: e.size,
                    is_dir: e.is_directory,
                });
            }
            Ok(out)
        }
        format => {
            let mut archive = tar::Archive::new(tar_reader(path, format)?);
            let mut out = Vec::new();
            for entry in archive
                .entries()
                .map_err(|e| Error::io(path.display().to_string(), e))?
            {
                let entry = entry.map_err(|e| Error::io(path.display().to_string(), e))?;
                let header = entry.header();
                out.push(Entry {
                    name: entry.path().map(|p| p.display().to_string()).unwrap_or_default(),
                    size: header.size().unwrap_or(0),
                    is_dir: header.entry_type().is_dir(),
                });
            }
            Ok(out)
        }
    }
}

/// The single top level directory an archive is wrapped in, if there is
/// exactly one and nothing sits beside it.
pub fn single_root(entries: &[Entry]) -> Option<String> {
    let mut root: Option<String> = None;
    for e in entries {
        let first = e.name.split('/').next().unwrap_or("").to_string();
        if first.is_empty() {
            return None;
        }
        match &root {
            None => root = Some(first),
            Some(r) if *r == first => {}
            Some(_) => return None,
        }
    }
    root
}

fn tar_reader(path: &Path, format: Format) -> Result<Box<dyn Read>> {
    let file = File::open(path).map_err(|e| Error::io(path.display().to_string(), e))?;
    let buf = BufReader::new(file);
    Ok(match format {
        Format::Tar => Box::new(buf),
        Format::TarGz => Box::new(flate2::read::GzDecoder::new(buf)),
        Format::TarXz => Box::new(xz2::read::XzDecoder::new(buf)),
        Format::TarZst => Box::new(
            zstd::stream::read::Decoder::new(buf)
                .map_err(|e| Error::io(path.display().to_string(), e))?,
        ),
        _ => return Err(Error::BadRequest("not a tar".into())),
    })
}

// ------------------------------------------------------------- extraction --

/// Where an extraction should put its contents.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Destination {
    /// Straight into the folder given.
    Here,
    /// Into a new folder named after the archive.
    ChildFolder,
    /// Here when the archive wraps itself in one directory, a child folder
    /// when it would otherwise scatter loose files.
    Smart,
}

/// Extract, refusing every entry that tries to leave `into`.
pub fn extract(
    path: &Path,
    into: &Path,
    dest: Destination,
    password: Option<&str>,
    report: crate::ops::fs::Reporter,
) -> Result<(PathBuf, Done)> {
    extract_with(path, into, dest, password, Names::Default, report)
}

/// [`extract`], reading zip names the chosen way.
pub fn extract_with(
    path: &Path,
    into: &Path,
    dest: Destination,
    password: Option<&str>,
    names: Names,
    report: crate::ops::fs::Reporter,
) -> Result<(PathBuf, Done)> {
    let name = path.file_name().unwrap_or_default().to_string_lossy().into_owned();
    let format = format_of(path)?;

    let target = match dest {
        Destination::Here => into.to_path_buf(),
        Destination::ChildFolder => into.join(strip_archive_suffix(&name)),
        Destination::Smart => {
            let entries = list_with(path, password, names)?;
            if single_root(&entries).is_some() {
                into.to_path_buf()
            } else {
                into.join(strip_archive_suffix(&name))
            }
        }
    };
    fs::create_dir_all(&target)
        .map_err(|e| Error::io(target.display().to_string(), e))?;

    //: What the archive says is in it, so the bar has something to fill. A
    //: listing is cheap next to the extraction; for a 7z it is the header,
    //: which has already been read to decide the destination above.
    let listed = list_with(path, password, names).unwrap_or_default();
    let mut progress = crate::ops::fs::Progress {
        total_items: listed.len() as u64,
        total_bytes: listed.iter().map(|e| e.size).sum(),
        ..Default::default()
    };
    let done = match format {
        Format::Zip => extract_zip(path, &target, password, names, report, &mut progress)?,
        Format::SevenZip => extract_7z(path, &target, password, report, &mut progress)?,
        _ => extract_tar(path, &target, format, report, &mut progress)?,
    };
    Ok((target, done))
}

/// `project.tar.gz` becomes `project`, not `project.tar`.
pub fn strip_archive_suffix(name: &str) -> String {
    //: `thing.7z.001` is one piece of `thing.7z` and extracts into `thing`,
    //: not into a folder named after the piece.
    let name = match name.rsplit_once('.') {
        Some((base, digits))
            if digits.len() >= 3
                && digits.bytes().all(|b| b.is_ascii_digit())
                && base.to_ascii_lowercase().ends_with(".7z") =>
        {
            base
        }
        _ => name,
    };
    let lower = name.to_ascii_lowercase();
    for suffix in [
        ".tar.gz", ".tar.xz", ".tar.zst", ".tgz", ".txz", ".tzst", ".tar", ".zip", ".7z",
    ] {
        if lower.ends_with(suffix) {
            return name[..name.len() - suffix.len()].to_string();
        }
    }
    name.to_string()
}

fn extract_zip(
    path: &Path,
    target: &Path,
    password: Option<&str>,
    names: Names,
    report: crate::ops::fs::Reporter,
    progress: &mut crate::ops::fs::Progress,
) -> Result<Done> {
    let file = File::open(path).map_err(|e| Error::io(path.display().to_string(), e))?;
    let mut zip = zip::ZipArchive::new(BufReader::new(file))
        .map_err(|e| zip_error(path, e))?;
    let mut done = Done::default();
    for i in 0..zip.len() {
        let mut entry = match password {
            Some(password) => zip
                .by_index_decrypt(i, password.as_bytes())
                .map_err(|e| zip_error(path, e))?,
            None => zip.by_index(i).map_err(|e| zip_error(path, e))?,
        };
        let name = names.zip_name(&entry);
        let out = safe_join(target, &name)?;
        if step(report, progress, &out) == crate::ops::fs::Flow::Cancel {
            done.cancelled = true;
            break;
        }
        if entry.is_dir() {
            fs::create_dir_all(&out)
                .map_err(|e| Error::io(out.display().to_string(), e))?;
            progress.done_items += 1;
            done.items += 1;
            finished(report, progress);
            continue;
        }
        //: A symlink entry is the other half of zip slip: the path check
        //: passes and the link then points anywhere. Refused rather than
        //: followed.
        if is_symlink_mode(entry.unix_mode()) {
            return Err(Error::Escapes(format!("{} is a symlink entry", entry.name())));
        }
        create_parent(&out)?;
        let mut sink = BufWriter::new(
            File::create(&out).map_err(|e| Error::io(out.display().to_string(), e))?,
        );
        io::copy(&mut entry, &mut sink)
            .map_err(|e| Error::io(out.display().to_string(), e))?;
        sink.flush().map_err(|e| Error::io(out.display().to_string(), e))?;
        if let Some(mode) = entry.unix_mode() {
            set_mode(&out, mode)?;
        }
        progress.done_items += 1;
        progress.done_bytes += entry.size();
        done.items += 1;
        done.bytes += entry.size();
        finished(report, progress);
    }
    Ok(done)
}

/// Extract a 7z entry by entry.
///
/// The crate ships a `decompress_file` that does all of this in one call, and
/// it joins each stored name straight onto the destination. An entry named
/// `../../.bashrc` therefore lands outside the folder the user picked. So the
/// walk is written here instead, over the same reader, with every name going
/// through [`safe_join`] like the zip and tar paths already did.
fn extract_7z(
    path: &Path,
    target: &Path,
    password: Option<&str>,
    report: crate::ops::fs::Reporter,
    progress: &mut crate::ops::fs::Progress,
) -> Result<Done> {
    let mut reader =
        sevenz_rust2::ArchiveReader::new(seven_zip_source(path)?, seven_zip_password(password))
            .map_err(|e| seven_zip_error(path, e))?;
    //: A refusal has to stop the walk and come back out whole. The closure can
    //: only report true or false to the crate, so the reason is carried here.
    let mut refused: Option<Error> = None;
    let encrypted = password.is_some();
    let mut done = Done::default();
    reader
        .for_each_entries(|entry, stream| {
            //: Reported before the entry is written, so the name on screen is
            //: the one being worked on rather than the one just finished.
            let named = target.join(&entry.name);
            if step(report, progress, &named) == crate::ops::fs::Flow::Cancel {
                done.cancelled = true;
                return Ok(false);
            }
            match write_7z_entry(path, target, entry, stream, encrypted) {
                Ok(()) => {
                    progress.done_items += 1;
                    progress.done_bytes += entry.size;
                    done.items += 1;
                    done.bytes += entry.size;
                    finished(report, progress);
                    Ok(true)
                }
                Err(e) => {
                    refused = Some(e);
                    Ok(false)
                }
            }
        })
        .map_err(|e| seven_zip_error(path, e))?;
    match refused {
        Some(e) => Err(e),
        None => Ok(done),
    }
}

fn write_7z_entry(
    archive: &Path,
    target: &Path,
    entry: &sevenz_rust2::ArchiveEntry,
    stream: &mut dyn Read,
    encrypted: bool,
) -> Result<()> {
    let out = safe_join(target, &entry.name)?;
    if entry.is_directory {
        return fs::create_dir_all(&out).map_err(|e| Error::io(out.display().to_string(), e));
    }
    let mode = unix_mode(entry);
    //: The same refusal the zip path makes: a link entry passes the name check
    //: and then points wherever it likes.
    if is_symlink_mode(mode) {
        return Err(Error::Escapes(format!("{} is a symlink entry", entry.name)));
    }
    create_parent(&out)?;
    let mut sink =
        BufWriter::new(File::create(&out).map_err(|e| Error::io(out.display().to_string(), e))?);
    io::copy(stream, &mut sink).map_err(|e| {
        //: A wrong password does not fail at the header. The block decrypts to
        //: rubbish and the mismatch arrives here, partway through a file, as a
        //: checksum that does not match. The crate reports that with no errno,
        //: which is what tells it apart from the destination filling up or
        //: turning read only, both of which always carry one.
        if encrypted && e.raw_os_error().is_none() {
            Error::NeedsPassword(archive.display().to_string())
        } else {
            Error::io(out.display().to_string(), e)
        }
    })?;
    sink.flush().map_err(|e| Error::io(out.display().to_string(), e))?;
    if let Some(mode) = mode {
        set_mode(&out, mode)?;
    }
    Ok(())
}

/// The unix mode a 7z entry carries, if it carries one.
///
/// p7zip puts it in the top half of the Windows attribute word and sets
/// `0x8000` to say so. Without that bit the low bits are Windows attributes
/// and the top half is zero, so reading a mode out of them would produce 0.
fn unix_mode(entry: &sevenz_rust2::ArchiveEntry) -> Option<u32> {
    const UNIX_EXTENSION: u32 = 0x8000;
    if !entry.has_windows_attributes || entry.windows_attributes & UNIX_EXTENSION == 0 {
        return None;
    }
    Some(entry.windows_attributes >> 16)
}

fn seven_zip_password(password: Option<&str>) -> sevenz_rust2::Password {
    password.unwrap_or("").into()
}

/// Tell "this needs a password" apart from every other way 7z can fail, so the
/// caller can ask for one instead of showing a decode error.
fn seven_zip_error(path: &Path, e: sevenz_rust2::Error) -> Error {
    match e {
        sevenz_rust2::Error::PasswordRequired | sevenz_rust2::Error::MaybeBadPassword(_) => {
            Error::NeedsPassword(path.display().to_string())
        }
        other => Error::Tool { tool: "7z".into(), message: other.to_string() },
    }
}

fn zip_error(path: &Path, e: zip::result::ZipError) -> Error {
    match &e {
        zip::result::ZipError::InvalidPassword => Error::NeedsPassword(path.display().to_string()),
        zip::result::ZipError::UnsupportedArchive(
            zip::result::ZipError::PASSWORD_REQUIRED,
        ) => Error::NeedsPassword(path.display().to_string()),
        _ => Error::Tool { tool: "zip".into(), message: e.to_string() },
    }
}

fn extract_tar(
    path: &Path,
    target: &Path,
    format: Format,
    report: crate::ops::fs::Reporter,
    progress: &mut crate::ops::fs::Progress,
) -> Result<Done> {
    let mut archive = tar::Archive::new(tar_reader(path, format)?);
    let mut done = Done::default();
    for entry in archive
        .entries()
        .map_err(|e| Error::io(path.display().to_string(), e))?
    {
        let mut entry = entry.map_err(|e| Error::io(path.display().to_string(), e))?;
        let name = entry
            .path()
            .map_err(|e| Error::io(path.display().to_string(), e))?
            .display()
            .to_string();
        let kind = entry.header().entry_type();
        if kind.is_symlink() || kind.is_hard_link() {
            return Err(Error::Escapes(format!("{name} is a link entry")));
        }
        let out = safe_join(target, &name)?;
        if step(report, progress, &out) == crate::ops::fs::Flow::Cancel {
            done.cancelled = true;
            break;
        }
        if kind.is_dir() {
            fs::create_dir_all(&out)
                .map_err(|e| Error::io(out.display().to_string(), e))?;
            progress.done_items += 1;
            done.items += 1;
            finished(report, progress);
            continue;
        }
        let size = entry.header().size().unwrap_or(0);
        create_parent(&out)?;
        let mut sink = BufWriter::new(
            File::create(&out).map_err(|e| Error::io(out.display().to_string(), e))?,
        );
        io::copy(&mut entry, &mut sink)
            .map_err(|e| Error::io(out.display().to_string(), e))?;
        sink.flush().map_err(|e| Error::io(out.display().to_string(), e))?;
        if let Ok(mode) = entry.header().mode() {
            set_mode(&out, mode)?;
        }
        progress.done_items += 1;
        progress.done_bytes += size;
        done.items += 1;
        done.bytes += size;
        finished(report, progress);
    }
    Ok(done)
}

fn is_symlink_mode(mode: Option<u32>) -> bool {
    mode.map(|m| m & 0o170_000 == 0o120_000).unwrap_or(false)
}

fn set_mode(path: &Path, mode: u32) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    //: Only the permission bits, and never setuid or setgid: an archive is
    //: untrusted and must not be able to drop a setuid binary on the disk.
    let bits = mode & 0o777;
    fs::set_permissions(path, fs::Permissions::from_mode(bits))
        .map_err(|e| Error::io(path.display().to_string(), e))
}

// -------------------------------------------------------------- progress ---

/// What a compress or an extract did.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Done {
    pub items: u64,
    pub bytes: u64,
    /// True when the caller stopped it.
    ///
    /// A cancelled compress removes the archive it was building, because half
    /// an archive is not an archive and nothing else can be done with it. A
    /// cancelled extract leaves what it wrote: those are ordinary files in a
    /// folder the user chose, some of which may have been there already, and
    /// deleting them would be a worse answer than an unfinished job.
    pub cancelled: bool,
    /// The numbered parts, when the archive was written as a set. Empty when
    /// it is one file, which is the ordinary case.
    pub parts: Vec<PathBuf>,
}

/// Everything to be written, and how much of it there is.
struct Plan {
    paths: Vec<PathBuf>,
    bytes: u64,
}

fn plan(base: &Path, sources: &[PathBuf]) -> Result<Plan> {
    let mut paths = Vec::new();
    for src in sources {
        walk(base, src, &mut paths)?;
    }
    let bytes = paths
        .iter()
        .filter_map(|p| fs::symlink_metadata(p).ok())
        .filter(|m| m.is_file())
        .map(|m| m.len())
        .sum();
    Ok(Plan { paths, bytes })
}

// -------------------------------------------------------------- creation ---

/// Compress a set of paths into one archive. Every source must sit under
/// `base`, which is what makes the stored names relative and predictable.
pub fn compress(
    base: &Path,
    sources: &[PathBuf],
    out: &Path,
    format: Format,
    options: &Options,
    report: crate::ops::fs::Reporter,
) -> Result<Done> {
    if sources.is_empty() {
        return Err(Error::BadRequest("nothing to compress".into()));
    }
    options.check(format)?;
    if out.symlink_metadata().is_ok() {
        return Err(Error::Exists(out.display().to_string()));
    }
    let plan = plan(base, sources)?;
    let done = match format {
        Format::Zip => compress_zip(base, out, &plan, options, report),
        Format::SevenZip => compress_7z(base, out, &plan, options, report),
        _ => compress_tar(base, out, &plan, format, options, report),
    };
    match done {
        //: The archive goes with the job that was making it. Leaving a
        //: truncated one behind would put a file in the folder that looks like
        //: an archive and opens as nothing.
        Ok(done) if done.cancelled => {
            let _ = fs::remove_file(out);
            Ok(done)
        }
        //: Cut up only once it is whole, because the split is a byte split and
        //: there is nothing to cut until the last header is written. A failure
        //: here takes the archive with it rather than leaving both a whole one
        //: and the parts of it in the same folder.
        Ok(mut done) => match options.split.bytes() {
            None => Ok(done),
            Some(size) => match volume::split_file(out, size) {
                Ok(parts) => {
                    done.parts = parts;
                    Ok(done)
                }
                Err(e) => {
                    let _ = fs::remove_file(out);
                    Err(e)
                }
            },
        },
        Err(e) => {
            let _ = fs::remove_file(out);
            Err(e)
        }
    }
}

/// Tell the caller where the job has got to, and ask whether to carry on.
fn step(
    report: crate::ops::fs::Reporter,
    progress: &mut crate::ops::fs::Progress,
    path: &Path,
) -> crate::ops::fs::Flow {
    progress.current = path.to_path_buf();
    report(progress)
}

/// Say what has now been done.
///
/// [`step`] reports the entry that is about to be worked on, which leaves the
/// counts one entry behind, and for a job of one entry leaves them at zero for
/// the whole of it: a bar that sits still and then jumps. This is the other
/// half of it, the entry that is finished. The answer is not read, because the
/// place to stop is the `step` at the top of the next entry and stopping here
/// would leave a half written one behind.
fn finished(report: crate::ops::fs::Reporter, progress: &crate::ops::fs::Progress) {
    let _ = report(progress);
}

fn compress_7z(
    base: &Path,
    out: &Path,
    plan: &Plan,
    options: &Options,
    report: crate::ops::fs::Reporter,
) -> Result<Done> {
    //: push_source_path would name entries relative to the folder being added,
    //: which loses the folder itself and disagrees with every other format
    //: here. The plan's paths are named relative to base, exactly as the zip
    //: and tar writers name theirs.
    let mut w = sevenz_rust2::ArchiveWriter::create(out)
        .map_err(|e| Error::Tool { tool: "7z".into(), message: e.to_string() })?;
    w.set_content_methods(seven_zip_methods(options));
    let mut progress = starting(plan);
    let mut done = Done::default();
    for path in &plan.paths {
        let rel = path.strip_prefix(base).unwrap_or(path).display().to_string();
        if rel.is_empty() {
            continue;
        }
        if step(report, &mut progress, path) == crate::ops::fs::Flow::Cancel {
            done.cancelled = true;
            break;
        }
        let entry = sevenz_rust2::ArchiveEntry::from_path(path, rel);
        let reader = if path.is_dir() {
            None
        } else {
            Some(File::open(path).map_err(|e| Error::io(path.display().to_string(), e))?)
        };
        w.push_archive_entry(entry, reader)
            .map_err(|e| Error::Tool { tool: "7z".into(), message: e.to_string() })?;
        counted(report, &mut progress, &mut done, path);
    }
    w.finish().map_err(|e| Error::Tool { tool: "7z".into(), message: e.to_string() })?;
    Ok(done)
}

fn starting(plan: &Plan) -> crate::ops::fs::Progress {
    crate::ops::fs::Progress {
        total_items: plan.paths.len() as u64,
        total_bytes: plan.bytes,
        ..Default::default()
    }
}

fn counted(
    report: crate::ops::fs::Reporter,
    progress: &mut crate::ops::fs::Progress,
    done: &mut Done,
    path: &Path,
) {
    let size = fs::symlink_metadata(path).ok().filter(|m| m.is_file()).map(|m| m.len());
    progress.done_items += 1;
    done.items += 1;
    if let Some(size) = size {
        progress.done_bytes += size;
        done.bytes += size;
    }
    finished(report, progress);
}

/// The codec chain a 7z writes with, innermost first.
///
/// AES is appended rather than substituted: the content is compressed and then
/// encrypted, which is the order every other 7z writer uses and the only order
/// that compresses anything, since encrypted bytes do not compress.
fn seven_zip_methods(options: &Options) -> Vec<sevenz_rust2::EncoderConfiguration> {
    use sevenz_rust2::{EncoderConfiguration, EncoderMethod};
    let mut chain = Vec::new();
    if options.level == Level::Store {
        chain.push(EncoderConfiguration::new(EncoderMethod::COPY));
    } else {
        chain.push(
            EncoderConfiguration::new(EncoderMethod::LZMA2)
                .with_options(options.lzma2().into()),
        );
    }
    if let Some(password) = &options.password {
        chain.push(
            sevenz_rust2::encoder_options::AesEncoderOptions::new(password.as_str().into()).into(),
        );
    }
    chain
}

/// What a 7z write is going to need, for the dialog's line and for the
/// refusal above.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct Lzma2Estimate {
    /// The dictionary the encoder will use, after the level or the choice.
    pub dictionary: u32,
    /// The nice length it will use.
    pub word_size: u32,
    /// How many encoders run: one per thread.
    pub threads: u32,
    /// Each thread's chunk of input, or 0 for one stream.
    pub chunk: u64,
    /// The whole of it, in bytes.
    pub bytes: u64,
}

impl Options {
    /// The LZMA2 options a 7z is written with: the level's preset, then the
    /// dictionary and the word size on top of it where they were chosen,
    /// then the threads. Every choice reaches the codec through here, so a
    /// test that reads the archive back sees the choice rather than the
    /// preset.
    pub fn lzma2(&self) -> sevenz_rust2::encoder_options::Lzma2Options {
        use sevenz_rust2::encoder_options::Lzma2Options;
        let level = self.level.lzma();
        let threads = self.threads.max(1);
        let mut lzma2 = if threads > 1 {
            Lzma2Options::from_level_mt(level, threads, 1 << 20)
        } else {
            Lzma2Options::from_level(level)
        };
        if let Some(d) = self.dictionary {
            lzma2.set_dictionary_size(d);
        }
        if let Some(w) = self.word_size {
            lzma2.set_nice_len(w);
        }
        if threads > 1 {
            //: 7-Zip cuts LZMA2 into blocks of four dictionaries, within
            //: 1 MB and 256 MB. Set after the dictionary, because the crate
            //: sizes the chunk against the preset's dictionary at
            //: construction and would leave an eight megabyte chunk on a
            //: sixty four kilobyte dictionary.
            let dictionary = u64::from(lzma2.dictionary_size());
            lzma2.set_chunk_size((dictionary * 4).clamp(1 << 20, 256 << 20));
        }
        lzma2
    }

    /// What [`Options::lzma2`] will need in memory: one encoder per thread,
    /// each with its dictionary and match finder, plus each thread's chunk
    /// of input held while it is compressed.
    ///
    /// The sum is the encoder's own allocations, not the crate's estimate,
    /// which adds a byte count to a kibibyte count and lands a thousand
    /// times high. The window is the dictionary, half of it again in
    /// reserve and the chunk it works in; presets 4 and up run the binary
    /// tree match finder, two ints a position, and the fast presets the hash
    /// chain, one; the hash tables are ints, one a position; and 6 MB covers
    /// the range coder, the optimum table and the rest, which is the figure
    /// 7-Zip's own rule of thumb carries.
    pub fn lzma2_estimate(&self) -> Lzma2Estimate {
        let lzma2 = self.lzma2();
        let threads = lzma2.threads().max(1);
        let chunk = if threads > 1 { lzma2.chunk_size().unwrap_or(0) } else { 0 };
        let dictionary = u64::from(lzma2.dictionary_size());
        let window = dictionary + (dictionary / 2).min(512 << 20) + (320 << 10);
        let finder = if self.level.lzma() >= 4 { 8 } else { 4 };
        let per_encoder = window + dictionary * (finder + 4) + (6 << 20);
        Lzma2Estimate {
            dictionary: lzma2.dictionary_size(),
            word_size: lzma2.nice_len(),
            threads,
            chunk,
            bytes: (per_encoder + chunk) * u64::from(threads),
        }
    }
}

/// Bytes as the dialog and the refusal say them: KB, MB and GB in powers of
/// two, the way 7-Zip and the reference's list of dictionaries count them.
pub fn human_size(bytes: u64) -> String {
    const KB: f64 = 1024.0;
    let b = bytes as f64;
    if b >= KB * KB * KB {
        format!("{:.1} GB", b / (KB * KB * KB))
    } else if b >= KB * KB {
        format!("{:.0} MB", b / (KB * KB))
    } else if b >= KB {
        format!("{:.0} KB", b / KB)
    } else {
        format!("{bytes} bytes")
    }
}

/// What the kernel says can still be had, from /proc/meminfo's MemAvailable,
/// which counts the page cache that would be given up. None where there is
/// no such file, which is nowhere this runs.
pub fn available_memory() -> Option<u64> {
    let text = fs::read_to_string("/proc/meminfo").ok()?;
    let line = text.lines().find(|l| l.starts_with("MemAvailable:"))?;
    let kib: u64 = line.split_whitespace().nth(1)?.parse().ok()?;
    Some(kib * 1024)
}

fn walk(base: &Path, path: &Path, out: &mut Vec<PathBuf>) -> Result<()> {
    let meta = fs::symlink_metadata(path)
        .map_err(|e| Error::io(path.display().to_string(), e))?;
    if meta.is_dir() && !meta.is_symlink() {
        out.push(path.to_path_buf());
        for entry in fs::read_dir(path)
            .map_err(|e| Error::io(path.display().to_string(), e))?
            .flatten()
        {
            walk(base, &entry.path(), out)?;
        }
    } else if !meta.is_symlink() {
        out.push(path.to_path_buf());
    }
    Ok(())
}

fn compress_zip(
    base: &Path,
    out: &Path,
    plan: &Plan,
    wanted: &Options,
    report: crate::ops::fs::Reporter,
) -> Result<Done> {
    let file = File::create(out).map_err(|e| Error::io(out.display().to_string(), e))?;
    let mut zip = zip::ZipWriter::new(BufWriter::new(file));
    let mut options: zip::write::FileOptions<'_, ()> = if wanted.level == Level::Store {
        zip::write::FileOptions::default().compression_method(zip::CompressionMethod::Stored)
    } else {
        zip::write::FileOptions::default()
            .compression_method(zip::CompressionMethod::Deflated)
            .compression_level(Some(wanted.level.deflate() as i64))
    };
    if let Some(password) = &wanted.password {
        //: AES-256, not the original zip cipher. That one is broken in a way
        //: a laptop can undo in seconds, and offering it under the same word
        //: would tell the user their files are protected when they are not.
        options = options.with_aes_encryption(zip::AesMode::Aes256, password);
    }
    let mut progress = starting(plan);
    let mut done = Done::default();
    for path in &plan.paths {
        let rel = path.strip_prefix(base).unwrap_or(path).display().to_string();
        if rel.is_empty() {
            continue;
        }
        if step(report, &mut progress, path) == crate::ops::fs::Flow::Cancel {
            done.cancelled = true;
            break;
        }
        if path.is_dir() {
            zip.add_directory(format!("{rel}/"), options)
                .map_err(|e| Error::Tool { tool: "zip".into(), message: e.to_string() })?;
            counted(report, &mut progress, &mut done, path);
            continue;
        }
        zip.start_file(rel, options)
            .map_err(|e| Error::Tool { tool: "zip".into(), message: e.to_string() })?;
        let mut src = File::open(path).map_err(|e| Error::io(path.display().to_string(), e))?;
        io::copy(&mut src, &mut zip).map_err(|e| Error::io(path.display().to_string(), e))?;
        counted(report, &mut progress, &mut done, path);
    }
    zip.finish()
        .map_err(|e| Error::Tool { tool: "zip".into(), message: e.to_string() })?;
    Ok(done)
}

fn compress_tar(
    base: &Path,
    out: &Path,
    plan: &Plan,
    format: Format,
    options: &Options,
    report: crate::ops::fs::Reporter,
) -> Result<Done> {
    let file = File::create(out).map_err(|e| Error::io(out.display().to_string(), e))?;
    //: Store means the lowest setting each codec has, not no codec at all: a
    //: .tar.gz with the gzip left out would not be a .tar.gz. Only zip and 7z
    //: can genuinely store a file uncompressed, and only those two are offered
    //: it as a real choice.
    let sink: Box<dyn Write> = match format {
        Format::Tar => Box::new(BufWriter::new(file)),
        Format::TarGz => Box::new(flate2::write::GzEncoder::new(
            BufWriter::new(file),
            flate2::Compression::new(options.level.deflate()),
        )),
        Format::TarZst => Box::new(
            zstd::stream::write::AutoFinishEncoder::from(
                zstd::stream::write::Encoder::new(BufWriter::new(file), options.level.zstd())
                    .map_err(|e| Error::io(out.display().to_string(), e))?
                    .auto_finish(),
            ),
        ),
        Format::TarXz => {
            Box::new(xz2::write::XzEncoder::new(BufWriter::new(file), options.level.lzma()))
        }
        _ => return Err(Error::BadRequest("not a tar".into())),
    };
    let mut builder = tar::Builder::new(sink);
    //: The same walk the other two writers use, rather than append_dir_all.
    //: One list of entries means one place that decides what goes into an
    //: archive, and it means a tar written here holds exactly what a zip
    //: written here would hold.
    let mut progress = starting(plan);
    let mut done = Done::default();
    for path in &plan.paths {
        let rel = path.strip_prefix(base).unwrap_or(path);
        if rel.as_os_str().is_empty() {
            continue;
        }
        if step(report, &mut progress, path) == crate::ops::fs::Flow::Cancel {
            done.cancelled = true;
            break;
        }
        if path.is_dir() {
            builder
                .append_dir(rel, path)
                .map_err(|e| Error::io(path.display().to_string(), e))?;
        } else {
            builder
                .append_path_with_name(path, rel)
                .map_err(|e| Error::io(path.display().to_string(), e))?;
        }
        counted(report, &mut progress, &mut done, path);
    }
    builder
        .into_inner()
        .map_err(|e| Error::io(out.display().to_string(), e))?
        .flush()
        .map_err(|e| Error::io(out.display().to_string(), e))?;
    Ok(done)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ops::fs::Flow;

    fn scratch(tag: &str) -> PathBuf {
        let base = std::env::temp_dir().join(format!("auradefs-archive-{tag}"));
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(base.join("src/inner")).unwrap();
        fs::write(base.join("src/top.txt"), b"top").unwrap();
        fs::write(base.join("src/inner/deep.txt"), b"deep").unwrap();
        fs::create_dir_all(base.join("out")).unwrap();
        base
    }

    /// Write a 7z whose single entry is stored under the name given, whatever
    /// that name is. This is the crafted archive an attacker sends.
    fn seven_zip_named(base: &Path, entry_name: &str, attributes: Option<u32>) -> PathBuf {
        let payload = base.join("payload.txt");
        fs::write(&payload, b"owned").unwrap();
        let out = base.join("crafted.7z");
        let mut writer = sevenz_rust2::ArchiveWriter::create(&out).unwrap();
        let mut entry = sevenz_rust2::ArchiveEntry::from_path(&payload, entry_name.to_string());
        if let Some(attributes) = attributes {
            entry.has_windows_attributes = true;
            entry.windows_attributes = attributes;
        }
        writer.push_archive_entry(entry, Some(File::open(&payload).unwrap())).unwrap();
        writer.finish().unwrap();
        out
    }

    #[test]
    fn a_7z_entry_that_climbs_out_of_the_destination_is_refused() {
        let base = scratch("7z-slip");
        let archive = seven_zip_named(&base, "../escaped.txt", None);
        let into = base.join("out/here");

        let err = extract(&archive, &into, Destination::Here, None, &mut crate::ops::fs::silent).unwrap_err();
        assert_eq!(err.code(), "escapes-root", "got {err:?}");
        //: The crate's own decompress_file joins the stored name straight onto
        //: the destination, so this is the file that used to appear.
        assert!(
            !base.join("out/escaped.txt").exists(),
            "the entry was written outside the folder it was extracted into"
        );
    }

    #[test]
    fn a_7z_entry_naming_an_absolute_path_is_refused() {
        let base = scratch("7z-abs");
        let archive = seven_zip_named(&base, "/etc/cron.d/owned", None);
        let err = extract(&archive, &base.join("out/here"), Destination::Here, None, &mut crate::ops::fs::silent).unwrap_err();
        assert_eq!(err.code(), "escapes-root", "got {err:?}");
    }

    #[test]
    fn a_7z_symlink_entry_is_refused_and_its_mode_is_read_the_way_p7zip_writes_it() {
        //: p7zip sets 0x8000 to say the top half is a unix mode. S_IFLNK is
        //: 0o120000, so this is a link with 0777 on it.
        const UNIX: u32 = 0x8000;
        let link = UNIX | (0o120_777 << 16);
        let base = scratch("7z-link");
        let archive = seven_zip_named(&base, "link", Some(link));
        let err = extract(&archive, &base.join("out/here"), Destination::Here, None, &mut crate::ops::fs::silent).unwrap_err();
        assert_eq!(err.code(), "escapes-root", "got {err:?}");

        //: And without that bit there is no mode to read, so an ordinary
        //: Windows-written entry is not mistaken for anything.
        let mut plain = sevenz_rust2::ArchiveEntry::new();
        plain.has_windows_attributes = true;
        plain.windows_attributes = 0x20; // FILE_ATTRIBUTE_ARCHIVE
        assert_eq!(unix_mode(&plain), None);
        let mut marked = sevenz_rust2::ArchiveEntry::new();
        marked.has_windows_attributes = true;
        marked.windows_attributes = UNIX | (0o100_644 << 16);
        assert_eq!(unix_mode(&marked), Some(0o100_644));
    }

    #[test]
    fn a_7z_round_trips_with_a_password_and_the_wrong_one_is_told_apart() {
        let base = scratch("7z-password");
        let archive = base.join("secret.7z");
        let options = Options { level: Level::Normal, password: Some("open sesame".into()), ..Options::default() };
        compress(&base.join("src"), &[base.join("src/top.txt")], &archive, Format::SevenZip, &options, &mut crate::ops::fs::silent)
            .unwrap();

        //: The names are still readable: only the content is encrypted, which
        //: is what 7z does unless the header is encrypted too.
        let listed = list(&archive, None).unwrap();
        assert_eq!(listed.len(), 1);

        let err = extract(&archive, &base.join("out/no"), Destination::Here, None, &mut crate::ops::fs::silent).unwrap_err();
        assert_eq!(err.code(), "needs-password", "got {err:?}");
        let err =
            extract(&archive, &base.join("out/bad"), Destination::Here, Some("wrong"), &mut crate::ops::fs::silent).unwrap_err();
        assert_eq!(err.code(), "needs-password", "got {err:?}");

        let target =
            extract(&archive, &base.join("out/yes"), Destination::Here, Some("open sesame"),
                &mut crate::ops::fs::silent)
                .unwrap().0;
        assert_eq!(fs::read(target.join("top.txt")).unwrap(), b"top");
    }

    #[test]
    fn a_zip_round_trips_with_a_password_and_the_wrong_one_is_told_apart() {
        const MARKER: &[u8] = b"the-quiet-part-out-loud";
        let base = scratch("zip-password");
        let secret = base.join("src/secret.txt");
        fs::write(&secret, MARKER).unwrap();
        let archive = base.join("secret.zip");
        let options = Options { level: Level::Normal, password: Some("open sesame".into()), ..Options::default() };
        compress(&base.join("src"), &[secret.clone()], &archive, Format::Zip, &options, &mut crate::ops::fs::silent).unwrap();

        let err = extract(&archive, &base.join("out/no"), Destination::Here, None, &mut crate::ops::fs::silent).unwrap_err();
        assert_eq!(err.code(), "needs-password", "got {err:?}");
        let err =
            extract(&archive, &base.join("out/bad"), Destination::Here, Some("wrong"), &mut crate::ops::fs::silent).unwrap_err();
        assert_eq!(err.code(), "needs-password", "got {err:?}");

        let target =
            extract(&archive, &base.join("out/yes"), Destination::Here, Some("open sesame"),
                &mut crate::ops::fs::silent)
                .unwrap().0;
        assert_eq!(fs::read(target.join("secret.txt")).unwrap(), MARKER);

        //: The bytes on disk are not the bytes that went in. Without this the
        //: test would pass over a writer that took the password and ignored
        //: it. Only the content is checked: zip leaves entry names in clear
        //: whatever the password, which is a property of the format.
        let raw = fs::read(&archive).unwrap();
        assert!(
            !raw.windows(MARKER.len()).any(|w| w == MARKER),
            "the content is sitting in the archive in clear"
        );
    }

    #[test]
    fn a_format_with_nowhere_to_put_a_password_says_so_rather_than_dropping_it() {
        let base = scratch("tar-password");
        for (name, format) in [
            ("x.tar", Format::Tar),
            ("x.tar.gz", Format::TarGz),
            ("x.tar.xz", Format::TarXz),
            ("x.tar.zst", Format::TarZst),
        ] {
            let options = Options { level: Level::Normal, password: Some("secret".into()), ..Options::default() };
            let out = base.join(name);
            let err =
                compress(&base.join("src"), &[base.join("src/top.txt")], &out, format, &options, &mut crate::ops::fs::silent)
                    .unwrap_err();
            assert_eq!(err.code(), "unsupported", "{name} took a password: {err:?}");
            assert!(!out.exists(), "{name} was written anyway");
        }

        //: And an empty box is a mistake, not a request for no password.
        let options = Options { level: Level::Normal, password: Some(String::new()), ..Options::default() };
        let err = compress(
            &base.join("src"),
            &[base.join("src/top.txt")],
            &base.join("empty.zip"),
            Format::Zip,
            &options,
            &mut crate::ops::fs::silent,
        )
        .unwrap_err();
        assert_eq!(err.code(), "bad-request", "got {err:?}");
    }

    /// The dictionary an archive's LZMA2 coder was written with, read back
    /// from the one property byte the header carries for it, decoded the
    /// way the codec decodes it.
    fn dictionary_in(path: &Path) -> u32 {
        let archive = sevenz_rust2::Archive::open(path).unwrap();
        let coder = archive.blocks[0]
            .coders
            .iter()
            .find(|c| c.encoder_method_id() == [0x21])
            .expect("an LZMA2 coder");
        let p = u32::from(coder.properties()[0]);
        if p == 40 { u32::MAX } else { (2 | (p & 1)) << (p / 2 + 11) }
    }

    #[test]
    fn a_dictionary_reaches_the_codec_and_the_header_says_so() {
        let base = scratch("dictionary");
        let big = base.join("src/big.txt");
        fs::write(&big, compressible(64 * 1024)).unwrap();
        for (name, dictionary) in [("small", 64 << 10), ("large", 4 << 20)] {
            let out = base.join(format!("{name}.7z"));
            let options = Options { dictionary: Some(dictionary), ..Options::new(Level::Normal) };
            compress(&base.join("src"), &[big.clone()], &out, Format::SevenZip, &options, &mut crate::ops::fs::silent)
                .unwrap();
            assert_eq!(dictionary_in(&out), dictionary, "{name}");
        }
        //: And none chosen is the level's own, the crate's preset table.
        let out = base.join("preset.7z");
        compress(&base.join("src"), &[big.clone()], &out, Format::SevenZip, &Options::new(Level::Normal), &mut crate::ops::fs::silent)
            .unwrap();
        assert_eq!(dictionary_in(&out), 8 << 20);
        assert_eq!(Options::new(Level::Normal).lzma2_estimate().dictionary, 8 << 20);
    }

    #[test]
    fn a_word_size_reaches_the_codec() {
        let base = scratch("word-size");
        let big = base.join("src/big.txt");
        fs::write(&big, compressible(200 * 1024)).unwrap();
        let raw = fs::metadata(&big).unwrap().len();
        let at = |word: u32| {
            let out = base.join(format!("fb{word}.7z"));
            let options = Options { word_size: Some(word), ..Options::new(Level::Normal) };
            compress(&base.join("src"), &[big.clone()], &out, Format::SevenZip, &options, &mut crate::ops::fs::silent)
                .unwrap();
            assert_eq!(options.lzma2_estimate().word_size, word);
            (out.clone(), fs::metadata(&out).unwrap().len())
        };
        let (short_path, short) = at(8);
        let (_, long) = at(273);
        //: A match finder that gives up after 8 bytes writes a different
        //: stream from one that looks for 273; equal sizes would mean the
        //: number was carried and dropped.
        assert_ne!(short, long, "word size 8 and 273 wrote the same bytes");
        let (target, _) = extract(&short_path, &base.join("out"), Destination::Here, None, &mut crate::ops::fs::silent)
            .unwrap();
        assert_eq!(fs::read(target.join("big.txt")).unwrap().len(), raw as usize);
    }

    #[test]
    fn threads_cut_the_input_into_chunks_that_still_extract() {
        let base = scratch("threads");
        let big = base.join("src/big.txt");
        let payload = compressible(3 << 20);
        fs::write(&big, &payload).unwrap();
        let at = |threads: u32| {
            let out = base.join(format!("mt{threads}.7z"));
            //: Normal, whose preset dictionary is eight megabytes: the chunk
            //: has to follow the dictionary chosen, not the preset's.
            let options = Options { threads, dictionary: Some(64 << 10), ..Options::new(Level::Normal) };
            compress(&base.join("src"), &[big.clone()], &out, Format::SevenZip, &options, &mut crate::ops::fs::silent)
                .unwrap();
            (out, options.lzma2_estimate())
        };
        let (one_path, one) = at(1);
        let (four_path, four) = at(4);
        assert_eq!(one.threads, 1);
        assert_eq!(one.chunk, 0);
        assert_eq!(four.threads, 4);
        //: 7-Zip's block: four dictionaries, and at least a megabyte.
        assert_eq!(four.chunk, 1 << 20);
        assert!(four.bytes > one.bytes, "four threads should need more than one: {four:?} {one:?}");
        //: Chunks compressed on their own are a different stream from one
        //: stream, so the thread count is visible in what was written.
        assert_ne!(fs::read(&one_path).unwrap(), fs::read(&four_path).unwrap());
        let (target, _) = extract(&four_path, &base.join("out"), Destination::Here, None, &mut crate::ops::fs::silent)
            .unwrap();
        assert_eq!(fs::read(target.join("big.txt")).unwrap(), payload);
    }

    #[test]
    fn a_dictionary_or_word_size_on_a_zip_is_refused() {
        let base = scratch("zip-dictionary");
        fs::write(base.join("src/a.txt"), b"hello").unwrap();
        for options in [
            Options { dictionary: Some(1 << 20), ..Options::new(Level::Normal) },
            Options { word_size: Some(64), ..Options::new(Level::Normal) },
        ] {
            let out = base.join("no.zip");
            let err = compress(&base.join("src"), &[base.join("src/a.txt")], &out, Format::Zip, &options, &mut crate::ops::fs::silent)
                .unwrap_err();
            assert_eq!(err.code(), "unsupported", "got {err:?}");
            assert!(!out.exists(), "a refused zip was left on disk");
        }
    }

    #[test]
    fn a_dictionary_or_word_size_off_the_list_is_refused() {
        let base = scratch("bad-dictionary");
        fs::write(base.join("src/a.txt"), b"hello").unwrap();
        for options in [
            Options { dictionary: Some(4096), ..Options::new(Level::Normal) },
            Options { word_size: Some(4), ..Options::new(Level::Normal) },
            Options { word_size: Some(300), ..Options::new(Level::Normal) },
        ] {
            let out = base.join("no.7z");
            let err = compress(&base.join("src"), &[base.join("src/a.txt")], &out, Format::SevenZip, &options, &mut crate::ops::fs::silent)
                .unwrap_err();
            assert_eq!(err.code(), "bad-request", "got {err:?}");
            assert!(!out.exists());
        }
    }

    #[test]
    fn a_dictionary_the_machine_cannot_hold_is_refused_before_a_byte_is_written() {
        let base = scratch("too-much-memory");
        fs::write(base.join("src/a.txt"), b"hello").unwrap();
        //: The biggest dictionary on every one of a great many threads:
        //: a few hundred gigabytes, which no machine this runs on has free.
        let options = Options { dictionary: Some(1024 << 20), threads: 64, ..Options::new(Level::Normal) };
        assert!(options.lzma2_estimate().bytes > 500 << 30);
        let out = base.join("no.7z");
        let err = compress(&base.join("src"), &[base.join("src/a.txt")], &out, Format::SevenZip, &options, &mut crate::ops::fs::silent)
            .unwrap_err();
        assert_eq!(err.code(), "bad-request", "got {err:?}");
        assert!(err.to_string().contains("1.0 GB dictionary"), "{err}");
        assert!(err.to_string().contains("64 threads"), "{err}");
        assert!(!out.exists());
    }

    #[test]
    fn the_estimate_and_the_lists_agree_with_the_dialog() {
        assert_eq!(DICTIONARIES[0], 64 * 1024);
        assert_eq!(DICTIONARIES[12], 1024 * 1024 * 1024);
        assert_eq!(WORD_SIZES, [8, 16, 32, 64, 128, 256, 273]);
        assert_eq!(human_size(64 << 10), "64 KB");
        assert_eq!(human_size(1024 << 20), "1.0 GB");
        assert_eq!(human_size(16 << 20), "16 MB");
        assert!(available_memory().unwrap() > 0);
    }

    /// A zip written the old way: one stored entry whose name is whatever
    /// bytes the writer had, with the UTF-8 flag off. The zip crate's writer
    /// sets the flag for any name that is not ASCII, which is right for new
    /// archives and useless for making one of these, so it is written by
    /// hand: local header, central directory, end record.
    fn legacy_zip(name: &[u8], content: &[u8], utf8_flag: bool) -> Vec<u8> {
        let crc = crc32fast::hash(content);
        let flags: u16 = if utf8_flag { 1 << 11 } else { 0 };
        let mut out = Vec::new();
        let le16 = |v: u16| v.to_le_bytes();
        let le32 = |v: u32| v.to_le_bytes();
        // local file header
        out.extend_from_slice(&le32(0x0403_4b50));
        out.extend_from_slice(&le16(20));
        out.extend_from_slice(&le16(flags));
        out.extend_from_slice(&le16(0)); // stored
        out.extend_from_slice(&le16(0));
        out.extend_from_slice(&le16(0x21));
        out.extend_from_slice(&le32(crc));
        out.extend_from_slice(&le32(content.len() as u32));
        out.extend_from_slice(&le32(content.len() as u32));
        out.extend_from_slice(&le16(name.len() as u16));
        out.extend_from_slice(&le16(0));
        out.extend_from_slice(name);
        out.extend_from_slice(content);
        let central = out.len() as u32;
        // central directory
        out.extend_from_slice(&le32(0x0201_4b50));
        out.extend_from_slice(&le16(20));
        out.extend_from_slice(&le16(20));
        out.extend_from_slice(&le16(flags));
        out.extend_from_slice(&le16(0));
        out.extend_from_slice(&le16(0));
        out.extend_from_slice(&le16(0x21));
        out.extend_from_slice(&le32(crc));
        out.extend_from_slice(&le32(content.len() as u32));
        out.extend_from_slice(&le32(content.len() as u32));
        out.extend_from_slice(&le16(name.len() as u16));
        out.extend_from_slice(&le16(0));
        out.extend_from_slice(&le16(0));
        out.extend_from_slice(&le16(0));
        out.extend_from_slice(&le16(0));
        out.extend_from_slice(&le32(0));
        out.extend_from_slice(&le32(0));
        out.extend_from_slice(name);
        let central_len = out.len() as u32 - central;
        // end of central directory
        out.extend_from_slice(&le32(0x0605_4b50));
        out.extend_from_slice(&le16(0));
        out.extend_from_slice(&le16(0));
        out.extend_from_slice(&le16(1));
        out.extend_from_slice(&le16(1));
        out.extend_from_slice(&le32(central_len));
        out.extend_from_slice(&le32(central));
        out.extend_from_slice(&le16(0));
        out
    }

    #[test]
    fn a_zip_named_in_a_code_page_is_read_the_way_the_dialog_says() {
        let base = scratch("code-page");
        let japanese = "日本語のファイル名を持つ文書です.txt";
        let (sjis, _, _) = encoding_rs::SHIFT_JIS.encode(japanese);
        let archive = base.join("legacy.zip");
        fs::write(&archive, legacy_zip(&sjis, b"content", false)).unwrap();

        //: The names are in question, and the guess is the right one.
        let names = zip_names(&archive).unwrap();
        assert!(names.undetermined);
        assert_eq!(names.detected, Some(encoding_rs::SHIFT_JIS));
        assert_eq!(encoding_label(encoding_rs::SHIFT_JIS), ("shift_jis", "Japanese (Shift-JIS)"));

        //: Left to the default, the bytes are not UTF-8, so the name comes
        //: out as the specification's CP437 reading, which is wrong but is
        //: what every zip tool does without being told.
        let listed = list(&archive, None).unwrap();
        assert_ne!(listed[0].name, japanese);
        //: Told, it is the real name, in the listing and on the disk.
        let told = Names::from_label("shift_jis").unwrap();
        assert_eq!(list_with(&archive, None, told).unwrap()[0].name, japanese);
        let (target, done) =
            extract_with(&archive, &base.join("out"), Destination::Here, None, told, &mut crate::ops::fs::silent)
                .unwrap();
        assert_eq!(done.items, 1);
        assert_eq!(fs::read(target.join(japanese)).unwrap(), b"content");
    }

    #[test]
    fn a_utf8_name_without_the_flag_is_read_as_utf8_by_default() {
        let base = scratch("unflagged-utf8");
        let name = "résumé façade.txt";
        let archive = base.join("unflagged.zip");
        fs::write(&archive, legacy_zip(name.as_bytes(), b"cv", false)).unwrap();
        //: In question, as the reference has it: the flag is off and the
        //: bytes are not ASCII. But the guess is UTF-8 and the default
        //: reading already is UTF-8, so the name is right before anyone
        //: chooses anything.
        let names = zip_names(&archive).unwrap();
        assert!(names.undetermined);
        assert_eq!(names.detected, Some(encoding_rs::UTF_8));
        assert_eq!(list(&archive, None).unwrap()[0].name, name);
        let (target, _) = extract(&archive, &base.join("out"), Destination::Here, None, &mut crate::ops::fs::silent).unwrap();
        assert_eq!(fs::read(target.join(name)).unwrap(), b"cv");
    }

    #[test]
    fn a_zip_that_flags_its_names_has_nothing_to_ask() {
        let base = scratch("flagged");
        let name = "naïve.txt";
        let archive = base.join("flagged.zip");
        fs::write(&archive, legacy_zip(name.as_bytes(), b"x", true)).unwrap();
        assert_eq!(zip_names(&archive).unwrap(), ZipNames::default());
        //: And a chosen code page does not touch a flagged name.
        let told = Names::from_label("windows-1252").unwrap();
        assert_eq!(list_with(&archive, None, told).unwrap()[0].name, name);
        //: Nor an ASCII one, nor anything in a 7z or a tar.
        let plain = base.join("plain.zip");
        fs::write(&plain, legacy_zip(b"plain.txt", b"x", false)).unwrap();
        assert_eq!(zip_names(&plain).unwrap(), ZipNames::default());
        fs::write(base.join("src/a.txt"), b"x").unwrap();
        let seven = base.join("a.7z");
        compress(&base.join("src"), &[base.join("src/a.txt")], &seven, Format::SevenZip, &Options::new(Level::Store), &mut crate::ops::fs::silent).unwrap();
        assert_eq!(zip_names(&seven).unwrap(), ZipNames::default());
    }

    #[test]
    fn the_encoding_list_is_the_dialogs_and_a_label_off_it_is_refused() {
        for (label, _) in ENCODINGS {
            let names = Names::from_label(label).unwrap();
            assert!(matches!(names, Names::Encoding(_)), "{label}");
            assert_eq!(names, Names::from_label(&label.to_uppercase()).unwrap());
        }
        assert_eq!(Names::from_label("").unwrap(), Names::Default);
        assert_eq!(Names::from_label("Default").unwrap(), Names::Default);
        let err = Names::from_label("klingon").unwrap_err();
        assert_eq!(err.code(), "bad-request");
        //: The Korean row is the reference's ks_c_5601-1987, which is a label
        //: for EUC-KR, and the two must agree.
        assert_eq!(Names::from_label("ks_c_5601-1987").unwrap(), Names::from_label("euc-kr").unwrap());
    }

    /// A payload where the effort a codec spends actually shows: long enough
    /// to matter, repetitive enough to compress, and varied enough that
    /// searching harder finds more. A wall of one character compresses to
    /// almost nothing at every setting and would hide the difference
    /// completely, which is how a level that never reached the codec passed
    /// this test once already.
    fn compressible(bytes: usize) -> Vec<u8> {
        const WORDS: [&str; 8] =
            ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"];
        let mut out = String::with_capacity(bytes + 128);
        let mut seed: u64 = 7;
        let mut line = 0u32;
        while out.len() < bytes {
            out.push_str(&format!("{line:06} "));
            for _ in 0..8 {
                seed = seed.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
                out.push_str(WORDS[(seed >> 33) as usize % WORDS.len()]);
                out.push(' ');
            }
            out.push('\n');
            line += 1;
        }
        out.into_bytes()
    }

    /// Compress `src` into a set of parts and hand back the parts.
    ///
    /// Stored rather than compressed, so the archive is about the size of what
    /// went into it and the number of parts is something the test can state
    /// rather than discover.
    fn split_seven_zip(base: &Path, name: &str, part: u64) -> Vec<PathBuf> {
        fs::write(base.join("src/big.txt"), compressible(200 * 1024)).unwrap();
        let out = base.join(name);
        let options = Options {
            level: Level::Store,
            password: None,
            split: Split::of_bytes(part).unwrap(),
            ..Options::default()
        };
        let done = compress(
            &base.join("src"),
            &[base.join("src")],
            &out,
            Format::SevenZip,
            &options,
            &mut crate::ops::fs::silent,
        )
        .unwrap();
        assert!(!out.exists(), "the whole archive does not survive beside its parts");
        done.parts
    }

    #[test]
    fn a_split_seven_zip_reads_back_through_any_of_its_parts() {
        let base = scratch("split-round");
        let parts = split_seven_zip(&base, "all.7z", volume::SMALLEST_PART);
        assert!(parts.len() > 2, "200 KB at 64 KB should be several parts, got {}", parts.len());
        assert_eq!(parts[0], base.join("all.7z.001"));

        //: The listing is the harder half: a 7z keeps its header at the end,
        //: so reading the names at all means seeking to the last part and back.
        let listed = list(&base.join("all.7z.001"), None).unwrap();
        let names: Vec<&str> = listed.iter().map(|e| e.name.as_str()).collect();
        assert!(names.contains(&"big.txt"), "got {names:?}");
        assert!(names.contains(&"inner/deep.txt"), "got {names:?}");

        //: And opening the piece the person happened to click on works the
        //: same as opening the first.
        let from_third = list(&parts[2], None).unwrap().len();
        assert_eq!(from_third, listed.len());

        let (target, done) = extract(
            &base.join("all.7z.001"),
            &base.join("out"),
            Destination::Here,
            None,
            &mut crate::ops::fs::silent,
        )
        .unwrap();
        assert!(done.items > 0);
        assert_eq!(fs::read(target.join("top.txt")).unwrap(), b"top");
        assert_eq!(fs::read(target.join("inner/deep.txt")).unwrap(), b"deep");
        assert_eq!(
            fs::read(target.join("big.txt")).unwrap(),
            compressible(200 * 1024),
            "the bytes across the part boundaries are the ones that went in"
        );
    }

    #[test]
    fn a_part_extracts_under_the_name_of_the_archive_not_the_piece() {
        let base = scratch("split-name");
        split_seven_zip(&base, "photos.7z", volume::SMALLEST_PART);
        assert_eq!(strip_archive_suffix("photos.7z.001"), "photos");
        //: A three digit run that is not a part is left where it is.
        assert_eq!(strip_archive_suffix("photos.7z"), "photos");
        assert_eq!(strip_archive_suffix("backup.2024"), "backup.2024");

        let (target, _) = extract(
            &base.join("photos.7z.001"),
            &base.join("out"),
            Destination::ChildFolder,
            None,
            &mut crate::ops::fs::silent,
        )
        .unwrap();
        assert_eq!(target, base.join("out/photos"));
    }

    #[test]
    fn only_a_seven_zip_is_written_in_parts() {
        let base = scratch("split-formats");
        let options = Options {
            level: Level::Store,
            password: None,
            split: Split::of_bytes(volume::SMALLEST_PART).unwrap(),
            ..Options::default()
        };
        for (name, format) in [("no.zip", Format::Zip), ("no.tar.gz", Format::TarGz)] {
            let out = base.join(name);
            let refused = compress(
                &base.join("src"),
                &[base.join("src")],
                &out,
                format,
                &options,
                &mut crate::ops::fs::silent,
            )
            .unwrap_err();
            assert!(matches!(refused, Error::Unsupported(_)), "{name}: got {refused:?}");
            //: Refused before a byte is written, not after.
            assert!(!out.exists(), "{name} was written anyway");
        }
    }

    #[test]
    fn a_zip_named_as_a_part_is_not_stitched() {
        let base = scratch("split-zipparts");
        let refused = format_of(&base.join("thing.zip.001")).unwrap_err();
        assert!(matches!(refused, Error::Unsupported(_)), "got {refused:?}");
        //: And something that is neither is still just unknown.
        assert!(matches!(
            format_of(&base.join("notes.txt.001")).unwrap_err(),
            Error::BadRequest(_)
        ));
        assert_eq!(format_of(&base.join("thing.7z.001")).unwrap(), Format::SevenZip);
        assert_eq!(format_of(&base.join("thing.7z")).unwrap(), Format::SevenZip);
    }

    #[test]
    fn a_split_archive_can_still_carry_a_password() {
        let base = scratch("split-password");
        fs::write(base.join("src/big.txt"), compressible(200 * 1024)).unwrap();
        let out = base.join("locked.7z");
        let options = Options {
            level: Level::Store,
            password: Some("hunter2".into()),
            split: Split::of_bytes(volume::SMALLEST_PART).unwrap(),
            ..Options::default()
        };
        let done = compress(
            &base.join("src"),
            &[base.join("src")],
            &out,
            Format::SevenZip,
            &options,
            &mut crate::ops::fs::silent,
        )
        .unwrap();
        assert!(done.parts.len() > 2);

        let wrong = extract(
            &base.join("locked.7z.001"),
            &base.join("out/wrong"),
            Destination::Here,
            Some("hunter3"),
            &mut crate::ops::fs::silent,
        )
        .unwrap_err();
        assert!(matches!(wrong, Error::NeedsPassword(_)), "got {wrong:?}");

        let (target, _) = extract(
            &base.join("locked.7z.001"),
            &base.join("out/right"),
            Destination::Here,
            Some("hunter2"),
            &mut crate::ops::fs::silent,
        )
        .unwrap();
        assert_eq!(fs::read(target.join("top.txt")).unwrap(), b"top");
    }

    #[test]
    fn a_level_reaches_the_codec_rather_than_being_carried_and_dropped() {
        let base = scratch("levels");
        let big = base.join("src/big.txt");
        fs::write(&big, compressible(200 * 1024)).unwrap();
        let raw = fs::metadata(&big).unwrap().len();
        let size = |p: &Path| fs::metadata(p).unwrap().len();

        for (name, format) in
            [("zip", Format::Zip), ("7z", Format::SevenZip), ("tar.gz", Format::TarGz)]
        {
            let at = |level: Level| {
                let out = base.join(format!("{}.{name}", level.name()));
                compress(&base.join("src"), &[big.clone()], &out, format, &Options::new(level), &mut crate::ops::fs::silent)
                    .unwrap();
                (out, size(&base.join(format!("{}.{name}", level.name()))))
            };
            let (_, stored) = at(Level::Store);
            let (_, fast) = at(Level::Fast);
            let (ultra_path, ultra) = at(Level::Ultra);

            assert!(stored >= raw, "{name}: store shrank it, {stored} against {raw}");
            assert!(fast < stored, "{name}: fast {fast} did not beat store {stored}");
            //: The whole point of a scale: trying harder gives a smaller file.
            //: Ultra against Normal is not asserted, because on a payload this
            //: size lzma2 reaches the same answer at both and that would be a
            //: test that fails for being right.
            assert!(ultra < fast, "{name}: ultra {ultra} is not smaller than fast {fast}");

            //: And what came out still extracts to what went in.
            let (target, _) = extract(
                &ultra_path,
                &base.join("out").join(name),
                Destination::Here,
                None,
                &mut crate::ops::fs::silent,
            )
            .unwrap();
            assert_eq!(fs::read(target.join("big.txt")).unwrap().len(), raw as usize);
        }
    }

    #[test]
    fn a_compress_reports_what_it_is_doing_and_counts_what_it_did() {
        let base = scratch("progress");
        let archive = base.join("all.zip");
        let mut seen: Vec<(u64, u64, u64, u64, String)> = Vec::new();
        let done = compress(
            &base.join("src"),
            &[base.join("src")],
            &archive,
            Format::Zip,
            &Options::default(),
            &mut |p| {
                seen.push((
                    p.done_items,
                    p.done_bytes,
                    p.total_items,
                    p.total_bytes,
                    p.current.file_name().unwrap_or_default().to_string_lossy().into_owned(),
                ));
                Flow::Continue
            },
        )
        .unwrap();

        assert!(!done.cancelled);
        //: top.txt, inner, inner/deep.txt. The folder being archived is not
        //: itself an entry: its name is relative to itself, which is nothing,
        //: and an archive with an empty name in it is not one anybody can open.
        assert_eq!(done.items, 3, "counted {} entries", done.items);
        assert_eq!(done.bytes, 7, "top plus deep is seven bytes, got {}", done.bytes);
        //: Two reports an entry: the one about to be written, and the one that
        //: now is. Without the second the counts trail an entry behind, and a
        //: job of one entry reads zero from the first report to the last.
        assert_eq!(seen.len(), 6, "two reports per entry, got {seen:?}");
        //: The total counts the walk, including the folder that is skipped, so
        //: it is a ceiling rather than a promise. What matters for a bar is
        //: that it is known from the start rather than growing as it goes.
        assert!(seen.iter().all(|(_, _, total, _, _)| *total == 4), "{seen:?}");
        assert!(seen.iter().all(|(_, _, _, bytes, _)| *bytes == 7), "{seen:?}");
        //: The first is reported before the entry is written, so the name on
        //: screen is the one being worked on rather than the one just done.
        assert_eq!(seen[0].0, 0, "the first report already counted an entry");
        assert_eq!(seen[0].1, 0, "the first report already counted bytes");
        //: And the last says everything is done, which is what a bar reaching
        //: the end of its track means.
        let last = seen.last().unwrap();
        assert_eq!((last.0, last.1), (3, 7), "the last report is {last:?}");
        //: The counts never go backwards on the way there.
        for pair in seen.windows(2) {
            assert!(pair[1].0 >= pair[0].0 && pair[1].1 >= pair[0].1, "{seen:?}");
        }
        assert!(seen.iter().any(|(_, _, _, _, name)| name == "deep.txt"), "{seen:?}");
    }

    #[test]
    fn an_extract_reports_what_it_has_written_and_not_only_what_is_next() {
        let base = scratch("extract-reports");
        let archive = base.join("all.zip");
        compress(
            &base.join("src"),
            &[base.join("src")],
            &archive,
            Format::Zip,
            &Options::default(),
            &mut crate::ops::fs::silent,
        )
        .unwrap();

        let mut seen: Vec<(u64, u64, u64, u64)> = Vec::new();
        let (_, done) = extract(
            &archive,
            &base.join("out"),
            Destination::ChildFolder,
            None,
            &mut |p| {
                seen.push((p.done_items, p.done_bytes, p.total_items, p.total_bytes));
                Flow::Continue
            },
        )
        .unwrap();

        assert_eq!(done.items, 3);
        assert_eq!(seen.len(), 6, "two reports per entry, got {seen:?}");
        assert_eq!((seen[0].0, seen[0].1), (0, 0));
        let last = seen.last().unwrap();
        assert_eq!(last.0, 3, "the last report is {last:?}");
        assert_eq!(last.1, last.3, "the bytes end at the total, {last:?}");
    }

    #[test]
    fn a_cancelled_compress_takes_its_half_written_archive_with_it() {
        let base = scratch("cancel-compress");
        for format in [Format::Zip, Format::SevenZip, Format::TarGz] {
            let archive = base.join(format!("stopped.{}", format.extension()));
            let mut seen = 0;
            let done = compress(
                &base.join("src"),
                &[base.join("src")],
                &archive,
                format,
                &Options::default(),
                &mut |_| {
                    seen += 1;
                    //: Stopped after the first entry, which is the case that
                    //: leaves a file on disk with a header and nothing else.
                    if seen >= 2 { Flow::Cancel } else { Flow::Continue }
                },
            )
            .unwrap();
            assert!(done.cancelled, "{:?} did not report the stop", format);
            assert!(
                !archive.exists(),
                "{:?} left {} behind, which opens as nothing",
                format,
                archive.display()
            );
        }
    }

    #[test]
    fn a_cancelled_extract_keeps_what_it_wrote_and_says_so() {
        let base = scratch("cancel-extract");
        let archive = base.join("all.zip");
        compress(
            &base.join("src"),
            &[base.join("src")],
            &archive,
            Format::Zip,
            &Options::default(),
            &mut crate::ops::fs::silent,
        )
        .unwrap();

        let into = base.join("out/stopped");
        let mut seen = 0;
        let (target, done) = extract(&archive, &into, Destination::Here, None, &mut |_| {
            seen += 1;
            if seen >= 3 { Flow::Cancel } else { Flow::Continue }
        })
        .unwrap();
        assert!(done.cancelled);
        assert!(
            done.items > 0 && done.items < 3,
            "it did not stop partway, {} of 3 entries",
            done.items
        );
        //: What it wrote stays. Those are ordinary files in a folder the user
        //: chose, and some of them may have been there already.
        assert!(target.exists(), "the destination was removed");
        assert!(
            std::fs::read_dir(&target).unwrap().next().is_some(),
            "nothing was written before the stop, so this proves nothing"
        );
    }

    #[test]
    fn an_extract_knows_how_much_there_is_before_it_starts() {
        let base = scratch("extract-progress");
        let archive = base.join("all.tar.gz");
        compress(
            &base.join("src"),
            &[base.join("src")],
            &archive,
            Format::TarGz,
            &Options::default(),
            &mut crate::ops::fs::silent,
        )
        .unwrap();

        let mut totals = Vec::new();
        let (_, done) = extract(
            &archive,
            &base.join("out/all"),
            Destination::Here,
            None,
            &mut |p| {
                totals.push((p.total_items, p.total_bytes));
                Flow::Continue
            },
        )
        .unwrap();
        assert!(!done.cancelled);
        assert_eq!(done.items, 3);
        assert!(!totals.is_empty());
        //: Read from the archive's own listing before a byte is written, so
        //: the bar starts full width instead of growing under the cursor.
        assert!(totals.iter().all(|(items, _)| *items == 3), "{totals:?}");
        assert!(totals.iter().all(|(_, bytes)| *bytes == 7), "{totals:?}");
    }

    #[test]
    fn every_format_puts_the_same_things_in_an_archive() {
        //: One walk feeds all three writers, so a folder archived as a tar
        //: holds what it would hold as a zip. Before this the tar path used
        //: append_dir_all and could disagree, which meant an archive this
        //: service wrote could contain an entry it would refuse to extract.
        let base = scratch("same-entries");
        std::os::unix::fs::symlink("top.txt", base.join("src/link.txt")).unwrap();

        let mut names: Vec<Vec<String>> = Vec::new();
        for format in [Format::Zip, Format::SevenZip, Format::Tar] {
            let archive = base.join(format!("same.{}", format.extension()));
            compress(
                &base.join("src"),
                &[base.join("src")],
                &archive,
                format,
                &Options::default(),
                &mut crate::ops::fs::silent,
            )
            .unwrap();
            let mut listed: Vec<String> = list(&archive, None)
                .unwrap()
                .into_iter()
                .map(|e| e.name.trim_end_matches('/').to_string())
                .filter(|n| !n.is_empty() && n != ".")
                .collect();
            listed.sort();
            names.push(listed);
        }
        assert_eq!(names[0], names[1], "zip and 7z disagree");
        assert_eq!(names[1], names[2], "7z and tar disagree");
        //: And the symlink is in none of them, because extraction refuses a
        //: link entry: writing one would be writing an archive this service
        //: will not open.
        assert!(
            names[0].iter().all(|n| !n.ends_with("link.txt")),
            "a link was archived that could not be extracted: {:?}",
            names[0]
        );
    }

    #[test]
    fn a_level_name_is_the_one_the_dialog_shows() {
        for level in Level::ALL {
            assert_eq!(Level::from_name(level.name()), Some(level));
            assert_eq!(Level::from_name(&level.name().to_uppercase()), Some(level));
        }
        assert_eq!(Level::from_name(" maximum "), Some(Level::High));
        assert_eq!(Level::from_name("none"), Some(Level::Store));
        assert_eq!(Level::from_name("11"), None, "a number is not one of the names");
        assert_eq!(Level::default(), Level::Normal);

        //: Every scale stays inside what its codec accepts, and the two ends
        //: are pinned: Ultra has to mean the top of the scale or the word is
        //: not true, and Store has to mean no compression asked for.
        for level in Level::ALL {
            assert!(level.deflate() <= 9);
            assert!((1..=22).contains(&level.zstd()));
            assert!(level.lzma() <= 9);
        }
        assert_eq!(Level::Ultra.deflate(), 9, "ultra is not the top of the deflate scale");
        assert_eq!(Level::Ultra.lzma(), 9, "ultra is not the top of the lzma scale");
        assert_eq!(Level::Normal.deflate(), 6, "normal is not deflate's own default");
        assert_eq!(Level::Normal.zstd(), 3, "normal is not zstd's own default");
        assert_eq!(Level::Store.deflate(), 0);
        assert!(Level::Ultra.zstd() > Level::Fast.zstd());
        assert!(Format::Zip.takes_password() && Format::SevenZip.takes_password());
        assert!(!Format::TarGz.takes_password());
    }

    #[test]
    fn format_reads_two_part_extensions_before_one() {
        assert_eq!(Format::from_name("x.tar.gz"), Some(Format::TarGz));
        assert_eq!(Format::from_name("x.tar.xz"), Some(Format::TarXz));
        assert_eq!(Format::from_name("x.tar"), Some(Format::Tar));
        assert_eq!(Format::from_name("x.ZIP"), Some(Format::Zip));
        assert_eq!(Format::from_name("x.txt"), None);
    }

    #[test]
    fn the_child_folder_name_drops_the_whole_suffix() {
        assert_eq!(strip_archive_suffix("project.tar.gz"), "project");
        assert_eq!(strip_archive_suffix("project.zip"), "project");
        assert_eq!(strip_archive_suffix("no-suffix"), "no-suffix");
    }

    #[test]
    fn safe_join_refuses_every_way_out() {
        let dest = Path::new("/tmp/dest");
        for bad in [
            "../escape",
            "a/../../escape",
            "/absolute",
            "/etc/passwd",
            "..",
        ] {
            assert!(
                safe_join(dest, bad).is_err(),
                "{bad} was allowed through"
            );
        }
        //: A backslash inside one component is how a Windows written entry
        //: smuggles a separator past a POSIX component walk.
        assert!(safe_join(dest, "a\\..\\..\\escape").is_err());
        assert_eq!(
            safe_join(dest, "a/b/c.txt").unwrap(),
            Path::new("/tmp/dest/a/b/c.txt")
        );
        assert_eq!(safe_join(dest, "./a.txt").unwrap(), Path::new("/tmp/dest/a.txt"));
    }

    fn round_trip(tag: &str, format: Format) {
        let base = scratch(tag);
        let archive = base.join(format!("bundle.{}", format.extension()));
        let sources = vec![base.join("src")];
        compress(&base, &sources, &archive, format, &Options::default(), &mut crate::ops::fs::silent).unwrap();
        assert!(archive.exists(), "{format:?} produced nothing");

        let entries = list(&archive, None).unwrap();
        assert!(
            entries.iter().any(|e| e.name.contains("top.txt")),
            "{format:?} listing lost top.txt: {entries:?}"
        );

        let into = base.join("out");
        extract(&archive, &into, Destination::Here, None, &mut crate::ops::fs::silent).unwrap().0;
        assert_eq!(fs::read(into.join("src/top.txt")).unwrap(), b"top");
        assert_eq!(fs::read(into.join("src/inner/deep.txt")).unwrap(), b"deep");
    }

    #[test]
    fn zip_round_trips() { round_trip("zip", Format::Zip); }

    #[test]
    fn tar_round_trips() { round_trip("tar", Format::Tar); }

    #[test]
    fn tar_gz_round_trips() { round_trip("targz", Format::TarGz); }

    #[test]
    fn tar_xz_round_trips() { round_trip("tarxz", Format::TarXz); }

    #[test]
    fn tar_zst_round_trips() { round_trip("tarzst", Format::TarZst); }

    #[test]
    fn seven_zip_round_trips() { round_trip("7z", Format::SevenZip); }

    #[test]
    fn smart_extraction_uses_the_archives_own_root_when_it_has_one() {
        let base = scratch("smart-wrapped");
        let archive = base.join("bundle.zip");
        compress(&base, &[base.join("src")], &archive, Format::Zip, &Options::default(), &mut crate::ops::fs::silent)
            .unwrap();
        //: Everything is under src/, so there is nothing to tidy and the
        //: contents land where they are.
        let target = extract(&archive, &base.join("out"), Destination::Smart, None, &mut crate::ops::fs::silent).unwrap().0;
        assert_eq!(target, base.join("out"));
        assert!(base.join("out/src/top.txt").exists());
    }

    #[test]
    fn smart_extraction_makes_a_folder_for_loose_files() {
        let base = scratch("smart-loose");
        let archive = base.join("loose.zip");
        compress(
            &base.join("src"),
            &[base.join("src/top.txt"), base.join("src/inner")],
            &archive,
            Format::Zip,
            &Options::default(),
            &mut crate::ops::fs::silent,
        )
        .unwrap();
        let target = extract(&archive, &base.join("out"), Destination::Smart, None, &mut crate::ops::fs::silent).unwrap().0;
        assert_eq!(target, base.join("out/loose"));
        assert!(base.join("out/loose/top.txt").exists());
    }

    #[test]
    fn a_zip_that_climbs_out_is_refused_before_it_writes() {
        let base = scratch("zipslip");
        let archive = base.join("evil.zip");
        {
            let file = File::create(&archive).unwrap();
            let mut zip = zip::ZipWriter::new(file);
            let opts: zip::write::FileOptions<'_, ()> = zip::write::FileOptions::default();
            zip.start_file("../pwned.txt", opts).unwrap();
            zip.write_all(b"owned").unwrap();
            zip.finish().unwrap();
        }
        let into = base.join("out");
        let err = extract(&archive, &into, Destination::Here, None, &mut crate::ops::fs::silent).unwrap_err();
        assert!(matches!(err, Error::Escapes(_)), "got {err:?}");
        assert!(!base.join("pwned.txt").exists(), "it wrote outside anyway");
    }

    #[test]
    fn a_zip_symlink_entry_is_refused() {
        let base = scratch("ziplink");
        let archive = base.join("link.zip");
        {
            let file = File::create(&archive).unwrap();
            let mut zip = zip::ZipWriter::new(file);
            let opts: zip::write::FileOptions<'_, ()> = zip::write::FileOptions::default();
            //: unix_permissions masks to 0o777, so the file type bits cannot
            //: be smuggled in that way; add_symlink writes a real one.
            zip.add_symlink("escape", "/etc/passwd", opts).unwrap();
            zip.finish().unwrap();
        }
        let err = extract(&archive, &base.join("out"), Destination::Here, None, &mut crate::ops::fs::silent).unwrap_err();
        assert!(matches!(err, Error::Escapes(_)), "got {err:?}");
        assert!(!base.join("out/escape").exists(), "the link was created anyway");
    }

    #[test]
    fn extraction_never_restores_setuid() {
        use std::os::unix::fs::PermissionsExt;
        let base = scratch("setuid");
        //: A tar, not a zip: the zip writer masks a stored mode to 0o777, so a
        //: zip fixture cannot carry a setuid bit at all and would prove
        //: nothing about the code that strips it.
        let archive = base.join("suid.tar");
        {
            let file = File::create(&archive).unwrap();
            let mut builder = tar::Builder::new(file);
            let body = b"#!/bin/sh\n";
            let mut header = tar::Header::new_gnu();
            header.set_path("tool").unwrap();
            header.set_size(body.len() as u64);
            header.set_mode(0o4_755);
            header.set_cksum();
            builder.append(&header, &body[..]).unwrap();

            let mut sgid = tar::Header::new_gnu();
            sgid.set_path("shared").unwrap();
            sgid.set_size(body.len() as u64);
            sgid.set_mode(0o2_755);
            sgid.set_cksum();
            builder.append(&sgid, &body[..]).unwrap();
            builder.finish().unwrap();
        }
        let into = base.join("out");
        extract(&archive, &into, Destination::Here, None, &mut crate::ops::fs::silent).unwrap().0;
        for (name, expected) in [("tool", 0o755), ("shared", 0o755)] {
            let mode = fs::metadata(into.join(name)).unwrap().permissions().mode();
            assert_eq!(mode & 0o7000, 0, "{name}: setuid or setgid survived extraction");
            assert_eq!(mode & 0o777, expected);
        }
    }

    #[test]
    fn compressing_over_something_that_exists_is_refused() {
        let base = scratch("clobber");
        let archive = base.join("bundle.zip");
        fs::write(&archive, b"do not lose me").unwrap();
        let err =
            compress(&base, &[base.join("src")], &archive, Format::Zip, &Options::default(), &mut crate::ops::fs::silent)
                .unwrap_err();
        assert!(matches!(err, Error::Exists(_)), "got {err:?}");
        assert_eq!(fs::read(&archive).unwrap(), b"do not lose me");
    }
}
