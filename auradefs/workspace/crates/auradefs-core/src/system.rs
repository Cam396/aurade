//! The verbs that reach outside the file manager: installing a font, adding a
//! certificate, checking a signature, setting the wallpaper, sharing a file,
//! and remembering how a particular program should be launched.
//!
//! Each of these is the Linux answer to something Files does through a Windows
//! shell call. None of them silently gains authority: installing a font writes
//! to the user's own font directory, a certificate goes into the user's own NSS
//! store with the trust the caller asked for and no more, and verifying a
//! signature reports what gpg said rather than an opinion about it.

use std::path::{Path, PathBuf};
use std::process::Command;

use crate::error::{Error, Result};
use crate::mime::{xdg_config_home, xdg_data_home};

// ------------------------------------------------------------------ fonts ---

/// What a font file says about itself.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct FontInfo {
    pub family: Option<String>,
    pub style: Option<String>,
    pub full_name: Option<String>,
}

/// Read a font's names, through fontconfig so the answer matches what the rest
/// of the system will call it once it is installed.
pub fn font_info(path: &Path) -> Result<FontInfo> {
    let out = Command::new("fc-scan")
        .arg("--format")
        .arg("%{family[0]}\\n%{style[0]}\\n%{fullname[0]}\\n")
        .arg(path)
        .output()
        .map_err(|e| match e.kind() {
            std::io::ErrorKind::NotFound => Error::NotFound("fontconfig is not installed".into()),
            _ => Error::io("running fc-scan", e),
        })?;
    if !out.status.success() {
        return Err(Error::BadRequest(format!(
            "{} is not a font fontconfig can read",
            path.display()
        )));
    }
    Ok(parse_fc_scan(&String::from_utf8_lossy(&out.stdout)))
}

fn parse_fc_scan(text: &str) -> FontInfo {
    let mut lines = text.lines().map(|l| l.trim().to_string());
    let take = |v: Option<String>| v.filter(|s| !s.is_empty() && s != "(null)");
    FontInfo {
        family: take(lines.next()),
        style: take(lines.next()),
        full_name: take(lines.next()),
    }
}

/// Where a font installed for this user goes. The system wide directory is not
/// an option offered here: that is a change to every account on the machine,
/// and it belongs to the package manager.
pub fn font_dir() -> Result<PathBuf> {
    Ok(xdg_data_home()
        .ok_or_else(|| Error::NotFound("no data directory".into()))?
        .join("fonts"))
}

/// Extensions fontconfig can actually use.
const FONT_EXTENSIONS: &[&str] = &["ttf", "otf", "ttc", "otc", "pfb", "pfa", "woff", "woff2"];

/// Install a font for this user, and refresh the cache so it appears in
/// running programs without a logout.
pub fn install_font(path: &Path) -> Result<PathBuf> {
    let name = path
        .file_name()
        .ok_or_else(|| Error::BadRequest("no file name".into()))?
        .to_string_lossy()
        .to_string();
    let extension = path
        .extension()
        .map(|e| e.to_string_lossy().to_ascii_lowercase())
        .unwrap_or_default();
    if !FONT_EXTENSIONS.contains(&extension.as_str()) {
        return Err(Error::BadRequest(format!("{name} is not a font file")));
    }
    //: Reading it first means a corrupt file is refused before it is copied,
    //: rather than being installed and then ignored by everything.
    font_info(path)?;

    let dir = font_dir()?;
    std::fs::create_dir_all(&dir).map_err(|e| Error::io(dir.display().to_string(), e))?;
    let dest = dir.join(&name);
    if dest.exists() {
        return Err(Error::Exists(dest.display().to_string()));
    }
    std::fs::copy(path, &dest).map_err(|e| Error::io(dest.display().to_string(), e))?;
    //: A failed cache refresh is not a failed install: the font is on disk and
    //: will be picked up on the next login either way.
    let _ = Command::new("fc-cache").arg("--force").arg(&dir).output();
    Ok(dest)
}

/// Is this font already installed for this user?
pub fn font_installed(path: &Path) -> Result<bool> {
    let Some(name) = path.file_name() else { return Ok(false) };
    Ok(font_dir()?.join(name).exists())
}

// ----------------------------------------------------------- certificates ---

/// How much a certificate is to be trusted once it is in the store.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Trust {
    /// Stored, trusted for nothing. The safe default, and the only one that is
    /// reasonable without the user being told exactly what they are agreeing
    /// to.
    None,
    /// Trusted to sign server certificates. This makes the holder of the
    /// matching private key able to impersonate any site to this user, so it
    /// is never chosen on the user's behalf.
    Ca,
}

