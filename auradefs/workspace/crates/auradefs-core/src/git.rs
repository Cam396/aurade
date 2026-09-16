//! What git says about the files in a folder.
//!
//! Files.App reads a repository through LibGit2Sharp, so this reads it through
//! libgit2 as well. That is not a stylistic choice: parsing porcelain output
//! means spawning a process for every folder change and re-deriving rules that
//! the library already gets right, and the two disagree about renames, about
//! ignored directories, and about what a submodule counts as.
//!
//! Fetch, pull, push and clone reach a remote, and this service still holds no
//! credentials of its own. Every one of them asks the same places the person's
//! own `git` asks: the ssh agent for a key, and git's configured credential
//! helper for a password. Nothing is stored, nothing is prompted for here, and
//! a remote that needs a credential nobody has offered fails saying so.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

use crate::error::{Error, Result};

/// What happened to one path, as a single answer. Git tracks the index and the
/// working tree separately; a file manager column shows one thing, so the two
/// are folded and `staged` records whether the index was involved.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Status {
    Unchanged,
    Ignored,
    Untracked,
    Modified,
    Renamed,
    TypeChange,
    Added,
    Deleted,
    Conflicted,
}

impl Status {
    /// The short letter the list column draws.
    pub fn letter(self) -> &'static str {
        match self {
            Status::Unchanged => "",
            Status::Ignored => "I",
            Status::Untracked => "?",
            Status::Modified => "M",
            Status::Renamed => "R",
            Status::TypeChange => "T",
            Status::Added => "A",
            Status::Deleted => "D",
            Status::Conflicted => "U",
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Status::Unchanged => "unchanged",
            Status::Ignored => "ignored",
            Status::Untracked => "untracked",
            Status::Modified => "modified",
            Status::Renamed => "renamed",
            Status::TypeChange => "typechange",
            Status::Added => "added",
            Status::Deleted => "deleted",
            Status::Conflicted => "conflicted",
        }
    }

    /// Fold a libgit2 bitfield into the one answer. The order is the order of
    /// severity: a conflict outranks a deletion, which outranks an addition,
    /// and so on down to an ignored file.
    fn from_flags(flags: git2::Status) -> Status {
        use git2::Status as S;
        if flags.contains(S::CONFLICTED) {
            return Status::Conflicted;
        }
        if flags.intersects(S::INDEX_DELETED | S::WT_DELETED) {
            return Status::Deleted;
        }
        if flags.contains(S::INDEX_NEW) {
            return Status::Added;
        }
        if flags.intersects(S::INDEX_RENAMED | S::WT_RENAMED) {
            return Status::Renamed;
        }
        if flags.intersects(S::INDEX_TYPECHANGE | S::WT_TYPECHANGE) {
            return Status::TypeChange;
        }
        if flags.intersects(S::INDEX_MODIFIED | S::WT_MODIFIED) {
            return Status::Modified;
        }
        if flags.contains(S::WT_NEW) {
            return Status::Untracked;
        }
        if flags.contains(S::IGNORED) {
            return Status::Ignored;
        }
        Status::Unchanged
    }

    fn is_staged(flags: git2::Status) -> bool {
        use git2::Status as S;
        flags.intersects(
            S::INDEX_NEW
                | S::INDEX_MODIFIED
                | S::INDEX_DELETED
                | S::INDEX_RENAMED
                | S::INDEX_TYPECHANGE,
        )
    }
}

/// One row's git state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Entry {
    pub status: Status,
    pub staged: bool,
}

/// The repository a folder is in, and what it says about that folder.
#[derive(Debug, Clone)]
pub struct Info {
    /// The working tree root, which is what the sidebar labels the repository.
    pub root: PathBuf,
    pub branch: Option<String>,
    pub head: Option<String>,
    /// A checkout that is not on a branch. Committing here loses work unless a
    /// branch is made, so the UI says so.
    pub detached: bool,
    pub ahead: usize,
    pub behind: usize,
    /// Repository relative paths to their state. A directory carries the worst
    /// state of anything under it, because that is what a collapsed row has to
    /// convey.
    pub entries: BTreeMap<String, Entry>,
}

impl Info {
    /// The state of one absolute path, or `Unchanged` if git has nothing to
    /// say about it.
    pub fn of(&self, path: &Path) -> Entry {
        let rel = path
            .strip_prefix(&self.root)
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_default();
        self.entries
            .get(&rel)
            .copied()
            .unwrap_or(Entry { status: Status::Unchanged, staged: false })
    }
}

/// Read the repository containing `dir`, or `None` when there is not one.
///
/// `include_ignored` is off by default because a folder of build output would
/// otherwise cost more to describe than to list.
pub fn info(dir: &Path, include_ignored: bool) -> Result<Option<Info>> {
    let repo = match git2::Repository::discover(dir) {
        Ok(r) => r,
        Err(e) if e.code() == git2::ErrorCode::NotFound => return Ok(None),
        Err(e) => return Err(tool(e)),
    };
    let root = match repo.workdir() {
        Some(w) => w.to_path_buf(),
        //: A bare repository has no working tree, so there are no rows to mark.
        None => return Ok(None),
    };

    let mut options = git2::StatusOptions::new();
    options
        .include_untracked(true)
        .recurse_untracked_dirs(false)
        .include_ignored(include_ignored)
        .recurse_ignored_dirs(false)
        .renames_head_to_index(true)
        .renames_index_to_workdir(true)
        .include_unmodified(false);
    let statuses = repo.statuses(Some(&mut options)).map_err(tool)?;

    let mut entries: BTreeMap<String, Entry> = BTreeMap::new();
    for entry in statuses.iter() {
        let Some(path) = entry.path() else { continue };
        let flags = entry.status();
        let status = Status::from_flags(flags);
        if status == Status::Unchanged {
            continue;
        }
        let record = Entry { status, staged: Status::is_staged(flags) };
        //: An untracked directory arrives as one entry with a trailing slash.
        //: The rows are folders and files, so it is stored without.
        let key = path.trim_end_matches('/').to_string();
        merge(&mut entries, key.clone(), record);
        //: And every folder above it carries the worst of what is inside, so a
        //: collapsed row still shows that something changed under it.
        let mut parent = Path::new(&key).parent();
        while let Some(p) = parent {
            let s = p.to_string_lossy().to_string();
            if s.is_empty() {
                break;
            }
            merge(&mut entries, s, Entry { status, staged: record.staged });
            parent = p.parent();
        }
    }

    let head = repo.head().ok();
    let branch = head
        .as_ref()
        .filter(|h| h.is_branch())
        .and_then(|h| h.shorthand().map(str::to_string));
    let detached = repo.head_detached().unwrap_or(false);
    let sha = head.as_ref().and_then(|h| h.target()).map(|oid| oid.to_string());

    let (ahead, behind) = ahead_behind(&repo, branch.as_deref()).unwrap_or((0, 0));

    Ok(Some(Info { root, branch, head: sha, detached, ahead, behind, entries }))
}

