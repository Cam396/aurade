  /* ==========================================================================
     Commands
     ========================================================================== */

  // Files keeps every command in one table: a label, a description, a
  // category, a shortcut and an icon, with the menus, the toolbar, the
  // keyboard and the command palette all going through it rather than each
  // knowing its own list. This is that table under Files' own command names,
  // so what is here and what is there can be compared instead of guessed at.
  //
  // The descriptions come from assets/files-commands.json, which
  // tools/extract_commands.py generates out of the reference source. Nothing
  // is retyped: a label typed twice is a label that drifts the next time the
  // reference moves.
  const FILES_COMMANDS = __BUILD("COMMAND_TABLE_JSON");
  const COMMANDS = new Map();

  function cmd(code, spec) {
    const known = FILES_COMMANDS[code];
    if (!known) {
      console.warn('no such command in the reference table: ' + code);
      return;
    }
    COMMANDS.set(code, Object.assign({
      code: code,
      label: known.label || code,
      description: known.description || '',
      category: known.category,
      hotkeys: known.hotkeys || [],
      glyph: known.glyph || null,
      toggle: !!known.toggle,
      act: null,
      enabled: null,
      on: null,
      run: null,
      // A command this platform has no counterpart for keeps its row and says
      // why. A command that is missing and a command that cannot apply are
      // different facts, and the person reading the palette should be able to
      // tell them apart.
      unavailable: null
    }, spec));
  }

  // The ones already wired to a page action, joined up without moving any of
  // their code.
  function cmdAct(code, act, spec) {
    // The wired dispatcher, not the local one: `handleAction` answers a dozen
    // acts before this scope's `doAct` ever sees them, and calling `doAct`
    // directly would quietly do nothing for every one of those.
    cmd(code, Object.assign({
      act: act,
      run: (el) => (window.__doAct || doAct)(act, el)
    }, spec || {}));
  }

  window.__commands = COMMANDS;
  window.__runCommand = function (code, el) {
    const c = COMMANDS.get(code);
    if (!c || !c.run) return false;
    if (c.enabled && !c.enabled()) return false;
    c.run(el);
    return true;
  };
  // What the parity gate reads: every command, and what state it is in.
  window.__commandStates = function () {
    const out = {};
    COMMANDS.forEach((c, code) => {
      out[code] = c.unavailable ? 'unavailable' : (c.run ? 'ready' : 'stub');
    });
    return out;
  };

  // What Files' own conditions mean on this page. `COMMAND_WHEN` in
  // build_v3.py turns each command's `IsExecutable` into a call to these, so a
  // row appears and disappears for the reason the reference gives rather than
  // for one invented here. Everything the reference asks that this page has no
  // answer for is left out rather than guessed at.
  const atHome = () => {
    const hw = document.getElementById('home-widgets');
    return !!(hw && !hw.hidden);
  };
  const picked = () => (window.__live && window.__live.selection)
    ? window.__live.selection().length
    : document.querySelectorAll('.cell.sel, .row.sel, .lrow.sel').length;
  // The trash is a real place here, not a shell folder: it is the freedesktop
  // directory, and the sidebar lists it as a volume like any other.
  // Grouping is three settings, and a command can set any one of them or two
  // at once. Passing null for one leaves it as it was, which is what Files
  // does: choosing Month while grouped by date created regroups by month
  // without changing the field.
  const setGrouping = (field, unit) => {
    if (unit && window.__setGroupUnit) window.__setGroupUnit(unit);
    if (field && window.__setGroupBy) window.__setGroupBy(field);
    else if (unit && window.__setGroupBy) window.__setGroupBy(window.__groupBy());
  };
  const setGroupWay = (dir) => {
    if (window.__setGroupDir) window.__setGroupDir(dir);
  };
  const inTrash = () => {
    const p = (window.__livePath || (activeTab() ? activeTab().path : '')) || '';
    return p.indexOf('/.local/share/Trash') !== -1;
  };