impl Trust {
    fn flags(self) -> &'static str {
        match self {
            Trust::None => ",,",
            Trust::Ca => "C,,",
        }
    }
}

/// The NSS database Chromium and therefore this desktop reads.
pub fn nss_db() -> Result<PathBuf> {
    Ok(PathBuf::from(
        std::env::var("HOME").map_err(|_| Error::NotFound("HOME is not set".into()))?,
    )
    .join(".pki/nssdb"))
}

/// Add a certificate to the user's store.
///
/// `trust` is required rather than defaulted at the call site, because the
/// difference between the two values is the difference between keeping a copy
/// of a certificate and handing someone the ability to read this user's
/// encrypted traffic.
pub fn install_certificate(path: &Path, nickname: &str, trust: Trust) -> Result<()> {
    if nickname.trim().is_empty() {
        return Err(Error::BadRequest("a certificate needs a nickname".into()));
    }
    let bytes = std::fs::read(path).map_err(|e| Error::io(path.display().to_string(), e))?;
    if !looks_like_certificate(&bytes) {
        return Err(Error::BadRequest(format!(
            "{} does not look like a certificate",
            path.display()
        )));
    }
    let db = nss_db()?;
    std::fs::create_dir_all(&db).map_err(|e| Error::io(db.display().to_string(), e))?;
    let db_arg = format!("sql:{}", db.display());
    certutil(&[
        "-d",
        &db_arg,
        "-A",
        "-n",
        nickname,
        "-t",
        trust.flags(),
        "-i",
        &path.display().to_string(),
    ])
    .map(|_| ())
}

/// One certificate already in the store.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Certificate {
    pub nickname: String,
    /// The raw trust flags, in NSS's own three part spelling.
    pub trust: String,
}

pub fn certificates() -> Result<Vec<Certificate>> {
    let db = nss_db()?;
    if !db.exists() {
        return Ok(Vec::new());
    }
    let db_arg = format!("sql:{}", db.display());
    let text = certutil(&["-d", &db_arg, "-L"])?;
    Ok(parse_certutil_list(&text))
}

fn parse_certutil_list(text: &str) -> Vec<Certificate> {
    let mut out = Vec::new();
    for line in text.lines() {
        let line = line.trim_end();
        if line.trim().is_empty() || line.starts_with("Certificate Nickname") || line.starts_with('-')
        {
            continue;
        }
        //: The nickname can contain spaces, and the trust flags are the last
        //: field, so the split has to come from the right.
        let Some((nickname, trust)) = line.rsplit_once(char::is_whitespace) else { continue };
        let nickname = nickname.trim();
        //: The header's second line is only the column legend, and it has
        //: commas in it, so "contains a comma" is not enough to call a line an
        //: entry. An entry always has a nickname in front of the flags.
        if nickname.is_empty() || !trust.contains(',') {
            continue;
        }
        out.push(Certificate {
            nickname: nickname.to_string(),
            trust: trust.trim().to_string(),
        });
    }
    out
}

fn certutil(args: &[&str]) -> Result<String> {
    let out = Command::new("certutil").args(args).output().map_err(|e| match e.kind() {
        std::io::ErrorKind::NotFound => {
            Error::NotFound("nss is not installed, so there is no certificate store to use".into())
        }
        _ => Error::io("running certutil", e),
    })?;
    if out.status.success() {
        return Ok(String::from_utf8_lossy(&out.stdout).into_owned());
    }
    let message = String::from_utf8_lossy(&out.stderr);
    Err(Error::Tool {
        tool: "certutil".into(),
        message: message.lines().last().unwrap_or("failed").trim().to_string(),
    })
}

/// A PEM header, or a DER sequence. Not a validation, just enough to refuse the
/// obviously wrong file before handing it to the store.
fn looks_like_certificate(bytes: &[u8]) -> bool {
    let head = &bytes[..bytes.len().min(64)];
    if head.starts_with(b"-----BEGIN CERTIFICATE-----") {
        return true;
    }
    //: DER: a SEQUENCE with a long form length, which every real certificate
    //: has because none of them are under 128 bytes.
    matches!(head.first(), Some(0x30)) && matches!(head.get(1), Some(0x81..=0x84))
}

// ------------------------------------------------------------- signatures ---

