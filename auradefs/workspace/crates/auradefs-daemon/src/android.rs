//! Android apps as Open with choices. The AuraDE Android service
//! (org.aurade.Android1) knows which installed apps can view a type and can
//! hand a file to one; this asks it over the system bus with busctl, which is
//! on every system that runs the service, so the daemon needs no D-Bus library.

use std::path::Path;
use std::process::{Command, Stdio};

use auradefs_core::error::{Error, Result};
use serde_json::Value;

const SERVICE: &str = "org.aurade.Android1";
const PATH: &str = "/org/aurade/Android1";

fn busctl(args: &[&str], seconds: &str) -> Option<std::process::Output> {
    Command::new("timeout")
        .arg(seconds)
        .args(["busctl", "--system", "--json=short", "call", SERVICE, PATH, SERVICE])
        .args(args)
        .stdin(Stdio::null())
        .output()
        .ok()
}

/// The prefix that marks an Open with entry as an Android app.
pub const PREFIX: &str = "android:";

/// (package, label) of the Android apps that can open this type. Empty when
/// the service is not there or Android is off.
pub fn handlers_for(mime: &str) -> Vec<(String, String)> {
    let Some(out) = busctl(&["HandlersFor", "s", mime], "8") else { return Vec::new() };
    if !out.status.success() {
        return Vec::new();
    }
    let Ok(value) = serde_json::from_slice::<Value>(&out.stdout) else { return Vec::new() };
    value["data"][0]
        .as_array()
        .map(|rows| {
            rows.iter()
                .filter_map(|row| {
                    Some((row[0].as_str()?.to_string(), row[1].as_str()?.to_string()))
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Opens a file in an Android app.
pub fn open(package: &str, path: &Path) -> Result<()> {
    let path = path.to_string_lossy();
    let out = busctl(&["OpenFile", "ss", package, &path], "40")
        .ok_or_else(|| Error::NotFound("the Android service".into()))?;
    if out.status.success() {
        Ok(())
    } else {
        Err(Error::BadRequest(
            String::from_utf8_lossy(&out.stderr).trim().to_string(),
        ))
    }
}