__BUILD("COMMAND_REGISTRATIONS")

  // ---- Display: sorting -------------------------------------------------
  const sortField = (f) => (window.__sortBy ? window.__sortBy(f) : false);
  cmd('SortByPath', {run: () => sortField('Path'),
    on: () => sortState.fieldName === 'Path'});
  cmd('SortByTag', {run: () => sortField('Tag'),
    on: () => sortState.fieldName === 'Tag'});
  cmd('SortBySyncStatus', {run: () => sortField('Sync status'),
    on: () => sortState.fieldName === 'Sync status'});
  cmd('SortByDateDeleted', {run: () => sortField('Date deleted'),
    on: () => sortState.fieldName === 'Date deleted'});
  cmd('SortByOriginalFolder', {run: () => sortField('Original folder'),
    on: () => sortState.fieldName === 'Original folder'});
  cmd('ToggleSortDirection', {run: () => {
    sortState.dir = sortState.dir === 1 ? -1 : 1;
    applySort(); updateSortChevron();
  }});
  // Where folders sit relative to files. One setting with three values, so
  // each command sets its own rather than toggling.
  function folderOrder(which) {
    sortState.folderGroup = which;
    applySort(); updateSortChevron();
  }
  cmd('SortFoldersFirst', {run: () => folderOrder('Folders first'),
    on: () => sortState.folderGroup === 'Folders first'});
  cmd('SortFilesFirst', {run: () => folderOrder('Files first'),
    on: () => sortState.folderGroup === 'Files first'});
  cmd('SortFilesAndFoldersTogether', {
    run: () => folderOrder('Files and folders together'),
    on: () => sortState.folderGroup === 'Files and folders together'});

  // ---- Display: grouping ------------------------------------------------
  // Every grouping command is generated above, out of what each one says it
  // toggles: the field, the date unit, the direction, or a field and a unit
  // together. Nineteen registrations written by hand used to sit here, each
  // with its own copy of the state, which is one implementation too many: the
  // menu asked one of them for the check mark while the other one held the
  // answer. These two are what is left, because a command that cycles a
  // setting rather than choosing a value is not a toggle and says nothing
  // about which value it lands on.
  const GROUP_UNITS = ['year', 'month', 'day'];
  cmd('ToggleGroupByDateUnit', {run: () => {
    const at = GROUP_UNITS.indexOf(window.__groupUnit());
    setGrouping(null, GROUP_UNITS[(at + 1) % GROUP_UNITS.length]);
  }});
  cmd('ToggleGroupDirection', {
    run: () => setGroupWay(window.__groupDir() === 1 ? -1 : 1)});
  // Every column wide enough for what is in it, which is what a double click
  // on a column edge does and what the menu row means.
  cmd('AutoFitColumns', {run: () => {
    if (window.__cols && typeof window.__cols.autoFit === 'function') {
      window.__cols.autoFit();
      return;
    }
    setLayout('details');
  }});

  // ---- Navigation: history, tabs and panes ------------------------------
  const activeTab = () => tabs.find(t => t.id === activeTabId);
  cmd('NavigateBack', {run: () => goNavBack(),
    enabled: () => { const t = activeTab(); return !!t && t.histIdx > 0; }});
  cmd('NavigateForward', {run: () => goNavForward(),
    enabled: () => {
      const t = activeTab();
      return !!t && t.histIdx < t.history.length - 1;
    }});
  cmd('NavigateUp', {run: () => goNavUp()});
  cmd('NavigateHome', {run: () => navigateTo('~', 'Home', true, true)});
  cmd('NewWindow', {run: () => window.open(location.href, '_blank')});
  cmd('NextTab', {run: () => stepTab(1), enabled: () => tabs.length > 1});
  cmd('PreviousTab', {run: () => stepTab(-1), enabled: () => tabs.length > 1});
  function stepTab(by) {
    const at = tabs.findIndex(t => t.id === activeTabId);
    if (at < 0 || tabs.length < 2) return;
    const next = (at + by + tabs.length) % tabs.length;
    switchTab(tabs[next].id);
  }
  cmd('CloseAllTabs', {run: () => {
    tabs.slice().forEach(t => closeTab(t.id));
  }, enabled: () => tabs.length > 0});

  // The panes. setupDualPane already knows how to open, close, arrange and
  // move focus between them, so each command is the one call that means it.
  const panes = () => (window.__dualPane || dualPaneApi || null);
  const dual = () => {
    const p = panes();
    return !!(p && p.isDualPaneActive && p.isDualPaneActive());
  };
  cmd('ToggleDualPane', {run: () => {
    const p = panes(); if (p) p.toggleDualPane();
  }, on: dual});
  cmd('SplitPaneVertically', {run: () => openPane('vertical'), on: dual});
  cmd('SplitPaneHorizontally', {run: () => openPane('horizontal'), on: dual});
  cmd('ArrangePanesVertically', {run: () => arrangePanes('vertical'),
    on: () => paneArrangement === 'vertical'});
  cmd('ArrangePanesHorizontally', {run: () => arrangePanes('horizontal'),
    on: () => paneArrangement === 'horizontal'});
  cmd('CloseActivePane', {run: () => {
    const p = panes(); if (p && p.closeSecondaryPane) p.closeSecondaryPane();
  }, enabled: dual});
  cmd('FocusOtherPane', {run: () => {
    const p = panes(); if (p && p.focusOtherPane) p.focusOtherPane();
  }, enabled: dual});
  let paneArrangement = 'vertical';
  function arrangePanes(how) {
    paneArrangement = how;
    // Which way the splitter runs is a class on the container, so the same
    // two panes read as side by side or one above the other.
    const box = document.querySelector('.dual-pane-container');
    if (box) box.classList.toggle('stacked', how === 'horizontal');
  }
  function openPane(how) {
    const p = panes();
    if (!p) return;
    if (!dual()) p.toggleDualPane();
    arrangePanes(how);
  }
  // Opening something in the other pane is the second pane plus a navigation
  // in it, and the three entry points differ only in where the path comes
  // from: the list, the Home page, or the sidebar.
  function pathOf(el) {
    const from = el || ctxTarget;
    if (!from || !from.getAttribute) return null;
    return from.getAttribute('data-p') || from.getAttribute('data-path')
        || from.getAttribute('data-root') || null;
  }
  function intoOtherPane(el) {
    const where = pathOf(el);
    if (!where) return;
    const p = panes();
    if (p && !dual()) p.toggleDualPane();
    if (p && p.focusOtherPane) p.focusOtherPane();
    navigateTo(where, where.split('/').pop() || where, false, true);
  }
  ['OpenInNewPane', 'OpenInNewPaneFromHome', 'OpenInNewPaneFromSidebar',
   'OpenInOtherPane', 'OpenInOtherPaneFromHome', 'OpenInOtherPaneFromSidebar'
  ].forEach(code => cmd(code, {
    run: (el) => intoOtherPane(el),
    enabled: (el) => !!pathOf(el)
  }));
  cmd('OpenCurrentFolderInOtherPane', {run: () => {
    const t = activeTab();
    const p = panes();
    if (p && !dual()) p.toggleDualPane();
    if (p && p.focusOtherPane) p.focusOtherPane();
    if (t) navigateTo(t.path, t.name, t.isHome, true);
  }});

  // ---- Show: the panes and the things that are hidden --------------------
  function pressButton(sel) {
    const b = $(sel);
    if (!b) return false;
    b.click();
    return true;
  }
  cmd('ToggleFilterHeader', {run: () => pressButton('#btn-filter'),
    on: () => { const f = $('#frow'); return !!(f && !f.hidden); }});
  const detailsShown = () => {
    const pane = $('#infopane');
    return !!(pane && !pane.hidden);
  };
  cmd('ToggleInfoPane', {run: () => pressButton('#btn-pane'), on: detailsShown});
  cmd('ToggleDetailsPane', {run: () => {
    if (!detailsShown()) pressButton('#btn-pane');
    const tab = $('#infopane [data-itab="details"]');
    if (tab) tab.click();
  }, on: () => detailsShown() &&
    !!$('#infopane [data-itab="details"].on')});
  cmd('TogglePreviewPane', {run: () => {
    if (!detailsShown()) pressButton('#btn-pane');
    const tab = $('#infopane [data-itab="preview"]');
    if (tab) tab.click();
  }, on: () => detailsShown() &&
    !!$('#infopane [data-itab="preview"].on')});
  const sidebarShown = () => {
    const bar = $('#sidebar');
    return !!(bar && !bar.classList.contains('collapsed') && !bar.hidden);
  };
  cmd('ToggleSidebar', {run: () => {
    const bar = $('#sidebar');
    if (bar) bar.classList.toggle('collapsed');
  }, on: sidebarShown});
  cmd('ToggleToolbar', {run: () => {
    const bar = $('#toolbar') || document.querySelector('.toolbar');
    if (bar) bar.hidden = !bar.hidden;
  }, on: () => {
    const bar = $('#toolbar') || document.querySelector('.toolbar');
    return !!(bar && !bar.hidden);
  }});
  // Two settings rather than one: Windows hides by an attribute and Linux by
  // a leading dot, and Files offers both switches, so both are kept.
  function flipPref(key) {
    setPref(key, !getPref(key));
    if (window.__live && window.__live.path && window.__live.render) {
      window.__live.render(window.__live.path);
    }
  }
  cmd('ToggleShowHiddenItems', {run: () => flipPref('showHidden'),
    on: () => !!getPref('showHidden')});
  cmd('ToggleDotFilesSetting', {run: () => flipPref('showHidden'),
    on: () => !!getPref('showHidden')});
  cmd('ToggleShowFileExtensions', {run: () => flipPref('showExt'),
    on: () => !!getPref('showExt')});

  // ---- Global ------------------------------------------------------------
  cmd('Search', {run: () => {
    const box = $('#osearch');
    if (box) { box.hidden = false; box.focus(); box.select(); return; }
    pressButton('#btn-filter');
  }});
  cmd('EditPath', {run: () => {
    // The breadcrumb becomes a path box, which is what Ctrl+L does there.
    const crumbs = $('#crumbs') || document.querySelector('.crumbs');
    const box = $('#pathbox');
    if (box) {
      box.hidden = false;
      if (crumbs) crumbs.hidden = true;
      const t = activeTab();
      box.value = t ? t.path : '';
      box.focus();
      box.select();
      return;
    }
    if (crumbs) crumbs.click();
  }});
  cmd('Redo', {run: () => (window.__doAct || doAct)('redo')});
  cmd('SetLightTheme', {run: () => setTheme('light'),
    on: () => document.documentElement.dataset.theme === 'light'});
  cmd('SetDarkTheme', {run: () => setTheme('dark'),
    on: () => document.documentElement.dataset.theme === 'dark'});
  cmd('SetDefaultTheme', {run: () => setTheme(''),
    on: () => !document.documentElement.dataset.theme});
  cmd('ToggleAppTheme', {run: () => {
    setTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light');
  }});
  const isFull = () => !!document.fullscreenElement;
  cmd('ToggleFullScreen', {run: () => {
    if (isFull()) document.exitFullscreen();
    else document.documentElement.requestFullscreen().catch(() => {});
  }, on: isFull});
  // Compact overlay is Windows' always on top miniature window. The nearest
  // true thing here is the same window with everything but the list put away,
  // which is what the mode is for and what a person wants from it.
  let compact = false;
  function setCompact(on) {
    compact = !!on;
    document.documentElement.toggleAttribute('data-compact', compact);
  }
  cmd('EnterCompactOverlay', {run: () => setCompact(true), enabled: () => !compact});
  cmd('ExitCompactOverlay', {run: () => setCompact(false), enabled: () => compact});
  cmd('ToggleCompactOverlay', {run: () => setCompact(!compact), on: () => compact});

  // ---- reaching the backend ----------------------------------------------
  // One place that knows how to ask, so a command is the request it makes and
  // nothing else. Without a backend the command says so rather than failing
  // silently, because a menu row that does nothing teaches people to stop
  // trusting the menu.
  async function ask(route, body) {
    const api = window.__api;
    if (!api) {
      if (window.__toast) window.__toast('That needs the live backend.');
      throw new Error('no backend');
    }
    const r = await fetch(api + route, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body || {})
    });
    const answer = await r.json().catch(() => ({}));
    if (!r.ok) {
      const said = answer.error || ('http ' + r.status);
      if (window.__toast) window.__toast(said);
      const failed = new Error(said);
      failed.code = answer.code || '';
      throw failed;
    }
    return answer;
  }
  function quietly(work) {
    return () => { work().catch(() => {}); };
  }
  const selectedPaths = () => (window.__live && window.__live.selection)
    ? window.__live.selection()
    : selectedItems().map(el => el.getAttribute('data-p')).filter(Boolean);
  const onePath = (el) => pathOf(el) ||
    (selectedPaths().length === 1 ? selectedPaths()[0] : null);
  const here = () => {
    const t = activeTab();
    return (window.__livePath) || (t ? t.path : '');
  };
  function refreshHere() {
    if (window.__live && window.__live.render && window.__livePath) {
      window.__live.render(window.__livePath);
    } else {
      (window.__doAct || doAct)('ctx-refresh');
    }
  }

  // ---- FileSystem --------------------------------------------------------
  //: New. The reference opens AddItemDialog and acts on what was picked,
  //: rather than dropping a flyout: AddItemAction.ExecuteAsync.
  cmd('AddItem', {run: async () => {
    const pick = await openDialog('dlg-additem');
    if (pick === 'folder' || pick === 'file' || pick === 'shortcut') {
      (window.__doAct || doAct)('new' + pick);
    }
  }});
  cmd('OpenParentFolder', {run: () => goNavUp()});
  cmd('CopyItemFromHome', {run: (el) => (window.__doAct || doAct)('copy', el)});
  // The path in quotes, which is what a shell wants and what the plain copy
  // leaves you to add by hand.
  function copyText(text) {
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(() => {});
    }
    if (window.__toast) window.__toast('Copied');
  }
  const quoted = (paths) => paths.map(p => '"' + p + '"').join(' ');
  cmd('CopyPathWithQuotes', {
    run: (el) => copyText(quoted([onePath(el)].filter(Boolean))),
    enabled: (el) => !!onePath(el)});
  cmd('CopyItemPathWithQuotes', {
    run: () => copyText(quoted(selectedPaths())),
    enabled: () => selectedPaths().length > 0});
  cmd('FlattenFolder', {run: quietly(async () => {
    await ask('/api/flatten', {path: here()});
    refreshHere();
  })});
  cmd('CreateFolderWithSelection', {run: quietly(async () => {
    const paths = selectedPaths();
    if (!paths.length) return;
    await ask('/api/folder-with-selection', {paths: paths, dir: here()});
    refreshHere();
  }), enabled: () => selectedPaths().length > 0});
  cmd('EmptyRecycleBin', {run: quietly(async () => {
    if (!confirm('Empty the trash? This cannot be undone.')) return;
    await ask('/api/empty-trash', {});
    refreshHere();
  })});
  cmd('RestoreRecycleBin', {run: quietly(async () => {
    const paths = selectedPaths();
    if (!paths.length) return;
    await ask('/api/restore', {paths: paths});
    refreshHere();
  }), enabled: () => selectedPaths().length > 0});
  cmd('RestoreAllRecycleBin', {run: quietly(async () => {
    await ask('/api/restore-all', {});
    refreshHere();
  })});
  // A named stream on a file, which on Linux is an extended attribute in the
  // user namespace. Files calls it an alternate data stream because that is
  // what NTFS calls it; the thing itself is the same idea.
  cmd('CreateAlternateDataStream', {run: quietly(async () => {
    const path = onePath(null);
    if (!path) return;
    const name = window.prompt('Name for the new stream:');
    if (!name) return;
    await ask('/api/stream', {path: path, name: name, data: ''});
    if (window.__toast) window.__toast('Stream created');
  }), enabled: () => selectedPaths().length === 1});
  cmd('PasteItemAsShortcut', {run: quietly(async () => {
    const clip = window.__clipboardPaths ? window.__clipboardPaths() : [];
    if (!clip.length) {
      if (window.__toast) window.__toast('Nothing to paste');
      return;
    }
    //: `link` is the whole path of the link to make. It was `dir`, which
    //: neither backend has ever taken: the Python one answers 400 target and
    //: link required and the Rust one 400 path is required, so this command
    //: had never once made a shortcut.
    for (const from of clip) {
      const base = (from.split('/').pop() || 'item');
      const into = here().replace(/\/+$/, '');
      await ask('/api/mksymlink',
                {target: from, link: into + '/' + base + ' - Shortcut'});
    }
    refreshHere();
  })});
  cmd('OpenItemWithApplicationPicker', {
    run: (el) => (window.__doAct || doAct)('ctx-openwith', el)});

  // ---- Content -----------------------------------------------------------
  cmd('ToggleSelect', {run: (el) => {
    const item = el || ctxTarget || selectedItems()[0];
    if (item) item.classList.toggle('sel');
    updateStatus();
  }});
  cmd('RunAsAdmin', {run: quietly(async () => {
    const path = onePath(null);
    if (path) await ask('/api/run-admin', {path: path});
  }), enabled: () => selectedPaths().length === 1});
  cmd('RunAsAnotherUser', {run: quietly(async () => {
    const path = onePath(null);
    if (!path) return;
    const who = window.prompt('Run as which user?');
    if (!who) return;
    await ask('/api/run-admin', {path: path, user: who});
  }), enabled: () => selectedPaths().length === 1});
  cmd('InstallFont', {run: quietly(async () => {
    const paths = selectedPaths();
    if (!paths.length) return;
    await ask('/api/font', {paths: paths});
    if (window.__toast) window.__toast('Font installed');
  }), enabled: () => selectedPaths().length > 0});
  cmd('InstallCertificate', {run: quietly(async () => {
    const path = onePath(null);
    if (!path) return;
    await ask('/api/certificate', {path: path});
    if (window.__toast) window.__toast('Certificate installed');
  }), enabled: () => selectedPaths().length === 1});
  cmd('SetAsWallpaperBackground', {run: quietly(async () => {
    const path = onePath(null);
    if (!path) return;
    await ask('/api/wallpaper', {path: path});
    if (window.__toast) window.__toast('Wallpaper set');
  }), enabled: () => selectedPaths().length === 1});
  cmd('SetAsSlideshowBackground', {run: quietly(async () => {
    const paths = selectedPaths();
    if (!paths.length) return;
    await ask('/api/wallpaper', {paths: paths, mode: 'slideshow'});
    if (window.__toast) window.__toast('Slideshow set');
  }), enabled: () => selectedPaths().length > 0});
  cmd('OpenAllTagged', {run: quietly(async () => {
    const tag = ctxTarget && ctxTarget.getAttribute('data-tag');
    if (!tag) return;
    navigateTo('tag:' + tag, tag, false, true);
  })});
  cmd('PlayAll', {run: quietly(async () => {
    const paths = selectedPaths();
    if (!paths.length) return;
    await ask('/api/open', {paths: paths});
  }), enabled: () => selectedPaths().length > 0});
  // Space on a selected file, which is the preview a person expects from
  // every other file manager and the one Files puts on that key.
  cmd('LaunchPreviewPopup', {run: () => {
    if (!detailsShown()) pressButton('#btn-pane');
    const tab = $('#infopane [data-itab="preview"]');
    if (tab) tab.click();
  }});

  // ---- Open --------------------------------------------------------------
  cmd('OpenSettings', {run: () => openSettings()});
  cmd('OpenCommandPalette', {run: () => openPal()});
  cmd('OpenTerminal', {run: quietly(async () => {
    await ask('/api/terminal', {path: here()});
  })});
  cmd('OpenTerminalFromHome', {run: quietly(async () => {
    await ask('/api/terminal', {path: here()});
  })});
  cmd('OpenTerminalFromSidebar', {run: quietly(async (el) => {
    await ask('/api/terminal', {path: pathOf(el) || here()});
  })});
  cmd('OpenTerminalAsAdmin', {run: quietly(async () => {
    await ask('/api/run-terminal', {path: here(), admin: true});
  })});
  // Files opens the folder in whichever IDE it found. The one to use is a
  // setting here rather than a probe, because guessing wrong launches
  // something the person did not ask for.
  const ideName = () => getPref('ideName') || 'the editor';
  cmd('OpenInIDE', {run: quietly(async () => {
    await ask('/api/run', {command: getPref('idePath'), args: [here()]});
  }), enabled: () => !!getPref('idePath'),
    label: 'Open folder in ' + ideName()});
  cmd('OpenRepoInIDE', {run: quietly(async () => {
    const root = (window.__git && window.__git.root) ? window.__git.root() : here();
    await ask('/api/run', {command: getPref('idePath'), args: [root]});
  }), enabled: () => !!getPref('idePath'),
    label: 'Open repo in ' + ideName()});
  cmd('EditInNotepad', {run: quietly(async () => {
    const path = onePath(null);
    if (path) await ask('/api/run', {command: 'xdg-open', args: [path]});
  }), enabled: () => selectedPaths().length === 1,
    label: 'Edit in the text editor'});
  cmd('CustomizeToolbar', {run: () => {
    openSettings();
    const row = document.querySelector('[data-spage="toolbar"]');
    if (row) row.click();
  }});
  cmd('OpenReleaseNotes', {run: () => {
    openSettings();
    const row = document.querySelector('[data-spage="about"]');
    if (row) row.click();
  }});
  cmd('OpenHelp', {run: () => {
    openSettings();
    const row = document.querySelector('[data-spage="about"]');
    if (row) row.click();
  }});
  cmd('OpenSettingsFile', {run: quietly(async () => {
    await ask('/api/open', {paths: [settingsFilePath()]});
  })});
  cmd('OpenLogFile', {run: quietly(async () => {
    await ask('/api/open', {paths: [logFilePath()]});
  })});
  cmd('OpenLogFileLocation', {run: () => {
    const at = logFilePath();
    navigateTo(at.slice(0, at.lastIndexOf('/')) || '/', 'Logs', false, true);
  }});
  // Where this keeps its own two files, by the XDG rules rather than beside
  // the program, because a config file in the install directory is a file
  // nobody can write and nobody finds.
  const homeDir = () => (window.__caps && window.__caps.home) || '~';
  const settingsFilePath = () => homeDir() + '/.config/aurade/files.json';
  const logFilePath = () => homeDir() + '/.local/state/aurade/files.log';

  // ---- the shelf ---------------------------------------------------------
  const shelf = () => window.__shelf || null;
  cmd('ToggleShelfPane', {run: () => {
    const pane = $('#shelf');
    if (pane) pane.hidden = !pane.hidden;
  }, on: () => { const p = $('#shelf'); return !!(p && !p.hidden); }});
  cmd('CopyItemFromShelf', {run: () => {
    const s = shelf();
    if (s) copyText(s.selected().join('\n'));
  }, enabled: () => !!(shelf() && shelf().selected().length)});
  cmd('CutItemFromShelf', {run: () => {
    const s = shelf();
    if (!s) return;
    copyText(s.selected().join('\n'));
    s.selected().forEach(p => s.remove(p));
  }, enabled: () => !!(shelf() && shelf().selected().length)});
  cmd('DeleteItemFromShelf', {run: () => {
    const s = shelf();
    if (!s) return;
    s.selected().forEach(p => s.remove(p));
  }, enabled: () => !!(shelf() && shelf().selected().length)});

  // ---- the sidebar -------------------------------------------------------
  cmd('CopyItemFromSidebar', {run: (el) => copyText(pathOf(el) || ''),
    enabled: (el) => !!pathOf(el)});
  cmd('UnpinFolderFromSidebar', {run: quietly(async (el) => {
    const path = pathOf(el);
    if (!path) return;
    const api = window.__api;
    if (!api) return;
    await fetch(api + '/api/bookmark?path=' + encodeURIComponent(path),
                {method: 'DELETE'});
    if (window.__toast) window.__toast('Unpinned');
  }), enabled: (el) => !!pathOf(el)});


  // ---- Git: the remote half ----------------------------------------------
  //
  // Six commands that reach a network, so all six go through the job machinery
  // rather than a plain request: a clone of anything real is a progress bar
  // and a Cancel, not a menu row that appears to have done nothing for a
  // minute. The service holds no credentials of its own; it asks the ssh agent
  // and git's own credential helper, the same two places the person's own git
  // asks, so a remote nobody has offered a credential for fails saying so.
  // What the backend said it can do. Read off the shared object rather than
  // through a function of its own: this scope cannot see `can`, and one
  // bridge that goes stale is better than two.
  const can = (name) => !!(window.__caps && Array.isArray(window.__caps.names) &&
                           window.__caps.names.indexOf(name) >= 0);
  const havePowershell = () => !!(window.__caps && window.__caps.powershell);
  const gitInfo = () => (window.__git && window.__git.info) ? (window.__git.info() || {}) : {};
  const inRepo = () => !!gitInfo().repo;
  const gitRemote = () => can('git-remote');
  function afterGit(said) {
    if (window.__git && window.__git.refresh) window.__git.refresh();
    refreshHere();
    if (said && window.__toast) window.__toast(said);
  }
  // The job runner lives in the scope that owns the backend, so it is reached
  // through the window and not by name: calling it directly here is a
  // NameError at click time rather than at build time.
  async function gitJob(route, body, title) {
    if (!window.__runJob) return ask(route, body);
    return window.__runJob(route, body, {title: title, subtitle: body.path || body.url || ''},
                           'copy', 600000);
  }

  cmd('GitInit', {run: quietly(async () => {
    await ask('/api/git/init', {path: here()});
    afterGit('Repository started');
  }), enabled: () => gitRemote() && !!here() && !inRepo()});

  cmd('GitClone', {run: quietly(async () => {
    //: The reference's CloneRepoDialog: the address, and the folder is what
    //: git itself names it, the last piece of the address with .git off. It
    //: was two window.prompt boxes.
    const url = await askClone('');
    if (!url) return;
    const name = url.replace(/[\/]+$/, '').split(/[\/:]/).pop()
                    .replace(/\.git$/, '') || 'repository';
    const into = here().replace(/\/+$/, '') + '/' + name;
    await gitJob('/api/git/clone', {url: url, into: into}, 'Cloning ' + url);
    afterGit('Cloned into ' + name);
  }), enabled: () => gitRemote() && !!here()});

  cmd('GitFetch', {run: quietly(async () => {
    const got = await gitJob('/api/git/fetch', {path: here()}, 'Fetching');
    afterGit(got && got.behind ? (got.behind + ' to pull') : 'Up to date');
  }), enabled: () => gitRemote() && inRepo()});

  cmd('GitPull', {run: quietly(async () => {
    const got = await gitJob('/api/git/pull', {path: here()}, 'Pulling');
    afterGit(got && got.moved ? 'Pulled' : 'Already up to date');
  }), enabled: () => gitRemote() && inRepo()});

  cmd('GitPush', {run: quietly(async () => {
    const got = await gitJob('/api/git/push', {path: here()}, 'Pushing');
    afterGit('Pushed ' + ((got && got.branch) || ''));
  }), enabled: () => gitRemote() && inRepo()});

  cmd('GitSync', {run: quietly(async () => {
    await gitJob('/api/git/sync', {path: here()}, 'Syncing');
    afterGit('In sync');
  }), enabled: () => gitRemote() && inRepo()});

  // ---- the last of the Windows only rows ---------------------------------
  //
  // Set as app background is the app's own backdrop, which is a preference
  // this page already has, so it is set here rather than asked of anyone.
  cmd('SetAsAppBackground', {run: () => {
    const path = onePath(null);
    if (!path) return;
    if (window.__setPref) window.__setPref('bgImagePath', path);
    if (window.__toast) window.__toast('Background set');
  }, enabled: () => selectedPaths().length === 1});

  // PowerShell is a real program on this system when it is installed, so this
  // is the command Files has and not a stand in. `-File`, so the script's
  // path is one argument to the interpreter and never part of a string it
  // parses. When pwsh is not installed the row says so instead of failing.
  cmd('RunWithPowershell', {run: quietly(async () => {
    const path = onePath(null);
    if (!path) return;
    await ask('/api/powershell', {path: path});
  }), enabled: () => havePowershell() && selectedPaths().length === 1,
    unavailable: null});

  // Pin to Start, in the shape this desktop has one: a desktop entry in the
  // applications directory, which the launcher and the search both already
  // read. A list of our own would show up in exactly one place.
  cmd('PinToStart', {run: quietly(async () => {
    const path = onePath(null) || here();
    if (!path) return;
    await ask('/api/pin-to-launcher', {path: path});
    if (window.__toast) window.__toast('Pinned to the launcher');
  }), enabled: () => !!(onePath(null) || here())});
  cmd('UnpinFromStart', {run: quietly(async () => {
    const path = onePath(null) || here();
    if (!path) return;
    await ask('/api/unpin-from-launcher', {path: path});
    if (window.__toast) window.__toast('Unpinned from the launcher');
  }), enabled: () => !!(onePath(null) || here())});

  // ---- the keyboard ------------------------------------------------------
  //
  // Files gives seventy one of its commands a shortcut and some of them two.
  // They are in the table already, so binding them from the registry means
  // the key, the menu row and the palette all come from the same line of the
  // reference, rather than from three lists that drift apart.
  //
  // Matched on `code` and not on `key` wherever the reference names a letter
  // or a digit. With shift held the 3 key reports "#" and the n key reports
  // "N", so a table written against `key` would miss Ctrl+Shift+3 entirely
  // and match Ctrl+Shift+N only by luck of the layout.
  const KEY_CODE = {
    ',': 'Comma', '.': 'Period', '-': 'Minus', '+': 'Equal', '/': 'Slash',
    '\\': 'Backslash', '[': 'BracketLeft', ']': 'BracketRight',
    ';': 'Semicolon', "'": 'Quote', '`': 'Backquote',
    'Space': 'Space', 'Enter': 'Enter', 'Tab': 'Tab', 'Esc': 'Escape',
    'Delete': 'Delete', 'Backspace': 'Backspace', 'Menu': 'ContextMenu',
    'Up': 'ArrowUp', 'Down': 'ArrowDown', 'Left': 'ArrowLeft',
    'Right': 'ArrowRight', 'Home': 'Home', 'End': 'End',
    'PageUp': 'PageUp', 'PageDown': 'PageDown'
  };
  // Four the reference names that a page cannot be given. Mouse4 and Mouse5
  // are buttons, and the browser keeps its own navigation keys. Listed rather
  // than dropped silently, so the count of what is bound can say why the rest
  // is not.
  const NOT_A_KEY = ['Mouse4', 'Mouse5', 'GoBack', 'GoForward'];

  function keyCode(face) {
    if (!face || NOT_A_KEY.indexOf(face) >= 0) return null;
    if (/^[A-Za-z]$/.test(face)) return 'Key' + face.toUpperCase();
    if (/^[0-9]$/.test(face)) return 'Digit' + face;
    if (/^F([1-9]|1[0-2])$/.test(face)) return face;
    if (/^Numpad [0-9]$/.test(face)) return 'Numpad' + face.slice(-1);
    return KEY_CODE[face] || null;
  }

  // "Ctrl+Shift+N" into its pieces. Not a plain split: `Ctrl++` is Ctrl and
  // the plus key, and splitting on every plus leaves two empty pieces where
  // the key should be.
  function keyParts(text) {
    const out = [];
    let piece = '';
    for (const ch of String(text || '')) {
      if (ch === '+' && piece) { out.push(piece); piece = ''; }
      else piece += ch;
    }
    if (piece) out.push(piece);
    return out;
  }

  // One shortcut as the string a keydown is turned into, or null when the
  // reference names something this cannot listen for.
  function shortcutKey(text) {
    const pieces = keyParts(text);
    if (!pieces.length) return null;
    const face = pieces[pieces.length - 1];
    const code = keyCode(face);
    if (!code) return null;
    const held = pieces.slice(0, -1).map(p => p.toLowerCase());
    return [held.indexOf('ctrl') >= 0 ? 'C' : '',
            held.indexOf('alt') >= 0 ? 'A' : '',
            held.indexOf('shift') >= 0 ? 'S' : '',
            code].join('');
  }

  function pressed(e) {
    return [e.ctrlKey || e.metaKey ? 'C' : '', e.altKey ? 'A' : '',
            e.shiftKey ? 'S' : '', e.code].join('');
  }

  // One shortcut the page answers better than the registry can, so the
  // registry does not take it. Bare Enter opens whatever the keyboard focus
  // is on, which is what a person means by it after arrowing through a list;
  // Files' OpenItem works from the selection, and after an arrow key those
  // are not the same item. The command keeps its row in every menu and in the
  // palette, and its shortcut is still what the reference says it is; only
  // the key binding defers.
  const PAGE_ANSWERS = ['Enter'];

  const HOTKEYS = new Map();
  //: Every shortcut the reference declares that this cannot listen for, kept
  //: so the count is honest about what is bound and what is not.
  const UNBOUND = [];
  (function bindHotkeys() {
    COMMANDS.forEach((c, code) => {
      (c.hotkeys || []).forEach(text => {
        const combo = shortcutKey(text);
        if (!combo) { UNBOUND.push([code, text]); return; }
        //: The first command to claim a key keeps it. Three of them ask for
        //: Ctrl+` and three for Ctrl+Alt+Enter, because Files has one command
        //: per place the row can be clicked from and they all do the same
        //: thing; the second registration taking the key would be a coin toss
        //: about which of the three runs.
        if (PAGE_ANSWERS.indexOf(combo) >= 0) return;
        if (!HOTKEYS.has(combo)) HOTKEYS.set(combo, code);
      });
    });
  })();
  window.__hotkeys = () => {
    const out = {};
    HOTKEYS.forEach((code, combo) => { out[combo] = code; });
    return out;
  };
  window.__unboundHotkeys = () => UNBOUND.slice();

  // On the window and in the capture phase, which is the whole point: an
  // event dispatched at the document reaches the window's capture listener
  // first, so a shortcut the registry claims runs the registry's command and
  // the older handlers below never see it. Anything the registry does not
  // claim passes straight through to them.
  window.addEventListener('keydown', (e) => {
    if (e.defaultPrevented || e.repeat) return;
    const t = e.target;
    const typing = !!(t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' ||
                            t.isContentEditable));
    //: While someone is typing, a shortcut is only theirs if it holds a
    //: modifier that a typist would not: Delete, F2 and Enter in a rename box
    //: belong to the box.
    if (typing && !(e.ctrlKey || e.altKey || e.metaKey)) return;
    const code = HOTKEYS.get(pressed(e));
    if (!code) return;
    const c = COMMANDS.get(code);
    if (!c || !c.run || c.unavailable) return;
    if (c.enabled) {
      try { if (!c.enabled(null)) return; } catch (err) { return; }
    }
    e.preventDefault();
    e.stopImmediatePropagation();
    try { c.run(null); } catch (err) { }
  }, true);

  function doAct(act, el) {
    if (window.__live && window.__live.path && window.__liveOp &&
        (act === 'cut' || act === 'copy' || act === 'paste' ||
        act === 'rename' || act === 'trash' || act === 'delete' ||
        act === 'newfolder' || act === 'newfile' || act === 'newshortcut')) {
      window.__liveOp(act);
      return;
    }
    switch (act) {
      case 'sel-all':
        visibleItems().forEach(el => el.classList.add('sel'));
        updateStatus(); break;
      case 'sel-inv':
        visibleItems().forEach(el => el.classList.toggle('sel'));
        updateStatus(); updateDetails(selectedItems().length === 1 ? selectedItems()[0] : null);
        break;
      case 'sel-clear':
        window.__clearSelection();
        updateStatus(); updateDetails(null); break;
      case 'lay-grid': setLayout('grid'); break;
      case 'lay-details': setLayout('details'); break;
      case 'lay-list': setLayout('list'); break;
      case 'lay-cards': setLayout('cards'); break;
      case 'lay-columns': setLayout('columns'); break;
      case 'lay-grid-small': setGridSize('small'); setLayout('grid'); break;
      case 'lay-grid-large': setGridSize('large'); setLayout('grid'); break;
      case 'lay-adaptive': setLayout('adaptive'); break;
      case 'ctx-props': {
        const fromCtx = el && el.closest && el.closest('.ctx');
        openProps(fromCtx ? ctxTarget : null);
        ctxTarget = null;
        break;
      }
      case 'ctx-refresh':
        if (window.__live && window.__live.path) {
          window.__live.render(window.__live.path);
        } else {
          applyFilter(); updateStatus();
        }
        break;
      case 'ctx-view': {
        const i = MODES.indexOf(mode());
        setLayout(MODES[(i + 1) % MODES.length]);
        break;
      }
      case 'cut': {
        const sel = selectedItems();
        const targets = sel.length ? sel : (ctxTarget ? [ctxTarget] : []);
        $$('.cut').forEach(el => el.classList.remove('cut'));
        targets.forEach(el => el.classList.add('cut'));
        break;
      }
      case 'copy': {
        const sel = selectedItems();
        const targets = sel.length ? sel : (ctxTarget ? [ctxTarget] : []);
        const p = targets.map(el => el.getAttribute('data-p') || el.getAttribute('data-n')).filter(Boolean).join(String.fromCharCode(10));
        if (p && navigator.clipboard) navigator.clipboard.writeText(p).catch(() => {});
        break;
      }
      case 'rename': {
        const sel = selectedItems();
        //: More than one selected is Bulk rename, which is what Files'
        //: RenameAction does with a multiple selection.
        if (sel.length > 1) {
          askBulkName().then(stem => {
            if (!stem) return;
            sel.forEach(el => {
              const was = el.getAttribute('data-n') || '';
              const kind = (el.getAttribute('data-k') || '');
              const ext = extensionOf(was, kind === 'Folder');
              const now = stem + ext;
              el.setAttribute('data-n', now);
              const label = el.querySelector('.cname, .rname, .lname, .kname');
              if (label) label.textContent = now;
            });
            updateStatus();
          });
          break;
        }
        const it = sel.length === 1 ? sel[0] : ctxTarget;
        if (it) {
          const oldName = it.getAttribute('data-n') || '';
          openNameDialog('Rename', oldName, 'Rename', it, clean => {
            it.setAttribute('data-n', clean);
            const lbl = it.querySelector('.cname, .rname, .lname, .wcard-name, .lbl');
            if (lbl) lbl.textContent = clean;
            updateStatus();
            updateDetails(it);
          });
        }
        break;
      }
      case 'share': {
        const p = ctxData('data-p') || ctxData('data-path') || location.href;
        if (p && navigator.clipboard) navigator.clipboard.writeText(p).catch(() => {});
        break;
      }
      case 'trash':
      case 'delete': {
        const sel = selectedItems();
        const targets = sel.length ? sel : (ctxTarget ? [ctxTarget] : []);
        if (!targets.length) break;
        const go = () => {
          targets.forEach(el => {
            if (el.parentElement) el.parentElement.removeChild(el);
          });
          updateStatus();
          updateDetails(null);
        };
        if (deleteAsks()) {
          askFsop({kind: 'delete', permanent: act === 'delete',
                   names: targets.map(t => t.getAttribute('data-n') || 'item')})
            .then(ok => { if (ok) go(); });
        } else {
          go();
        }
        break;
      }
      case 'newfolder': {
        openNameDialog('New folder', 'New folder', 'Create', null, name => {
          const tpl = $('#tpl-cell');
          const root = grid() || $('.dbody');
          if (tpl && root) {
            const el = tpl.content.firstElementChild.cloneNode(true);
            el.setAttribute('data-n', name);
            el.setAttribute('data-k', 'Folder');
            el.setAttribute('data-s', '');
            el.setAttribute('data-w', 'Just now');
            const cn = el.querySelector('.cname, .rname');
            if (cn) cn.textContent = name;
            const th = el.querySelector('.thumb, .rico');
            const art = document.querySelector('#artlib [data-rico="folder"] svg, #artlib [data-thumb="folder"] svg');
            if (th && art) th.appendChild(art.cloneNode(true));
            root.insertBefore(el, root.firstChild);
            updateStatus();
          }
        });
        break;
      }
      case 'newfile': {
        openNameDialog('New file', 'New text document.txt', 'Create', null, name => {
          const tpl = $('#tpl-cell');
          const root = grid() || $('.dbody');
          if (tpl && root) {
            const el = tpl.content.firstElementChild.cloneNode(true);
            el.setAttribute('data-n', name);
            el.setAttribute('data-k', 'File');
            el.setAttribute('data-s', '0 B');
            el.setAttribute('data-w', 'Just now');
            const cn = el.querySelector('.cname, .rname');
            if (cn) cn.textContent = name;
            const th = el.querySelector('.thumb, .rico');
            const art = document.querySelector('#artlib [data-rico="txt"] svg, #artlib [data-thumb="txt"] svg');
            if (th && art) th.appendChild(art.cloneNode(true));
            root.insertBefore(el, root.firstChild);
            updateStatus();
          }
        });
        break;
      }
      case 'newshortcut': {
        //: Files asks for the location and the name together, in
        //: CreateShortcutDialog, and the name it saves has no extension of
        //: its own: .lnk is a Windows shortcut file and this makes a symlink.
        askShortcut('').then(made => {
          if (!made) return;
          const tpl = $('#tpl-cell');
          const root = grid() || $('.dbody');
          if (tpl && root) {
            const el = tpl.content.firstElementChild.cloneNode(true);
            el.setAttribute('data-n', made.name);
            el.setAttribute('data-k', 'Shortcut');
            el.setAttribute('data-s', '0 B');
            el.setAttribute('data-w', 'Just now');
            el.setAttribute('data-target', made.target);
            const cn = el.querySelector('.cname, .rname');
            if (cn) cn.textContent = made.name;
            const th = el.querySelector('.thumb, .rico');
            const art = document.querySelector('#artlib [data-rico="txt"] svg, #artlib [data-thumb="txt"] svg');
            if (th && art) th.appendChild(art.cloneNode(true));
            root.insertBefore(el, root.firstChild);
            updateStatus();
          }
        });
        break;
      }
      case 'sidebar-reorder': askReorder(); break;
      case 'tab-new': newTab(); break;
      case 'tab-dup': duplicateTab(tabHere()); break;
      case 'tab-close': closeTab(tabHere()); break;
      case 'tab-close-others': closeOtherTabs(tabHere()); break;
      case 'tab-close-left': closeTabsToSide(tabHere(), -1); break;
      case 'tab-close-right': closeTabsToSide(tabHere(), 1); break;
      case 'tab-reopen': reopenClosedTab(); break;
      case 'tab-movewin': moveTabToNewWindow(tabHere()); break;
      // One call each, through the one function that knows which attribute
      // holds which field. Four of these used to set the attribute and leave
      // `fieldName` alone, so sorting by size left every check mark and the
      // column chevron saying Name; and each set a direction of its own,
      // which the reference does not do. Files' SortOption setter writes the
      // option and nothing else, so the direction a person chose survives
      // their choosing a different column to sort on.
      case 'ctx-sort':
      case 'sort-name': sortBy('Name'); break;
      case 'sort-date': sortBy('Date modified'); break;
      case 'sort-type': sortBy('Type'); break;
      case 'sort-size': sortBy('Size'); break;
      case 'sort-created': sortBy('Date created'); break;
      case 'sort-asc':
        sortState.dir = 1;
        applySort(); updateSortChevron(); break;
      case 'sort-desc':
        sortState.dir = -1;
        applySort(); updateSortChevron(); break;
      case 'ctx-open': {
        const h = ctxHref();
        const p = ctxTarget ? (ctxTarget.getAttribute('data-p') || ctxTarget.getAttribute('data-path') || ctxTarget.getAttribute('data-root')) : null;
        const n = ctxTarget ? (ctxTarget.getAttribute('data-n') || 'Folder') : 'Folder';
        if (p) {
          const isH = (isHomePath(p) || n === 'Home');
          navigateTo(p, n, isH, true);
        } else if (h) {
          navigateTo(h, n, false, true);
        }
        break;
      }
      case 'ctx-opentab': {
        const h = ctxHref();
        const p = ctxTarget ? (ctxTarget.getAttribute('data-p') || ctxTarget.getAttribute('data-path')) : null;
        const n = ctxTarget ? (ctxTarget.getAttribute('data-n') || 'Folder') : 'Folder';
        newTab(p || h, n, false, true);
        break;
      }
      case 'ctx-openwin': {
        const h = ctxHref();
        window.open(h || location.href, '_blank');
        break;
      }
      case 'ctx-copypath': {
        const p = ctxData('data-p') || ctxData('data-path') || ctxData('data-n');
        if (p && navigator.clipboard) navigator.clipboard.writeText(p).catch(() => {});
        break;
      }
      case 'ctx-openloc': {
        const p = ctxData('data-p');
        const dir = parentOf(p);
        if (dir) navigateActiveTab(dir, dir.split('/').pop() || 'Folder', false);
        break;
      }
      case 'ctx-remove-recent': {
        if (ctxTarget && ctxTarget.classList.contains('wrecent-row')) {
          ctxTarget.parentElement.removeChild(ctxTarget);
        }
        break;
      }
      case 'ctx-unpin-qa': {
        if (ctxTarget && ctxTarget.classList.contains('wcard')) {
          ctxTarget.parentElement.removeChild(ctxTarget);
        }
        break;
      }
      case 'storage-sense': {
        openStorageSense(ctxTarget);
        break;
      }
      case 'format-drive': {
        openFormatDrive(ctxTarget);
        break;
      }
      case 'toggle-widget': {
        //: All five, through the preference. Two of them used to fall past
        //: the map into a branch that hid the section without storing
        //: anything, so the Home menu and the settings page disagreed about
        //: whether Tags was on, and neither survived a reload.
        const item = el || ctxTarget;
        if (item) {
          const key = { quickaccess: 'widgets.qa', drives: 'widgets.drives',
            network: 'widgets.network', tags: 'widgets.tags',
            recent: 'widgets.recent' }[item.getAttribute('data-widget')];
          if (key) setPref(key, !getPref(key));
        }
        break;
      }
      case 'ctx-up': {
        goNavUp();
        break;
      }
    }
  }

  const pal = () => $('#palette');
  const palInput = () => $('#pal-input');
  function openPal() {
    hideOverlays();
    const p = pal(); if (!p) return;
    p.hidden = false;
    palInput().value = '';
    markPal();
    filterPal('');
    setTimeout(() => palInput().focus(), 0);
  }
  // What each row can do, read once as the list opens rather than on every
  // keystroke: `enabled` runs the command's own test, and a couple of hundred
  // of those between two letters is a list that stutters.
  function markPal() {
    $$('.pcmd').forEach(row => {
      const c = COMMANDS.get(row.getAttribute('data-code'));
      if (!c) { row.removeAttribute('data-state'); return; }
      if (c.unavailable) {
        row.setAttribute('data-state', 'na');
        row.setAttribute('title', c.unavailable);
        return;
      }
      row.removeAttribute('title');
      let ready = !!c.run;
      if (ready && c.enabled) {
        try { ready = !!c.enabled(null); } catch (err) { ready = false; }
      }
      //: The reference skips a command that is not executable rather than
      //: showing it greyed, so this does too. The row stays in the markup, so
      //: the parity count still reads every command the reference has; it is
      //: the filter below that leaves it out of the list.
      if (ready) row.removeAttribute('data-state');
      else row.setAttribute('data-state', 'off');
      // A command that is on shows it, the way its menu row does.
      if (c.on) {
        try { row.classList.toggle('checked', !!c.on()); } catch (err) {}
      }
    });
  }
  // The part of the title that matched, in bold. The reference splits the
  // title into three Runs, pre, matched and post, and bolds the middle one.
  // Built as nodes rather than as markup: this page allows no HTML sink, and
  // a title comes from the reference's own strings but is still text.
  function markMatch(row, q) {
    const title = row.getAttribute('data-title') || '';
    const label = row.querySelector('.mi-t');
    if (!label) return;
    //: The first word that is actually in the title. A query of two words
    //: matches on all of them, but only one run can be bold, and the reference
    //: bolds where the text was found.
    const at = q ? title.toLowerCase().indexOf(q.split(/\s+/)[0]) : -1;
    if (at < 0) {
      if (label.textContent !== title) label.replaceChildren(title);
      return;
    }
    const hit = document.createElement('b');
    hit.textContent = title.slice(at, at + q.split(/\s+/)[0].length);
    label.replaceChildren(title.slice(0, at), hit,
                          title.slice(at + hit.textContent.length));
  }

  function filterPal(q) {
    q = q.trim().toLowerCase();
    let first = null;
    // Every word has to appear, so "sort name" finds the one row rather than
    // every row with either word in it.
    const words = q ? q.split(/\s+/) : [];
    $$('.pcmd').forEach(c => {
      const hay = (c.getAttribute('data-cmd') || '').toLowerCase();
      //: A command that cannot run right now is not offered. A command with
      //: no counterpart on this platform still is, because its row exists to
      //: say so.
      const ok = c.getAttribute('data-state') !== 'off' &&
                 words.every(w => hay.indexOf(w) !== -1);
      c.style.display = ok ? '' : 'none';
      c.classList.toggle('hot', false);
      if (ok) markMatch(c, q);
      if (ok && !first) first = c;
    });
    if (first) first.classList.add('hot');
    return first;
  }
  // The palette runs the registry and nothing else. It used to carry a table
  // of its own mapping nineteen labels to nineteen actions, which meant the
  // palette and the menus could disagree about what a command does, and every
  // command added after it was written was missing from here.
  function runPal(row) {
    const code = typeof row === 'string' ? row : row.getAttribute('data-code');
    const c = COMMANDS.get(code);
    if (c && c.unavailable) {
      if (window.__toast) window.__toast(c.unavailable);
      return;
    }
    pal().hidden = true;
    if (window.__runCommand) window.__runCommand(code, null);
  }

  document.addEventListener('click', e => {
    const wrapBtn = e.target.closest('.twrap > button');
    if (wrapBtn) {
      const menu = wrapBtn.parentElement.querySelector('.menu');
      const wasHidden = menu ? menu.hidden : true;
      hideOverlays();
      if (menu && wasHidden) menu.hidden = false;
      e.stopPropagation();
      return;
    }
    if (e.target.closest('#btn-filter')) {
      const f = $('#frow'), b = $('#btn-filter');
      const show = f.hidden;
      hideOverlays();
      f.hidden = !show;
      b.setAttribute('aria-pressed', show ? 'true' : 'false');
      if (show) $('#finput').focus();
      else { $('#finput').value = ''; applyFilter(); }
      return;
    }
    if (e.target.closest('#btn-pane')) {
      const p = $('#infopane'), b = $('#btn-pane');
      const show = p.hidden;
      hideOverlays();
      p.hidden = !show;
      b.setAttribute('aria-pressed', show ? 'true' : 'false');
      return;
    }
    if (e.target.closest('#btn-sc, #show-status-center-btn')) {
      if (window.StatusCenter) {
        window.StatusCenter.toggleFlyout();
      } else {
        const f = $('#sc-fly'), b = $('#btn-sc');
        if (f) {
          const show = f.hidden;
          hideOverlays();
          f.hidden = !show;
          if (b) b.setAttribute('aria-pressed', show ? 'true' : 'false');
        }
      }
      e.stopPropagation();
      return;
    }
    if (e.target.closest('#btn-palette')) { openPal(); return; }
    if (e.target.closest('#btn-search')) {
      const o = $('#osearch'), c = $('#crumbs'), b = $('#btn-search');
      const show = o.hidden;
      hideOverlays();
      o.hidden = !show;
      if (c) c.hidden = show;
      b.setAttribute('aria-pressed', show ? 'true' : 'false');
      if (show) o.focus();
      else { o.value = ''; applyFilter(); }
      return;
    }
    const cchev = e.target.closest('.cchev');
    if (cchev) {
      const menu = cchev.parentElement.querySelector('.menu');
      const wasHidden = menu ? menu.hidden : true;
      hideOverlays();
      if (menu && wasHidden) menu.hidden = false;
      e.stopPropagation();
      return;
    }
    if (e.target.closest('#btn-newtab')) {
      newTab();
      return;
    }
    const tabEl = e.target.closest('.tab');
    if (tabEl) {
      const tid = parseInt(tabEl.getAttribute('data-tab-id'), 10);
      if (e.target.closest('.x')) {
        closeTab(tid, e);
      } else {
        switchTab(tid);
      }
      return;
    }
    if (e.target.closest('#nav-back')) { goNavBack(); return; }
    if (e.target.closest('#nav-fwd')) { goNavForward(); return; }
    if (e.target.closest('#nav-refresh')) { doAct('ctx-refresh'); return; }
    const navUp = e.target.closest('.nav a, .nav .nbtn');
    if (navUp && navUp.getAttribute('title') === 'Up') {
      e.preventDefault();
      goNavUp();
      return;
    }
    const stBtn = e.target.closest('.wd-storage');
    if (stBtn) {
      e.stopPropagation();
      e.preventDefault();
      const driveCard = stBtn.closest('.wcard-drive');
      openStorageSense(driveCard);
      return;
    }
    const wsecHeader = e.target.closest('.wsec-h');
    if (wsecHeader && !e.target.closest('.wsec-more')) {
      const wsec = wsecHeader.closest('.wsec');
      if (wsec) wsec.classList.toggle('collapsed');
      return;
    }
    const wsecMore = e.target.closest('.wsec-more');
    if (wsecMore) {
      e.stopPropagation();
      openCtx('ctx-home', e.clientX, e.clientY);
      return;
    }
    const crumb = e.target.closest('.crumb, .crumbs [data-p]');
    if (crumb) {
      e.preventDefault();
      const p = crumb.getAttribute('data-p');
      const txt = (crumb.querySelector('span:last-child') || crumb).textContent.trim();
      const isH = (!p || isHomePath(p) || txt === 'Home');
      navigateTo(p || '~', isH ? 'Home' : txt, isH, true);
      return;
    }
    const qaCard = e.target.closest('.wcard-folder');
    if (qaCard) {
      e.preventDefault();
      const p = qaCard.getAttribute('data-path') || homePath();
      const n = qaCard.getAttribute('data-n') || 'Folder';
      navigateTo(p, n, false, true);
      return;
    }
    const drvCard = e.target.closest('.wcard-drive');
    if (drvCard) {
      e.preventDefault();
      const p = drvCard.getAttribute('data-path') || '/';
      const n = drvCard.getAttribute('data-n') || 'Drive';
      navigateTo(p, n, false, true);
      return;
    }
    const recRow = e.target.closest('.wrecent-row');
    if (recRow) {
      openProps(recRow);
      return;
    }
    const itab = e.target.closest('.itab');
    if (itab) { selectTab(itab.getAttribute('data-itab')); return; }
    const ptab = e.target.closest('.ptab');
    if (ptab) {
      if (ptab.getAttribute('data-ptab')) selectPTab(ptab.getAttribute('data-ptab'));
      return;
    }
    const snav = e.target.closest('.snav');
    if (snav) { selectSTab(snav.getAttribute('data-snav')); return; }
    const sw = e.target.closest('.sw[data-pref]');
    if (sw) {
      const k = sw.getAttribute('data-pref');
      setPref(k, !getPref(k));
      return;
    }
    const themeRow = e.target.closest('.mi[data-theme]');
    if (themeRow) { setTheme(themeRow.getAttribute('data-theme')); return; }
    if (e.target.closest('#settings-back')) { closeSettings(); return; }
    if (dlgOpen) {
      const shown = document.getElementById(dlgOpen.id);
      const pick = e.target.closest('[data-pick]');
      if (pick && shown && shown.contains(pick)) {
        closeDialog(pick.getAttribute('data-pick'));
        return;
      }
      const btn = e.target.closest('[data-dlg]');
      if (btn && shown && shown.contains(btn)) {
        if (!btn.disabled) closeDialog(btn.getAttribute('data-dlg'));
        return;
      }
      //: The scrim itself, which is the part of it outside the dialog.
      if (e.target.id === dlgOpen.id) { closeDialog('close'); return; }
    }
    if (e.target.closest('#namedlg-ok')) { submitNameDialog(); return; }
    if (e.target.closest('#namedlg-cancel') || e.target.closest('#namedlg-x')) {
      closeNameDialog(); return;
    }
    if (e.target.id === 'namedlg') { closeNameDialog(); return; }
    if (e.target.closest('#side-settings')) { openSettings(); return; }
    const side = e.target.closest('.srow.item');
    if (side) {
      e.preventDefault();
      const p = side.getAttribute('data-root') || side.getAttribute('href') || '/';
      const isH = (isHomePath(p) || side.getAttribute('data-n') === 'Home');
      navigateTo(p, side.getAttribute('data-n') || (isH ? 'Home' : 'Folder'), isH, true);
      return;
    }
    if (e.target.closest('#btn-prefs-export')) {
      downloadJson('aurade-files-settings.json', PREFS);
      return;
    }
    if (e.target.closest('#btn-prefs-import')) {
      const f = $('#prefs-file');
      if (f) f.click();
      return;
    }
    if (e.target.closest('#btn-prefs-clear')) {
      try { localStorage.clear(); } catch (err) {}
      location.reload();
      return;
    }
    if (e.target.closest('#btn-diag')) {
      downloadJson('aurade-files-diagnostics.json', {
        url: location.href,
        mode: window.__mode ? window.__mode() : 'grid',
        items: listItems().length,
        selected: selectedItems().length,
        prefs: PREFS
      });
      return;
    }
    if (e.target.closest('#btn-link-repo')) {
      window.open('https://github.com/Cam396/aurade', '_blank');
      return;
    }
    if (e.target.closest('#btn-link-issues')) {
      window.open('https://github.com/Cam396/aurade/issues', '_blank');
      return;
    }

    const hc = e.target.closest('.hcopy[data-copy]');
    if (hc) {
      const h = document.getElementById(hc.getAttribute('data-copy'));
      if (h && h.textContent && navigator.clipboard)
        navigator.clipboard.writeText(h.textContent).catch(() => {});
      return;
    }
    if (e.target.closest('#props-clear-btn')) {
      ['Title', 'Subject', 'Tags', 'Categories', 'Comments'].forEach(k => {
        const c = document.querySelector('[data-detk="' + k + '"]');
        if (c) c.textContent = '';
      });
      return;
    }
    if (e.target.closest('#hash-compare-file')) { compareHashFile(); return; }
    const coverRow = e.target.closest('#m-cover .mi[data-cover]');
    if (coverRow) {
      hideOverlays();
      if (!window.__albumCover) showToast('Changing album art needs the backend.');
      else window.__albumCover(coverRow.getAttribute('data-cover'));
      return;
    }
    if (e.target.closest('#hash-compare')) { compareHash(); return; }
    if (e.target.closest('#props-close, #props-ok, #props-cancel')) {
      const p = $('#props');
      if (p) p.hidden = true;
      return;
    }
    //: Apply writes what changed and keeps the window open, the reference's
    //: SaveChangesAsync without the close that OK adds.
    if (e.target.closest('#props-apply')) return;
    if (e.target.closest('#btn-drive-cleanup')) {
      const p = $('#props');
      if (p) p.hidden = true;
      openStorageSense(propsTargetDrive);
      return;
    }
    if (e.target.closest('#btn-drive-format')) {
      const p = $('#props');
      if (p) p.hidden = true;
      openFormatDrive(propsTargetDrive);
      return;
    }

    if (e.target.closest('#storage-close, #storage-ok')) {
      const s = $('#storage-sense');
      if (s) s.hidden = true;
      return;
    }
    if (e.target.closest('#btn-storage-clean')) {
      cleanStorageSense();
      return;
    }

    if (e.target.closest('#format-close, #btn-format-cancel')) {
      const f = $('#format-drive');
      if (f) f.hidden = true;
      return;
    }
    if (e.target.closest('#btn-format-start')) {
      startFormatDrive();
      return;
    }

    if (e.target.id === 'props' || e.target.id === 'palette' || e.target.id === 'storage-sense' || e.target.id === 'format-drive') {
      e.target.hidden = true;
      return;
    }

    const sortRow = e.target.closest('.mi[data-sort]');
    if (sortRow) {
      const name = sortRow.getAttribute('data-sort');
      const grp = sortRow.getAttribute('data-sort-group');
      if (name === 'Ascending' || name === 'Descending') {
        sortState.dir = name === 'Ascending' ? 1 : -1;
      } else if (name === 'Folders first' || name === 'Files first' || name === 'Files and folders together') {
        sortState.folderGroup = name;
      } else if (grp === 'sort-field') {
        const f = SORT_FIELD[name] || ['data-n', false];
        sortState.attr = f[0]; sortState.numeric = f[1];
        sortState.fieldName = name;
      }
      if (grp) {
        $$('.mi[data-sort-group="' + grp + '"] .ck').forEach(k => k.classList.remove('on'));
      } else {
        const menu = sortRow.closest('.menu');
        if (menu) $$('.ck', menu).forEach(k => k.classList.remove('on'));
      }
      const ck = sortRow.querySelector('.ck');
      if (ck) ck.classList.add('on');
      applySort();
      updateSortChevron();
      hideOverlays();
      return;
    }

    const miAct = e.target.closest('[data-act]');
    if (miAct) {
      const a = miAct.getAttribute('data-act');
      hideOverlays();
      if (a !== 'ctx-dis') doAct(a, miAct);
      return;
    }
    const named = e.target.closest('[data-command]');
    if (named) {
      hideOverlays();
      if (window.__runCommand) {
        window.__runCommand(named.getAttribute('data-command'), named);
      }
      return;
    }
    const pc = e.target.closest('.pcmd');
    if (pc) { runPal(pc); return; }
    if (e.target.closest('.mi.dis')) { hideOverlays(); return; }
    if (e.target.closest('.mi')) { hideOverlays(); return; }

    const dh = e.target.closest('.dh-col');
    if (dh) {
      const field = dh.getAttribute('data-dh');
      if (field) {
        if (sortState.fieldName === field) {
          sortState.dir = -sortState.dir;
        } else {
          sortState.fieldName = field;
          const f = SORT_FIELD[field] || ['data-n', false];
          sortState.attr = f[0];
          sortState.numeric = f[1];
          sortState.dir = 1;
        }
        $$('.mi[data-sort-group="sort-field"] .ck').forEach(k => {
          k.classList.toggle('on', k.closest('.mi').getAttribute('data-sort') === sortState.fieldName);
        });
        $$('.mi[data-sort-group="sort-dir"] .ck').forEach(k => {
          const dname = sortState.dir === 1 ? 'Ascending' : 'Descending';
          k.classList.toggle('on', k.closest('.mi').getAttribute('data-sort') === dname);
        });
        applySort();
        updateSortChevron();
        return;
      }
    }

    const it = e.target.closest('.cell,.row,.lrow,.tile,.crow');
    if (it) {
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) {
        it.classList.toggle('sel');
      } else {
        window.__clearSelection();
        it.classList.add('sel');
        if (getPref('singleClick') && it.getAttribute('data-k') === 'Folder') {
          const p = it.getAttribute('data-p') || it.getAttribute('data-n');
          if (p) openFolder(p, it.getAttribute('data-n') || 'Folder');
          return;
        }
      }
      updateStatus();
      const sel = selectedItems();
      updateDetails(sel.length === 1 ? sel[0] : null);
      return;
    }

    if (!e.target.closest('.twrap,.ctx,.scwrap,.pal,.infopane')) {
      hideOverlays();
      if (e.target.closest('#filearea')
          && !e.target.closest('.wcard, .wsec, .wrecent-row, .wtag-item')) {
        window.__clearSelection();
        updateStatus(); updateDetails(null);
      }
    }
  });

  document.addEventListener('contextmenu', e => {
    const tabEl = e.target.closest('.tab');
    if (tabEl) {
      e.preventDefault();
      ctxTarget = tabEl;
      openCtx('ctx-tab', e.clientX, e.clientY);
      return;
    }
    const navBtn = e.target.closest('#nav-back,#nav-fwd');
    if (navBtn) {
      e.preventDefault();
      openHistory(e.clientX, e.clientY);
      return;
    }
    const driveCard = e.target.closest('.wcard-drive');
    if (driveCard) {
      e.preventDefault();
      ctxTarget = driveCard;
      openCtx('ctx-drive', e.clientX, e.clientY);
      return;
    }
    const qaCard = e.target.closest('.wcard-folder');
    if (qaCard) {
      e.preventDefault();
      ctxTarget = qaCard;
      openCtx('ctx-qa', e.clientX, e.clientY);
      return;
    }
    const recentRow = e.target.closest('.wrecent-row');
    if (recentRow) {
      e.preventDefault();
      ctxTarget = recentRow;
      openCtx('ctx-recent', e.clientX, e.clientY);
      return;
    }
    const netCard = e.target.closest('.wnet-card');
    if (netCard) {
      e.preventDefault();
      ctxTarget = netCard;
      openCtx('ctx-network', e.clientX, e.clientY);
      return;
    }
    const tagItem = e.target.closest('.wtag-item');
    if (tagItem) {
      e.preventDefault();
      ctxTarget = tagItem;
      openCtx('ctx-filetags', e.clientX, e.clientY);
      return;
    }
    const side = e.target.closest('.srow.item');
    if (side) {
      e.preventDefault();
      ctxTarget = side;
      if (side.getAttribute('data-kind') === 'drive') {
        openCtx('ctx-drive', e.clientX, e.clientY);
      } else {
        openCtx('ctx-side', e.clientX, e.clientY);
      }
      return;
    }
    const it = e.target.closest('.cell,.row,.lrow,.tile,.crow');
    if (it) {
      e.preventDefault();
      ctxTarget = it;
      if (!it.classList.contains('sel')) {
        window.__clearSelection();
        it.classList.add('sel');
        updateStatus();
        updateDetails(it);
      }
      if (window.__tags) window.__tags.fillSub(ctxData('data-p'));
      openCtx('ctx-file', e.clientX, e.clientY);
      return;
    }
    if (e.target.closest('#filearea')) {
      e.preventDefault();
      ctxTarget = null;
      const curTab = tabs.find(t => t.id === activeTabId);
      if (curTab && curTab.isHome) {
        openCtx('ctx-home', e.clientX, e.clientY);
      } else {
        openCtx('ctx-bg', e.clientX, e.clientY);
      }
      return;
    }
  });

  document.addEventListener('auxclick', e => {
    if (e.button !== 1) return;
    const tabEl = e.target.closest('.tab');
    if (tabEl) {
      const tid = parseInt(tabEl.getAttribute('data-tab-id'), 10);
      closeTab(tid, e);
      return;
    }
    const qaCard = e.target.closest('.wcard-folder');
    if (qaCard) {
      e.preventDefault();
      newTab(qaCard.getAttribute('data-path') || homePath(), qaCard.getAttribute('data-n') || 'Folder', false, false);
      return;
    }
    const driveCard = e.target.closest('.wcard-drive');
    if (driveCard) {
      e.preventDefault();
      newTab(driveCard.getAttribute('data-path') || '/', driveCard.getAttribute('data-n') || 'Drive', false, false);
      return;
    }
    const side = e.target.closest('.srow.item');
    if (side) {
      e.preventDefault();
      newTab(side.getAttribute('data-root') || side.getAttribute('href') || '/', side.getAttribute('data-n') || 'Place', false, false);
      return;
    }
    const it = e.target.closest('.cell,.row,.lrow,.tile,.crow');
    if (it && it.getAttribute('data-k') === 'Folder') {
      e.preventDefault();
      newTab(it.getAttribute('data-p') || it.getAttribute('data-n'), it.getAttribute('data-n') || 'Folder', false, false);
      return;
    }
  });

  document.addEventListener('dblclick', e => {
    if (e.target.id === 'tabstrip' || (e.target.classList.contains('titlebar') && !e.target.closest('.caption'))) {
      newTab();
      return;
    }
    const it = e.target.closest('.cell,.row,.lrow,.tile,.crow');
    if (it && it.getAttribute('data-k') === 'Folder') {
      const p = it.getAttribute('data-p') || it.getAttribute('data-n');
      navigateTo(p, it.getAttribute('data-n') || 'Folder', false, true);
      return;
    }
    if (getPref('dblclickUp') && e.target.closest('#filearea')) {
      goNavUp();
    }
  });

  // kbdFocus and setKbd moved to top of Tab System
  function selectOnly(el) {
    window.__clearSelection();
    if (el) el.classList.add('sel');
    kbdAnchor = el;
    updateStatus();
    updateDetails(el);
  }
  function kbdPick(buf) {
    return kbdVisible().find(el =>
      (el.getAttribute('data-n') || '').toLowerCase().startsWith(buf));
  }
  function moveKbd(dx, dy, extend) {
    const items = kbdVisible();
    if (!items.length) return;
    if (!kbdFocus || items.indexOf(kbdFocus) === -1) {
      const first = items[0];
      setKbd(first); selectOnly(first);
      return;
    }
    const r = kbdFocus.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    let best = null, bestScore = Infinity;
    items.forEach(el => {
      if (el === kbdFocus) return;
      const q = el.getBoundingClientRect();
      const ex = q.left + q.width / 2, ey = q.top + q.height / 2;
      const vx = ex - cx, vy = ey - cy;
      if (dx > 0 && vx <= 2) return;
      if (dx < 0 && vx >= -2) return;
      if (dy > 0 && vy <= 2) return;
      if (dy < 0 && vy >= -2) return;
      const primary = dx !== 0 ? Math.abs(vx) : Math.abs(vy);
      const secondary = dx !== 0 ? Math.abs(vy) : Math.abs(vx);
      const score = primary + secondary * 3;
      if (score < bestScore) { bestScore = score; best = el; }
    });
    if (!best) return;
    setKbd(best);
    if (extend && kbdAnchor && items.indexOf(kbdAnchor) !== -1) {
      const a = items.indexOf(kbdAnchor), b = items.indexOf(best);
      const lo = Math.min(a, b), hi = Math.max(a, b);
      window.__clearSelection();
      items.slice(lo, hi + 1).forEach(x => x.classList.add('sel'));
      updateStatus();
      updateDetails(b === a ? best : null);
    } else {
      selectOnly(best);
    }
  }
  document.addEventListener('click', e => {
    const it = e.target.closest && e.target.closest('.cell,.row,.lrow,.tile,.crow');
    if (it) setKbd(it);
  }, true);

  document.addEventListener('keydown', e => {
    const t = e.target || {};
    const inInput = t.tagName === 'INPUT' || t.tagName === 'TEXTAREA';
    if (dlgOpen && e.key === 'Enter' && t.tagName !== 'TEXTAREA') {
      const shown = document.getElementById(dlgOpen.id);
      const go = shown && shown.querySelector('[data-dlg="primary"]');
      if (go && !go.disabled) { e.preventDefault(); closeDialog('primary'); return; }
    }
    if (e.key === 'Escape') {
      if (dlgOpen) { closeDialog('close'); return; }
      if (pal() && !pal().hidden) { pal().hidden = true; return; }
      const pr = $('#props');
      if (pr && !pr.hidden) { pr.hidden = true; return; }
      const nd = $('#namedlg');
      if (nd && !nd.hidden) { closeNameDialog(); return; }
      if (settingsOpen()) { closeSettings(); return; }
      const ss = $('#storage-sense');
      if (ss && !ss.hidden) { ss.hidden = true; return; }
      const fd = $('#format-drive');
      if (fd && !fd.hidden) { fd.hidden = true; return; }
      const o = $('#osearch');
      if (o && !o.hidden) { exitSearch(); return; }
      hideOverlays();
      window.__clearSelection();
      setKbd(null); kbdAnchor = null;
      updateStatus(); updateDetails(null);
      return;
    }
    if (inInput) {
      if (e.key === 'Enter' && t.id === 'pal-input') {
        //: The highlighted row, which is the first showing one, and the row
        //: itself rather than its text: `data-cmd` is what the filter reads
        //: and `data-code` is what names the command.
        const first = $$('.pcmd').filter(c => c.style.display !== 'none')[0];
        if (first) runPal(first);
      }
      return;
    }
    if (settingsOpen()) return;
    if ((e.ctrlKey || e.metaKey) && (e.key === 't' || e.key === 'T')) {
      e.preventDefault();
      newTab();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'w' || e.key === 'W')) {
      e.preventDefault();
      closeTab(activeTabId);
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'f' || e.key === 'F')) {
      e.preventDefault();
      const bs = $('#btn-search');
      if (bs) bs.click();
      return;
    }
    if (e.key === 'F5') {
      e.preventDefault();
      doAct('ctx-refresh');
      return;
    }
    if (e.key === 'F2') {
      e.preventDefault();
      doAct('rename');
      return;
    }
    if (e.key === 'Delete') {
      e.preventDefault();
      doAct('trash');
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'a' || e.key === 'A')) {
      e.preventDefault();
      visibleItems().forEach(el => el.classList.add('sel'));
      updateStatus();
      return;
    }
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft' ||
        e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (e.altKey) {
        if (e.key === 'ArrowUp') { e.preventDefault(); goNavUp(); }
        return;
      }
      e.preventDefault();
      const dx = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      const dy = e.key === 'ArrowDown' ? 1 : e.key === 'ArrowUp' ? -1 : 0;
      moveKbd(dx, dy, e.shiftKey);
      return;
    }
    if (e.key === 'Enter') {
      const cur = kbdFocus && visibleItems().indexOf(kbdFocus) !== -1
        ? kbdFocus : selectedItems()[0];
      if (cur && cur.getAttribute('data-k') === 'Folder') {
        e.preventDefault();
        openFolder(cur.getAttribute('data-p') || cur.getAttribute('data-n'),
          cur.getAttribute('data-n') || 'Folder');
      }
      return;
    }
    if (e.key === 'Backspace') {
      e.preventDefault();
      goNavUp();
      return;
    }
    if (!e.ctrlKey && !e.metaKey && !e.altKey && e.key.length === 1) {
      clearTimeout(typeTimer);
      typeBuf += e.key.toLowerCase();
      typeTimer = setTimeout(() => { typeBuf = ''; }, 800);
      const hit = kbdPick(typeBuf);
      if (hit) { setKbd(hit); selectOnly(hit); }
      return;
    }
    if (e.altKey && e.key === 'ArrowUp') {
      e.preventDefault();
      goNavUp();
    }
  });

  function trail() {
    try { return JSON.parse(sessionStorage.getItem('aurade-trail') || '[]'); }
    catch (err) { return []; }
  }
  function recordTrail() {
    const t = trail();
    const here = location.href;
    const nameEl = document.querySelector('.tname');
    const entry = { t: nameEl ? nameEl.textContent : document.title, u: here };
    const kept = t.filter(e => e.u !== here);
    kept.push(entry);
    while (kept.length > 25) kept.shift();
    try { sessionStorage.setItem('aurade-trail', JSON.stringify(kept)); }
    catch (err) {}
  }
  function openHistory(x, y) {
    const menu = document.getElementById('hist-menu');
    if (!menu) return;
    Array.from(menu.children).forEach(c => {
      if (!c.classList.contains('hist-tpl')) menu.removeChild(c);
    });
    const tpl = menu.querySelector('.hist-tpl');
    const items = trail().slice().reverse();
    if (!tpl || !items.length) return;
    items.forEach(e => {
      const row = tpl.cloneNode(true);
      row.classList.remove('hist-tpl');
      row.hidden = false;
      row.setAttribute('href', e.u);
      const label = row.querySelector('.mi-t');
      if (label) label.textContent = e.t;
      menu.appendChild(row);
    });
    openCtx('hist-menu', x, y);
  }

  const fi = $('#finput'), os = $('#osearch'), pi = $('#pal-input');
  if (fi) fi.addEventListener('input', applyFilter);
  if (os) os.addEventListener('input', applyFilter);
  if (pi) pi.addEventListener('input', () => filterPal(pi.value));
  const hyi = $('#hash-input');
  if (hyi) hyi.addEventListener('keydown', e => {
    if (e.key === 'Enter') compareHash();
    e.stopPropagation();
  });
  const fa = $('#filearea');
  if (fa) fa.addEventListener('scroll', hideOverlays);
  window.addEventListener('resize', hideOverlays);
  restoreTheme();
  initPrefs();
  $$('.ssel[data-pref]').forEach(s => {
    s.addEventListener('change', () => setPref(s.getAttribute('data-pref'), s.value));
  });
  const ssearch = $('#settings-search');
  if (ssearch) ssearch.addEventListener('input', () => filterSettings(ssearch.value));
  const ni = $('#namedlg-input');
  if (ni) ni.addEventListener('keydown', e => {
    if (e.key === 'Enter') submitNameDialog();
    e.stopPropagation();
  });
  const pf = $('#prefs-file');
  if (pf) pf.addEventListener('change', () => {
    const f = pf.files && pf.files[0];
    if (!f) return;
    const rd = new FileReader();
    rd.onload = () => {
      try {
        const obj = JSON.parse(rd.result);
        Object.keys(DEF_PREFS).forEach(k => {
          if (k in obj) PREFS[k] = obj[k];
        });
        savePrefs();
        syncPrefControls();
        Object.keys(DEF_PREFS).forEach(applyPref);
      } catch (err) {}
      pf.value = '';
    };
    rd.readAsText(f);
  });
  recordTrail();
  snapDefaults();
  const btnLayout = document.getElementById("btn-layout");
  if (btnLayout) {
    btnLayout.addEventListener("click", () => {
      const curTab = tabs.find(t => t.id === activeTabId);
      if (curTab) curTab.view = mode();
    });
  }
  setupEditableAddressBar({
    navigateTo: navigateTo,
    getActivePath: () => {
      const curTab = tabs.find(t => t.id === activeTabId);
      return curTab ? curTab.path : "~";
    }
  });
  setupMarqueeSelection({
    getItems: visibleItems,
    updateStatus: updateStatus,
    updateDetails: updateDetails,
    isHome: () => {
      const curTab = tabs.find(t => t.id === activeTabId);
      return curTab ? curTab.isHome : false;
    }
  });
  updateToolbarHomeGating(initialIsHome);
  updateEmptyFolderIndicator(listItems().length, initialIsHome);

  // Wave 2 Dual Pane / Split View
  const dualPaneApi = setupDualPane({
    fileArea: $('#filearea'),
    getCurrentPath: () => {
      const curTab = tabs.find(t => t.id === activeTabId);
      return curTab ? curTab.path : homePath();
    },
    isHome: () => {
      const curTab = tabs.find(t => t.id === activeTabId);
      return curTab ? curTab.isHome : false;
    },
    onActivePaneChange: (info) => {
      if (!info) return;
      const curTab = tabs.find(t => t.id === activeTabId);
      if (curTab) {
        if (info.pane === 'left') {
          updateToolbarHomeGating(curTab.isHome);
          updateEmptyFolderIndicator(listItems().length, curTab.isHome);
        } else {
          updateToolbarHomeGating(info.isHome);
          const rightCount = info.element ? info.element.querySelectorAll('.cell:not([hidden]), .row:not([hidden])').length : 0;
          updateEmptyFolderIndicator(rightCount, info.isHome);
        }
      }
    }
  });
  window.__dualPane = dualPaneApi;

  // Wave 3 Rich InfoPane Previews
  const infoPanePreviewsApi = setupInfoPanePreviews({
    pane: $('#infopane') || $('.infopane'),
    fileArea: $('#filearea'),
    fetchPreview: window.__fetchPreview || null
  });
  window.__infoPanePreviews = infoPanePreviewsApi;

  // Wave 4 Status Center is auto-initialized on window.StatusCenter

  // Wave 5 Drag and Drop and File Conflict Dialog
  if (typeof setupDragAndDropAndConflict === 'function') {
    const dndApi = setupDragAndDropAndConflict({
      container: document.body,
      getCurrentPath: () => {
        const curTab = tabs.find(t => t.id === activeTabId);
        return curTab ? curTab.path : homePath();
      },
      getExistingNames: (destPath) => {
        const curTab = tabs.find(t => t.id === activeTabId);
        const items = (curTab && curTab.items) || [];
        return items.map(it => it.name);
      }
    });
    window.__dndApi = dndApi;
  }

  snapProps();