/// What gpg concluded.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SignatureStatus {
    /// The signature matches, and the key is one this user has marked as
    /// trusted.
    GoodAndTrusted,
    /// The signature matches a key, but nothing says that key belongs to who
    /// it claims to. This is the common case for a downloaded file and it is
    /// **not** proof of origin.
    GoodButUntrusted,
    /// The signature does not match. The file has changed, or it was never
    /// signed by that key.
    Bad,
    /// The key is not in the keyring, so there is nothing to check against.
    KeyMissing,
    /// The key is expired or revoked. The signature matches, but the owner has
    /// said not to rely on it.
    KeyExpiredOrRevoked,
    /// gpg had nothing to say, usually because the file is not signed.
    NotSigned,
}

/// The answer when nothing was checked, because there was nothing to check.
impl Signature {
    pub fn unsigned() -> Signature {
        Signature {
            status: SignatureStatus::NotSigned,
            key_id: None,
            signer: None,
            detail: String::new(),
        }
    }
}

/// The result of checking a signature.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Signature {
    pub status: SignatureStatus,
    pub key_id: Option<String>,
    pub signer: Option<String>,
    /// What gpg printed, kept so the dialog can show it rather than a
    /// paraphrase of it.
    ///
    /// All of it, not the last line. gpg's verdict runs over several lines and
    /// the last one is as often a fingerprint or the tail of a sentence as it
    /// is the answer, which on its own reads as nonsense.
    pub detail: String,
}

/// Whether there is anything here for gpg to look at.
///
/// Without this, opening properties on a four gigabyte disk image spawns a gpg
/// that reads all four gigabytes to conclude the file was never signed. There
/// are two reasons to look: a detached signature beside it, or the file being
/// an OpenPGP file itself. Anything else is not unsigned, it is not a question.
pub fn signable(path: &Path, beside: Option<&Path>) -> bool {
    if beside.is_some() {
        return true;
    }
    let name = path.file_name().unwrap_or_default().to_string_lossy().to_ascii_lowercase();
    [".gpg", ".pgp", ".asc", ".sig", ".sign", ".signature"]
        .iter()
        .any(|extension| name.ends_with(extension))
}

/// Check a detached signature, or a file that carries one. `signature` is the
/// `.sig` or `.asc` beside it, when there is one.
pub fn verify_signature(path: &Path, signature: Option<&Path>) -> Result<Signature> {
    let mut args: Vec<String> = vec![
        "--status-fd=1".into(),
        "--batch".into(),
        "--no-tty".into(),
        "--verify".into(),
    ];
    match signature {
        Some(sig) => {
            args.push(sig.display().to_string());
            args.push(path.display().to_string());
        }
        None => args.push(path.display().to_string()),
    }
    let out = Command::new("gpg").args(&args).output().map_err(|e| match e.kind() {
        std::io::ErrorKind::NotFound => Error::NotFound("gnupg is not installed".into()),
        _ => Error::io("running gpg", e),
    })?;
    let status_text = String::from_utf8_lossy(&out.stdout);
    let human = String::from_utf8_lossy(&out.stderr);
    Ok(parse_gpg_status(&status_text, &human))
}

