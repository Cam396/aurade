//! Drives, partitions and how much room is left on them.
//!
//! The sidebar has to show what is plugged in, whether it is mounted, and how
//! full it is, and the toolbar has to be able to mount, unmount and eject.
//!
//! Two sources, each for what it is actually good at. `lsblk` knows the
//! topology, the labels and the filesystem types, because it reads libblkid
//! and udev; reimplementing that would mean reading superblock magic numbers
//! from raw devices, which needs privileges a desktop session does not have.
//! `/proc/self/mountinfo` knows what is mounted right now and with which
//! options, which lsblk reports less precisely.
//!
//! Actions go through `udisksctl`, so mounting a stick asks polkit rather than
//! asking for root. Unlocking an encrypted volume is deliberately **not** here:
//! a passphrase must not travel as a command line argument where every process
//! on the system can read it, so that one belongs to the daemon and its D-Bus
//! connection.

use std::path::{Path, PathBuf};
use std::process::Command;

use crate::error::{Error, Result};

/// One line of `/proc/self/mountinfo`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Mount {
    pub source: String,
    pub mount_point: PathBuf,
    pub fstype: String,
    pub options: Vec<String>,
    pub read_only: bool,
}

/// Everything mounted, in the order the kernel lists it, which is mount order.
pub fn mounts() -> Result<Vec<Mount>> {
    let text = std::fs::read_to_string("/proc/self/mountinfo")
        .map_err(|e| Error::io("/proc/self/mountinfo", e))?;
    Ok(parse_mountinfo(&text))
}

/// The mount a path is on: the longest mount point that is a prefix of it.
pub fn mount_for(path: &Path) -> Result<Option<Mount>> {
    let mut best: Option<Mount> = None;
    for mount in mounts()? {
        if !path.starts_with(&mount.mount_point) {
            continue;
        }
        let better = best
            .as_ref()
            .map(|b| mount.mount_point.as_os_str().len() > b.mount_point.as_os_str().len())
            .unwrap_or(true);
        if better {
            best = Some(mount);
        }
    }
    Ok(best)
}

fn parse_mountinfo(text: &str) -> Vec<Mount> {
    let mut out = Vec::new();
    for line in text.lines() {
        //: The format is: id parent major:minor root mountpoint options
        //: optional-fields... - fstype source super-options. The optional
        //: fields are variable in number and end at a lone dash, which is the
        //: only reliable way to find the second half.
        let Some((left, right)) = line.split_once(" - ") else { continue };
        let left: Vec<&str> = left.split(' ').collect();
        let right: Vec<&str> = right.split(' ').collect();
        if left.len() < 6 || right.len() < 2 {
            continue;
        }
        let options: Vec<String> = left[5].split(',').map(str::to_string).collect();
        let super_options: Vec<String> = right
            .get(2)
            .map(|o| o.split(',').map(str::to_string).collect())
            .unwrap_or_default();
        out.push(Mount {
            mount_point: PathBuf::from(unescape_octal(left[4])),
            read_only: options.iter().any(|o| o == "ro") || super_options.iter().any(|o| o == "ro"),
            options,
            fstype: unescape_octal(right[0]),
            source: unescape_octal(right[1]),
        });
    }
    out
}

/// The kernel escapes space, tab, newline and backslash in these fields as
/// three digit octal. A mount point with a space in it is common on removable
/// media, so this is not a corner case.
fn unescape_octal(value: &str) -> String {
    if !value.contains('\\') {
        return value.to_string();
    }
    let bytes = value.as_bytes();
    let mut out = String::with_capacity(value.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'\\' && i + 3 < bytes.len() {
            let digits = &value[i + 1..i + 4];
            if let Ok(n) = u8::from_str_radix(digits, 8) {
                out.push(n as char);
                i += 4;
                continue;
            }
        }
        out.push(bytes[i] as char);
        i += 1;
    }
    out
}

/// How full a filesystem is.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Usage {
    pub total: u64,
    /// Free including the reserve only root may use.
    pub free: u64,
    /// Free to this user, which is the number the bar should draw.
    pub available: u64,
}

impl Usage {
    pub fn used(&self) -> u64 {
        self.total.saturating_sub(self.free)
    }

    /// Zero to one, using the space a normal user can actually reach.
    pub fn fraction_used(&self) -> f64 {
        let reachable = self.used() + self.available;
        if reachable == 0 {
            return 0.0;
        }
        self.used() as f64 / reachable as f64
    }
}

