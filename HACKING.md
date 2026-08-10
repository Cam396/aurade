# HACKING: Running ChromiumOS Ash on Linux

## The core problem

ChromeOS has a daemon called `session_manager` that talks to the Chrome browser
over D-Bus/Mojo. One call it makes during login is
`SessionControllerImpl::SetUserSessionOrder()`, which triggers a cascade of
observer notifications:

```
SetUserSessionOrder()
  -> OnActiveUserSessionChanged(account_id)    // MultiUserWindowManager, DesksClient
  -> OnActiveUserPrefServiceChanged(prefs)     // ShelfController, Geolocation...
  -> SetSessionState(ACTIVE)                   // everyone else
```

On a real Chromebook, this cascade initializes half the Ash UI. On linux-chromeos
with `--login-manager --stub-config --stub-auth`, there's no `session_manager`
daemon, so **none of these observer methods ever fire**. Subsystems sit in their
default-constructed states, which are designed for the login screen, not an
active user session.

Every fix in the patch stack is a workaround for one of these unfired
notifications. There are two strategies:

**A) Provide a sensible default** — if a crash happens because an optional or
   pointer was never set, initialize it to a safe value at construction time.

**B) Poke the observer manually** — from the point in the Chrome startup where
   we know the user profile is available (`OnUserProfileLoaded`), call the
   observer method that `session_manager` would have triggered.

---

## What fires when

```
Timeline on real ChromeOS:

  session_manager daemon           Chrome
  ──────────────────────           ─────
                                   Shell::Init()
                                   Ash window server starts
                                   Shelf widget created (auto_hide=kAlwaysHidden)

  SetUserSessionOrder() ────────>  OnActiveUserSessionChanged()
                                   OnActiveUserPrefServiceChanged()
                                   SetSessionState(ACTIVE)
                                     -> Shelf auto_hide set to user pref
                                     -> DesksClient storage manager initialized
                                     -> MultiUserWindowManager sets current_account_id_
                                     -> Geolocation controller caches access level

Timeline on linux-chromeos:

  No session_manager                Chrome
  ──────────────────────           ─────
                                   Shell::Init()
                                   Ash window server starts
                                   Shelf widget created (auto_hide=kAlwaysHidden)
                                   Login UI shows (OOBE / sign-in screen)

  User types password ──────────>  OnUserProfileLoaded()
                                     (we inject missing notifications here)
                                   SetSessionState(ACTIVE)
                                     (via SessionStarted(), but key observers
                                      that depend on SetUserSessionOrder were
                                      never called, so they're still in their
                                      default-initialized state)
```

---

## The fixes

### Fix 1: Right-click crash (SIGABRT)

**File:** `ash/multi_user/multi_user_window_manager.cc`
**Root cause:** `current_account_id_` is a `std::optional<AccountId>`. It gets
set in `OnActiveUserSessionChanged()`, which never fires. When a right-click
creates a transient window, `*current_account_id_` dereferences an empty
optional. SIGABRT.
**Fix (A+B):** Guard the dereference with `has_value()`, and call
`OnActiveUserSessionChanged()` manually from the profile-loaded handler.

### Fix 2: Welcome-recap "Got it" crash (DCHECK in desk model)

**Files:** `chrome/browser/ui/ash/desks/desks_client.cc`,
`chrome/browser/ui/ash/main_extra_parts/chrome_browser_main_extra_parts_ash.cc`
**Root cause:** `DesksClient::OnActiveUserSessionChanged()` never fires, so
`save_and_recall_desks_storage_manager_` is never created. When the saved-desk
presenter calls `GetDeskModel()`, it DCHECKs on the null storage manager.
**Fix (B):** Call `DesksClient::OnActiveUserSessionChanged()` from the
profile-loaded handler.

### Fix 3: Welcome-recap "Got it" crash #2 (NOTREACHED in BirchBarController)

**File:** `ash/wm/overview/birch/birch_bar_controller.cc`
**Root cause:** Dismissing the welcome-recap dialog starts an informed-restore
session, which creates a `BirchBarController`. Its constructor calls
`GetPrimaryUserPrefService()`, which returns null because the pref service
isn't ready yet. `PrefChangeRegistrar::Init()` accepts null silently, but
`Add()` hits NOTREACHED.
**Fix (A):** Guard the constructor and all pref accessors: if the pref service
is null, skip pref registration and return false from getters.

### Fix 4: Settings crash (CHECK on empty optional)

**File:** `ash/system/privacy_hub/geolocation_privacy_switch_controller.cc`
**Root cause:** `cached_access_level_` is a `std::optional` set inside
`OnActiveUserPrefServiceChanged()`, which never fires. Opening Settings opens
the Privacy section, which calls `AccessLevel()`, which CHECKs that the
optional has a value.
**Fix (A):** Initialize `cached_access_level_` to `kAllowed` in the
constructor. If the real callback fires later, it overwrites the default.

