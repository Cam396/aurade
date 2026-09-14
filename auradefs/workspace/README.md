# auradefs

The file service behind AuraDE's Files app.

Everything the file manager *does* lives in `auradefs-core` as a plain Rust
library that knows nothing about transports. `auradefs-daemon` puts an HTTP
interface on it for the prototype page. The D-Bus interface the shipped desktop
will use is the same library behind a different front door, which is the reason
no decision lives in the transport.

## Why this exists

The prototype backend was `proto/backend.py`: two thousand lines of Python that
resolved paths with `os.path.abspath` and then opened them by name. That is a
check-then-open race with a person as the attacker, and it had no answer for
half of what Files offers. This replaces it.

## Layout

```
crates/auradefs-core/
  error.rs      one error type, keeping the errno and a stable code for the wire
  root.rs       resolving a path exactly once, through directory descriptors
  mime.rs       shared-mime-info read directly, plus a small magic table
  apps.rs       desktop entries, associations, and launching things detached
  xattr.rs      tags, comments, download origin, custom icons, named streams
  git.rs        status, branches, checkout, last commit, through libgit2
  volumes.rs    drives and mounts, from lsblk and /proc/self/mountinfo
  props.rs      ownership, permissions, POSIX ACLs, folder size, hashes,
                and the read only and hidden boxes on the General tab
  media.rs      EXIF parsed here, and everything ffprobe knows about a video
  places.rs     XDG user dirs, GTK bookmarks, the recent list
  thumbs.rs     the freedesktop thumbnail cache, read and written
  system.rs     fonts, certificates, GPG signatures with their six verdicts,
                wallpaper, share
  tags.rs       the tag index, so "everything tagged Work" is answerable
  ops/
    fs.rs       copy, move, delete, rename, duplicate, flatten, shortcuts
    image.rs    turning a picture, by its orientation note where it has one
    list.rs     reading a folder into rows, in one pass
    search.rs   the search box, bounded in time, depth, results and devices
    trash.rs    the freedesktop trash, home and per volume
    archive.rs  zip, 7z and tar in five compressions, at six effort levels,
                with a password on the two formats that can hold one, both
                directions reporting progress and stoppable partway
    volume.rs   a 7z written as numbered parts, and read back as one file

crates/auradefs-daemon/
  b64.rs        base64, for the data URIs a thumbnail arrives in
  http.rs       a small HTTP/1.1 server with every length capped
  jobs.rs       long operations, watchable and cancellable
  api.rs        the routes
  main.rs       loopback only, and it refuses to be anything else
```

## The rules the code holds to

**A path is resolved once.** Operations take a `Root` and a relative path and
walk it one component at a time with `openat(... O_NOFOLLOW | O_DIRECTORY ...)`,
so a symlink swapped in between the check and the write cannot move the target.
`..` is refused outright rather than resolved, because a file manager always
knows the parent it means.

**A refusal carries its reason.** `Error` keeps the errno and a stable string
code, because the UI says a different thing for "no such file", "permission
denied" and "read only volume".

**Nothing untrusted is followed.** A tree copy recreates a symlink rather than
walking it. An archive entry that climbs out of the destination is refused
before a byte is written, symlink entries in archives are refused outright, and
extracted modes are masked so nothing can drop a setuid binary on the disk. That
applies to all three formats: the 7z crate ships a one call extractor that joins
each stored name straight onto the destination, so the walk over a 7z is written
here instead, over the same reader, so that it goes through the same check.
A search does not cross a mount point unless asked, because a network share
below the search root can block a `stat` for minutes with no way to interrupt it.

**Untrusted input is parsed defensively.** EXIF is a set of offsets written by
whoever made the file, pointing anywhere they like. Every read is range checked,
nothing is allocated in proportion to a length the file claims, and the parse
window stops at the end of the segment the block lives in rather than running on
into the picture. The test feeds it every truncation of a real photograph and
every single byte change in its header.

**A tool is asked, never trusted to guess.** ffprobe handed a text file finds
its ansi demuxer and reports a 640 by 400 video at 25 frames a second. So the
file name decides whether it is worth asking, and ffprobe answers only about
files that claim to be media. Every external tool also runs under a deadline and
is killed and reaped if it outstays it.

**Everything long is bounded.** Search has a deadline, a depth, a result cap and
a content size cap. A folder listing has a limit and says when it used it. A
folder size walk has an entry cap and reports that its numbers are a floor.

**A picture is turned, not re-encoded.** A photograph that carries an
orientation is turned by rewriting those two bytes: no decode, nothing lost, and
every other thing the camera recorded still there. Only a file with no such note
is decoded and written back, and then the note it gets is "upright", so no
viewer turns it a second time. The thumbnailer honours the note as well, which
is both a bug fix and the thing that makes the cheap turn visible.

**The desktop's files are the desktop's files.** Tags are `user.xdg.tags`.
Bookmarks are the same `gtk-3.0/bookmarks` every file chooser reads. Thumbnails
go in the shared cache with the URI and modification time the specification
requires, so another program will trust them and will not generate them twice.
Setting a default application writes `mimeapps.list`, which means it is a change
the whole desktop honours rather than a private preference. A tag with a comma
in it is refused rather than escaped, because the attribute is a plain comma
separated list and an escape invented here would be legible in this one program
and nowhere else. Hiding a file writes the folder's `.hidden`, never a rename,
so nothing pointing at the file stops working.

## What it does not do

- **No remote git.** Fetch, pull and push need credentials, and this service
  holds none.