pub fn usage(path: &Path) -> Result<Usage> {
    let vfs = rustix::fs::statvfs(path).map_err(|e| {
        Error::io(path.display().to_string(), std::io::Error::from_raw_os_error(e.raw_os_error()))
    })?;
    let block = if vfs.f_frsize > 0 { vfs.f_frsize } else { vfs.f_bsize };
    Ok(Usage {
        total: vfs.f_blocks * block,
        free: vfs.f_bfree * block,
        available: vfs.f_bavail * block,
    })
}

/// A row in the sidebar's This PC section.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Volume {
    /// The device node, which is also the id every action takes.
    pub path: PathBuf,
    pub name: String,
    pub label: Option<String>,
    pub uuid: Option<String>,
    pub fstype: Option<String>,
    pub model: Option<String>,
    pub size: u64,
    pub mount_point: Option<PathBuf>,
    pub removable: bool,
    pub read_only: bool,
    pub optical: bool,
    /// A LUKS container. Locked until something unlocks it, and then it holds
    /// a mapped device rather than a filesystem.
    pub encrypted: bool,
    pub locked: bool,
    /// The root filesystem or one of the mounts the system needs. Ejecting one
    /// of these is not something to offer.
    pub system: bool,
    pub usage: Option<Usage>,
}

/// Everything worth showing in the sidebar.
pub fn volumes() -> Result<Vec<Volume>> {
    let output = Command::new("lsblk")
        .args([
            "--json",
            "--bytes",
            "--paths",
            "--output",
            "NAME,PATH,TYPE,FSTYPE,LABEL,UUID,SIZE,MOUNTPOINT,RM,RO,MODEL",
        ])
        .output()
        .map_err(|e| Error::io("running lsblk", e))?;
    if !output.status.success() {
        return Err(Error::Tool {
            tool: "lsblk".into(),
            message: String::from_utf8_lossy(&output.stderr).lines().next().unwrap_or("failed").into(),
        });
    }
    let mounts = mounts()?;
    Ok(parse_lsblk(&output.stdout, &mounts))
}

fn parse_lsblk(json: &[u8], mounts: &[Mount]) -> Vec<Volume> {
    let Ok(root) = serde_json::from_slice::<serde_json::Value>(json) else { return Vec::new() };
    let mut out = Vec::new();
    if let Some(devices) = root.get("blockdevices").and_then(|d| d.as_array()) {
        for device in devices {
            walk_lsblk(device, false, mounts, &mut out);
        }
    }
    out
}

fn walk_lsblk(
    node: &serde_json::Value,
    parent_removable: bool,
    mounts: &[Mount],
    out: &mut Vec<Volume>,
) {
    let kind = node.get("type").and_then(|v| v.as_str()).unwrap_or("");
    let removable = parent_removable || node.get("rm").and_then(as_bool).unwrap_or(false);
    let fstype = node.get("fstype").and_then(|v| v.as_str()).map(str::to_string);

    //: A whole disk is only worth a row when it holds a filesystem directly,
    //: which is rare but happens on formatted sticks. Otherwise its partitions
    //: are the rows.
    let interesting = matches!(kind, "part" | "crypt" | "lvm" | "rom")
        || (kind == "disk" && fstype.is_some());

    if interesting {
        let path = PathBuf::from(node.get("path").and_then(|v| v.as_str()).unwrap_or_default());
        let mount_point = node
            .get("mountpoint")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(PathBuf::from);
        let label = node.get("label").and_then(|v| v.as_str()).filter(|s| !s.is_empty()).map(str::to_string);
        let encrypted = fstype.as_deref() == Some("crypto_LUKS");
        //: A LUKS partition with no children is still locked. Once unlocked
        //: udisks maps it and the mapping shows up as a child of type crypt.
        let locked = encrypted && node.get("children").and_then(|c| c.as_array()).map(|c| c.is_empty()).unwrap_or(true);
        let mount = mount_point.as_ref().and_then(|mp| mounts.iter().find(|m| &m.mount_point == mp));

        let name = label
            .clone()
            .or_else(|| node.get("model").and_then(|v| v.as_str()).map(|m| m.trim().to_string()).filter(|m| !m.is_empty()))
            .unwrap_or_else(|| {
                path.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default()
            });

        out.push(Volume {
            usage: mount_point.as_ref().and_then(|mp| usage(mp).ok()),
            system: mount_point
                .as_deref()
                .map(is_system_mount)
                .unwrap_or(false),
            read_only: node.get("ro").and_then(as_bool).unwrap_or(false)
                || mount.map(|m| m.read_only).unwrap_or(false),
            optical: kind == "rom",
            model: node.get("model").and_then(|v| v.as_str()).map(|m| m.trim().to_string()).filter(|m| !m.is_empty()),
            uuid: node.get("uuid").and_then(|v| v.as_str()).filter(|s| !s.is_empty()).map(str::to_string),
            size: node.get("size").and_then(|v| v.as_u64()).unwrap_or(0),
            path,
            name,
            label,
            fstype,
            mount_point,
            removable,
            encrypted,
            locked,
        });
    }

    if let Some(children) = node.get("children").and_then(|c| c.as_array()) {
        for child in children {
            walk_lsblk(child, removable, mounts, out);
        }
    }
}