/// Keep the more severe of two answers for the same path.
fn merge(entries: &mut BTreeMap<String, Entry>, key: String, record: Entry) {
    entries
        .entry(key)
        .and_modify(|existing| {
            if record.status > existing.status {
                existing.status = record.status;
            }
            existing.staged |= record.staged;
        })
        .or_insert(record);
}

fn ahead_behind(repo: &git2::Repository, branch: Option<&str>) -> Option<(usize, usize)> {
    let name = branch?;
    let local = repo.find_branch(name, git2::BranchType::Local).ok()?;
    let upstream = local.upstream().ok()?;
    let local_oid = local.get().target()?;
    let upstream_oid = upstream.get().target()?;
    repo.graph_ahead_behind(local_oid, upstream_oid).ok()
}

/// One branch, for the switcher.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Branch {
    pub name: String,
    pub is_head: bool,
    pub is_remote: bool,
    /// The remote branch this one tracks, if it tracks one.
    pub upstream: Option<String>,
}

/// Every branch, local first, then remote tracking ones.
pub fn branches(dir: &Path) -> Result<Vec<Branch>> {
    let repo = git2::Repository::discover(dir).map_err(tool)?;
    let mut out = Vec::new();
    for kind in [git2::BranchType::Local, git2::BranchType::Remote] {
        let iter = repo.branches(Some(kind)).map_err(tool)?;
        for item in iter {
            let (branch, _) = item.map_err(tool)?;
            let Some(name) = branch.name().ok().flatten() else { continue };
            out.push(Branch {
                name: name.to_string(),
                is_head: branch.is_head(),
                is_remote: kind == git2::BranchType::Remote,
                upstream: branch
                    .upstream()
                    .ok()
                    .and_then(|u| u.name().ok().flatten().map(str::to_string)),
            });
        }
    }
    Ok(out)
}

/// Switch branches.
///
/// Deliberately the safe checkout: libgit2 refuses rather than overwriting a
/// file with uncommitted changes. Losing an edit to a branch switch is the one
/// mistake a file manager must not make on someone's behalf, so the refusal is
/// passed straight through for the UI to explain.
pub fn checkout(dir: &Path, name: &str) -> Result<()> {
    valid_revision(name)?;
    let repo = git2::Repository::discover(dir).map_err(tool)?;
    let (object, reference) = repo
        .revparse_ext(name)
        //: Not found is the repository's state, not a malformed request: the
        //: caller asked for something reasonable and this repository does not
        //: have it.
        .map_err(|e| match e.code() {
            git2::ErrorCode::NotFound => Error::Conflict(format!("no branch or commit {name}")),
            _ => Error::Conflict(e.message().to_string()),
        })?;
    let mut builder = git2::build::CheckoutBuilder::new();
    builder.safe();
    //: A refusal here is git protecting uncommitted work, which is a state
    //: the person can do something about rather than a failure.
    repo.checkout_tree(&object, Some(&mut builder))
        .map_err(|e| Error::Conflict(e.message().to_string()))?;
    match reference {
        Some(r) => {
            let refname = r
                .name()
                .ok_or_else(|| Error::BadRequest(format!("{name} has an unreadable ref name")))?;
            repo.set_head(refname).map_err(tool)?;
        }
        //: A bare commit id detaches HEAD, which is what git itself does.
        None => repo.set_head_detached(object.id()).map_err(tool)?,
    }
    Ok(())
}

/// Make a branch at a starting point, and optionally move onto it.
pub fn create_branch(dir: &Path, name: &str, from: Option<&str>, switch: bool) -> Result<()> {
    valid_revision(name)?;
    let repo = git2::Repository::discover(dir).map_err(tool)?;
    let target = match from {
        Some(rev) => repo.revparse_single(rev).map_err(tool)?,
        None => repo.head().map_err(tool)?.peel(git2::ObjectType::Commit).map_err(tool)?,
    };
    let commit = target.peel_to_commit().map_err(tool)?;
    repo.branch(name, &commit, false).map_err(|e| match e.code() {
        git2::ErrorCode::Exists => Error::Exists(format!("branch {name}")),
        git2::ErrorCode::InvalidSpec => Error::BadRequest(format!("{name} is not a usable branch name")),
        _ => tool(e),
    })?;
    if switch {
        checkout(dir, name)?;
    }
    Ok(())
}

/// What the last commit touching a path said. Files shows these as columns, so
/// the walk is bounded: a file that has not been touched in the last few
/// thousand commits reports nothing rather than reading the whole history.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Commit {
    pub sha: String,
    pub short_sha: String,
    pub summary: String,
    pub author: String,
    pub email: String,
    /// Seconds since the epoch, in UTC.
    pub time: i64,
}

const WALK_LIMIT: usize = 4096;

pub fn last_commit(dir: &Path, path: &Path) -> Result<Option<Commit>> {
    let repo = git2::Repository::discover(dir).map_err(tool)?;
    let Some(workdir) = repo.workdir().map(Path::to_path_buf) else { return Ok(None) };
    let rel = path.strip_prefix(&workdir).unwrap_or(path).to_path_buf();

    let mut walk = repo.revwalk().map_err(tool)?;
    walk.push_head().map_err(tool)?;
    walk.set_sorting(git2::Sort::TIME).map_err(tool)?;

    for (seen, oid) in walk.enumerate() {
        if seen >= WALK_LIMIT {
            break;
        }
        let oid = oid.map_err(tool)?;
        let commit = repo.find_commit(oid).map_err(tool)?;
        let tree = commit.tree().map_err(tool)?;
        let here = tree.get_path(&rel).ok().map(|e| e.id());
        let there = match commit.parent(0) {
            Ok(parent) => parent.tree().ok().and_then(|t| t.get_path(&rel).ok().map(|e| e.id())),
            //: The first commit has no parent, so anything in it is new.
            Err(_) => None,
        };
        if here != there {
            let author = commit.author();
            return Ok(Some(Commit {
                sha: oid.to_string(),
                short_sha: oid.to_string()[..7].to_string(),
                summary: commit.summary().unwrap_or_default().to_string(),
                author: author.name().unwrap_or_default().to_string(),
                email: author.email().unwrap_or_default().to_string(),
                time: commit.time().seconds(),
            }));
        }
    }
    Ok(None)
}