### Fix 5: Invisible shelf (no space allocated)

**Files:** `chrome/browser/ui/ash/shelf/chrome_shelf_controller.cc`,
`chrome/browser/ui/ash/main_extra_parts/chrome_browser_main_extra_parts_ash.cc`
**Root cause:** `Shelf::auto_hide_behavior_` defaults to `kAlwaysHidden` (see
`shelf.h:348`). The comment says "hide the shelf until user preferences are
available." On real ChromeOS, `ShelfController::OnActiveUserPrefServiceChanged()`
sets it from the user's pref. On linux-chromeos, that call never comes.
**Fix (B):** From the profile-loaded handler, iterate all root windows and set
`auto_hide_behavior` to `kNever`, then force a visibility recalculation.

### Fix 6: LOGIN_PRIMARY shelf creation crash

**Files:** `chrome/browser/ui/ash/main_extra_parts/chrome_browser_main_extra_parts_ash.cc`
**Root cause:** Creating `ChromeShelfController` at `LOGIN_PRIMARY` with the
sign-in profile crashes because `AppServiceProxyFactory::GetForProfile()` fails
on the sign-in profile (no AppService).
**Fix:** Skip shelf creation at LOGIN_PRIMARY and wait until ACTIVE, when the
real user profile is available.

---

## The shelf init dance

The shelf has two layers:

- **Ash layer** (`ash/shelf/`): owns the `ShelfModel` singleton, the
  `ShelfWidget`, and the `ShelfLayoutManager`. Created during `Shell::Init()`.
  Starts with `auto_hide_behavior_ = kAlwaysHidden`.

- **Chrome layer** (`chrome/browser/.../chrome_shelf_controller.cc`): owns
  the app-model connection, pinned apps, and profile-specific prefs. Created
  at ACTIVE by `ChromeShelfControllerInitializer`.

The order matters:

1. `Shell::Init()` → Ash shelf widget exists but hidden.
2. Login screen shows.
3. User authenticates → profile loads → session enters ACTIVE.
4. `ChromeShelfControllerInitializer::OnSessionStateChanged()` fires:
   - Creates `ChromeShelfController` with the user's profile.
   - Calls `ShelfLayoutManager::UpdateVisibilityState()` to recalculate.
5. `OnUserProfileLoaded()` fires:
   - Sets `auto_hide_behavior` to `kNever` on all shelves.
   - Calls `UpdateVisibilityState()` again.

Step 5 is the hack. Without it, the shelf stays hidden because the pref-based
notification that normally sets `auto_hide_behavior` never arrives.

---

## The phantom system update

ChromeOS has a real update engine (`update_engine`) that checks Google's
servers for OS updates. On linux-chromeos, it may still be active. The
"System update" notification and restart prompt are real ChromeOS behavior,
not a bug. To disable it, you would need to either stub out `update_engine`
at the D-Bus level or pass a command-line flag. That's a separate task from
the crash fixes.

---

## Patch workflow

Patches live in `patches/` and are git-format diffs applied by
`build-chromeos-ash.sh` in `patches/SERIES` order:

```
patches/
  0001-local-accounts-core.patch
  0002-local-account-oobe.patch
  0003-local-account-login-flow.patch
  0004-session-lifecycle-generic-linux.patch
  ...
  0026-top-shelf-shell.patch
  0027-display-scaling-settings.patch
  0028-runtime-resources-linux.patch
```

Since 2026-07-09 the series is disjoint: every changed file is owned by
exactly one patch, so hunks never overlap and apply order is not
load-bearing. The full series reproduces the entire Chromium working tree
byte-for-byte; verify both properties with:

```bash
ci/verify-patch-series.sh --expect-tree-match
```

To move a file's changes between patches or capture new work, regenerate the
owning patch from the working tree (`git diff HEAD -- <owned files...>`,
with `git add -N` first for new files) rather than hand-editing hunks, and
re-run the verifier. The pre-normalization series is archived in
`patches-backup/2026-07-09-pre-normalize/`.

---

## What's still flaky

- **SWA install failure**: "Exceeded SWA install retry attempts" means no
  system web apps (Settings, Files, etc.) are installed. The shelf will have
  no pinned apps beyond the browser shortcut. This happens because the SWA
  manager starts at the sign-in profile, which doesn't have the right services,
  and exhausts its retry budget before the real user profile is available.
- **Update notification**: Real ChromeOS update_engine may prompt for restart.
- **Drive**, **metrics**, **Bluetooth**, **brightness**: all expected failures
  on linux-chromeos without the corresponding hardware or daemons.
