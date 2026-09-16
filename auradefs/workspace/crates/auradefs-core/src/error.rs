//! One error type for the whole service.

use std::io;

/// What went wrong, in terms the UI can act on.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// The path does not exist.
    #[error("not found: {0}")]
    NotFound(String),

    /// The path exists but the caller may not do this to it.
    #[error("permission denied: {0}")]
    Denied(String),

    /// The path exists and something is already there.
    #[error("already exists: {0}")]
    Exists(String),

    /// The path left the root it was resolved against. This is a refusal, not
    /// a failure: it means a `..` or a symlink tried to escape.
    #[error("path escapes its root: {0}")]
    Escapes(String),

    /// The volume will not take writes.
    #[error("read only: {0}")]
    ReadOnly(String),

    /// The request itself was malformed.
    #[error("bad request: {0}")]
    BadRequest(String),

    /// Something below us failed and kept its errno.
    #[error("{context}: {source}")]
    Io {
        context: String,
        #[source]
        source: io::Error,
    },

    /// The current state of the thing refuses this. A checkout that would
    /// overwrite uncommitted work, or a branch that is not there: both are the
    /// repository saying no rather than a fault in the request.
    #[error("refused: {0}")]
    Conflict(String),

    /// The filesystem cannot do this. A FAT formatted stick has no extended
    /// attributes and no permissions worth setting, and the UI should say so
    /// rather than report a failure the user could act on.
    #[error("not supported here: {0}")]
    Unsupported(String),

    /// A helper process failed. Carries what it said on stderr, trimmed to a
    /// line, because that line is usually the only useful thing.
    #[error("{tool}: {message}")]
    Tool { tool: String, message: String },

    /// The archive is encrypted and no password was given, or the one given
    /// was wrong. Not a denial by the filesystem: what the caller should do
    /// about it is ask for a password and try again, which is a different
    /// thing for the UI to do than either of those.
    #[error("a password is needed: {0}")]
    NeedsPassword(String),
}

impl Error {
    /// Attach a human context to an [`io::Error`], mapping the kinds the UI
    /// treats specially so callers do not have to re-derive them.
    pub fn io(context: impl Into<String>, source: io::Error) -> Self {
        let context = context.into();
        match source.kind() {
            io::ErrorKind::NotFound => Error::NotFound(context),
            io::ErrorKind::PermissionDenied => Error::Denied(context),
            io::ErrorKind::AlreadyExists => Error::Exists(context),
            _ => Error::Io { context, source },
        }
    }

    /// There is not enough room at the destination. Raised before the copy
    /// starts rather than halfway through it, because a half copied tree is
    /// worse than a refusal.
    pub fn no_space(context: impl Into<String>) -> Self {
        Error::Io {
            context: context.into(),
            source: io::Error::from_raw_os_error(28),
        }
    }

    /// The errno, when there is one. The UI distinguishes ENOSPC from EROFS
    /// from EACCES, so the number has to survive the trip.
    pub fn errno(&self) -> Option<i32> {
        match self {
            Error::Io { source, .. } => source.raw_os_error(),
            Error::NotFound(_) => Some(libc_enoent()),
            Error::Denied(_) => Some(libc_eacces()),
            Error::Exists(_) => Some(libc_eexist()),
            Error::ReadOnly(_) => Some(libc_erofs()),
            Error::Unsupported(_) => Some(libc_enotsup()),
            _ => None,
        }
    }

    /// A stable string for the wire, so the page can branch without parsing
    /// prose.
    pub fn code(&self) -> &'static str {
        match self {
            Error::NotFound(_) => "not-found",
            Error::Denied(_) => "denied",
            Error::Exists(_) => "exists",
            Error::Escapes(_) => "escapes-root",
            Error::ReadOnly(_) => "read-only",
            Error::BadRequest(_) => "bad-request",
            Error::Conflict(_) => "conflict",
            Error::Unsupported(_) => "unsupported",
            Error::Io { .. } => "io",
            Error::Tool { .. } => "tool",
            Error::NeedsPassword(_) => "needs-password",
        }
    }
}

const fn libc_enoent() -> i32 { 2 }
const fn libc_eacces() -> i32 { 13 }
const fn libc_eexist() -> i32 { 17 }
const fn libc_erofs() -> i32 { 30 }
const fn libc_enotsup() -> i32 { 95 }

pub type Result<T> = std::result::Result<T, Error>;