/// The last commit that touched each child of a folder, in one walk.
///
/// The reference's four git columns ask git once per row. One walk over the
/// history that looks at every unresolved child at each commit answers a
/// folder of a thousand files in about the time one file took, and a commit
/// that left the folder's subtree alone is skipped by comparing two tree
/// ids. The same walk limit as [`last_commit`]: a child older than that
/// reports nothing rather than reading the whole history.
pub fn last_commits(dir: &Path) -> Result<Option<BTreeMap<String, Commit>>> {
    let repo = match git2::Repository::discover(dir) {
        Ok(repo) => repo,
        Err(e) if e.code() == git2::ErrorCode::NotFound => return Ok(None),
        Err(e) => return Err(tool(e)),
    };
    let Some(workdir) = repo.workdir().map(Path::to_path_buf) else { return Ok(None) };
    let rel = match dir.strip_prefix(&workdir) {
        Ok(rel) => rel.to_path_buf(),
        Err(_) => return Ok(None),
    };
    //: The children as the folder has them now. A name not in the history
    //: is simply never resolved, which is how an untracked file reads.
    let mut pending: BTreeSet<String> = std::fs::read_dir(dir)
        .map_err(|e| Error::io(dir.display().to_string(), e))?
        .filter_map(|e| e.ok())
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|n| n != ".git")
        .collect();
    let mut out = BTreeMap::new();
    if pending.is_empty() {
        return Ok(Some(out));
    }

    //: The folder's own subtree in a commit, or None when the folder was not
    //: there yet.
    let subtree = |tree: &git2::Tree<'_>| -> Option<git2::Oid> {
        if rel.as_os_str().is_empty() {
            Some(tree.id())
        } else {
            tree.get_path(&rel).ok().map(|entry| entry.id())
        }
    };
    let mut walk = repo.revwalk().map_err(tool)?;
    if walk.push_head().is_err() {
        //: No commits yet: nothing has touched anything.
        return Ok(Some(out));
    }
    walk.set_sorting(git2::Sort::TIME).map_err(tool)?;
    for (seen, oid) in walk.enumerate() {
        if seen >= WALK_LIMIT || pending.is_empty() {
            break;
        }
        let oid = oid.map_err(tool)?;
        let commit = repo.find_commit(oid).map_err(tool)?;
        let tree = commit.tree().map_err(tool)?;
        let parent_tree = commit.parent(0).ok().and_then(|p| p.tree().ok());
        let here = subtree(&tree);
        let there = parent_tree.as_ref().and_then(|t| subtree(t));
        if here == there {
            continue;
        }
        let here_tree = here.and_then(|id| repo.find_tree(id).ok());
        let there_tree = there.and_then(|id| repo.find_tree(id).ok());
        let id_in = |t: &Option<git2::Tree<'_>>, name: &str| -> Option<git2::Oid> {
            t.as_ref().and_then(|t| t.get_name(name).map(|e| e.id()))
        };
        let touched: Vec<String> = pending
            .iter()
            .filter(|name| id_in(&here_tree, name) != id_in(&there_tree, name))
            .cloned()
            .collect();
        if touched.is_empty() {
            continue;
        }
        let author = commit.author();
        let found = Commit {
            sha: oid.to_string(),
            short_sha: oid.to_string()[..7].to_string(),
            summary: commit.summary().unwrap_or_default().to_string(),
            author: author.name().unwrap_or_default().to_string(),
            email: author.email().unwrap_or_default().to_string(),
            time: commit.time().seconds(),
        };
        for name in touched {
            pending.remove(&name);
            out.insert(name, found.clone());
        }
    }
    Ok(Some(out))
}

/// A branch or commit name that is safe to pass on.
///
/// The name arrives from a page and ends up as an argument. A leading dash
/// would be read as an option by anything that shells out, and whitespace
/// means the caller has sent something that is not one name. Both are refused
/// here so they are a bad request rather than whatever git makes of them.
pub fn valid_revision(name: &str) -> Result<()> {
    if name.is_empty() {
        return Err(Error::BadRequest("a branch name is required".into()));
    }
    if name.starts_with('-') {
        return Err(Error::BadRequest(format!("{name} is an option, not a branch")));
    }
    if name.chars().any(char::is_whitespace) {
        return Err(Error::BadRequest(format!("{name} is not one name")));
    }
    if name.contains("..") || name.contains('\0') || name.contains('\\') {
        return Err(Error::BadRequest(format!("{name} is not a usable branch name")));
    }
    Ok(())
}

// ------------------------------------------------------------- remotes ----

/// How far a transfer has got, for the bar and for the cancel.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Transfer {
    pub objects: u32,
    pub total: u32,
    pub bytes: u64,
}

/// Told how far a transfer has got; answer false to stop it.
pub type Watcher<'a> = &'a mut dyn FnMut(Transfer) -> bool;

/// A watcher that wants nothing and stops nothing.
pub fn unwatched(_t: Transfer) -> bool {
    true
}

/// The transports a remote may use.
///
/// Not a style rule. git's `ext::` transport runs the rest of the URL as a
/// command, so a repository address is a way to execute something if every
/// scheme is accepted, and a URL can arrive here from a page. Only the four
/// that move bytes are allowed, plus a path on this machine.
///
/// libgit2 does not implement the remote helper protocol, and answers such an
/// address with "unsupported URL protocol" rather than running anything; the
/// test below records that. This is checked here anyway, because a policy that
/// holds only because a dependency has not implemented a feature is not a
/// policy, and because the person gets told which part of the address was
/// refused rather than a message about protocols.
const TRANSPORTS: [&str; 5] = ["https://", "http://", "ssh://", "git://", "file://"];

/// Check a remote address before anything is opened.
pub fn safe_remote(url: &str) -> Result<()> {
    let trimmed = url.trim();
    if trimmed.is_empty() {
        return Err(Error::BadRequest("no address given".into()));
    }
    //: `<name>::<address>` is git's remote helper form, and the `ext` helper
    //: hands the rest of the address to a shell. This is checked before the
    //: schemes below because the shorthand branch would otherwise read `ext`
    //: as a host name and wave the whole thing through. Only the part before
    //: the path is examined, so a `::` inside a repository name is not a
    //: helper and is not refused.
    let path_starts = trimmed.find('/').unwrap_or(trimmed.len());
    if trimmed[..path_starts].contains("::") {
        let helper = trimmed.split("::").next().unwrap_or(trimmed);
        return Err(Error::Unsupported(format!(
            "{helper}:: runs a helper program rather than opening a connection"
        )));
    }
    let lower = trimmed.to_ascii_lowercase();
    if TRANSPORTS.iter().any(|t| lower.starts_with(t)) {
        return Ok(());
    }
    //: The scp shorthand, `git@host:owner/repo`, which is ssh and is what
    //: every host's copy button gives you.
    if let Some((before, after)) = trimmed.split_once(':') {
        let looks_like_a_scheme = before.contains("://") || after.starts_with("//");
        if !looks_like_a_scheme
            && !before.is_empty()
            && !after.is_empty()
            && !before.contains('/')
            && before.chars().all(|c| {
                c.is_ascii_alphanumeric() || c == '@' || c == '.' || c == '-' || c == '_'
            })
        {
            return Ok(());
        }
        return Err(Error::Unsupported(format!(
            "{before} is not a transport this will use"
        )));
    }
    //: A plain path on this machine, which is a legitimate thing to clone.
    if trimmed.starts_with('/') || trimmed.starts_with('.') {
        return Ok(());
    }
    Err(Error::BadRequest(format!("{trimmed} is not an address")))
}

