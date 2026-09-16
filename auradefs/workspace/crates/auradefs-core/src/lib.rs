//! The AuraDE file service, without any transport attached.
//!
//! Everything a file manager needs to *do* lives here as a plain library:
//! listing, copying, trashing, archives, tags, git. Nothing in this crate
//! knows about D-Bus, HTTP or JSON, which is what lets the shipped daemon and
//! the development shim be the same code rather than two implementations that
//! drift.
//!
//! Two rules hold throughout:
//!
//! 1. **A path is resolved once.** Operations take a [`Root`] and a relative
//!    path and do their work through directory file descriptors, so a symlink
//!    swapped between the check and the write cannot move the target. The
//!    prototype's Python backend resolved with `os.path.abspath` and then
//!    opened by name, which is a race with a person as the attacker.
//! 2. **A refusal carries its reason.** [`Error`] keeps the errno so a caller
//!    can tell "no such file" from "permission denied" from "read only
//!    volume", because the UI says a different thing for each.

pub mod error;
pub mod root;
pub mod mime;
pub mod apps;
pub mod xattr;
pub mod tags;
pub mod git;
pub mod volumes;
pub mod props;
pub mod places;
pub mod thumbs;
pub mod media;
pub mod cover;
pub mod system;
pub mod ops;

pub use error::{Error, Result};
pub use root::Root;