/// The signature file beside a download, if one is there. `.sig` and `.asc`
/// are the two spellings in use.
pub fn signature_beside(path: &Path) -> Option<PathBuf> {
    for extension in ["sig", "asc", "sign"] {
        let candidate = PathBuf::from(format!("{}.{extension}", path.display()));
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

/// What gpg said, tidied but not summarised.
///
/// Capped, because this ends up in a JSON body and the size of a tool's
/// output is the tool's business rather than a promise it made.
fn gpg_detail(human: &str) -> String {
    const MOST: usize = 4096;
    let kept: Vec<&str> = human.lines().map(str::trim_end).filter(|l| !l.is_empty()).collect();
    let mut out = kept.join("\n");
    if out.len() > MOST {
        //: On a character boundary, since this is going into a JSON string.
        let mut cut = MOST;
        while cut > 0 && !out.is_char_boundary(cut) {
            cut -= 1;
        }
        out.truncate(cut);
    }
    out
}

fn parse_gpg_status(status: &str, human: &str) -> Signature {
    let mut key_id = None;
    let mut signer = None;
    let mut good = false;
    let mut bad = false;
    let mut missing = false;
    let mut expired = false;
    let mut trusted = false;

    for line in status.lines() {
        let Some(rest) = line.strip_prefix("[GNUPG:] ") else { continue };
        let mut parts = rest.split(' ');
        let Some(keyword) = parts.next() else { continue };
        match keyword {
            "GOODSIG" => {
                good = true;
                key_id = parts.next().map(str::to_string);
                let name: Vec<&str> = parts.collect();
                if !name.is_empty() {
                    signer = Some(name.join(" "));
                }
            }
            "BADSIG" => {
                bad = true;
                key_id = parts.next().map(str::to_string);
            }
            "NO_PUBKEY" => {
                missing = true;
                key_id = parts.next().map(str::to_string);
            }
            "EXPKEYSIG" | "REVKEYSIG" => {
                expired = true;
                key_id = parts.next().map(str::to_string);
            }
            //: Only these two mean the user has actually vouched for the key.
            //: TRUST_UNDEFINED and TRUST_NEVER do not, and neither does a
            //: signature that simply verifies.
            "TRUST_FULLY" | "TRUST_ULTIMATE" => trusted = true,
            _ => {}
        }
    }

    let status = if bad {
        SignatureStatus::Bad
    } else if expired {
        SignatureStatus::KeyExpiredOrRevoked
    } else if missing {
        SignatureStatus::KeyMissing
    } else if good && trusted {
        SignatureStatus::GoodAndTrusted
    } else if good {
        SignatureStatus::GoodButUntrusted
    } else {
        SignatureStatus::NotSigned
    };

    Signature {
        status,
        key_id,
        signer,
        detail: gpg_detail(human),
    }
}

// -------------------------------------------------------------- wallpaper ---

/// Where this desktop records the wallpaper. One line, one path, which is what
/// the session reads at startup and what the page's backdrop samples.
pub fn wallpaper_config() -> Result<PathBuf> {
    Ok(xdg_config_home()
        .ok_or_else(|| Error::NotFound("no config directory".into()))?
        .join("aurade/wallpaper"))
}

/// Where the wallpaper might be, most specific first: an explicit override in
/// the environment, then the session's own file. The override is what a test
/// harness and a kiosk configuration both use, and honouring it means the
/// backdrop can be pointed somewhere without editing the user's settings.
pub fn wallpaper() -> Result<Option<PathBuf>> {
    let mut candidates: Vec<String> = Vec::new();
    if let Ok(from_env) = std::env::var("AURADE_WALLPAPER") {
        if !from_env.trim().is_empty() {
            candidates.push(from_env.trim().to_string());
        }
    }
    if let Ok(text) = std::fs::read_to_string(wallpaper_config()?) {
        if let Some(line) = text.lines().next() {
            if !line.trim().is_empty() {
                candidates.push(line.trim().to_string());
            }
        }
    }
    for candidate in candidates {
        let path =
            crate::places::from_file_url(&candidate).unwrap_or_else(|| PathBuf::from(&candidate));
        if path.is_file() {
            return Ok(Some(path));
        }
    }
    Ok(None)
}

/// Set the desktop background.
pub fn set_wallpaper(path: &Path) -> Result<()> {
    if !path.is_file() {
        return Err(Error::NotFound(path.display().to_string()));
    }
    //: An image, checked by opening it rather than by trusting the name: a
    //: background that will not decode leaves the desktop blank with no
    //: explanation.
    image::ImageReader::open(path)
        .map_err(|e| Error::io(path.display().to_string(), e))?
        .with_guessed_format()
        .map_err(|e| Error::io(path.display().to_string(), e))?
        .into_dimensions()
        .map_err(|_| {
            Error::BadRequest(format!(
                "{} is not an image this desktop can show",
                path.display()
            ))
        })?;

    let config = wallpaper_config()?;
    if let Some(dir) = config.parent() {
        std::fs::create_dir_all(dir).map_err(|e| Error::io(dir.display().to_string(), e))?;
    }
    let tmp = config.with_extension(format!("tmp{}", std::process::id()));
    std::fs::write(&tmp, format!("{}\n", path.display()))
        .map_err(|e| Error::io(tmp.display().to_string(), e))?;
    std::fs::rename(&tmp, &config).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        Error::io(config.display().to_string(), e)
    })
}

/// A tiny blurred sample of the wallpaper, and the original's size.
///
/// This is the Mica backdrop: the window's surface picks up the colour of what
/// is behind it without ever showing it. Sixty four pixels wide, blurred, then
/// upscaled by CSS is indistinguishable from the full image and costs a few
/// kilobytes rather than a few megabytes. Deliberately unrecognisable: a
/// backdrop must not leak what the wallpaper actually is.
pub fn wallpaper_sample(width: u32) -> Result<(Vec<u8>, u32, u32)> {
    let path = wallpaper()?.ok_or_else(|| Error::NotFound("no wallpaper is set".into()))?;
    let image = image::ImageReader::open(&path)
        .map_err(|e| Error::io(path.display().to_string(), e))?
        .with_guessed_format()
        .map_err(|e| Error::io(path.display().to_string(), e))?
        .decode()
        .map_err(|e| Error::Unsupported(format!("{}: {e}", path.display())))?;
    let (w, h) = (image.width(), image.height());
    let width = width.max(1);
    let height = ((h as u64 * width as u64) / w.max(1) as u64).max(1) as u32;
    let small = image::imageops::thumbnail(&image.to_rgb8(), width, height);
    //: A light blur on the sample as well as in the page's own filter, so the
    //: upscale has nothing hard left in it to alias against.
    let blurred = image::imageops::blur(&small, 1.2);

    let mut out = std::io::Cursor::new(Vec::new());
    image::codecs::jpeg::JpegEncoder::new_with_quality(&mut out, 82)
        .encode(blurred.as_raw(), width, height, image::ExtendedColorType::Rgb8)
        .map_err(|e| Error::Tool { tool: "jpeg".into(), message: e.to_string() })?;
    Ok((out.into_inner(), w, h))
}