/// Where a credential comes from: the same two places the person's own git
/// looks. This service keeps none and asks for none.
fn credentials(
    url: &str,
    username: Option<&str>,
    allowed: git2::CredentialType,
) -> std::result::Result<git2::Cred, git2::Error> {
    if allowed.contains(git2::CredentialType::SSH_KEY) {
        //: The agent, not a key file: reading a private key off disk here
        //: would mean holding one, and the agent exists so that nothing has to.
        return git2::Cred::ssh_key_from_agent(username.unwrap_or("git"));
    }
    if allowed.contains(git2::CredentialType::USER_PASS_PLAINTEXT) {
        let config = git2::Config::open_default()?;
        return git2::Cred::credential_helper(&config, url, username);
    }
    if allowed.contains(git2::CredentialType::DEFAULT) {
        return git2::Cred::default();
    }
    Err(git2::Error::from_str(
        "this remote needs a credential and none was offered",
    ))
}

fn callbacks<'a>(report: Watcher<'a>) -> git2::RemoteCallbacks<'a> {
    let mut hooks = git2::RemoteCallbacks::new();
    hooks.credentials(|url, username, allowed| credentials(url, username, allowed));
    hooks.transfer_progress(move |stats| {
        report(Transfer {
            objects: stats.received_objects() as u32,
            total: stats.total_objects() as u32,
            bytes: stats.received_bytes() as u64,
        })
    });
    hooks
}

/// Start a repository where there is not one.
pub fn init(dir: &Path, bare: bool) -> Result<PathBuf> {
    if git2::Repository::open(dir).is_ok() {
        return Err(Error::Exists(format!("{} is already a repository", dir.display())));
    }
    let repo = if bare {
        git2::Repository::init_bare(dir).map_err(tool)?
    } else {
        git2::Repository::init(dir).map_err(tool)?
    };
    Ok(repo.path().to_path_buf())
}

/// Copy a remote repository into a new folder.
///
/// The destination has to be somewhere nothing is yet: cloning on top of a
/// folder with things in it is how a person loses those things.
pub fn clone(url: &str, into: &Path, report: Watcher<'_>) -> Result<PathBuf> {
    safe_remote(url)?;
    if let Ok(mut entries) = std::fs::read_dir(into) {
        if entries.next().is_some() {
            return Err(Error::Exists(format!("{} is not empty", into.display())));
        }
    }
    let mut fetch = git2::FetchOptions::new();
    fetch.remote_callbacks(callbacks(report));
    let repo = git2::build::RepoBuilder::new()
        .fetch_options(fetch)
        .clone(url, into)
        .map_err(remote_error)?;
    Ok(repo.workdir().unwrap_or_else(|| repo.path()).to_path_buf())
}

/// What a fetch brought back.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Fetched {
    pub remote: String,
    pub objects: u32,
    pub bytes: u64,
    /// The branch the working tree is on, when there is one.
    pub branch: Option<String>,
    /// How far ahead and behind that branch is of its upstream afterwards.
    pub ahead: usize,
    pub behind: usize,
}

/// Bring the remote's refs up to date without touching the working tree.
pub fn fetch(dir: &Path, remote: Option<&str>, report: Watcher<'_>) -> Result<Fetched> {
    let repo = git2::Repository::discover(dir).map_err(tool)?;
    let name = remote_name(&repo, remote)?;
    let mut origin = repo.find_remote(&name).map_err(tool)?;
    if let Some(url) = origin.url() {
        safe_remote(url)?;
    }
    let mut options = git2::FetchOptions::new();
    options.remote_callbacks(callbacks(report));
    let refspecs: Vec<String> = origin
        .fetch_refspecs()
        .map_err(tool)?
        .iter()
        .flatten()
        .map(str::to_string)
        .collect();
    origin.fetch(&refspecs, Some(&mut options), None).map_err(remote_error)?;
    let stats = origin.stats();
    let (branch, ahead, behind) = tracking(&repo);
    Ok(Fetched {
        remote: name,
        objects: stats.received_objects() as u32,
        bytes: stats.received_bytes() as u64,
        branch,
        ahead,
        behind,
    })
}

/// What a pull did.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Pulled {
    pub fetched: Fetched,
    /// True when the branch moved. False means it was already up to date.
    pub moved: bool,
}

/// Fetch, then move the branch forward if that is all it takes.
///
/// Fast forward only, deliberately. A pull that has to make a merge commit is
/// a decision about history, and a file manager quietly making one on a
/// person's behalf is how a repository ends up in a state they did not choose.
/// When the two have diverged this says so and stops.
pub fn pull(dir: &Path, remote: Option<&str>, report: Watcher<'_>) -> Result<Pulled> {
    let fetched = fetch(dir, remote, report)?;
    let repo = git2::Repository::discover(dir).map_err(tool)?;
    let head = repo.head().map_err(tool)?;
    let name = head
        .shorthand()
        .ok_or_else(|| Error::Conflict("HEAD is not on a branch".into()))?
        .to_string();
    let upstream = repo
        .find_branch(&name, git2::BranchType::Local)
        .and_then(|b| b.upstream())
        .map_err(|_| Error::Conflict(format!("{name} is not tracking a remote branch")))?;
    let target = upstream.get().peel_to_commit().map_err(tool)?;
    let mine = head.peel_to_commit().map_err(tool)?;
    if mine.id() == target.id() {
        return Ok(Pulled { fetched, moved: false });
    }
    let (ahead, behind) = repo
        .graph_ahead_behind(mine.id(), target.id())
        .map_err(tool)?;
    if ahead > 0 && behind > 0 {
        return Err(Error::Conflict(format!(
            "{name} and its upstream have both moved, {ahead} here and {behind} \
             there: this will not make a merge commit for you"
        )));
    }
    if behind == 0 {
        return Ok(Pulled { fetched, moved: false });
    }
    let mut builder = git2::build::CheckoutBuilder::new();
    builder.safe();
    let object = target.as_object();
    repo.checkout_tree(object, Some(&mut builder))
        .map_err(|e| Error::Conflict(e.message().to_string()))?;
    let refname = head
        .name()
        .ok_or_else(|| Error::BadRequest("HEAD has an unreadable name".into()))?
        .to_string();
    repo.reference(&refname, target.id(), true, "pull: fast forward")
        .map_err(tool)?;
    //: Read again. The fetch counted the branch before it moved, and telling
    //: someone they are still one behind immediately after a pull that
    //: worked is worse than saying nothing.
    let (branch, ahead, behind) = tracking(&repo);
    let fetched = Fetched { branch, ahead, behind, ..fetched };
    Ok(Pulled { fetched, moved: true })
}

