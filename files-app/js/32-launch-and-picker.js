  //: Opening files, and the window as other programs open it. Ash hands the
  //: Files app its arguments as JSON in the query, the way it always has:
  //: a folder to show and what to select in it, from Show in folder or from
  //: an application asking AuraDE Files to show something; or a dialog type,
  //: when a web page, Ash itself or a Linux application wants a file chosen.
  //: Then this window is the file chooser, and the choice goes back to Ash
  //: through fileManagerPrivate, the way the stock dialog returned it.

  // ---- opening ------------------------------------------------------------
  async function openFiles(paths) {
    if (!paths || !paths.length) return;
    try {
      const j = await apiPost('/api/open', {paths});
      const names = Array.from(new Set(j.apps || []));
      if (window.__toast && names.length) {
        window.__toast('Opening in ' + names.join(', '));
      }
    } catch (err) {
      //: Nothing on the machine says it opens this type, so ask which
      //: application should, the way every desktop does.
      if (err.status === 404 && window.__openWith) {
        window.__openWith(paths);
        return;
      }
      if (window.__toast) window.__toast(err.message || 'That could not be opened');
    }
  }
  window.__openFiles = openFiles;

  // ---- what the window was asked to show ----------------------------------
  function launchArgs() {
    const query = location.search.slice(1);
    if (!query) return {};
    try {
      const args = JSON.parse(decodeURIComponent(query));
      return (args && typeof args === 'object') ? args : {};
    } catch (err) {
      return {};
    }
  }

  //: Ash names a place by its address in the Files app's file system: the
  //: mount after external/, then the path inside it. Each mount is named
  //: for the volume the AuraDE volumes patch registers for it.
  const VOLUME_DIRS = {
    'local_root:root': '',
    'local_root:home': '/home',
    'local_root:media': '/run/media',
    'local_root:mnt': '/mnt',
    'local_root:local': '/usr/local',
    'local_root:opt': '/opt',
  };
  const HOME_FOLDERS = ['Desktop', 'Documents', 'Downloads', 'Music',
                        'Pictures', 'Videos'];
  //: The volume a chosen file is handed back in: the filesystem root holds
  //: every path, so one address works for all of them.
  const ROOT_VOLUME = 'local_root:root';
  const ROOT_URL = 'filesystem:chrome://file-manager/external/' +
                   encodeURIComponent(ROOT_VOLUME);

  function pathOfFilesUrl(url) {
    const m = /^filesystem:chrome:\/\/file-manager\/external\/([^/]+)(\/.*)?$/
      .exec(url || '');
    if (!m) return null;
    let volume, rest;
    try {
      volume = decodeURIComponent(m[1]);
      rest = m[2] ? decodeURIComponent(m[2]).replace(/\/+$/, '') : '';
    } catch (err) {
      return null;
    }
    if (rest.split('/').indexOf('..') !== -1) return null;
    if (Object.prototype.hasOwnProperty.call(VOLUME_DIRS, volume)) {
      return (VOLUME_DIRS[volume] + rest) || '/';
    }
    const name = volume.replace(/^local_root:/, '');
    if (volume !== name && HOME_FOLDERS.indexOf(name) !== -1) {
      return '~/' + name + rest;
    }
    //: Home is published under the account's name, and a Downloads- mount
    //: is the My files volume, which on this desktop is home too.
    if (volume !== name || volume.indexOf('Downloads-') === 0) return '~' + rest;
    return null;
  }

  function filesUrlOf(path) {
    return ROOT_URL + path.split('/').map(encodeURIComponent).join('/');
  }

  function parentOf(path) {
    const cut = path.lastIndexOf('/');
    if (cut > 0) return path.slice(0, cut);
    return cut === 0 ? '/' : '~';
  }
  function baseOf(path) {
    return path.slice(path.lastIndexOf('/') + 1);
  }

  const args = launchArgs();
  const PICKERS = {
    'open-file': 'Open',
    'open-multi-file': 'Open',
    'saveas-file': 'Save',
    'folder': 'Select',
    'upload-folder': 'Upload',
  };
  const pickerType = Object.prototype.hasOwnProperty.call(PICKERS, args.type)
    ? args.type : '';
  const choosesFolder = pickerType === 'folder' || pickerType === 'upload-folder';

  let directory = typeof args.auradeDirectory === 'string' ? args.auradeDirectory : '';
  const selection = Array.isArray(args.auradeSelection)
    ? args.auradeSelection.filter(p => typeof p === 'string') : [];
  if (!directory && args.currentDirectoryURL) {
    directory = pathOfFilesUrl(args.currentDirectoryURL) || '';
  }
  let suggestedName = typeof args.targetName === 'string' ? args.targetName : '';
  const asked = args.selectionURL ? pathOfFilesUrl(args.selectionURL) : null;
  if (asked) {
    if (!directory) directory = parentOf(asked);
    if (pickerType === 'saveas-file') {
      if (!suggestedName) suggestedName = baseOf(asked);
    } else {
      selection.push(asked);
    }
  }

  //: The selection is matched by name in the folder being shown: a path
  //: Ash sent may begin at ~ where the rows carry it in full.
  function selectNamed(names) {
    const want = new Set(names);
    if (!want.size) return null;
    let first = null;
    $$(ITEMS).filter(onScreen).forEach(el => {
      if (!want.has(el.getAttribute('data-n'))) return;
      if (!first) {
        //: The page's own click, so the details pane and the status bar
        //: follow, then the rest added to it.
        el.click();
        first = el;
      } else {
        el.classList.add('sel');
      }
    });
    if (first) {
      first.scrollIntoView({block: 'center'});
      if (window.__updateStatus) window.__updateStatus();
    }
    return first;
  }

  window.__launch = {
    directory,
    started() {
      if (pickerType) {
        picker.start();
        if (suggestedName && nameBox) {
          nameBox.focus();
          const dot = suggestedName.lastIndexOf('.');
          nameBox.setSelectionRange(0, dot > 0 ? dot : suggestedName.length);
        }
        return;
      }
      const first = selectNamed(selection.map(baseOf));
      if (first && args.auradeProperties && window.__doAct) {
        window.__doAct('ctx-props');
      }
    },
  };

  // ---- the file chooser ---------------------------------------------------
  //: Each filter Ash sent, as typeList: extensions and a description. The
  //: index handed back counts from one, and nought is All files, which is
  //: how the dialog's caller reads it.
  const types = (Array.isArray(args.typeList) ? args.typeList : [])
    .map(t => ({
      exts: (Array.isArray(t && t.extensions) ? t.extensions : [])
        .filter(e => typeof e === 'string' && e)
        .map(e => e.toLowerCase().replace(/^\./, '')),
      label: (t && typeof t.description === 'string' && t.description) || '',
      selected: !!(t && t.selected),
    }))
    .filter(t => t.exts.length);
  types.forEach(t => {
    if (!t.label) t.label = t.exts.map(e => e.toUpperCase()).join(', ') + ' files';
  });
  const allFiles = !types.length || args.includeAllFiles !== false;
  //: The type Ash marked, and with none marked All files where there is
  //: one: an application offering "Unknown" as its current filter means
  //: anything may be chosen.
  const marked = types.findIndex(t => t.selected) + 1;
  let filterIndex = marked || (allFiles || !types.length ? 0 : 1);

  let bar = null, nameBox = null, okBtn = null, warn = null, replacing = '';

  function shows(el) {
    if (el.getAttribute('data-k') === 'Folder') return true;
    if (!filterIndex || !types[filterIndex - 1]) return true;
    const name = (el.getAttribute('data-n') || '').toLowerCase();
    return types[filterIndex - 1].exts.some(e => name.endsWith('.' + e));
  }
  function choosable(el) {
    const folder = el.getAttribute('data-k') === 'Folder';
    return choosesFolder ? folder : (pickerType === 'saveas-file' || !folder);
  }
  function chosenEls() {
    return liveSelEls().filter(el => !el.classList.contains('picker-hide'));
  }

  function syncRows() {
    if (!pickerType) return;
    $$(ITEMS).forEach(el => {
      const hide = !shows(el);
      el.classList.toggle('picker-hide', hide);
      //: Inline as well, which is what the keyboard and Select all read.
      if (hide) el.style.display = 'none';
      else if (el.style.display === 'none') el.style.display = '';
      el.classList.toggle('picker-off', !hide && choosesFolder &&
                          el.getAttribute('data-k') !== 'Folder');
      if (hide) el.classList.remove('sel');
    });
    updateOk();
  }

  function updateOk() {
    if (!okBtn) return;
    const sel = chosenEls();
    let ready;
    if (pickerType === 'saveas-file') {
      ready = !!(nameBox && nameBox.value.trim());
    } else if (choosesFolder) {
      ready = true;
    } else {
      ready = sel.some(el => el.getAttribute('data-k') !== 'Folder') ||
              sel.length === 1;
    }
    okBtn.disabled = !ready;
    okBtn.textContent = replacing ? 'Replace' : PICKERS[pickerType];
  }

  function say(text) {
    if (!warn) return;
    warn.textContent = text || '';
    warn.hidden = !text;
  }

  function fmp() {
    return (window.chrome && chrome.fileManagerPrivate) || null;
  }
  function call(fn, ...rest) {
    return new Promise((done, fail) => {
      fn(...rest, (value) => {
        const failed = window.chrome && chrome.runtime && chrome.runtime.lastError;
        if (failed) fail(new Error(failed.message || 'failed'));
        else done(value);
      });
    });
  }
  function closeDialog() {
    if (window.chrome && typeof chrome.send === 'function') {
      chrome.send('dialogClose', ['']);
    }
    //: In case nothing above was listening: a closed window is the answer
    //: either way, and Ash treats one closed without a choice as Cancel.
    setTimeout(() => window.close(), 400);
  }

  async function finish(paths) {
    const api = fmp();
    if (!api) {
      if (window.__toast) window.__toast('This window is not a file chooser');
      return;
    }
    okBtn.disabled = true;
    try {
      //: Asking for the root volume is what grants this page the root's
      //: file system, without which the addresses below do not resolve.
      await call(api.getVolumeRoot, {volumeId: ROOT_VOLUME});
      const urls = paths.map(filesUrlOf);
      if (pickerType === 'open-multi-file') {
        await call(api.selectFiles, urls, true);
      } else {
        await call(api.selectFile, urls[0], filterIndex,
                   pickerType !== 'saveas-file', true);
      }
      closeDialog();
    } catch (err) {
      okBtn.disabled = false;
      if (window.__toast) window.__toast(err.message || 'That could not be chosen');
    }
  }

  function cancel() {
    const api = fmp();
    if (api && api.cancelDialog) {
      try { api.cancelDialog(); } catch (err) {}
    }
    closeDialog();
  }

  function here() {
    return (window.__livePath || '/').replace(/\/+$/, '') || '';
  }

  async function choose(els) {
    const sel = (els && els.length ? els : chosenEls())
      .filter(el => !el.classList.contains('picker-hide'));
    const folders = sel.filter(el => el.getAttribute('data-k') === 'Folder');
    const files = sel.filter(el => el.getAttribute('data-k') !== 'Folder');
    if (choosesFolder) {
      //: A double click on a file chooses nothing in a folder chooser.
      if (els && els.length && !folders.length) return;
      const one = folders.length === 1 ? folders[0].getAttribute('data-p') : null;
      finish([one || here() || '/']);
      return;
    }
    if (pickerType !== 'saveas-file') {
      if (!files.length) {
        //: A folder is gone into, which is what Open on one means.
        if (folders.length === 1) renderLive(folders[0].getAttribute('data-p'));
        return;
      }
      const paths = files.map(el => el.getAttribute('data-p')).filter(Boolean);
      finish(pickerType === 'open-multi-file' ? paths : paths.slice(0, 1));
      return;
    }
    const name = (nameBox.value || '').trim();
    if (!name) {
      if (folders.length === 1) renderLive(folders[0].getAttribute('data-p'));
      return;
    }
    if (name.indexOf('/') !== -1 || name === '.' || name === '..') {
      say('A file name cannot have a / in it');
      return;
    }
    const existing = $$(ITEMS).find(el => el.getAttribute('data-n') === name);
    if (existing && existing.getAttribute('data-k') === 'Folder') {
      nameBox.value = suggestedName;
      renderLive(existing.getAttribute('data-p'));
      return;
    }
    if (existing && replacing !== name) {
      replacing = name;
      say('"' + name + '" already exists. Replace it?');
      updateOk();
      return;
    }
    finish([(here() || '') + '/' + name]);
  }

  function button(text, cls) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'picker-btn ' + cls;
    b.textContent = text;
    return b;
  }

  function buildBar() {
    bar = document.createElement('div');
    bar.className = 'picker-bar';
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', PICKERS[pickerType]);
    const fields = document.createElement('div');
    fields.className = 'picker-fields';
    if (pickerType === 'saveas-file') {
      const label = document.createElement('label');
      label.className = 'picker-name';
      const cap = document.createElement('span');
      cap.textContent = 'File name';
      nameBox = document.createElement('input');
      nameBox.type = 'text';
      nameBox.id = 'picker-name';
      nameBox.spellcheck = false;
      nameBox.autocomplete = 'off';
      nameBox.value = suggestedName;
      nameBox.addEventListener('input', () => {
        replacing = '';
        say('');
        updateOk();
      });
      label.append(cap, nameBox);
      fields.appendChild(label);
    }
    if (types.length) {
      const pick = document.createElement('select');
      pick.className = 'picker-types';
      pick.setAttribute('aria-label', 'File type');
      types.forEach((t, i) => {
        const o = document.createElement('option');
        o.value = String(i + 1);
        o.textContent = t.label;
        pick.appendChild(o);
      });
      if (allFiles) {
        const o = document.createElement('option');
        o.value = '0';
        o.textContent = 'All files';
        pick.appendChild(o);
      }
      pick.value = String(filterIndex);
      pick.addEventListener('change', () => {
        filterIndex = Number(pick.value) || 0;
        syncRows();
      });
      fields.appendChild(pick);
    }
    warn = document.createElement('div');
    warn.className = 'picker-warn';
    warn.setAttribute('role', 'alert');
    warn.hidden = true;
    const cancelBtn = button('Cancel', 'picker-cancel');
    okBtn = button(PICKERS[pickerType], 'picker-ok primary');
    cancelBtn.addEventListener('click', cancel);
    okBtn.addEventListener('click', () => choose(null));
    const buttons = document.createElement('div');
    buttons.className = 'picker-buttons';
    buttons.append(cancelBtn, okBtn);
    bar.append(fields, warn, buttons);
    const win = document.querySelector('.win');
    (win || document.body).appendChild(bar);
  }

  const picker = {
    active: () => !!pickerType,
    type: () => pickerType,
    sync: syncRows,
    choose,
    start() {
      if (!pickerType || bar) return;
      document.body.classList.add('picker');
      document.body.setAttribute('data-picker', pickerType);
      if (typeof args.title === 'string' && args.title) document.title = args.title;
      buildBar();
      syncRows();
      //: A row clicked in a save dialog names the file to save over, the
      //: way every save dialog has it; and the button follows the selection.
      document.addEventListener('click', e => {
        const it = e.target.closest && e.target.closest(ITEMS);
        if (it && nameBox && it.getAttribute('data-k') !== 'Folder') {
          nameBox.value = it.getAttribute('data-n') || '';
          replacing = '';
          say('');
        }
        setTimeout(updateOk, 0);
      });
      document.addEventListener('keyup', () => setTimeout(updateOk, 0));
      //: Before the page's own Escape, which closes menus and dialogs: one
      //: of those open takes the key, and only then is it Cancel.
      document.addEventListener('keydown', e => {
        const t = e.target || {};
        const typing = (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA') &&
                       t !== nameBox;
        if (e.key === 'Escape' && !typing && !document.querySelector(
              '.ctx:not([hidden]), .menu:not([hidden]), .scrim:not([hidden]),' +
              ' .open-with-scrim:not([hidden]), #props:not([hidden]),' +
              ' #namedlg:not([hidden])')) {
          e.preventDefault();
          cancel();
        } else if (e.key === 'Enter' && t === nameBox) {
          e.preventDefault();
          choose(null);
        }
      }, true);
    },
  };
  window.__picker = picker;