// ------------------------------------------------------------------ share ---

/// Hand a file to whatever the desktop uses for sharing. Files' Share opens
/// the Windows share sheet; the equivalent here is the desktop portal, and the
/// fallback is a mail composer, which is what the portal usually offers anyway.
pub fn share(paths: &[PathBuf]) -> Result<()> {
    if paths.is_empty() {
        return Err(Error::BadRequest("nothing to share".into()));
    }
    if crate::apps::which("xdg-email").is_some() {
        let mut argv = vec!["xdg-email".to_string()];
        for path in paths {
            argv.push("--attach".into());
            argv.push(path.display().to_string());
        }
        return crate::apps::spawn(&crate::apps::Launch::new(argv));
    }
    Err(Error::NotFound(
        "nothing on this system offers a way to share a file".into(),
    ))
}

// -------------------------------------------------- how to launch a thing ---

/// Files' Compatibility tab sets how a program should be started. The same
/// idea here is arguments and environment kept with the file, so a script or
/// an executable always runs the way it was set up to.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct LaunchOptions {
    pub args: Vec<String>,
    /// `NAME=value` pairs.
    pub env: Vec<String>,
    pub in_terminal: bool,
}

const LAUNCH_ATTR: &str = "user.aurade.launch";

pub fn launch_options(path: &Path) -> Result<LaunchOptions> {
    let Some(text) = crate::xattr::get_string(path, LAUNCH_ATTR)? else {
        return Ok(LaunchOptions::default());
    };
    Ok(parse_launch_options(&text))
}

fn parse_launch_options(text: &str) -> LaunchOptions {
    let mut out = LaunchOptions::default();
    for line in text.lines() {
        let line = line.trim();
        let Some((key, value)) = line.split_once('=') else { continue };
        match key {
            //: One argument per line. Quoting them onto a single line would
            //: mean agreeing on an escaping scheme with whatever reads it
            //: back, and an argument with a quote in it is exactly the case
            //: that would then go wrong.
            "arg" => out.args.push(value.to_string()),
            "env" => {
                if value.contains('=') {
                    out.env.push(value.to_string());
                }
            }
            "terminal" => out.in_terminal = value == "true",
            _ => {}
        }
    }
    out
}

pub fn set_launch_options(path: &Path, options: &LaunchOptions) -> Result<()> {
    if options == &LaunchOptions::default() {
        return crate::xattr::remove(path, LAUNCH_ATTR);
    }
    let mut text = String::new();
    for arg in &options.args {
        //: A newline inside an argument would be read back as two arguments,
        //: so it is refused rather than silently split.
        if arg.contains('\n') {
            return Err(Error::BadRequest("an argument cannot contain a newline".into()));
        }
        text.push_str(&format!("arg={arg}\n"));
    }
    for pair in &options.env {
        //: A pair without an equals sign is not an assignment, and putting it
        //: in the environment would be a silently ignored setting.
        if pair.contains('=') && !pair.contains('\n') {
            text.push_str(&format!("env={pair}\n"));
        }
    }
    if options.in_terminal {
        text.push_str("terminal=true\n");
    }
    crate::xattr::set(path, LAUNCH_ATTR, text.as_bytes())
}

/// Run an executable with whatever was set for it.
pub fn run_with_options(path: &Path) -> Result<()> {
    let options = launch_options(path)?;
    let mut argv = vec![path.display().to_string()];
    argv.extend(options.args.iter().cloned());
    //: The environment is deliberately not merged into this process's own:
    //: `spawn` starts a fresh child, and anything it needs has to be on that
    //: child's command line or in its own environment.
    for pair in &options.env {
        if let Some((name, value)) = pair.split_once('=') {
            unsafe { std::env::set_var(name, value) };
        }
    }
    crate::apps::spawn(&crate::apps::Launch {
        argv,
        cwd: path.parent().map(Path::to_path_buf),
        in_terminal: options.in_terminal,
        hold: options.in_terminal,
        ..Default::default()
    })
}