/// Send the current branch to its remote.
pub fn push(dir: &Path, remote: Option<&str>, report: Watcher<'_>) -> Result<String> {
    let repo = git2::Repository::discover(dir).map_err(tool)?;
    let name = remote_name(&repo, remote)?;
    let head = repo.head().map_err(tool)?;
    let branch = head
        .shorthand()
        .ok_or_else(|| Error::Conflict("HEAD is not on a branch".into()))?
        .to_string();
    let refname = head
        .name()
        .ok_or_else(|| Error::BadRequest("HEAD has an unreadable name".into()))?
        .to_string();
    let mut origin = repo.find_remote(&name).map_err(tool)?;
    if let Some(url) = origin.url() {
        safe_remote(url)?;
    }
    let mut options = git2::PushOptions::new();
    options.remote_callbacks(callbacks(report));
    //: No leading plus. A forced push rewrites what is on the remote, and
    //: nothing on a menu should be able to do that without being asked for.
    let spec = format!("{refname}:{refname}");
    origin.push(&[spec.as_str()], Some(&mut options)).map_err(remote_error)?;
    Ok(branch)
}

/// Pull, then push: the one button that makes a branch match its remote.
pub fn sync(dir: &Path, remote: Option<&str>, report: Watcher<'_>) -> Result<Pulled> {
    let pulled = pull(dir, remote, report)?;
    push(dir, remote, &mut unwatched)?;
    Ok(pulled)
}

/// The remote to act on: the one named, or the only one, or `origin`.
fn remote_name(repo: &git2::Repository, wanted: Option<&str>) -> Result<String> {
    if let Some(name) = wanted.filter(|n| !n.is_empty()) {
        valid_revision(name)?;
        return Ok(name.to_string());
    }
    let all = repo.remotes().map_err(tool)?;
    let names: Vec<String> = all.iter().flatten().map(str::to_string).collect();
    if names.is_empty() {
        return Err(Error::NotFound("this repository has no remote".into()));
    }
    if let Some(origin) = names.iter().find(|n| *n == "origin") {
        return Ok(origin.clone());
    }
    if names.len() == 1 {
        return Ok(names[0].clone());
    }
    Err(Error::BadRequest(format!(
        "this repository has {} remotes and none is called origin: name one",
        names.len()
    )))
}

/// The branch HEAD is on and how it stands against its upstream.
fn tracking(repo: &git2::Repository) -> (Option<String>, usize, usize) {
    let Ok(head) = repo.head() else { return (None, 0, 0) };
    let Some(name) = head.shorthand().map(str::to_string) else { return (None, 0, 0) };
    let counted = repo
        .find_branch(&name, git2::BranchType::Local)
        .and_then(|b| b.upstream())
        .ok()
        .and_then(|up| {
            let theirs = up.get().peel_to_commit().ok()?.id();
            let mine = head.peel_to_commit().ok()?.id();
            repo.graph_ahead_behind(mine, theirs).ok()
        })
        .unwrap_or((0, 0));
    (Some(name), counted.0, counted.1)
}

/// A remote failure, told apart from a local one.
///
/// Authentication is the case worth naming: a caller can do something about
/// "the agent has no key for this host" and nothing at all about a generic
/// error, and libgit2 reports both through the same type.
fn remote_error(e: git2::Error) -> Error {
    match e.class() {
        git2::ErrorClass::Ssh | git2::ErrorClass::Http | git2::ErrorClass::Callback
            if e.code() == git2::ErrorCode::Auth =>
        {
            Error::Denied(format!("the remote refused the credential: {}", e.message()))
        }
        _ if e.code() == git2::ErrorCode::Auth => {
            Error::Denied(format!("the remote refused the credential: {}", e.message()))
        }
        _ if e.code() == git2::ErrorCode::Certificate => {
            Error::Denied(format!("the remote's certificate was not accepted: {}", e.message()))
        }
        _ => Error::Tool { tool: "git".into(), message: e.message().to_string() },
    }
}