/// lsblk writes booleans as real booleans in newer versions and as the strings
/// "0" and "1" in older ones.
fn as_bool(value: &serde_json::Value) -> Option<bool> {
    match value {
        serde_json::Value::Bool(b) => Some(*b),
        serde_json::Value::Number(n) => Some(n.as_u64().unwrap_or(0) != 0),
        serde_json::Value::String(s) => Some(s == "1" || s == "true"),
        _ => None,
    }
}

/// Mount points the session depends on. Offering Eject on the root filesystem
/// is the kind of thing that gets a file manager blamed for a lost afternoon.
pub fn is_system_mount(mount_point: &Path) -> bool {
    matches!(
        mount_point.to_string_lossy().as_ref(),
        "/" | "/boot" | "/boot/efi" | "/efi" | "/home" | "/var" | "/usr" | "/nix" | "/etc"
    )
}

// ---------------------------------------------------------------- actions ---

fn udisksctl(args: &[&str]) -> Result<String> {
    let output = Command::new("udisksctl")
        .args(args)
        .output()
        .map_err(|e| match e.kind() {
            std::io::ErrorKind::NotFound => {
                Error::NotFound("udisks2 is not installed, so drives cannot be mounted".into())
            }
            _ => Error::io("running udisksctl", e),
        })?;
    if output.status.success() {
        return Ok(String::from_utf8_lossy(&output.stdout).trim().to_string());
    }
    let message = String::from_utf8_lossy(&output.stderr);
    let line = message.lines().last().unwrap_or("failed").trim().to_string();
    //: polkit's refusal is a decision, not a fault, and the UI says something
    //: different for it.
    if line.contains("Not authorized") || line.contains("NotAuthorized") {
        return Err(Error::Denied(line));
    }
    Err(Error::Tool { tool: "udisksctl".into(), message: line })
}

/// Mount a device, returning where it landed.
pub fn mount(device: &Path) -> Result<PathBuf> {
    let out = udisksctl(&["mount", "-b", &device.display().to_string()])?;
    //: "Mounted /dev/sdb1 at /run/media/cam/STICK"
    let at = out.rsplit_once(" at ").map(|(_, p)| p.trim().trim_end_matches('.').to_string());
    match at {
        Some(p) if !p.is_empty() => Ok(PathBuf::from(p)),
        //: It mounted but said so in a form this does not recognise, so ask
        //: the kernel rather than guessing.
        _ => mounts()?
            .into_iter()
            .find(|m| Path::new(&m.source) == device)
            .map(|m| m.mount_point)
            .ok_or_else(|| Error::Tool { tool: "udisksctl".into(), message: out }),
    }
}

pub fn unmount(device: &Path) -> Result<()> {
    udisksctl(&["unmount", "-b", &device.display().to_string()]).map(|_| ())
}

/// Unmount and then power the drive down, which is what Eject means for a
/// stick. For optical media it is the tray.
pub fn eject(device: &Path) -> Result<()> {
    let name = device.display().to_string();
    //: Unmounting first is not optional: powering off a mounted drive loses
    //: whatever is still in the page cache. An already unmounted drive makes
    //: this a no-op, so its failure is not fatal.
    let _ = udisksctl(&["unmount", "-b", &name]);
    udisksctl(&["power-off", "-b", &name]).map(|_| ())
}

#[cfg(test)]
mod tests {
    use super::*;

    const MOUNTINFO: &str = concat!(
        "23 28 0:21 / /proc rw,nosuid,nodev,noexec,relatime shared:12 - proc proc rw\n",
        "28 1 254:1 / / rw,relatime shared:1 - btrfs /dev/sda2 rw,ssd,subvol=/@\n",
        "50 28 8:17 / /run/media/cam/MY\\040STICK rw,nosuid,nodev,relatime shared:40 - vfat /dev/sdb1 rw,uid=1000\n",
        "61 28 0:44 / /mnt/ro ro,relatime shared:50 - ext4 /dev/sdc1 ro\n",
    );