- **No unlocking encrypted volumes.** A passphrase must not travel as a command
  line argument where every process can read it, so that belongs to the daemon
  and its D-Bus connection, not here.
- **No silent escalation.** Run as administrator is `pkexec`, which means a
  polkit prompt, and a refusal there is the end of it.
- **No trusting a certificate by default.** `Trust` is a required argument, and
  the difference between its two values is the difference between keeping a copy
  of a certificate and letting its holder impersonate any site to this user.
- **No encrypted tar.** A tar has no encryption of its own and never has had;
  what people call an encrypted tarball is a tar handed to gpg afterwards, with
  different keys and a different threat model. So a password on one of those
  formats is refused rather than quietly dropped.
- **No old zip encryption.** A password on a zip means AES-256. The original zip
  cipher is broken in a way a laptop undoes in seconds, and offering it under
  the same word would tell somebody their files were protected when they are not.

## Running it

```
cargo build --release
./target/release/auradefs --port 8901
```

It binds `127.0.0.1` and refuses anything else. Loopback is not a security
boundary on its own, so an `Origin` that is not one of this machine's own
surfaces gets a 403 and no CORS header: without that, any page on the internet
could read a listing of the user's home directory.

## Tests

```
cargo test
```

293 of them, and the ones that matter have been mutation tested: the mutation is
applied, the suite is run, and a test that still passes is a test that was not
checking what it claimed to.

## Parity with the backend it replaces

```
python3 tools/parity.py
```

Starts `proto/backend.py` and this daemon against the same scratch tree and asks
both the same questions. For a read it compares the *shape* of the answer, since
the page reads keys and a key on one side only is a page that breaks on the
swap. For a write it also compares the tree afterwards, because a route can
answer correctly and have done something different on disk.

31 cases: 30 identical, and the differences kept on purpose listed at the top of
the harness, so an intended change is never mistaken for a regression. The
oldest is the name a copy takes when the destination is occupied: the Python
backend writes `solo.txt.1`, which changes the file's type, and this writes
`solo (2).txt`. The rest are keys this service adds and the Python one has no
answer for.

`AURADE_BACKEND=rust python3 verify_all.py` runs the whole acceptance suite, all
99 gates, against this daemon instead: 99 passing, 0 failing.

## Beyond the backend it replaces

These are Files features the Python backend had no answer for at all:

- **Archives with a password and an effort level.** Six named levels mapped onto
  each codec's own scale, AES-256 on zip and 7z, and a wrong password reported
  as `needs-password` with a 401 so the caller knows to ask rather than to
  apologise. A wrong 7z password does not fail at the header, so the checksum
  mismatch that arrives partway through a file is recognised for what it is.
- **Archives that say where they are up to, and stop when asked.** Both
  directions report an item and a byte count against a total known before the
  first entry, and both take a cancel. Two reports an entry, not one: the entry
  about to be written, so the name on screen is the one being worked on, and
  the entry that now is, so the counts are not left trailing one behind. With
  only the first, a job of a single file reads zero from its first report to
  its last, which is a bar that sits still and then jumps. A stopped compress removes the archive it
  was building, because half an archive is not an archive; a stopped extract
  keeps what it wrote, because those are ordinary files in a folder the user
  chose and some may have been there already. All three formats are written from
  one walk, so a tar this makes holds exactly what a zip this makes would hold,
  and neither contains an entry this would refuse to extract.
- **The Details tab.** EXIF, parsed here: camera, lens, shutter, aperture, ISO,
  focal length, when the shutter fired, and where. Media, through ffprobe:
  duration, bitrate, codecs, frame rate, channels, sample rate, and the tags a
  music file carries.
- **Archives split into parts.** A 7z written as `thing.7z.001`, `.002` and so
  on, at any of the twelve sizes Files offers, most of which are media
  capacities. The parts are a plain byte split, which is what 7z's own multi
  volume form is, so the set reads back through whichever part the person
  happened to click on. Reading it is a `Read + Seek` over the sequence rather
  than a temporary stitched copy, because at the sizes people split archives at
  the copy is the whole reason not to. A missing part is named rather than read
  past: a 7z keeps its header at the end, so a hole is not a shorter archive but
  an unreadable one. Only 7z is offered the box, because a spanned zip is not a
  byte split and cutting one up produces parts no reader will open.
- **Turning a picture.** Left, right, half turn, and both mirrors, applied to a
  selection, without re-encoding anything that does not need it.
- **Read only and hidden.** The two boxes on the General tab, as the nearest
  true thing on Linux: the write permission, and the folder's own `.hidden`.
- **A Signatures tab.** Files reads Authenticode there, which has no
  counterpart; the nearest true thing is a detached OpenPGP signature beside
  the file, or a file that carries one inside it. Six verdicts, told apart
  rather than collapsed into signed and not: a good signature from a key the
  user trusts is a different thing from a good signature from a key nothing
  vouches for, and both are different from a key that has been revoked. What
  gpg printed is shown as it was printed. Nothing is spawned for a file that
  has no signature beside it and is not itself an OpenPGP file, so opening
  properties on a four gigabyte image does not read four gigabytes.

## Swapping it in

Because the shapes agree, the swap is not a page change. The page reads
`http://127.0.0.1:8902`, so running

```
./target/release/auradefs --port 8902
```

instead of `python3 backend.py` is the whole of it.

## What is next

1. The Chromium patch routing `fileManagerPrivate` at `org.aurade.Files1`.
2. A D-Bus front end on the session bus, over the same `api` module.
3. Retiring `proto/backend.py`.