fn tool(e: git2::Error) -> Error {
    //: libgit2's message is one line and usually the only useful thing, which
    //: is exactly what the Tool variant is for.
    Error::Tool { tool: "git".into(), message: e.message().to_string() }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    /// A repository built through libgit2 rather than the git binary, so the
    /// tests do not depend on one being installed or on its configuration.
    fn repo(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("auradefs-git-{tag}"));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(dir.join("src")).unwrap();
        let repo = git2::Repository::init(&dir).unwrap();
        fs::write(dir.join("tracked.txt"), b"one\n").unwrap();
        fs::write(dir.join("src/lib.rs"), b"fn main() {}\n").unwrap();
        fs::write(dir.join(".gitignore"), b"build/\n").unwrap();
        let mut index = repo.index().unwrap();
        for p in ["tracked.txt", "src/lib.rs", ".gitignore"] {
            index.add_path(Path::new(p)).unwrap();
        }
        index.write().unwrap();
        let tree = repo.find_tree(index.write_tree().unwrap()).unwrap();
        let who = git2::Signature::now("Test", "test@example.invalid").unwrap();
        repo.commit(Some("HEAD"), &who, &who, "first", &tree, &[]).unwrap();
        drop(tree);
        drop(index);
        dir
    }

    #[test]
    fn a_folder_outside_a_repository_reports_nothing() {
        let dir = std::env::temp_dir().join("auradefs-git-none");
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        //: Only true if no ancestor is a repository, which /tmp is not.
        assert!(info(&dir, false).unwrap().is_none());
    }

    #[test]
    fn a_clean_checkout_has_a_branch_and_no_marked_rows() {
        let dir = repo("clean");
        let got = info(&dir, false).unwrap().unwrap();
        assert_eq!(got.root, fs::canonicalize(&dir).unwrap());
        assert!(matches!(got.branch.as_deref(), Some("main") | Some("master")));
        assert!(!got.detached);
        assert_eq!(got.head.map(|h| h.len()), Some(40));
        assert!(got.entries.is_empty(), "a clean tree marked rows: {:?}", got.entries);
    }

    #[test]
    fn each_kind_of_change_gets_its_own_answer() {
        let dir = repo("kinds");
        fs::write(dir.join("tracked.txt"), b"changed\n").unwrap();
        fs::write(dir.join("fresh.txt"), b"new\n").unwrap();
        fs::create_dir_all(dir.join("build")).unwrap();
        fs::write(dir.join("build/out.o"), b"binary").unwrap();

        let got = info(&dir, false).unwrap().unwrap();
        assert_eq!(got.entries["tracked.txt"].status, Status::Modified);
        assert!(!got.entries["tracked.txt"].staged, "nothing was added to the index");
        assert_eq!(got.entries["fresh.txt"].status, Status::Untracked);
        assert!(!got.entries.contains_key("build"), "an ignored folder was reported");

        let with_ignored = info(&dir, true).unwrap().unwrap();
        assert_eq!(with_ignored.entries["build"].status, Status::Ignored);
    }

    #[test]
    fn staging_a_change_is_visible_as_staged() {
        let dir = repo("staged");
        fs::write(dir.join("tracked.txt"), b"changed\n").unwrap();
        let r = git2::Repository::open(&dir).unwrap();
        let mut index = r.index().unwrap();
        index.add_path(Path::new("tracked.txt")).unwrap();
        index.write().unwrap();

        let got = info(&dir, false).unwrap().unwrap();
        assert_eq!(got.entries["tracked.txt"].status, Status::Modified);
        assert!(got.entries["tracked.txt"].staged);
    }

    #[test]
    fn a_folder_carries_the_worst_of_what_is_under_it() {
        let dir = repo("rollup");
        fs::write(dir.join("src/lib.rs"), b"edited\n").unwrap();
        let got = info(&dir, false).unwrap().unwrap();
        assert_eq!(got.entries["src/lib.rs"].status, Status::Modified);
        assert_eq!(
            got.entries["src"].status,
            Status::Modified,
            "the folder row said nothing about its contents"
        );

        //: A deletion outranks a modification, so the folder shows the deletion.
        fs::create_dir_all(dir.join("src/deep")).unwrap();
        fs::write(dir.join("src/deep/gone.txt"), b"x").unwrap();
        let r = git2::Repository::open(&dir).unwrap();
        let mut index = r.index().unwrap();
        index.add_path(Path::new("src/deep/gone.txt")).unwrap();
        index.write().unwrap();
        let tree = r.find_tree(index.write_tree().unwrap()).unwrap();
        let who = git2::Signature::now("Test", "test@example.invalid").unwrap();
        let head = r.head().unwrap().peel_to_commit().unwrap();
        r.commit(Some("HEAD"), &who, &who, "add", &tree, &[&head]).unwrap();
        drop(tree);
        drop(index);
        fs::remove_file(dir.join("src/deep/gone.txt")).unwrap();

        let got = info(&dir, false).unwrap().unwrap();
        assert_eq!(got.entries["src/deep"].status, Status::Deleted);
        assert_eq!(got.entries["src"].status, Status::Deleted);
    }

    #[test]
    fn of_answers_for_an_absolute_path_and_defaults_to_unchanged() {
        let dir = repo("of");
        fs::write(dir.join("tracked.txt"), b"changed\n").unwrap();
        let got = info(&dir, false).unwrap().unwrap();
        assert_eq!(got.of(&got.root.join("tracked.txt")).status, Status::Modified);
        assert_eq!(got.of(&got.root.join("src/lib.rs")).status, Status::Unchanged);
        assert_eq!(got.of(Path::new("/elsewhere/x")).status, Status::Unchanged);
    }

    #[test]
    fn branches_are_listed_and_switched() {
        let dir = repo("branches");
        create_branch(&dir, "feature", None, false).unwrap();
        let names: Vec<String> = branches(&dir).unwrap().into_iter().map(|b| b.name).collect();
        assert!(names.contains(&"feature".to_string()));

        checkout(&dir, "feature").unwrap();
        let got = info(&dir, false).unwrap().unwrap();
        assert_eq!(got.branch.as_deref(), Some("feature"));
        assert!(!got.detached);
    }

    #[test]
    fn a_branch_name_that_is_not_one_is_refused() {
        let dir = repo("bad-branch");
        for bad in ["", "with space", "two words"] {
            assert!(create_branch(&dir, bad, None, false).is_err(), "{bad:?} allowed");
        }
        create_branch(&dir, "ok", None, false).unwrap();
        let err = create_branch(&dir, "ok", None, false).unwrap_err();
        assert!(matches!(err, Error::Exists(_)), "got {err:?}");
    }

    #[test]
    fn checking_out_something_that_does_not_exist_is_the_repositorys_answer() {
        let dir = repo("missing-branch");
        let err = checkout(&dir, "nope").unwrap_err();
        //: A refusal by the repository, not a malformed request: the caller
        //: asked for a perfectly good name that this repository lacks, and the
        //: UI says a different thing for each.
        assert!(matches!(err, Error::Conflict(_)), "got {err:?}");
        assert_eq!(err.code(), "conflict");
    }

    #[test]
    fn a_name_that_is_really_an_option_never_reaches_git() {
        let dir = repo("argument-injection");
        for bad in ["--all", "-f", "a b", "a\tb", "", "a..b", "back\\slash"] {
            let err = checkout(&dir, bad).unwrap_err();
            assert_eq!(err.code(), "bad-request", "{bad:?} gave {err:?}");
            let err = create_branch(&dir, bad, None, false).unwrap_err();
            assert_eq!(err.code(), "bad-request", "{bad:?} gave {err:?}");
        }
        //: And a name that is merely unusual still works.
        create_branch(&dir, "feature/with-slash", None, false).unwrap();
        checkout(&dir, "feature/with-slash").unwrap();
    }

    #[test]
    fn a_commit_id_detaches_head_the_way_git_does() {
        let dir = repo("detach");
        let sha = info(&dir, false).unwrap().unwrap().head.unwrap();
        checkout(&dir, &sha).unwrap();
        let got = info(&dir, false).unwrap().unwrap();
        assert!(got.detached);
        assert_eq!(got.branch, None);
    }

    #[test]
    fn the_last_commit_that_touched_a_file_is_found() {
        let dir = repo("history");
        let first = last_commit(&dir, &dir.join("tracked.txt")).unwrap().unwrap();
        assert_eq!(first.summary, "first");
        assert_eq!(first.author, "Test");
        assert_eq!(first.short_sha.len(), 7);
        assert!(first.time > 0);

        //: A second commit that does not touch the file must not become its
        //: last commit.
        fs::write(dir.join("other.txt"), b"x").unwrap();
        let r = git2::Repository::open(&dir).unwrap();
        let mut index = r.index().unwrap();
        index.add_path(Path::new("other.txt")).unwrap();
        index.write().unwrap();
        let tree = r.find_tree(index.write_tree().unwrap()).unwrap();
        let who = git2::Signature::now("Test", "test@example.invalid").unwrap();
        let head = r.head().unwrap().peel_to_commit().unwrap();
        r.commit(Some("HEAD"), &who, &who, "second", &tree, &[&head]).unwrap();
        drop(tree);
        drop(index);

        assert_eq!(last_commit(&dir, &dir.join("tracked.txt")).unwrap().unwrap().summary, "first");
        assert_eq!(last_commit(&dir, &dir.join("other.txt")).unwrap().unwrap().summary, "second");
        assert_eq!(last_commit(&dir, &dir.join("never-existed")).unwrap(), None);
    }

    #[test]
    fn one_walk_answers_every_child_of_a_folder() {
        let dir = repo("commits");
        //: A second commit touching one file and adding another, so the
        //: three children resolve to two different commits.
        fs::write(dir.join("other.txt"), b"x").unwrap();
        fs::write(dir.join("tracked.txt"), b"two\n").unwrap();
        let r = git2::Repository::open(&dir).unwrap();
        let mut index = r.index().unwrap();
        index.add_path(Path::new("other.txt")).unwrap();
        index.add_path(Path::new("tracked.txt")).unwrap();
        index.write().unwrap();
        let tree = r.find_tree(index.write_tree().unwrap()).unwrap();
        let who = git2::Signature::now("Test", "test@example.invalid").unwrap();
        let head = r.head().unwrap().peel_to_commit().unwrap();
        r.commit(Some("HEAD"), &who, &who, "second", &tree, &[&head]).unwrap();
        drop(tree);
        drop(index);
        //: And something never committed, which must not be invented.
        fs::write(dir.join("untracked.txt"), b"?").unwrap();

        let got = last_commits(&dir).unwrap().expect("inside a repository");
        assert_eq!(got["tracked.txt"].summary, "second");
        assert_eq!(got["other.txt"].summary, "second");
        assert_eq!(got[".gitignore"].summary, "first");
        assert_eq!(got["src"].summary, "first", "a folder is answered by what changed under it");
        assert!(!got.contains_key("untracked.txt"), "never committed, never answered");
        assert!(!got.contains_key(".git"));
        //: The same answers one at a time, so the two cannot drift.
        for (name, commit) in &got {
            assert_eq!(last_commit(&dir, &dir.join(name)).unwrap().unwrap().sha, commit.sha, "{name}");
        }
        //: A subfolder is answered against its own subtree.
        let inner = last_commits(&dir.join("src")).unwrap().unwrap();
        assert_eq!(inner["lib.rs"].summary, "first");
        //: Outside any repository there is no answer at all.
        let plain = std::env::temp_dir().join("auradefs-git-commits-none");
        let _ = fs::remove_dir_all(&plain);
        fs::create_dir_all(&plain).unwrap();
        assert_eq!(last_commits(&plain).unwrap(), None);
    }

    #[test]
    fn the_letters_are_stable_because_the_column_shows_them() {
        assert_eq!(Status::Modified.letter(), "M");
        assert_eq!(Status::Untracked.letter(), "?");
        assert_eq!(Status::Unchanged.letter(), "");
        assert_eq!(Status::Conflicted.name(), "conflicted");
        //: U, the letter git's own porcelain uses for an unmerged path, which
        //: is what the details column reads.
        assert_eq!(Status::Conflicted.letter(), "U");
    }

    // ------------------------------------------------------------ remotes ---

    /// One more commit on whatever branch HEAD is on.
    fn commit(dir: &Path, name: &str, body: &str) -> git2::Oid {
        let r = git2::Repository::open(dir).unwrap();
        fs::write(dir.join(name), body.as_bytes()).unwrap();
        let mut index = r.index().unwrap();
        index.add_path(Path::new(name)).unwrap();
        index.write().unwrap();
        let tree = r.find_tree(index.write_tree().unwrap()).unwrap();
        let who = git2::Signature::now("Test", "test@example.invalid").unwrap();
        let head = r.head().unwrap().peel_to_commit().unwrap();
        let id = r
            .commit(Some("HEAD"), &who, &who, name, &tree, &[&head])
            .unwrap();
        drop(tree);
        drop(index);
        id
    }

    fn empty(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("auradefs-git-{tag}"));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    /// A `file://` address for a folder, which is how these tests reach a
    /// remote without reaching the network.
    fn local_url(dir: &Path) -> String {
        format!("file://{}", fs::canonicalize(dir).unwrap().display())
    }

    #[test]
    fn a_transport_that_runs_a_command_is_refused() {
        //: The whole reason this check exists. git's remote helpers are named
        //: `<name>::<rest>` and `ext::` hands the rest to a shell, so a
        //: repository address is a way to run something if the scheme is not
        //: checked. A URL reaches this from a page.
        for address in [
            "ext::sh -c 'id > /tmp/pwned'",
            "ext::git-upload-pack %S",
            "EXT::sh -c whoami",
            "hg::/tmp/somewhere",
            "bzr::/tmp/somewhere",
            "transport::anything",
        ] {
            let refused = safe_remote(address);
            assert!(
                refused.is_err(),
                "{address} was accepted as a repository address"
            );
        }
    }

    #[test]
    fn the_transports_that_only_move_bytes_are_accepted() {
        for address in [
            "https://github.com/files-community/Files.git",
            "http://example.invalid/thing.git",
            "ssh://git@example.invalid/owner/repo.git",
            "git://example.invalid/repo.git",
            "file:///srv/repos/thing.git",
            //: The case is the URL's, not ours.
            "HTTPS://example.invalid/repo.git",
        ] {
            safe_remote(address).unwrap_or_else(|e| panic!("{address} was refused: {e:?}"));
        }
    }

    #[test]
    fn the_shorthand_a_host_hands_you_is_accepted_and_a_path_is_too() {
        //: What every hosting page's copy button produces, which is ssh.
        safe_remote("git@github.com:files-community/Files.git").unwrap();
        safe_remote("example.invalid:owner/repo").unwrap();
        //: And a repository on this machine, which is a legitimate clone.
        safe_remote("/srv/repos/thing.git").unwrap();
        safe_remote("./nearby.git").unwrap();
    }

    #[test]
    fn an_address_that_is_not_one_is_refused_rather_than_guessed_at() {
        assert!(safe_remote("").is_err());
        assert!(safe_remote("   ").is_err());
        assert!(safe_remote("just-a-word").is_err());
    }

    #[test]
    fn init_starts_a_repository_and_will_not_start_a_second_over_it() {
        let dir = empty("init");
        let dot = init(&dir, false).unwrap();
        assert!(dot.ends_with(".git/"), "{dot:?} is not the repository folder");
        assert!(info(&dir, false).unwrap().is_some(), "init made nothing readable");
        //: Twice is a mistake, and doing it silently would throw away the
        //: index and the config of the repository already there.
        assert!(matches!(init(&dir, false), Err(Error::Exists(_))));

        let bare_dir = empty("init-bare");
        let bare = init(&bare_dir, true).unwrap();
        assert_eq!(bare, fs::canonicalize(&bare_dir).unwrap().join(""));
    }

    #[test]
    fn a_clone_of_a_local_repository_brings_the_commits_and_reports_progress() {
        let origin = repo("clone-origin");
        let into = empty("clone-into");
        let _ = fs::remove_dir_all(&into);

        let mut seen = Vec::new();
        let work = clone(&local_url(&origin), &into, &mut |t| {
            seen.push(t);
            true
        })
        .unwrap();

        assert!(work.join("tracked.txt").exists(), "the clone has no files");
        let got = info(&work, false).unwrap().unwrap();
        assert!(got.entries.is_empty(), "a fresh clone had changes: {:?}", got.entries);
        assert_eq!(
            last_commit(&work, &work.join("tracked.txt")).unwrap().unwrap().summary,
            "first"
        );
        assert!(!seen.is_empty(), "nothing was reported while the objects came across");
        let last = seen.last().unwrap();
        assert_eq!(last.objects, last.total, "the last report is short of the total");
    }

    #[test]
    fn a_clone_will_not_be_written_over_a_folder_with_things_in_it() {
        let origin = repo("clone-over-origin");
        let into = empty("clone-over-into");
        fs::write(into.join("notes.txt"), b"a year of them\n").unwrap();

        let refused = clone(&local_url(&origin), &into, &mut unwatched);
        assert!(matches!(refused, Err(Error::Exists(_))), "got {refused:?}");
        assert!(into.join("notes.txt").exists(), "the file was taken anyway");
    }

    #[test]
    fn a_pull_fast_forwards_once_and_then_says_it_did_not_move() {
        let origin = repo("pull-origin");
        let into = empty("pull-into");
        let _ = fs::remove_dir_all(&into);
        let work = clone(&local_url(&origin), &into, &mut unwatched).unwrap();

        commit(&origin, "second.txt", "two\n");

        let pulled = pull(&work, None, &mut unwatched).unwrap();
        assert!(pulled.moved, "the branch did not move");
        assert!(work.join("second.txt").exists(), "the working tree was not updated");
        assert_eq!(pulled.fetched.behind, 0, "still behind after a fast forward");

        //: Again with nothing new, which has to be an answer and not a commit.
        let again = pull(&work, None, &mut unwatched).unwrap();
        assert!(!again.moved);
    }

    #[test]
    fn a_branch_that_has_moved_on_both_sides_is_not_merged_for_you() {
        let origin = repo("diverge-origin");
        let into = empty("diverge-into");
        let _ = fs::remove_dir_all(&into);
        let work = clone(&local_url(&origin), &into, &mut unwatched).unwrap();

        commit(&origin, "theirs.txt", "theirs\n");
        commit(&work, "mine.txt", "mine\n");

        //: A file manager quietly making a merge commit is a decision about
        //: history that the person did not ask for.
        let refused = pull(&work, None, &mut unwatched);
        assert!(matches!(refused, Err(Error::Conflict(_))), "got {refused:?}");
        let said = format!("{:?}", refused.unwrap_err());
        assert!(said.contains("both moved"), "the reason was not given: {said}");
        assert!(work.join("mine.txt").exists(), "the local commit was thrown away");
        assert!(!work.join("theirs.txt").exists(), "the tree was moved anyway");
    }

    #[test]
    fn a_push_sends_the_branch_and_the_remote_has_it_afterwards() {
        let bare_dir = empty("push-bare");
        init(&bare_dir, true).unwrap();
        let work = repo("push-work");
        let r = git2::Repository::open(&work).unwrap();
        r.remote("origin", &local_url(&bare_dir)).unwrap();
        drop(r);

        let branch = push(&work, None, &mut unwatched).unwrap();
        assert!(matches!(branch.as_str(), "main" | "master"), "pushed {branch}");

        let sent = git2::Repository::open_bare(&bare_dir).unwrap();
        let there = sent.find_branch(&branch, git2::BranchType::Local).unwrap();
        let mine = git2::Repository::open(&work).unwrap();
        let here = mine.head().unwrap();
        assert_eq!(
            there.get().peel_to_commit().unwrap().id(),
            here.peel_to_commit().unwrap().id(),
            "the remote is not on the commit that was pushed"
        );
    }

    #[test]
    fn a_repository_with_no_remote_says_so_rather_than_guessing() {
        let dir = repo("no-remote");
        let asked = fetch(&dir, None, &mut unwatched);
        assert!(matches!(asked, Err(Error::NotFound(_))), "got {asked:?}");
    }
    #[test]
    fn what_libgit2_does_with_a_helper_address_when_the_check_is_not_there() {
        //: The check refuses `ext::` before anything opens it. This records
        //: what the library underneath would have done, so the comment above
        //: the allowlist claims no more than it should: a policy that holds
        //: only because a dependency has not implemented a feature is not a
        //: policy, and this is the evidence for saying so either way.
        let into = empty("ext-reality");
        let _ = std::fs::remove_dir_all(&into);
        let mut watch = unwatched;
        let mut fetch = git2::FetchOptions::new();
        fetch.remote_callbacks(callbacks(&mut watch));
        let mut builder = git2::build::RepoBuilder::new();
        builder.fetch_options(fetch);
        let out = builder.clone("ext::sh -c 'touch /tmp/auradefs-ext-ran'", &into);
        let said = out.err().map(|e| e.message().to_string()).unwrap_or_default();
        assert!(!said.is_empty(), "libgit2 opened a remote helper address");
        //: Recorded rather than asserted word for word: the exact wording is
        //: libgit2's to change, and what matters is that it refused.
        //:
        //: There are two shapes of refusal, and which one appears is the
        //: build's, not ours. A libgit2 that knows the name says the
        //: transport is unsupported. One that does not falls through to the
        //: scp-like `host:path` reading, takes `ext` for a hostname and
        //: refuses when that does not resolve. The second shape is the one
        //: this machine produces. Both are refusals and neither runs the
        //: command, which is why the assertion below this one is the one
        //: carrying the security property: a libgit2 that had grown ext::
        //: support would reach it with the file in place, whatever it said
        //: on the way.
        let refused_as_unsupported =
            said.contains("unsupported") || said.contains("Unsupported");
        let refused_by_not_resolving =
            said.contains("failed to resolve address") || said.contains("Name or service");
        assert!(refused_as_unsupported || refused_by_not_resolving,
                "libgit2 refused for some other reason: {said}");
        assert!(
            !Path::new("/tmp/auradefs-ext-ran").exists(),
            "the address ran as a command"
        );
    }
}