#[cfg(test)]
mod tests {
    #[test]
    fn what_gpg_printed_is_kept_whole_and_capped() {
        let spoken = "gpg: Signature made Wed\n\ngpg:  using EDDSA key AB   \ngpg: Good signature from \"Someone\" [ultimate]\n";
        let kept = gpg_detail(spoken);
        //: Every line, because gpg's verdict runs over several and the last
        //: one on its own is as often a fingerprint as it is the answer.
        assert_eq!(kept.lines().count(), 3, "{kept:?}");
        assert!(kept.starts_with("gpg: Signature made Wed"));
        assert!(kept.ends_with("[ultimate]"));
        //: Trailing space trimmed, blank lines dropped.
        assert!(!kept.contains("AB   "), "{kept:?}");
        assert!(!kept.contains("\n\n"), "{kept:?}");
        //: And it cannot grow without bound, because this goes into a JSON
        //: body and the size of a tool's output is the tool's business.
        let flood = "x".repeat(9000);
        assert_eq!(gpg_detail(&flood).len(), 4096);
        //: Cut on a character boundary, not in the middle of one.
        let wide = "é".repeat(9000);
        let cut = gpg_detail(&wide);
        assert!(cut.len() <= 4096 && cut.len() > 4090, "{}", cut.len());
        assert!(cut.chars().all(|c| c == 'é'));
    }

    #[test]
    fn only_a_file_with_something_to_check_is_handed_to_gpg() {
        let beside = std::path::PathBuf::from("/a/thing.iso.sig");
        //: A signature beside it is the reason to look.
        assert!(signable(Path::new("/a/thing.iso"), Some(&beside)));
        //: And so is the file being an OpenPGP file itself.
        assert!(signable(Path::new("/a/release.asc"), None));
        assert!(signable(Path::new("/a/RELEASE.GPG"), None));
        assert!(signable(Path::new("/a/x.signature"), None));
        //: An ordinary file is not unsigned, it is not a question, and reading
        //: four gigabytes of it to say so is the cost this avoids.
        assert!(!signable(Path::new("/a/thing.iso"), None));
        assert!(!signable(Path::new("/a/notes.txt"), None));
        assert_eq!(Signature::unsigned().status, SignatureStatus::NotSigned);
        assert!(Signature::unsigned().detail.is_empty());
    }

    use super::*;

    #[test]
    fn fc_scan_output_reads_and_a_missing_field_stays_missing() {
        let got = parse_fc_scan("Inter\nRegular\nInter Regular\n");
        assert_eq!(got.family.as_deref(), Some("Inter"));
        assert_eq!(got.style.as_deref(), Some("Regular"));
        assert_eq!(got.full_name.as_deref(), Some("Inter Regular"));

        let sparse = parse_fc_scan("Inter\n\n(null)\n");
        assert_eq!(sparse.family.as_deref(), Some("Inter"));
        assert_eq!(sparse.style, None);
        assert_eq!(sparse.full_name, None, "fontconfig's null was read as a name");
    }

    #[test]
    fn a_file_that_is_not_a_font_is_refused_before_anything_is_copied() {
        let dir = std::env::temp_dir().join("auradefs-system-font");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let not_a_font = dir.join("notes.txt");
        std::fs::write(&not_a_font, b"x").unwrap();
        let err = install_font(&not_a_font).unwrap_err();
        assert!(matches!(err, Error::BadRequest(_)), "got {err:?}");
    }

    #[test]
    fn certificate_trust_flags_are_the_ones_nss_expects() {
        assert_eq!(Trust::None.flags(), ",,");
        assert_eq!(Trust::Ca.flags(), "C,,");
    }

    #[test]
    fn something_that_is_not_a_certificate_is_recognised_as_such() {
        assert!(looks_like_certificate(b"-----BEGIN CERTIFICATE-----\nMIIB"));
        //: DER, a sequence with a two byte length.
        assert!(looks_like_certificate(&[0x30, 0x82, 0x03, 0x00]));
        assert!(!looks_like_certificate(b"-----BEGIN PRIVATE KEY-----"));
        assert!(!looks_like_certificate(b"just some text"));
        assert!(!looks_like_certificate(&[0x30, 0x10]), "a short sequence is not one");
        assert!(!looks_like_certificate(b""));
    }