    #[test]
    fn mountinfo_is_split_at_the_dash_and_not_by_counting() {
        let got = parse_mountinfo(MOUNTINFO);
        assert_eq!(got.len(), 4);
        assert_eq!(got[1].mount_point, Path::new("/"));
        assert_eq!(got[1].fstype, "btrfs");
        assert_eq!(got[1].source, "/dev/sda2");
        assert!(!got[1].read_only);
    }

    #[test]
    fn a_mount_point_with_a_space_in_it_comes_back_with_the_space() {
        let got = parse_mountinfo(MOUNTINFO);
        assert_eq!(got[2].mount_point, Path::new("/run/media/cam/MY STICK"));
        assert_eq!(got[2].fstype, "vfat");
    }

    #[test]
    fn read_only_is_seen_from_either_half_of_the_line() {
        let got = parse_mountinfo(MOUNTINFO);
        assert!(got[3].read_only, "a ro filesystem was reported writable");
        //: The per mount options are the first half; the super options are the
        //: second. A mount can be ro in one and not the other.
        let only_super = parse_mountinfo(
            "1 2 0:1 / /x rw,relatime shared:1 - ext4 /dev/x ro\n",
        );
        assert!(only_super[0].read_only);
    }

    #[test]
    fn the_longest_matching_mount_point_wins() {
        let text = concat!(
            "1 2 0:1 / / rw - btrfs /dev/sda2 rw\n",
            "2 1 0:2 / /home rw - ext4 /dev/sda3 rw\n",
            "3 1 0:3 / /home/cam/data rw - xfs /dev/sdb1 rw\n",
        );
        let mounts = parse_mountinfo(text);
        let pick = |p: &str| {
            let path = Path::new(p);
            mounts
                .iter()
                .filter(|m| path.starts_with(&m.mount_point))
                .max_by_key(|m| m.mount_point.as_os_str().len())
                .unwrap()
                .mount_point
                .clone()
        };
        assert_eq!(pick("/home/cam/data/file"), Path::new("/home/cam/data"));
        assert_eq!(pick("/home/cam/other"), Path::new("/home"));
        assert_eq!(pick("/etc/passwd"), Path::new("/"));
    }