    #[test]
    fn the_certificate_list_splits_from_the_right_so_a_name_can_have_spaces() {
        let text = concat!(
            "\n",
            "Certificate Nickname                                         Trust Attributes\n",
            "                                                             SSL,S/MIME,JAR/XPI\n",
            "\n",
            "My Company Root CA                                           C,,\n",
            "Another Cert                                                 ,,\n",
            "a line whose last field has no comma\n",
        );
        let got = parse_certutil_list(text);
        //: The two real entries. The column legend and the trailing prose are
        //: both rejected, each by a different half of the check.
        assert_eq!(got.len(), 2, "{got:?}");
        assert_eq!(got[0], Certificate { nickname: "My Company Root CA".into(), trust: "C,,".into() });
        assert_eq!(got[1].trust, ",,");
    }

    #[test]
    fn a_good_signature_from_an_unknown_key_is_not_reported_as_trusted() {
        let status = concat!(
            "[GNUPG:] NEWSIG\n",
            "[GNUPG:] GOODSIG A1B2C3D4E5F60708 Some Signer <signer@example.invalid>\n",
            "[GNUPG:] VALIDSIG AAAA 2026-01-01\n",
            "[GNUPG:] TRUST_UNDEFINED 0 pgp\n",
        );
        let got = parse_gpg_status(status, "gpg: Good signature from \"Some Signer\"\n");
        assert_eq!(got.status, SignatureStatus::GoodButUntrusted);
        assert_eq!(got.key_id.as_deref(), Some("A1B2C3D4E5F60708"));
        assert_eq!(got.signer.as_deref(), Some("Some Signer <signer@example.invalid>"));
    }

    #[test]
    fn a_signature_from_a_key_the_user_vouched_for_is_trusted() {
        let status = concat!(
            "[GNUPG:] GOODSIG A1B2 Signer\n",
            "[GNUPG:] TRUST_ULTIMATE 0 pgp\n",
        );
        assert_eq!(
            parse_gpg_status(status, "").status,
            SignatureStatus::GoodAndTrusted
        );
    }

    #[test]
    fn every_other_conclusion_gpg_can_reach_is_told_apart() {
        let case = |line: &str| parse_gpg_status(line, "").status;
        assert_eq!(case("[GNUPG:] BADSIG A1B2 Signer\n"), SignatureStatus::Bad);
        assert_eq!(case("[GNUPG:] NO_PUBKEY A1B2\n"), SignatureStatus::KeyMissing);
        assert_eq!(case("[GNUPG:] EXPKEYSIG A1B2 Signer\n"), SignatureStatus::KeyExpiredOrRevoked);
        assert_eq!(case("[GNUPG:] REVKEYSIG A1B2 Signer\n"), SignatureStatus::KeyExpiredOrRevoked);
        assert_eq!(case(""), SignatureStatus::NotSigned);
        //: A bad signature wins over everything, including a trust line that
        //: happens to be in the same output for another signature.
        assert_eq!(
            case("[GNUPG:] GOODSIG A1 X\n[GNUPG:] TRUST_ULTIMATE\n[GNUPG:] BADSIG A2 Y\n"),
            SignatureStatus::Bad
        );
    }

    #[test]
    fn a_status_line_is_only_read_when_it_is_one() {
        //: The signed file's own contents are on the same stream in some
        //: modes, and a line inside it that looks like a keyword must not be
        //: read as one.
        let got = parse_gpg_status("GOODSIG A1B2 Not really\nBADSIG oops\n", "");
        assert_eq!(got.status, SignatureStatus::NotSigned);
        assert_eq!(got.key_id, None);
    }

    #[test]
    fn a_signature_file_is_found_beside_the_download() {
        let dir = std::env::temp_dir().join("auradefs-system-sig");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let file = dir.join("release.tar.gz");
        std::fs::write(&file, b"x").unwrap();
        assert_eq!(signature_beside(&file), None);
        std::fs::write(dir.join("release.tar.gz.asc"), b"sig").unwrap();
        assert_eq!(signature_beside(&file), Some(dir.join("release.tar.gz.asc")));
    }