    const LSBLK: &str = r#"{
      "blockdevices": [
        {"name":"sda","path":"/dev/sda","type":"disk","fstype":null,"label":null,"uuid":null,
         "size":512110190592,"mountpoint":null,"rm":false,"ro":false,"model":"Samsung SSD",
         "children":[
           {"name":"sda1","path":"/dev/sda1","type":"part","fstype":"vfat","label":"ESP","uuid":"1234",
            "size":536870912,"mountpoint":"/boot","rm":false,"ro":false,"model":null},
           {"name":"sda2","path":"/dev/sda2","type":"part","fstype":"crypto_LUKS","label":null,"uuid":"abcd",
            "size":511573319680,"mountpoint":null,"rm":false,"ro":false,"model":null,
            "children":[
              {"name":"cryptroot","path":"/dev/mapper/cryptroot","type":"crypt","fstype":"btrfs",
               "label":"aurade","uuid":"beef","size":511573319680,"mountpoint":"/","rm":false,"ro":false,"model":null}
            ]}
         ]},
        {"name":"sdb","path":"/dev/sdb","type":"disk","fstype":null,"label":null,"uuid":null,
         "size":15728640000,"mountpoint":null,"rm":"1","ro":false,"model":"USB DISK ",
         "children":[
           {"name":"sdb1","path":"/dev/sdb1","type":"part","fstype":"vfat","label":"MY STICK","uuid":"5678",
            "size":15728640000,"mountpoint":"/run/media/cam/MY STICK","rm":false,"ro":false,"model":null}
         ]},
        {"name":"sr0","path":"/dev/sr0","type":"rom","fstype":"iso9660","label":"AURADE","uuid":null,
         "size":1073741824,"mountpoint":null,"rm":true,"ro":true,"model":"DVD-RW"}
      ]}"#;

    #[test]
    fn partitions_become_rows_and_the_disks_holding_them_do_not() {
        let got = parse_lsblk(LSBLK.as_bytes(), &[]);
        let paths: Vec<String> = got.iter().map(|v| v.path.display().to_string()).collect();
        assert_eq!(
            paths,
            [
                "/dev/sda1",
                "/dev/sda2",
                "/dev/mapper/cryptroot",
                "/dev/sdb1",
                "/dev/sr0"
            ],
            "a whole disk with no filesystem became a row"
        );
    }

    #[test]
    fn removable_is_inherited_from_the_disk_the_partition_is_on() {
        let got = parse_lsblk(LSBLK.as_bytes(), &[]);
        let stick = got.iter().find(|v| v.path == Path::new("/dev/sdb1")).unwrap();
        //: The partition's own rm flag is false; only the disk is marked, and
        //: a stick's partition is still on a stick.
        assert!(stick.removable);
        let esp = got.iter().find(|v| v.path == Path::new("/dev/sda1")).unwrap();
        assert!(!esp.removable);
    }

    #[test]
    fn a_locked_luks_partition_is_told_apart_from_an_unlocked_one() {
        let got = parse_lsblk(LSBLK.as_bytes(), &[]);
        let luks = got.iter().find(|v| v.path == Path::new("/dev/sda2")).unwrap();
        assert!(luks.encrypted);
        assert!(!luks.locked, "it has a mapping, so it is open");

        let locked_json = LSBLK.replace(
            r#""model":null,
            "children":[
              {"name":"cryptroot","path":"/dev/mapper/cryptroot","type":"crypt","fstype":"btrfs",
               "label":"aurade","uuid":"beef","size":511573319680,"mountpoint":"/","rm":false,"ro":false,"model":null}
            ]}"#,
            r#""model":null}"#,
        );
        let got = parse_lsblk(locked_json.as_bytes(), &[]);
        let luks = got.iter().find(|v| v.path == Path::new("/dev/sda2")).unwrap();
        assert!(luks.locked, "a LUKS partition with no mapping is locked");
    }

    #[test]
    fn a_system_mount_is_marked_so_eject_is_not_offered_for_it() {
        let got = parse_lsblk(LSBLK.as_bytes(), &[]);
        assert!(got.iter().find(|v| v.mount_point.as_deref() == Some(Path::new("/"))).unwrap().system);
        assert!(got.iter().find(|v| v.path == Path::new("/dev/sda1")).unwrap().system, "/boot");
        assert!(!got.iter().find(|v| v.path == Path::new("/dev/sdb1")).unwrap().system);
    }

    #[test]
    fn a_row_is_named_by_its_label_then_its_model_then_its_device() {
        let got = parse_lsblk(LSBLK.as_bytes(), &[]);
        assert_eq!(got.iter().find(|v| v.path == Path::new("/dev/sdb1")).unwrap().name, "MY STICK");
        //: No label, so the model, with the trailing space lsblk leaves on it
        //: trimmed off.
        assert_eq!(got.iter().find(|v| v.path == Path::new("/dev/sda2")).unwrap().name, "sda2");
        assert_eq!(got.iter().find(|v| v.path == Path::new("/dev/sr0")).unwrap().name, "AURADE");
    }

    #[test]
    fn the_older_string_spelling_of_a_boolean_still_reads() {
        assert_eq!(as_bool(&serde_json::json!(true)), Some(true));
        assert_eq!(as_bool(&serde_json::json!("1")), Some(true));
        assert_eq!(as_bool(&serde_json::json!("0")), Some(false));
        assert_eq!(as_bool(&serde_json::json!(1)), Some(true));
        assert_eq!(as_bool(&serde_json::json!(null)), None);
    }

    #[test]
    fn read_only_from_the_mount_reaches_the_row() {
        let mounts = parse_mountinfo("1 2 0:1 / /boot ro,relatime shared:1 - vfat /dev/sda1 ro\n");
        let got = parse_lsblk(LSBLK.as_bytes(), &mounts);
        assert!(got.iter().find(|v| v.path == Path::new("/dev/sda1")).unwrap().read_only);
    }

    #[test]
    fn a_fraction_used_is_measured_against_what_a_user_can_reach() {
        let u = Usage { total: 1000, free: 400, available: 300 };
        assert_eq!(u.used(), 600);
        //: 600 used out of the 900 that is reachable, not out of 1000, because
        //: the last hundred is reserved for root and will never be free.
        assert!((u.fraction_used() - 600.0 / 900.0).abs() < 1e-9);
        assert_eq!(Usage { total: 0, free: 0, available: 0 }.fraction_used(), 0.0);
    }

    #[test]
    fn the_live_filesystem_answers_for_the_root_it_is_running_on() {
        let mounts = mounts().unwrap();
        assert!(mounts.iter().any(|m| m.mount_point == Path::new("/")), "no root mount");
        let u = usage(Path::new("/")).unwrap();
        assert!(u.total > 0);
        assert!(u.available <= u.free);
        let on = mount_for(Path::new("/proc/self/mountinfo")).unwrap().unwrap();
        assert_eq!(on.mount_point, Path::new("/proc"));
    }
}