    #[test]
    fn launch_options_round_trip_through_their_stored_form() {
        let parsed = parse_launch_options("arg=--flag\narg=two words\nenv=LANG=C\nterminal=true\n");
        assert_eq!(parsed.args, ["--flag", "two words"]);
        assert_eq!(parsed.env, ["LANG=C"]);
        assert!(parsed.in_terminal);

        //: A line that is not an assignment is not an environment entry.
        let bad = parse_launch_options("env=JUSTNAME\narg=x\n");
        assert!(bad.env.is_empty());
        assert_eq!(bad.args, ["x"]);

        //: An argument with a quote or an equals sign in it survives, which is
        //: the case a single quoted line would have got wrong.
        let awkward = parse_launch_options("arg=--title=it's \"quoted\"\n");
        assert_eq!(awkward.args, [r#"--title=it's "quoted""#]);
    }

    #[test]
    fn launch_options_survive_the_trip_through_the_file() {
        let dir = std::env::temp_dir().join("auradefs-system-launch");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let script = dir.join("run.sh");
        std::fs::write(&script, b"#!/bin/sh\n").unwrap();
        if crate::xattr::set(&script, "user.auradefs.probe", b"1").is_err() {
            eprintln!("skipped: no extended attributes here");
            return;
        }

        let options = LaunchOptions {
            args: vec!["--title=it's \"quoted\"".into(), "two words".into()],
            env: vec!["LANG=C".into()],
            in_terminal: true,
        };
        set_launch_options(&script, &options).unwrap();
        assert_eq!(launch_options(&script).unwrap(), options);

        //: A newline would be read back as an extra argument, so it never gets
        //: written.
        let bad = LaunchOptions { args: vec!["one\ntwo".into()], ..Default::default() };
        assert!(set_launch_options(&script, &bad).is_err());

        set_launch_options(&script, &LaunchOptions::default()).unwrap();
        assert_eq!(launch_options(&script).unwrap(), LaunchOptions::default());
        assert!(!crate::xattr::list(&script).unwrap().iter().any(|k| k == LAUNCH_ATTR));
    }

    #[test]
    fn the_wallpaper_setting_refuses_something_that_is_not_an_image() {
        let dir = std::env::temp_dir().join("auradefs-system-wall");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let not_an_image = dir.join("notes.txt");
        std::fs::write(&not_an_image, b"definitely not a picture").unwrap();
        let err = set_wallpaper(&not_an_image).unwrap_err();
        assert!(matches!(err, Error::BadRequest(_)), "got {err:?}");
        assert!(set_wallpaper(&dir.join("missing.png")).is_err());
    }

    #[test]
    fn the_backdrop_sample_is_small_and_keeps_the_proportions() {
        let base = std::env::temp_dir().join("auradefs-system-sample");
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(&base).unwrap();
        let picture = base.join("bg.png");
        let mut img = image::RgbaImage::new(400, 200);
        for (x, y, p) in img.enumerate_pixels_mut() {
            *p = image::Rgba([(x % 256) as u8, (y % 256) as u8, 90, 255]);
        }
        img.save(&picture).unwrap();
        unsafe { std::env::set_var("XDG_CONFIG_HOME", base.join("config")) };
        set_wallpaper(&picture).unwrap();

        let (bytes, w, h) = wallpaper_sample(64).unwrap();
        assert_eq!((w, h), (400, 200), "the original size is what the page scales from");
        //: A few kilobytes at most. The whole point is that it is not the
        //: image.
        assert!(bytes.len() < 8 * 1024, "the sample was {} bytes", bytes.len());
        let decoded = image::load_from_memory(&bytes).unwrap();
        assert_eq!((decoded.width(), decoded.height()), (64, 32));
    }

    #[test]
    fn setting_and_reading_the_wallpaper_uses_the_sessions_own_file() {
        let base = std::env::temp_dir().join("auradefs-system-wall-set");
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(&base).unwrap();
        let picture = base.join("bg.png");
        image::RgbaImage::from_pixel(4, 4, image::Rgba([1, 2, 3, 255]))
            .save(&picture)
            .unwrap();
        unsafe {
            std::env::set_var("XDG_CONFIG_HOME", base.join("config"));
            std::env::remove_var("AURADE_WALLPAPER");
        }
        set_wallpaper(&picture).unwrap();
        assert_eq!(
            std::fs::read_to_string(wallpaper_config().unwrap()).unwrap(),
            format!("{}\n", picture.display())
        );
        assert_eq!(wallpaper().unwrap(), Some(picture.clone()));

        //: An override in the environment wins over the session's own file.
        let other = base.join("other.png");
        image::RgbaImage::from_pixel(4, 4, image::Rgba([9, 9, 9, 255])).save(&other).unwrap();
        unsafe { std::env::set_var("AURADE_WALLPAPER", &other) };
        assert_eq!(wallpaper().unwrap(), Some(other));
        //: And an override that points at nothing falls back rather than
        //: leaving the desktop with no wallpaper at all.
        unsafe { std::env::set_var("AURADE_WALLPAPER", base.join("missing.png")) };
        assert_eq!(wallpaper().unwrap(), Some(picture));
        unsafe { std::env::remove_var("AURADE_WALLPAPER") };
    }
}
