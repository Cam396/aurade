  // Menus, tabs, context menus, selection, search, palette, panes, sorting, properties, drive actions.
  // Rule: no HTML string is ever assigned to an element (Trusted Types).
  // Everything toggles hidden, classList, textContent, or clones nodes.
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const grid = () => document.querySelector('.grid');
  const rows = () => document.querySelector('.rows');
  const mode = () => (window.__mode ? window.__mode() : 'grid');
  const inDetails = () => mode() === 'details';
  const setLayout = window.__setLayout || (() => {});
  const MODES = window.__modes || ['grid', 'details', 'list', 'cards', 'columns'];
  const ITEM_SEL = '.cell,.row,.lrow,.tile,.crow';

  // Where Home is. The static export knows it from its catalogue, the entry
  // marked isHome; the live layer learns it from the daemon's /api/system and
  // says so through window.__setHome. Nothing else spells it out: the
  // builder's own home had been written into every check here, and a page
  // that only knows root's home is wrong on every other machine.
  let HOME_PATH = (() => {
    const cat = window.__DIR_CATALOG || {};
    return Object.keys(cat).find(k => cat[k] && cat[k].isHome) || '~';
  })();
  const homePath = () => HOME_PATH;
  const homeKey = () => (HOME_PATH === '~' ? '~' : 'file://' + HOME_PATH);
  const isHomePath = p =>
    (p === '~' || p === 'Home' || p === HOME_PATH || p === homeKey());
  window.__setHome = p => { if (p && typeof p === 'string') HOME_PATH = p; };
  window.__homePath = homePath;
  window.__isHome = isHomePath;

  function hideOverlays() {
    $$('.menu').forEach(m => { m.hidden = true; });
    $$('.ctx').forEach(m => { m.hidden = true; });
    const sc = $('#sc-fly'); if (sc) sc.hidden = true;
  }

  function listItems() {
    const m = mode();
    const root = m === 'details' ? $('.dbody')
      : m === 'list' ? $('.list')
      : m === 'cards' ? $('.cards')
      : m === 'columns' ? $('.columns .col:last-child') : grid();
    if (!root) return [];
    return Array.from(root.children).filter(el => el.matches(ITEM_SEL));
  }
  function visibleItems() {
    return listItems().filter(el => el.style.display !== 'none');
  }
  function kbdVisible() {
    return listItems().filter(el => el.style.display !== 'none' && el.offsetParent !== null);
  }
  function selectedItems() {
    return visibleItems().filter(el => el.classList.contains('sel'));
  }

  function human(n) {
    n = Math.max(0, n);
    if (n < 1024) return n + ' B';
    const u = ['KB', 'MB', 'GB', 'TB'];
    let i = -1;
    do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
    return n.toFixed(1) + ' ' + u[i];
  }

  /**
   * The status bar, in one place.
   *
   * There were four of these: this one, a second count written by applyFilter
   * immediately before it called this one, a third in the tab engine that knew
   * about Home but dropped the filter and the selected size, and a fourth
   * beside the live backend that knew neither. Whichever ran last decided what
   * the bar said, which is why a filtered folder showed its unfiltered count.
   *
   * `countOverride` is for the live backend, which knows how many entries a
   * folder has before the DOM does.
   */
  function updateStatus(countOverride) {
    // Not filtered by offsetParent: listItems() already scopes to the active
    // layout's root, and on Home that root sits inside a hidden ancestor, so
    // the extra filter emptied the selection text on the one page that has
    // both a grid and a widget view.
    const sel = selectedItems();
    const d = $('#st-div'), s = $('#st-sel');
    const zd = $('#st-sizediv'), z = $('#st-size');
    const c = $('#st-count');
    if (c) {
      const curTab = tabs.find(t => t.id === activeTabId);
      const q = activeFilter().trim();
      if (curTab && curTab.isHome) {
        c.textContent = 'Ready';
      } else if (typeof countOverride === 'number') {
        c.textContent = countOverride + (countOverride === 1 ? ' item' : ' items');
      } else {
        c.textContent = q
          ? visibleItems().length + ' of ' + listItems().length + ' items'
          : listItems().length + ' items';
      }
    }
    if (!d || !s) return;
    if (!sel.length) {
      d.hidden = true; s.hidden = true;
      if (zd) zd.hidden = true;
      if (z) z.hidden = true;
      return;
    }
    d.hidden = false; s.hidden = false;
    s.textContent = sel.length === 1 ? '1 item selected' : sel.length + ' items selected';
    let bytes = 0, known = false;
    sel.forEach(el => {
      const b = parseInt(el.getAttribute('data-sb') || '-1', 10);
      if (b >= 0) { bytes += b; known = true; }
    });
    if (zd && z && known) {
      zd.hidden = false; z.hidden = false;
      z.textContent = human(bytes);
    } else {
      if (zd) zd.hidden = true;
      if (z) z.hidden = true;
    }
  }
  // The later scopes are separate IIFEs and cannot see the binding above.
  window.__updateStatus = updateStatus;

  const folderDefaults = {};
  let initialArt = null;
  let pvToken = 0;
  function snapDefaults() {
    $$('[data-dk]').forEach(c => { folderDefaults[c.getAttribute('data-dk')] = c.textContent; });
    const pn = $('[data-pk="Name"]'), pt = $('[data-pk="Type"]');
    if (pn) folderDefaults._pName = pn.textContent;
    if (pt) folderDefaults._pType = pt.textContent;
    const a = document.getElementById('ipart') || document.getElementById('det-art');
    if (a) initialArt = a.cloneNode(true);
  }

  function updateDetails(el) {
    const setD = (k, v) => {
      const c = document.querySelector('[data-dk="' + k + '"]');
      if (c) c.textContent = v;
    };
    const setP = (k, v) => {
      const c = document.querySelector('[data-pk="' + k + '"]');
      if (c) c.textContent = v;
    };
    const artTarget = document.getElementById('ipart') || document.getElementById('det-art');
    if (!el) {
      Object.keys(folderDefaults).forEach(k => {
        if (!k.startsWith('_')) setD(k, folderDefaults[k]);
      });
      if (folderDefaults._pName) setP('Name', folderDefaults._pName);
      if (folderDefaults._pType) setP('Type', folderDefaults._pType);
      if (artTarget && initialArt) {
        while (artTarget.firstChild) artTarget.removeChild(artTarget.firstChild);
        Array.from(initialArt.childNodes).forEach(n => artTarget.appendChild(n.cloneNode(true)));
      }
      pvToken += 1;
      const pvBox0 = document.getElementById('ipreview-text');
      if (pvBox0) { pvBox0.textContent = ''; pvBox0.hidden = true; }
      setPreviewImage(null);
      return;
    }
    const name = el.getAttribute('data-n') || '';
    const kind = el.getAttribute('data-k') || '';
    const when = el.getAttribute('data-w') || '';
    const size = el.getAttribute('data-s') || '';
    setD('Name', name);
    setD('Type', kind);
    setD('Modified', when);
    setD('Size', size);
    setD('Path', el.getAttribute('data-p') || name);
    setP('Name', name);
    setP('Type', kind);
    if (artTarget) {
      const src = el.querySelector('.thumb svg, .rico svg, .ricobox svg, .wcard-ico svg');
      if (src) {
        while (artTarget.firstChild) artTarget.removeChild(artTarget.firstChild);
        artTarget.appendChild(src.cloneNode(true));
      }
    }
    // The picture, when the page baked one or the backend can serve one. It is
    // moved into the art box rather than placed beside it, so the box keeps its
    // one frame and the glyph underneath stays as the fallback.
    setPreviewImage(el);
    const pvBox = document.getElementById('ipreview-text');
    if (pvBox) {
      const embedded = el.getAttribute('data-pv') || '';
      const p = el.getAttribute('data-p') || '';
      const isDir = (el.getAttribute('data-k') === 'Folder');
      pvToken += 1;
      if (embedded) {
        pvBox.textContent = embedded;
        pvBox.hidden = false;
      } else if (!isDir && p && window.__fetchPreview) {
        const my = pvToken;
        pvBox.textContent = '';
        pvBox.hidden = true;
        window.__fetchPreview(p).then(t => {
          if (my !== pvToken) return;
          if (t) { pvBox.textContent = t; pvBox.hidden = false; }
        }).catch(() => {});
      } else {
        pvBox.textContent = '';
        pvBox.hidden = true;
      }
    }
  }

  // Which selection the last thumbnail request belonged to. A fetch that lands
  // after the user has moved on must not paint, which is the same reason
  // pvToken exists for the text preview.
  let thToken = 0;

  // ---- rich previews -------------------------------------------------------
  // The reference has a preview control per file family. These are the two that
  // pay for themselves on a developer's machine: a rendered README and a source
  // file that is not a wall of one colour. Both build nodes rather than markup,
  // because chrome://file-manager enforces Trusted Types and a string of HTML
  // has nowhere to go there.

  const CODE_EXTS = new RegExp(
    '\\.(c|h|cc|cpp|hpp|cxx|go|rs|java|kt|swift|cs|rb|php|pl|lua|r|jl|scala|hs' +
    '|py|pyi|js|mjs|cjs|ts|tsx|jsx|vue|svelte|css|scss|less|json|jsonl|yaml|yml' +
    '|toml|ini|conf|cfg|sh|bash|zsh|fish|ps1|sql|xml|html|htm|svg|xaml|gn|gni' +
    '|proto|patch|diff)$', 'i');

  //: One keyword set. Splitting it per language buys almost nothing at preview
  //: size and costs a language table nobody maintains.
  const KEYWORDS = new Set((
    'abstract as async await base bool break byte case catch char class const ' +
    'constexpr continue crate def default defer del delete do double ' +
    'elif else end enum event explicit export extends extern false final ' +
    'finally float fn for foreach friend from func function global go goto if ' +
    'impl implements import in include inline instanceof int interface is ' +
    'lambda let library long loop match mod module mut mutable namespace new ' +
    'nil none not null nullptr operator or override package pass private ' +
    'protected pub public raise readonly ref require return sealed self short ' +
    'signed sizeof static struct super switch template this throw throws trait ' +
    'true try type typedef typeof union unsafe unsigned use using var virtual ' +
    'void volatile where while with yield'
  ).split(' '));

  function tokenClass(word) {
    if (KEYWORDS.has(word)) return 'tok-kw';
    if (/^\d/.test(word)) return 'tok-num';
    return '';
  }

  function renderCodeInto(box, text, name) {
    // A single pass, longest match first: comments and strings swallow
    // everything inside them, which is the whole reason a naive keyword
    // replace on the raw text gets the wrong answer inside a string literal.
    const pre = document.createElement('pre');
    pre.className = 'pv-code';
    const isDiff = /\.(patch|diff)$/i.test(name || '');
    text.split('\n').forEach(line => {
      const row = document.createElement('div');
      row.className = 'pv-line';
      if (isDiff) {
        if (line.startsWith('+')) row.className += ' pv-add';
        else if (line.startsWith('-')) row.className += ' pv-del';
        else if (line.startsWith('@@')) row.className += ' pv-hunk';
        row.textContent = line || ' ';
        pre.appendChild(row);
        return;
      }
      const re = /(\/\/[^\n]*|#[^\n]*|\/\*[\s\S]*?\*\/)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)|([A-Za-z_$][\w$]*|\d[\w.]*)/g;
      let at = 0, m;
      const push = (s, cls) => {
        if (!s) return;
        const node = document.createElement('span');
        if (cls) node.className = cls;
        node.textContent = s;
        row.appendChild(node);
      };
      while ((m = re.exec(line)) !== null) {
        push(line.slice(at, m.index), '');
        if (m[1]) push(m[1], 'tok-com');
        else if (m[2]) push(m[2], 'tok-str');
        else push(m[3], tokenClass(m[3]));
        at = m.index + m[0].length;
      }
      push(line.slice(at), '');
      if (!row.firstChild) row.textContent = ' ';
      pre.appendChild(row);
    });
    box.appendChild(pre);
  }

  window.__highlightCode = renderCodeInto;
  window.__isCodeName = function (name) { return CODE_EXTS.test(name || ''); };

  function setPreviewImage(el) {
    const box = document.getElementById('ipart');
    const img = document.getElementById('ipreview-img');
    if (!box || !img) return;
    thToken += 1;
    const my = thToken;
    const show = uri => {
      if (my !== thToken) return;
      img.src = uri;
      img.hidden = false;
      box.classList.add('has-img');
      box.appendChild(img);
    };
    const clear = () => {
      img.hidden = true;
      img.removeAttribute('src');
      box.classList.remove('has-img');
    };
    clear();
    if (!el) return;
    const baked = el.getAttribute('data-th') || '';
    if (baked) { show(baked); return; }
    const p = el.getAttribute('data-p') || '';
    if (!p || el.getAttribute('data-k') === 'Folder') return;
    if (!window.__fetchThumb) return;
    window.__fetchThumb(p).then(uri => { if (uri) show(uri); })
      .catch(() => {});
  }
  window.__setPreviewImage = setPreviewImage;

  const sortState = {
    fieldName: 'Name',
    attr: 'data-n',
    numeric: false,
    dir: 1,
    folderGroup: 'Folders first'
  };
  const SORT_FIELD = {
    'Name': ['data-n', false],
    'Date modified': ['data-ms', true],
    'Date created': ['data-ms', true],
    'Date deleted': ['data-ms', true],
    'Size': ['data-sb', true],
    'Type': ['data-k', false],
    'Tag': ['data-tags', false],
    'Path': ['data-p', false],
    'Original folder': ['data-origin', false],
    'Sync status': ['data-sync', false],
    'None': ['data-n', false]
  };
  // Sorting by a field, by the name Files calls it, so a command does not
  // have to know which attribute holds it.
  function sortBy(field) {
    const known = SORT_FIELD[field];
    if (!known) return false;
    sortState.fieldName = field;
    sortState.attr = known[0];
    sortState.numeric = known[1];
    applySort();
    updateSortChevron();
    return true;
  }
  window.__sortBy = sortBy;
  window.__sortFields = () => Object.keys(SORT_FIELD);

  function sortCmp(a, b) {
    if (sortState.folderGroup !== 'Files and folders together') {
      const aDir = a.getAttribute('data-k') === 'Folder' ? 1 : 0;
      const bDir = b.getAttribute('data-k') === 'Folder' ? 1 : 0;
      if (sortState.folderGroup === 'Folders first' && aDir !== bDir) return bDir - aDir;
      if (sortState.folderGroup === 'Files first' && aDir !== bDir) return aDir - bDir;
    }
    const av = a.getAttribute(sortState.attr) || '';
    const bv = b.getAttribute(sortState.attr) || '';
    if (sortState.numeric) {
      const an = parseFloat(av) || 0, bn = parseFloat(bv) || 0;
      return (an - bn) * sortState.dir;
    }
    return av.localeCompare(bv, undefined, { sensitivity: 'base' }) * sortState.dir;
  }

  function applySort() {
    const roots = [
      document.querySelector('.grid'),
      document.querySelector('.dbody'),
      document.querySelector('.list'),
      document.querySelector('.cards'),
      document.querySelector('.columns .col:last-child')
    ].filter(Boolean);
    roots.forEach(root => {
      const items = Array.from(root.children).filter(el => el.matches(ITEM_SEL));
      items.sort(sortCmp);
      items.forEach(el => root.appendChild(el));
    });
  }

  function updateSortChevron() {
    $$('.dh-col').forEach(dh => {
      const stale = dh.querySelector('.sort-ch');
      if (stale) dh.removeChild(stale);
      const svg = dh.querySelector('.dh-sort');
      if (!svg) return;
      const on = dh.getAttribute('data-dh') === sortState.fieldName;
      svg.hidden = !on;
      svg.classList.toggle('desc', on && sortState.dir !== 1);
    });
  }

  function syncSelectionOnLayout() {
    const prev = new Set(
      $$('.cell.sel, .row.sel, .lrow.sel, .tile.sel, .crow.sel')
        .map(el => el.getAttribute('data-n'))
        .filter(Boolean)
    );
    if (!prev.size) return;
    listItems().forEach(el => {
      const n = el.getAttribute('data-n');
      if (n && prev.has(n)) el.classList.add('sel');
      else el.classList.remove('sel');
    });
    updateStatus();
    const sel = selectedItems();
    updateDetails(sel.length === 1 ? sel[0] : null);
  }
  window.__syncSelectionOnLayout = syncSelectionOnLayout;

  //: Clearing is the one selection operation that has to reach every layout
  //: rather than only the one on screen. `listItems()` is deliberately the
  //: visible container, so a clear through it leaves the other four holding
  //: rows nobody can see, and `syncSelectionOnLayout` above reads across all
  //: five and brings them back: Ctrl+A, Escape, then switch to details, and
  //: everything is selected again because the details rows were never
  //: cleared.
  function clearSelection() {
    $$('.cell.sel, .row.sel, .lrow.sel, .tile.sel, .crow.sel')
      .forEach(el => el.classList.remove('sel'));
  }
  window.__clearSelection = clearSelection;

  function activeFilter() {
    const f = $('#finput'), o = $('#osearch');
    if (o && !o.hidden && o.value) return o.value;
    if (f && f.value) return f.value;
    return '';
  }
  function applyFilter() {
    const q = activeFilter().trim().toLowerCase();
    listItems().forEach(el => {
      const n = (el.getAttribute('data-n') || '').toLowerCase();
      el.style.display = (!q || n.indexOf(q) !== -1) ? '' : 'none';
    });
    updateStatus();
  }

  function exitSearch() {
    const o = $('#osearch'), c = $('#crumbs'), b = $('#btn-search');
    if (o) { o.hidden = true; o.value = ''; }
    if (c) c.hidden = false;
    if (b) b.setAttribute('aria-pressed', 'false');
    applyFilter();
  }

  function openPane(tab) {
    const p = $('#infopane');
    if (p) p.hidden = false;
    const b = $('#btn-pane');
    if (b) b.setAttribute('aria-pressed', 'true');
    if (tab) selectTab(tab);
  }
  function selectTab(name) {
    $$('.itab').forEach(t =>
      t.classList.toggle('on', t.getAttribute('data-itab') === name));
    const d = $('#ipane-details'), v = $('#ipane-preview');
    if (d) d.hidden = name !== 'details';
    if (v) v.hidden = name !== 'preview';
  }

  function openSettings() {
    hideOverlays();
    const fa = $('#filearea'), sp = $('#settings-page');
    if (fa) fa.hidden = true;
    if (sp) sp.hidden = false;
    syncThemeCk();
  }
  function closeSettings() {
    const fa = $('#filearea'), sp = $('#settings-page');
    if (sp) sp.hidden = true;
    if (fa) fa.hidden = false;
  }
  function settingsOpen() {
    const sp = $('#settings-page');
    return !!(sp && !sp.hidden);
  }
  function syncThemeCk() {
    const light = document.documentElement.dataset.theme === 'light';
    const d = $('#ck-dark'), l = $('#ck-light');
    if (d) d.classList.toggle('on', !light);
    if (l) l.classList.toggle('on', light);
  }
  function setTheme(t) {
    if (t === 'light') document.documentElement.dataset.theme = 'light';
    else document.documentElement.removeAttribute('data-theme');
    try { localStorage.setItem('aurade-theme', t); } catch (err) {}
    syncThemeCk();
  }
  function restoreTheme() {
    if (document.documentElement.dataset.theme) { syncThemeCk(); return; }
    let t = '';
    try { t = localStorage.getItem('aurade-theme') || ''; } catch (err) {}
    if (t === 'light' || t === 'dark') setTheme(t);
  }
  // --- icon sets ------------------------------------------------------------
  // Every set the machine can offer is already in #artlib. Switching is a
  // reskin, not a reload: walk the art that is on screen and swap each glyph
  // for the same category out of the chosen set. takeArt does the lookup, so
  // rows rendered later pick up the new set with no extra bookkeeping.
  const ICON_SETS = __BUILD("ICON_SET_JSON");
  // A clone carries its source's ids, which is a duplicate the moment it lands
  // in the document. Renaming them per clone is what keeps a folder's gradient
  // pointing at its own defs rather than at whichever copy came first. It lives
  // on window because two scripts clone art and both need the same counter.
  if (!window.__uniqArtIds) {
    window.__artSeq = 0;
    window.__uniqArtIds = function (svg) {
      var owned = svg.querySelectorAll('[id]');
      if (!owned.length) return svg;
      var n = ++window.__artSeq;
      var map = {};
      owned.forEach(function (d) {
        var old = d.getAttribute('id');
        map[old] = old + '__c' + n;
        d.setAttribute('id', map[old]);
      });
      var ATTRS = ['fill', 'stroke', 'filter', 'clip-path', 'mask', 'href'];
      svg.querySelectorAll('*').forEach(function (node) {
        ATTRS.forEach(function (a) {
          var v = node.getAttribute(a);
          if (!v) return;
          var m = /^url\(#(.+)\)$|^#(.+)$/.exec(v);
          var key = m && (m[1] || m[2]);
          if (!key || !map[key]) return;
          node.setAttribute(a, m[1] ? 'url(#' + map[key] + ')' : '#' + map[key]);
        });
      });
      return svg;
    };
  }
  function uniqArtIds(svg) { return window.__uniqArtIds(svg); }
  function reskinArt() {
    // Skip #artlib. It is the source every other glyph is cloned from, so
    // reskinning it would overwrite the other sets with the active one and
    // there would be nothing left to switch back to.
    document.querySelectorAll('svg.art[data-art]').forEach(function (svg) {
      if (svg.closest('#artlib')) return;
      const key = svg.getAttribute('data-art');
      const rep = takeArt(key, svg.getAttribute('data-art-sm') === '1');
      if (rep) svg.replaceWith(rep);
    });
  }
  // What is on screen right now. The server rendered the built-in set, so at
  // boot the attribute needs setting but nothing needs replacing.
  let __appliedSet = '@@ICON_SET@@';
  function applyIconSet(name) {
    if (!ICON_SETS[name]) name = '@@ICON_SET@@';
    document.documentElement.setAttribute('data-iconset', name);
    if (name === __appliedSet) return;
    __appliedSet = name;
    reskinArt();
  }
  const TB_DEFAULT_MAIN = __BUILD("TOOLBAR_DEFAULT_JSON");
  function applyToolbar(ids) {
    const bar = document.querySelector('.toolbar');
    if (!bar) return;
    const list = (Array.isArray(ids) && ids.length) ? ids : TB_DEFAULT_MAIN;
    const rank = (el) => {
      const i = list.indexOf(el.getAttribute('data-tb'));
      return i === -1 ? 999 : i;
    };
    bar.querySelectorAll('[data-tb]').forEach((el) => {
      el.hidden = list.indexOf(el.getAttribute('data-tb')) === -1;
    });
    bar.querySelectorAll('.tbgroup').forEach((group) => {
      const kids = Array.from(group.children).filter(
        (c) => c.hasAttribute('data-tb'));
      kids.sort((a, b) => rank(a) - rank(b));
      kids.forEach((k) => group.appendChild(k));
      //: The separator has no id of its own and appendChild would strand it
      //: at the front, so it is put back after the first button.
      const sep = group.querySelector('.tsep');
      if (sep && group.firstElementChild) {
        group.insertBefore(sep, group.firstElementChild.nextSibling);
      }
    });
  }
  window.__applyToolbar = applyToolbar;
  window.__applyIconSet = applyIconSet;
  window.__iconSets = ICON_SETS;
  window.__takeArt = takeArt;

  const PREFS_KEY = 'aurade-prefs';
  const DEF_PREFS = {
    startup: 'home', 'widgets.qa': true, 'widgets.drives': true,
    'widgets.network': true, 'widgets.tags': true,
    'widgets.recent': true, showStatusbar: true, showSCBtn: true,
    showThumbnails: true,
    showPaneBtn: true, showToolbar: true, showShelfBtn: true,
    thumbnailCache: true,
    defLayout: 'grid', sortBy: 'Name', sortDesc: false,
    groupBy: 'first', showHidden: false, showExt: true, singleClick: false,
    openNewTab: false, confirmDelete: true, dblclickUp: false,
    iconSet: '@@ICON_SET@@', backdropMaterial: 'Mica',
    'columns.widths': null, gridSize: 'medium'
  };
  let PREFS = {};
  function loadPrefs() {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(PREFS_KEY) || '{}'); }
    catch (err) { saved = {}; }
    PREFS = Object.assign({}, DEF_PREFS, saved);
  }
  function savePrefs() {
    try { localStorage.setItem(PREFS_KEY, JSON.stringify(PREFS)); }
    catch (err) {}
  }
  function getPref(k) {
    return k in PREFS ? PREFS[k] : DEF_PREFS[k];
  }
  function setPref(k, v) {
    PREFS[k] = v;
    savePrefs();
    applyPref(k);
  }
  //: Grid size is a modifier on the grid layout, not a layout of its own, so
  //: it survives switching away to Details and back the way the reference's
  //: does.
  const GRID_SIZES = ['small', 'medium', 'large'];
  function setGridSize(size) {
    const s = GRID_SIZES.indexOf(size) === -1 ? 'medium' : size;
    document.documentElement.setAttribute('data-gridsize', s);
    setPref('gridSize', s);
    return s;
  }
  function applyGridSize() {
    const s = getPref('gridSize');
    document.documentElement.setAttribute(
      'data-gridsize', GRID_SIZES.indexOf(s) === -1 ? 'medium' : s);
  }
  window.__gridSize = { set: setGridSize, get: () => getPref('gridSize') };

  window.__setPref = setPref;

  //: Files' ContentDialog, as a promise. Every dialog in src/Files.App/Dialogs
  //: is one of these: it opens, it takes one answer, it closes, and whatever
  //: opened it waits for that answer. The answer is the name of the button,
  //: which is the reference's Primary, Secondary and Close, or the value on
  //: a row the dialog offered a choice from. Escape answers Close, because
  //: that is what a ContentDialog does with it.
  let dlgOpen = null;
  function openDialog(id, setup) {
    const d = document.getElementById(id);
    if (!d) return Promise.resolve('close');
    if (dlgOpen) closeDialog('close');
    const back = document.activeElement;
    if (typeof setup === 'function') setup(d);
    //: The primary button's state is read off what is in the boxes before
    //: the dialog is seen, so it never opens with a Create that a person can
    //: click and nothing behind it.
    dialogCheck(id);
    d.hidden = false;
    const first = d.querySelector(
      'input:not([type=hidden]):not([disabled]), select:not([disabled]),'
      + ' .cdlg-item, [data-dlg="primary"]');
    if (first) {
      first.focus();
      if (first.select) first.select();
    }
    return new Promise(resolve => { dlgOpen = {id: id, resolve: resolve, back: back}; });
  }
  function closeDialog(answer) {
    const open = dlgOpen;
    dlgOpen = null;
    if (!open) return;
    const d = document.getElementById(open.id);
    if (d) d.hidden = true;
    if (open.back && open.back.focus) open.back.focus();
    open.resolve(answer || 'close');
  }
  //: Which one is open, so the Escape chain can close it before it reaches
  //: the overlays underneath, and a second dialog can wait for the first.
  function dialogOpen() { return dlgOpen ? dlgOpen.id : null; }
  function dialogSay(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text || '';
    if (el) el.hidden = !text;
  }
  //: The reference binds IsPrimaryButtonEnabled to its view model, so a
  //: dialog holding something it cannot use greys its own button out rather
  //: than taking the answer and failing afterwards.
  const DLG_VALID = new Map();
  function dialogValidity(did, test) { DLG_VALID.set(did, test); }
  function dialogCheck(did) {
    const d = document.getElementById(did);
    const test = DLG_VALID.get(did);
    if (!d || !test) return;
    const go = d.querySelector('[data-dlg="primary"]');
    if (go) go.disabled = !test(d);
  }
  document.addEventListener('input', e => {
    if (!dlgOpen) return;
    const d = document.getElementById(dlgOpen.id);
    if (d && d.contains(e.target)) dialogCheck(dlgOpen.id);
  });

  //: A name Files would take for a file: something, with none of the
  //: characters a path is made of in it.
  function goodName(name) {
    const clean = (name || '').trim();
    return !!clean && !/[\/:*?"<>|]/.test(clean) && !/[. ]+$/.test(clean);
  }

  //: Bulk rename. Files shows it from Rename when more than one item is
  //: selected, and every one of them takes the name that was typed and keeps
  //: its own extension, with a clash making a new name rather than refusing.
  //: BulkRenameDialogViewModel.DoCommitRenameAsync.
  dialogValidity('dlg-bulkrename', d => {
    const v = (d.querySelector('#br-name').value || '').trim();
    return goodName(v) && v.indexOf('.') < 0;
  });
  async function askBulkName() {
    const answer = await openDialog('dlg-bulkrename', d => {
      d.querySelector('#br-name').value = '';
    });
    if (answer !== 'primary') return null;
    return (document.getElementById('br-name').value || '').trim() || null;
  }
  //: The extension an item keeps through a bulk rename, which is Files'
  //: ListedItem.FileExtension: the last dot onwards, and nothing for a
  //: folder or a name with no dot in it.
  function extensionOf(name, isFolder) {
    if (isFolder) return '';
    const at = (name || '').lastIndexOf('.');
    return at > 0 ? name.slice(at) : '';
  }

  //: Create a new shortcut. The location, then the name it is saved under.
  dialogValidity('dlg-createshortcut', d =>
    !!(d.querySelector('#cs-path').value || '').trim() &&
    goodName(d.querySelector('#cs-name').value));
  async function askShortcut(where, name) {
    const answer = await openDialog('dlg-createshortcut', d => {
      d.querySelector('#cs-path').value = where || '';
      d.querySelector('#cs-name').value = name || '';
      dialogSay('cs-err', '');
    });
    if (answer !== 'primary') return null;
    return {
      target: (document.getElementById('cs-path').value || '').trim(),
      name: (document.getElementById('cs-name').value || '').trim()
    };
  }
  //: Files' FilesystemOperationDialog, which is one dialog for two
  //: questions: what to do about each name that is already taken, and
  //: whether to delete. FileSystemDialogViewModel.GetDialogViewModel writes
  //: the title, the line under it and the buttons from the counts, and they
  //: are written here the same way, with the reference's own strings.
  const FSOP_CHOICES = [['keep-both', 'Generate new name'],
                        ['replace', 'Replace existing'],
                        ['skip', 'Skip']];
  function fsopRow(name, mode) {
    const row = document.createElement('div');
    row.className = 'cdlg-conflict';
    row.dataset.name = name;
    const lbl = document.createElement('span');
    lbl.className = 'cdlg-lbl';
    lbl.textContent = name;
    lbl.title = name;
    row.appendChild(lbl);
    if (mode) {
      //: The name can be typed over, which is the reference's NameEdit box:
      //: a tap on the name of a row set to Generate new name turns it into a
      //: box, and what is typed is the name the item lands under.
      fsopEditable(lbl);
      const sel = document.createElement('select');
      sel.setAttribute('aria-label', name);
      FSOP_CHOICES.forEach(([v, t]) => {
        const o = document.createElement('option');
        o.value = v;
        o.textContent = t;
        sel.appendChild(o);
      });
      sel.value = mode;
      row.appendChild(sel);
    }
    return row;
  }
  function fsopEditable(lbl) {
    lbl.classList.add('cdlg-editable');
    lbl.setAttribute('role', 'button');
    lbl.tabIndex = 0;
    lbl.title = 'Type a name for it';
  }
  //: FilesystemOperationDialog.StartRename: only a row that will generate a
  //: name has one to type; a row set to replace or skip has nothing to name.
  function fsopStartRename(row) {
    const sel = row.querySelector('select');
    if (!sel || sel.value !== 'keep-both') return;
    if (row.querySelector('.cdlg-namebox')) return;
    const lbl = row.querySelector('.cdlg-lbl');
    const box = document.createElement('input');
    box.type = 'text';
    box.className = 'cdlg-namebox';
    box.setAttribute('aria-label', 'Name');
    box.autocomplete = 'off';
    box.spellcheck = false;
    box.value = row.dataset.custom || row.dataset.name;
    lbl.replaceWith(box);
    box.focus();
    box.select();
  }
  //: FilesystemOperationDialog.EndRename: the restricted characters go, and
  //: a name another row already lands under leaves the box open and the
  //: Continue button greyed, IsNameAvailableForItem.
  function fsopEndRename(row) {
    const box = row.querySelector('.cdlg-namebox');
    if (!box) return true;
    const typed = box.value.replace(/[\/\\:*?"<>|]/g, '').trim();
    const taken = Array.from(document.querySelectorAll('#fsop-rows .cdlg-conflict'))
      .filter(r => r !== row)
      .map(r => r.dataset.custom || r.dataset.name);
    const ok = !!typed && typed !== '.' && typed !== '..' && taken.indexOf(typed) < 0;
    const go = document.querySelector('#dlg-fsop [data-dlg="primary"]');
    if (!ok) {
      box.classList.add('bad');
      if (go) go.disabled = true;
      return false;
    }
    if (typed === row.dataset.name) delete row.dataset.custom;
    else row.dataset.custom = typed;
    const lbl = document.createElement('span');
    lbl.className = 'cdlg-lbl';
    lbl.textContent = typed;
    fsopEditable(lbl);
    box.replaceWith(lbl);
    if (go) go.disabled = false;
    return true;
  }
  //: The names the rows will land under, for a row set to generate one:
  //: the typed name, or null for the generated one.
  function fsopNames() {
    return Array.from(document.querySelectorAll('#fsop-rows .cdlg-conflict')).map(r => {
      const sel = r.querySelector('select');
      return sel && sel.value === 'keep-both' ? (r.dataset.custom || null) : null;
    });
  }
  document.addEventListener('click', e => {
    const lbl = e.target && e.target.closest && e.target.closest('#fsop-rows .cdlg-editable');
    if (lbl) fsopStartRename(lbl.closest('.cdlg-conflict'));
  });
  document.addEventListener('keydown', e => {
    const lbl = e.target && e.target.closest && e.target.closest('#fsop-rows .cdlg-editable');
    if (lbl && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      fsopStartRename(lbl.closest('.cdlg-conflict'));
      return;
    }
    const box = e.target && e.target.closest && e.target.closest('#fsop-rows .cdlg-namebox');
    if (!box) return;
    const row = box.closest('.cdlg-conflict');
    if (e.key === 'Enter') {
      e.preventDefault();
      e.stopPropagation();
      fsopEndRename(row);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      box.value = row.dataset.custom || row.dataset.name;
      fsopEndRename(row);
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      //: The reference's NameEdit_PreviewKeyDown: Up and Down move the box
      //: to the next row that will generate a name.
      e.preventDefault();
      if (!fsopEndRename(row)) return;
      const rows = Array.from(document.querySelectorAll('#fsop-rows .cdlg-conflict'))
        .filter(r => { const sel = r.querySelector('select'); return sel && sel.value === 'keep-both'; });
      const at = rows.indexOf(row);
      const next = rows[at + (e.key === 'ArrowDown' ? 1 : -1)];
      if (next) fsopStartRename(next);
    }
  }, true);
  document.addEventListener('focusout', e => {
    const box = e.target && e.target.closest && e.target.closest('#fsop-rows .cdlg-namebox');
    if (box) fsopEndRename(box.closest('.cdlg-conflict'));
  });
  //: Apply this action to all conflicting items reads Custom while the rows
  //: disagree and the shared choice while they agree, and setting it sets
  //: every row: FileSystemDialogViewModel.ApplyConflictOptionToAll.
  function fsopSync() {
    const rows = Array.from(document.querySelectorAll('#fsop-rows select'));
    const all = document.getElementById('fsop-all');
    if (!all || !rows.length) return;
    const first = rows[0].value;
    all.value = rows.every(s => s.value === first) ? first : '';
  }
  document.addEventListener('change', e => {
    if (!e.target || !e.target.closest) return;
    if (e.target.id === 'fsop-all') {
      if (!e.target.value) return;
      document.querySelectorAll('#fsop-rows select').forEach(s => {
        s.value = e.target.value;
      });
      return;
    }
    if (e.target.closest('#fsop-rows')) fsopSync();
  });
  async function askFsop(spec) {
    const d = document.getElementById('dlg-fsop');
    if (!d) return null;
    const rows = document.getElementById('fsop-rows');
    const go = d.querySelector('[data-dlg="primary"]');
    rows.replaceChildren();
    if (spec.kind === 'delete') {
      const n = spec.names.length;
      document.getElementById('dlg-fsop-t').textContent =
        n === 1 ? 'Delete item' : 'Delete items';
      document.getElementById('fsop-what').textContent =
        n === 1 ? 'One item will be deleted' : n + ' items will be deleted';
      go.textContent = 'Delete';
      spec.names.forEach(name => rows.appendChild(fsopRow(name, null)));
      document.getElementById('fsop-all-row').hidden = true;
      document.getElementById('fsop-perm-row').hidden = false;
      document.getElementById('fsop-permanent').checked = !!spec.permanent;
    } else {
      const c = spec.conflicts.length;
      const o = spec.others || 0;
      document.getElementById('dlg-fsop-t').textContent =
        (c + o) === 1 ? 'Conflicting file name' : 'Conflicting file names';
      let line = c === 1 ? 'There is one conflicting file name'
        : 'There are ' + c + ' conflicting file names';
      if (o > 0) {
        line += ', and ' + (o === 1 ? 'one outgoing item' : o + ' outgoing items');
      }
      document.getElementById('fsop-what').textContent = line;
      go.textContent = 'Continue';
      spec.conflicts.forEach(name => rows.appendChild(fsopRow(name, 'keep-both')));
      document.getElementById('fsop-all-row').hidden = false;
      document.getElementById('fsop-perm-row').hidden = true;
      fsopSync();
    }
    const answer = await openDialog('dlg-fsop');
    if (answer !== 'primary') return null;
    if (spec.kind === 'delete') {
      return {permanent: document.getElementById('fsop-permanent').checked};
    }
    return {
      choices: Array.from(rows.querySelectorAll('select')).map(s => s.value),
      names: fsopNames()
    };
  }
  //: Whether deleting asks first, which is the reference's
  //: ShowConfirmDeleteDialog and this page's two spellings of it.
  function deleteAsks() {
    try {
      if (window.SettingsEngine && typeof window.SettingsEngine.getPref === 'function') {
        const pol = window.SettingsEngine.getPref('confirmDeletePolicy');
        if (pol) return pol !== 'Never';
      }
    } catch (err) {}
    return getPref('confirmDelete') !== false;
  }
  //: Clone repo: one box, the address, and the folder is what git itself
  //: would name it. CloneRepoDialogViewModel.
  dialogValidity('dlg-clonerepo', d =>
    !!(d.querySelector('#cr-url').value || '').trim());
  async function askClone(url) {
    const answer = await openDialog('dlg-clonerepo', d => {
      d.querySelector('#cr-url').value = url || '';
      dialogSay('cr-err', '');
    });
    if (answer !== 'primary') return null;
    return (document.getElementById('cr-url').value || '').trim() || null;
  }
  //: Create branch: the name, what it starts from, and whether to switch
  //: to it, which the reference has on by default. AddBranchDialogViewModel.
  dialogValidity('dlg-addbranch', d => {
    const v = (d.querySelector('#ab-name').value || '').trim();
    return !!v && !/[\s~^:?*[\]\\]/.test(v) && v.indexOf('..') < 0
      && !v.startsWith('-');
  });
  async function askBranch(current, branches) {
    const answer = await openDialog('dlg-addbranch', d => {
      d.querySelector('#ab-name').value = '';
      const from = d.querySelector('#ab-from');
      from.replaceChildren();
      (branches || []).forEach(b => {
        const o = document.createElement('option');
        o.value = b;
        o.textContent = b;
        from.appendChild(o);
      });
      if (current) from.value = current;
      d.querySelector('#ab-switch').checked = true;
      dialogSay('ab-err', '');
    });
    if (answer !== 'primary') return null;
    return {
      name: (document.getElementById('ab-name').value || '').trim(),
      from: document.getElementById('ab-from').value || null,
      switchTo: document.getElementById('ab-switch').checked
    };
  }
  //: Reorder sidebar items: the pinned rows, dragged into an order, and
  //: Save puts the sidebar in it. ReorderSidebarItemsDialogViewModel.
  let reorderDrag = null;
  async function askReorder() {
    const list = document.getElementById('reorder-rows');
    if (!list || !window.__pinned) return null;
    list.replaceChildren();
    window.__pinned.rows().forEach(row => {
      const el = document.createElement('div');
      el.className = 'cdlg-item cdlg-drag';
      el.setAttribute('draggable', 'true');
      el.setAttribute('data-key', row.key);
      el.tabIndex = 0;
      const t = document.createElement('span');
      t.textContent = row.name;
      el.appendChild(t);
      list.appendChild(el);
    });
    const answer = await openDialog('dlg-reorder');
    if (answer !== 'primary') return null;
    const order = Array.from(list.querySelectorAll('[data-key]'))
      .map(el => el.getAttribute('data-key'));
    window.__pinned.reorder(order);
    return order;
  }
  document.addEventListener('dragstart', e => {
    const row = e.target.closest && e.target.closest('#reorder-rows [data-key]');
    if (!row) return;
    reorderDrag = row;
    e.dataTransfer.effectAllowed = 'move';
    try { e.dataTransfer.setData('text/plain', row.getAttribute('data-key')); } catch (err) {}
  });
  document.addEventListener('dragover', e => {
    if (!reorderDrag) return;
    const over = e.target.closest && e.target.closest('#reorder-rows [data-key]');
    if (!over || over === reorderDrag) return;
    e.preventDefault();
    const box = over.getBoundingClientRect();
    const after = e.clientY > box.top + box.height / 2;
    over.parentNode.insertBefore(reorderDrag, after ? over.nextSibling : over);
  });
  document.addEventListener('drop', e => {
    if (reorderDrag && e.target.closest && e.target.closest('#reorder-rows')) e.preventDefault();
    reorderDrag = null;
  });
  document.addEventListener('dragend', () => { reorderDrag = null; });
  window.__askReorder = askReorder;
  window.__askClone = askClone;
  window.__askBranch = askBranch;
  window.__fsop = askFsop;
  window.__deleteAsks = deleteAsks;
  window.__askBulkName = askBulkName;
  window.__askShortcut = askShortcut;
  window.__extensionOf = extensionOf;

  window.__dialog = {
    open: openDialog, close: closeDialog, which: dialogOpen, say: dialogSay
  };

  //: Column resize. The width of a column is one custom property read by both
  //: its header cell and its body cells, so a drag sets one number and the
  //: two can never disagree. Double click resets that column alone.
  const COL_DEFAULTS = { name: 180, tag: 140, git: 96, when: 200,
                         kind: 150, size: 100 };
  const COL_MIN = 56;
  const COL_MAX = 720;

  function colWidths() {
    const saved = getPref('columns.widths');
    const out = {};
    Object.keys(COL_DEFAULTS).forEach(k => {
      const v = saved && saved[k];
      out[k] = (typeof v === 'number' && v >= COL_MIN && v <= COL_MAX)
        ? v : COL_DEFAULTS[k];
    });
    return out;
  }

  function applyColWidths(w) {
    const s = document.documentElement.style;
    Object.keys(COL_DEFAULTS).forEach(k => {
      s.setProperty('--col-' + k, (w[k] || COL_DEFAULTS[k]) + 'px');
    });
  }

  function setColWidth(key, px) {
    const w = colWidths();
    w[key] = Math.round(Math.min(COL_MAX, Math.max(COL_MIN, px)));
    applyColWidths(w);
    setPref('columns.widths', w);
    return w[key];
  }

  let colDrag = null;
  document.addEventListener('pointerdown', (e) => {
    const grip = e.target.closest ? e.target.closest('.dh-grip') : null;
    if (!grip) return;
    e.preventDefault();
    e.stopPropagation();
    const key = grip.getAttribute('data-grip');
    const cell = grip.closest('.dh-col');
    colDrag = { key: key, x: e.clientX,
                start: cell.getBoundingClientRect().width };
    grip.classList.add('dragging');
    document.body.classList.add('colresizing');
    try { grip.setPointerCapture(e.pointerId); } catch (err) {}
  }, true);

  document.addEventListener('pointermove', (e) => {
    if (!colDrag) return;
    setColWidth(colDrag.key, colDrag.start + (e.clientX - colDrag.x));
  });

  function endColDrag() {
    if (!colDrag) return;
    colDrag = null;
    document.body.classList.remove('colresizing');
    const g = document.querySelector('.dh-grip.dragging');
    if (g) g.classList.remove('dragging');
  }
  document.addEventListener('pointerup', endColDrag);
  document.addEventListener('pointercancel', endColDrag);

  document.addEventListener('dblclick', (e) => {
    const grip = e.target.closest ? e.target.closest('.dh-grip') : null;
    if (!grip) return;
    e.preventDefault();
    e.stopPropagation();
    setColWidth(grip.getAttribute('data-grip'),
                COL_DEFAULTS[grip.getAttribute('data-grip')]);
  }, true);

  window.__cols = {
    widths: colWidths,
    set: setColWidth,
    reset: () => { applyColWidths(COL_DEFAULTS);
                   setPref('columns.widths', Object.assign({}, COL_DEFAULTS)); },
    defaults: () => Object.assign({}, COL_DEFAULTS)
  };
  applyColWidths(colWidths());

  window.__getPref = getPref;
  window.__doAct = doAct;
  window.__sortState = sortState;
  const GROUP_MAP = { first: 'Folders first', last: 'Files first',
    together: 'Files and folders together' };
  function applyPref(k) {
    if (k === 'iconSet') applyIconSet(getPref('iconSet'));
    if (k === 'toolbar.default') applyToolbar(getPref('toolbar.default'));
    if (k === 'gridSize') applyGridSize();
    if (k === 'backdropMaterial' && window.__mica)
      window.__mica.material(getPref('backdropMaterial'));
    else if (k === 'showExt') applyShowExt();
    else if (k.indexOf('widgets.') === 0) applyWidgets();
    else if (k === 'showThumbnails') applyThumbnails();
    else if (k === 'showStatusbar' || k === 'showSCBtn'
             || k === 'showPaneBtn' || k === 'showToolbar'
             || k === 'showShelfBtn') applyChrome();
    else if (k === 'sortBy' || k === 'sortDesc' || k === 'groupBy') applyDefaultSort();
    else if (k === 'groupByProperty' || k === 'groupByDesc'
             || k === 'groupByDateUnit') applyDefaultGrouping();
    else if (k === 'defLayout') {
      const h = window.location.hash;
      if (h !== '#details' && h !== '#list' && h !== '#cards' && h !== '#columns')
        setLayout(getPref('defLayout'));
    }
  }
  function stemName(name) {
    const i = name.lastIndexOf('.');
    if (i <= 0) return name;
    return name.slice(0, i);
  }
  function applyShowExt() {
    const on = getPref('showExt');
    $$('.cell,.row,.lrow,.tile,.crow').forEach(el => {
      const full = el.getAttribute('data-n') || '';
      const isDir = el.getAttribute('data-k') === 'Folder';
      const lbl = el.querySelector('.cname,.rname,.lname,.wcard-name,.lbl');
      if (lbl) lbl.textContent = (on || isDir || !full) ? full : stemName(full);
    });
  }
  const WID_MAP = { 'widgets.qa': 'wsec-quickaccess',
    'widgets.drives': 'wsec-drives', 'widgets.network': 'wsec-network',
    'widgets.tags': 'wsec-tags', 'widgets.recent': 'wsec-recent' };
  const WID_CK = { 'widgets.qa': 'ck-w-quickaccess',
    'widgets.drives': 'ck-w-drives', 'widgets.network': 'ck-w-network',
    'widgets.tags': 'ck-w-tags', 'widgets.recent': 'ck-w-recent' };
  function applyWidgets() {
    Object.keys(WID_MAP).forEach(k => {
      const s = document.getElementById(WID_MAP[k]);
      if (s) s.hidden = !getPref(k);
      const ck = document.getElementById(WID_CK[k]);
      if (ck) ck.classList.toggle('on', !!getPref(k));
    });
  }
  //: Off means the glyph, which is under every picture in the markup, so
  //: nothing has to be rebuilt and a folder does not flash on the way back.
  function applyThumbnails() {
    document.documentElement.classList.toggle(
      'no-thumbs', !getPref('showThumbnails'));
  }
  function applyChrome() {
    const st = document.querySelector('.status');
    if (st) st.hidden = !getPref('showStatusbar');
    const sc = $('#btn-sc');
    if (sc) sc.hidden = !getPref('showSCBtn');
    const pn = $('#btn-pane');
    if (pn) pn.hidden = !getPref('showPaneBtn');
    const tb = document.querySelector('.toolbar');
    if (tb) tb.hidden = !getPref('showToolbar');
    const sh = $('#btn-shelf');
    if (sh) sh.hidden = !getPref('showShelfBtn');
  }
  function applyDefaultSort() {
    const f = SORT_FIELD[getPref('sortBy')] || SORT_FIELD['Name'];
    sortState.fieldName = getPref('sortBy');
    sortState.attr = f[0];
    sortState.numeric = f[1];
    sortState.dir = getPref('sortDesc') ? -1 : 1;
    sortState.folderGroup = GROUP_MAP[getPref('groupBy')] || GROUP_MAP['first'];
    applySort();
    updateSortChevron();
  }
  //: The grouping the list starts in. The engine that draws the headers
  //: lives in the other scope, so this reaches it the way everything else
  //: does. None is not a grouping, and asking for it would draw one header
  //: over the whole list.
  function applyDefaultGrouping() {
    if (!window.__setGroupBy) return;
    //: dateBucket compares the unit against 'year' and 'month', and the
    //: select offers them with a capital.
    if (window.__setGroupUnit) {
      window.__setGroupUnit(String(getPref('groupByDateUnit') || 'month')
                            .toLowerCase());
    }
    if (window.__setGroupDir) window.__setGroupDir(getPref('groupByDesc') ? -1 : 1);
    const field = getPref('groupByProperty');
    window.__setGroupBy(field && field !== 'None' ? field : null);
  }
  function syncPrefControls() {
    $$('.sw[data-pref]').forEach(b => {
      const on = !!getPref(b.getAttribute('data-pref'));
      b.classList.toggle('on', on);
      b.setAttribute('aria-checked', on ? 'true' : 'false');
    });
    $$('.ssel[data-pref]').forEach(s => {
      s.value = String(getPref(s.getAttribute('data-pref')));
    });
  }
  function initPrefs() {
    loadPrefs();
    syncPrefControls();
    applyIconSet(getPref('iconSet'));
    applyToolbar(getPref('toolbar.default'));
    applyGridSize();
    if (window.__mica) window.__mica.material(getPref('backdropMaterial'));
    applyShowExt();
    applyWidgets();
    applyChrome();
    applyDefaultSort();
    applyDefaultGrouping();
    applyThumbnails();
    if (getPref('startup') === 'last') {
      const t = trail();
      const last = t.length ? t[t.length - 1] : null;
      if (last && last.u && last.u !== location.href) location.href = last.u;
    }
  }
  function openFolder(p, n) {
    if (getPref('openNewTab')) newTab(p, n || 'Folder', false, true);
    else navigateTo(p, n || 'Folder', false, true);
  }
  function downloadJson(name, obj) {
    const blob = new Blob([JSON.stringify(obj, null, 2)],
      { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(a.href);
      a.parentElement.removeChild(a);
    }, 500);
  }
  let nameOkCb = null, nameExclude = null;
  function invalidName(name, exclude) {
    const clean = (name || '').trim();
    if (!clean) return 'Enter a name.';
    if (/[\/:*?"<>|]/.test(clean)) return 'A name cannot contain \ / : * ? " < > |.';
    if (/[. ]+$/.test(clean)) return 'A name cannot end with a space or period.';
    const clash = listItems().find(el => el !== exclude &&
      (el.getAttribute('data-n') || '').toLowerCase() === clean.toLowerCase());
    if (clash) return 'There is already an item with this name.';
    return '';
  }
  function openNameDialog(title, initial, okLabel, exclude, cb) {
    const d = $('#namedlg');
    if (!d) return;
    hideOverlays();
    $('#namedlg-title').textContent = title;
    $('#namedlg-ok').textContent = okLabel;
    const inp = $('#namedlg-input');
    inp.value = initial;
    const err = $('#namedlg-err');
    err.hidden = true;
    err.textContent = '';
    nameOkCb = cb;
    nameExclude = exclude || null;
    d.hidden = false;
    inp.focus();
    inp.select();
  }
  function closeNameDialog() {
    const d = $('#namedlg');
    if (d) d.hidden = true;
    nameOkCb = null;
    nameExclude = null;
  }
  function submitNameDialog() {
    if (!nameOkCb) return;
    const inp = $('#namedlg-input');
    const err = $('#namedlg-err');
    const bad = invalidName(inp.value, nameExclude);
    if (bad) {
      err.textContent = bad;
      err.hidden = false;
      inp.focus();
      return;
    }
    const cb = nameOkCb;
    const val = inp.value.trim();
    closeNameDialog();
    cb(val);
  }
  function selectSTab(name) {
    $$('#settings-page .snav').forEach(t =>
      t.classList.toggle('on', t.getAttribute('data-snav') === name));
    $$('#settings-page .spane').forEach(p => {
      p.hidden = p.id !== 'spane-' + name;
    });
  }
  function filterSettings(q) {
    q = (q || '').trim().toLowerCase();
    $$('#settings-page .spane').forEach(pane => {
      let any = false;
      pane.querySelectorAll('.scard,.sact').forEach(card => {
        const hit = !q || (card.textContent || '').toLowerCase().indexOf(q) !== -1;
        card.hidden = !hit;
        if (hit) any = true;
      });
      pane.querySelectorAll('.ssec').forEach(sec => {
        let next = sec.nextElementSibling, show = false;
        while (next && !next.classList.contains('ssec')) {
          if (!next.hidden) { show = true; break; }
          next = next.nextElementSibling;
        }
        sec.hidden = !show && !!q;
      });
      if (!any && q) pane.hidden = true;
      else if (pane.id === 'spane-' + currentSTab()) pane.hidden = false;
    });
    $$('#settings-page .snav').forEach(n => {
      const pane = document.getElementById('spane-' + n.getAttribute('data-snav'));
      n.hidden = !!q && (!pane || pane.querySelectorAll('.scard:not([hidden]),.sact:not([hidden])').length === 0);
    });
  }
  function currentSTab() {
    const on = document.querySelector('#settings-page .snav.on');
    return on ? on.getAttribute('data-snav') : 'general';
  }

  const folderProps = {};
  const folderDetProps = {};
  function snapProps() {
    $$('[data-gk]').forEach(c => {
      folderProps[c.getAttribute('data-gk')] = c.textContent;
    });
    $$('[data-detk]').forEach(c => {
      folderDetProps[c.getAttribute('data-detk')] = c.textContent;
    });
  }
  function parentOf(p) {
    if (!p) return '';
    const t = p.replace(new RegExp('/+$'), '');
    const i = t.lastIndexOf('/');
    return i <= 0 ? '/' : t.slice(0, i);
  }

  let propsTargetDrive = null;
  function openProps(target) {
    const sel = selectedItems();
    const el = target || (sel.length === 1 ? sel[0] : null);
    fillProps(el);
    hideOverlays();
    const p = $('#props');
    if (p) p.hidden = false;
  }

  function fillProps(el) {
    const setG = (k, v) => {
      const c = document.querySelector('[data-gk="' + k + '"]');
      if (c) c.textContent = v;
    };
    const setD = (k, v) => {
      const c = document.querySelector('[data-detk="' + k + '"]');
      if (c) c.textContent = v;
    };
    const t = $('#props-title');
    const note = $('#h-note'), res = $('#hash-result'), hi = $('#hash-input');
    if (res) res.hidden = true;
    if (hi) hi.value = '';

    const pfile = $('#pgen-file');
    const pdrive = $('#pgen-drive');
    const thash = $('#props [data-ptab="hashes"]');
    const tdet = $('#props [data-ptab="details"]');
    const tsec = $('#props [data-ptab="security"]');
    if (tsec) tsec.hidden = false;
    // The Shortcut tab is offered only for something that actually is one, the
    // same way the reference hides it for an ordinary file. What it is gets
    // asked for once, on open, rather than carried on every row.
    fillShortcutTab(el);
    fillSignaturesTab(el);
    fillCustomizationTab(el);
    fillSecurityTab(el);

    const isDrive = el ? (el.getAttribute('data-kind') === 'drive' || el.classList.contains('wcard-drive')) : false;

    if (isDrive) {
      propsTargetDrive = el;
      if (pfile) pfile.hidden = true;
      if (pdrive) pdrive.hidden = false;
      if (thash) thash.hidden = true;
      if (tdet) tdet.hidden = true;

      const driveLabel = el ? (el.getAttribute('data-n') || 'System (/)') : 'System (/)';
      if (t) t.textContent = driveLabel + ' Properties';
      const dLabelInp = $('#props-drive-label');
      if (dLabelInp) dLabelInp.value = driveLabel;

      const dType = $('#pdrive-type');
      if (dType) dType.textContent = 'Local Fixed Disk';
      const dFs = $('#pdrive-fs');
      if (dFs) dFs.textContent = (el && el.getAttribute('data-fs')) || 'ext4';

      const total = parseInt((el && el.getAttribute('data-total')) || '1081101176832', 10);
      const free = parseInt((el && el.getAttribute('data-free')) || '822742265344', 10);
      const used = parseInt((el && el.getAttribute('data-used')) || '258358911488', 10);
      const pct = (el && el.hasAttribute('data-pct'))
        ? parseInt(el.getAttribute('data-pct'), 10)
        : (total > 0 ? Math.round((used / total) * 100) : 0);

      const ringFill = $('#pdrive-ring-fill');
      if (ringFill) {
        const offset = 163.36 * (1 - pct / 100);
        ringFill.setAttribute('stroke-dashoffset', String(offset));
      }
      const pctTxt = $('#pdrive-pct-txt');
      if (pctTxt) pctTxt.textContent = `${pct}%`;

      const dUsedGb = $('#pdrive-used-gb');
      if (dUsedGb) dUsedGb.textContent = human(used);
      const dUsed = $('#pdrive-used');
      if (dUsed) dUsed.textContent = used.toLocaleString() + ' bytes';

      const dFreeGb = $('#pdrive-free-gb');
      if (dFreeGb) dFreeGb.textContent = human(free);
      const dFree = $('#pdrive-free');
      if (dFree) dFree.textContent = free.toLocaleString() + ' bytes';

      const dCapGb = $('#pdrive-cap-gb');
      if (dCapGb) dCapGb.textContent = human(total);
      const dCap = $('#pdrive-cap');
      if (dCap) dCap.textContent = total.toLocaleString() + ' bytes';

      selectPTab('general');
      return;
    }

    if (pdrive) pdrive.hidden = true;
    if (pfile) pfile.hidden = false;

    const hashIds = [
      ['h-crc32', 'data-crc32'],
      ['h-md5', 'data-md5'],
      ['h-sha1', 'data-sha1'],
      ['h-sha256', 'data-sha256'],
      ['h-sha512', 'data-sha512']
    ];

    if (!el) {
      fillPropsIcon(null, true);
      Object.keys(folderProps).forEach(k => setG(k, folderProps[k]));
      Object.keys(folderDetProps).forEach(k => setD(k, folderDetProps[k]));
      const pNameInput = $('#props-name-input');
      if (pNameInput) pNameInput.value = folderProps['Name'] || 'Folder';
      if (t) t.textContent = 'Properties';
      hashIds.forEach(([id]) => {
        const h = document.getElementById(id);
        if (h) h.textContent = '';
      });
      if (note) note.textContent = 'Hashes are computed for files only.';
      if (thash) thash.hidden = true;
      if (tdet) tdet.hidden = true;
      const prowContains = $('#prow-contains');
      if (prowContains) {
        prowContains.hidden = false;
        setG('Contains', '14 files, 3 folders');
      }
      selectPTab('general');
      return;
    }

    const name = el.getAttribute('data-n') || '';
    const kind = el.getAttribute('data-k') || '';
    const isDir = kind === 'Folder' || el.classList.contains('wcard-folder');
    if (thash) thash.hidden = isDir;
    if (tdet) tdet.hidden = isDir;
    if (isDir) selectPTab('general');
    if (t) t.textContent = name + ' Properties';
    const pNameInput = $('#props-name-input');
    if (pNameInput) pNameInput.value = name;
    fillPropsIcon(el, isDir);

    setG('Name', name);
    setG('Type', isDir ? 'File folder' : (kind || 'File'));
    const loc = parentOf(el.getAttribute('data-p') || el.getAttribute('data-path') || homePath());
    setG('Location', loc);
    const mod = el.getAttribute('data-w') || '';
    const cre = el.getAttribute('data-c') || mod;
    const acc = el.getAttribute('data-a') || mod;
    setG('Modified', mod);
    setG('Created', cre);
    setG('Accessed', acc);
    const sz = el.getAttribute('data-s') || '';
    const ob = parseInt(el.getAttribute('data-ob') || '-1', 10);
    const prowContains = $('#prow-contains');
    const prowOpensWith = $('#prow-openswith');
    if (isDir) {
      setG('Size', '124 KB (126,976 bytes)');
      setG('Size on disk', '128 KB (131,072 bytes)');
      if (prowContains) { prowContains.hidden = false; setG('Contains', '14 files, 3 folders'); }
      if (prowOpensWith) prowOpensWith.hidden = true;
    } else {
      setG('Size', sz || '4.0 KB');
      setG('Size on disk', ob >= 0 ? human(ob) : (sz || '4.0 KB'));
      if (prowContains) prowContains.hidden = true;
      if (prowOpensWith) prowOpensWith.hidden = false;
    }
    setD('Name', name);
    setD('Type', isDir ? 'Folder' : (kind || 'File'));
    setD('Location', loc);
    setD('Size', isDir ? '' : sz);
    setD('Modified', mod);
    setD('Created', cre);
    setD('Accessed', acc);
    setD('Attributes', isDir ? '755' : '644');
    setD('Owner', 'root');
    setD('Authors', 'root');

    const md5Val = el.getAttribute('data-md5') || (isDir ? '' : 'e4d909c290d0fb1ca068ffaddf22cbd0');
    const sha1Val = el.getAttribute('data-sha1') || (isDir ? '' : '2aae6c35c94fcfb415dbe95f408b9ce91ee846ed');
    const sha256Val = el.getAttribute('data-sha256') || (isDir ? '' : 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
    const crc32Val = el.getAttribute('data-crc32') || (isDir ? '' : 'cbf43926');
    const sha512Val = el.getAttribute('data-sha512') || (isDir ? '' : 'ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f');

    const hCrc = $('#h-crc32'); if (hCrc) hCrc.textContent = crc32Val;
    const hMd5 = $('#h-md5'); if (hMd5) hMd5.textContent = md5Val;
    const hSha1 = $('#h-sha1'); if (hSha1) hSha1.textContent = sha1Val;
    const hSha256 = $('#h-sha256'); if (hSha256) hSha256.textContent = sha256Val;
    const hSha512 = $('#h-sha512'); if (hSha512) hSha512.textContent = sha512Val;

    if (note) note.textContent = isDir ? 'Hashes are computed for files only.' : '';
    selectPTab('general');
  }

  //: The Signatures tab. Files reads Authenticode here, which is a Windows
  //: thing with no counterpart; the nearest true one is a detached OpenPGP
  //: signature beside the file, or a file that carries one inside it. The tab
  //: appears only when there is something to say, because one that always
  //: reads "not signed" teaches people to stop looking at it.
  const SIGNATURE_WORDS = {
    GoodAndTrusted: 'Signed, by a key you have marked as trusted',
    GoodButUntrusted: 'Signed, by a key nothing vouches for',
    Bad: 'The signature does not match this file',
    KeyMissing: 'Signed by a key that is not in your keyring',
    KeyExpiredOrRevoked: 'Signed by a key that is expired or revoked',
    NotSigned: 'Not signed'
  };
  const SIGNATURE_NOTES = {
    Bad: 'This file has changed since it was signed, or it was signed by a '
       + 'different key from the one being checked against.',
    KeyExpiredOrRevoked: 'The signature matches, and the owner of the key has '
       + 'since said not to rely on it.',
    GoodButUntrusted: 'A matching signature is not proof of origin. It says '
       + 'the file has not changed since that key signed it, and nothing yet '
       + 'says the key belongs to who it claims to.',
    KeyMissing: 'There is nothing to check the signature against until that '
       + 'key is in your keyring.'
  };
  //: Which three bits of the mode belong to each principal, and which row
  //: of the reference's table each combination of them lights up. Files'
  //: Windows rights map onto POSIX like this: Read is r, Write is w, Read
  //: and execute is r and x together, List directory contents is the same
  //: pair on a folder, Modify is r and w, and Full control is all three.
  const SEC_SHIFT = {owner: 6, group: 3, others: 0};
  const SEC_ROWS = {
    full: (r, w, x) => r && w && x,
    modify: (r, w, x) => r && w,
    readexec: (r, w, x) => r && x,
    list: (r, w, x) => r && x,
    read: (r, w, x) => r,
    write: (r, w, x) => w
  };
  //: What ticking a row asks for, as the bits it turns on, and what
  //: unticking it turns off. Read and execute and List directory contents
  //: are the same pair of bits under two names, which is true on Windows too.
  const SEC_SETS = {
    full: [7, 7], modify: [6, 2], readexec: [5, 1],
    list: [5, 1], read: [4, 4], write: [2, 2]
  };
  let secProps = null;
  let secWho = 'owner';

  function secBits(mode, who) {
    return (mode >> SEC_SHIFT[who]) & 7;
  }

  function secDraw() {
    const users = $('#sec-users');
    const perms = $('#sec-perms');
    const note = $('#sec-note');
    const empty = $('#sec-empty');
    const modeTxt = $('#sec-mode');
    if (!users || !perms) return;
    if (!secProps) {
      users.replaceChildren();
      if (empty) empty.hidden = false;
      if (modeTxt) modeTxt.textContent = '';
      perms.querySelectorAll('input').forEach(b => {
        b.checked = false;
        b.disabled = true;
      });
      if (note) {
        note.textContent = 'This backend does not report permissions, so'
          + ' none are shown. Nothing here is a guess.';
        note.hidden = false;
      }
      return;
    }
    if (empty) empty.hidden = true;
    if (note) note.hidden = true;
    const named = {
      owner: 'Owner (' + (secProps.user || secProps.uid) + ')',
      group: 'Group (' + (secProps.group || secProps.gid) + ')',
      others: 'Everyone else'
    };
    users.replaceChildren();
    Object.keys(named).forEach(who => {
      const row = document.createElement('div');
      row.className = 'sec-user' + (who === secWho ? ' on' : '');
      row.setAttribute('data-who', who);
      row.textContent = named[who];
      row.onclick = () => { secWho = who; secDraw(); };
      users.appendChild(row);
    });
    const label = $('#sec-who');
    if (label) label.textContent = named[secWho];
    const bits = secBits(secProps.mode, secWho);
    const r = !!(bits & 4), w = !!(bits & 2), x = !!(bits & 1);
    perms.querySelectorAll('.sec-perm-row').forEach(row => {
      const key = row.getAttribute('data-perm');
      const box = row.querySelector('input');
      if (key === 'list') row.hidden = !secProps.isDirectory;
      if (key === 'readexec') row.hidden = !!secProps.isDirectory;
      if (!box || !SEC_ROWS[key]) return;
      box.checked = !!SEC_ROWS[key](r, w, x);
      box.disabled = false;
      box.onchange = () => secSet(key, box.checked);
    });
    if (modeTxt) {
      modeTxt.textContent = secProps.symbolic + '  '
        + (secProps.mode & 0o777).toString(8).padStart(3, '0');
    }
    const acl = $('#sec-acl');
    if (acl && !acl.hidden) secDrawAcl();
  }

  function secSet(key, on) {
    if (!secProps) return;
    const shift = SEC_SHIFT[secWho];
    const pair = SEC_SETS[key];
    let bits = secBits(secProps.mode, secWho);
    bits = on ? (bits | pair[0]) : (bits & ~pair[1]);
    const next = (secProps.mode & ~(7 << shift)) | ((bits & 7) << shift);
    secApply(next);
  }

  function secApply(mode) {
    const path = secProps && secProps.path;
    if (!path || !window.__chmod) return;
    window.__chmod(path, mode).then(out => {
      const note = $('#sec-note');
      if (!out || typeof out.mode !== 'number') {
        if (note) {
          note.textContent = 'The permission was not changed.';
          note.hidden = false;
        }
        return;
      }
      secProps.mode = out.mode;
      secProps.symbolic = secSymbolic(out.mode);
      secDraw();
    });
  }

  //: The same nine letters the backend writes, recomputed here after a
  //: change rather than asked for again, so the table does not flicker
  //: through a stale value on the way to the same answer.
  function secSymbolic(mode) {
    let out = '';
    [[6, 0o4000, 'S', 's'], [3, 0o2000, 'S', 's'],
     [0, 0o1000, 'T', 't']].forEach(([shift, special, upper, lower]) => {
      const bits = (mode >> shift) & 7;
      out += (bits & 4) ? 'r' : '-';
      out += (bits & 2) ? 'w' : '-';
      out += (bits & 1) ? ((mode & special) ? lower : 'x')
                        : ((mode & special) ? upper : '-');
    });
    return out;
  }

  function secDrawAcl() {
    const box = $('#sec-acl');
    if (!box) return;
    box.replaceChildren();
    const list = secProps && secProps.acl;
    if (!Array.isArray(list)) {
      const p = document.createElement('div');
      p.className = 'sec-desc';
      p.textContent = 'This backend does not read access control lists.';
      box.appendChild(p);
      return;
    }
    if (!list.length) {
      const p = document.createElement('div');
      p.className = 'sec-desc';
      p.textContent = 'No entries beyond the mode bits above.';
      box.appendChild(p);
      return;
    }
    const head = document.createElement('div');
    head.className = 'sec-perm-h';
    ['Type', 'Principal', 'Access', 'Applies to'].forEach(t => {
      const s = document.createElement('span');
      s.textContent = t;
      head.appendChild(s);
    });
    box.appendChild(head);
    list.forEach(e => {
      const row = document.createElement('div');
      row.className = 'sec-perm-row';
      [e.kind || '', e.who || '', e.perms || '',
       e.default ? 'This folder, subfolders and files' : 'Only this folder']
        .forEach(t => {
          const s = document.createElement('span');
          s.textContent = t;
          row.appendChild(s);
        });
      box.appendChild(row);
    });
  }

  //: Files' Advanced dialog is a window of its own; here it is the same
  //: list opened underneath, because the entries beyond the mode bits are
  //: the whole of what that window adds.
  function secAdvanced() {
    const box = $('#sec-acl');
    if (!box) return;
    box.hidden = !box.hidden;
    if (!box.hidden) secDrawAcl();
  }

  function fillSecurityTab(el) {
    const tab = $('#props [data-ptab="security"]');
    const path = el ? (el.getAttribute('data-p') || '') : '';
    secProps = null;
    secWho = 'owner';
    const acl = $('#sec-acl');
    if (acl) acl.hidden = true;
    const owner = $('#sec-owner');
    if (owner) owner.textContent = '';
    if (tab) tab.hidden = false;
    const adv = $('#sec-advanced');
    if (adv) adv.onclick = secAdvanced;
    secDraw();
    if (!path || !window.__props) return;
    window.__props(path).then(p => {
      if (!p || typeof p.mode !== 'number') return;
      secProps = p;
      if (owner) {
        owner.textContent = (p.user || String(p.uid))
          + ' (' + p.uid + ':' + p.gid + ')';
      }
      secDraw();
    });
  }

  function fillSignaturesTab(el) {
    const tab = $('#props [data-ptab="signatures"]');
    if (tab) tab.hidden = true;
    const path = el ? (el.getAttribute('data-p') || '') : '';
    if (!path || !window.__signature) return;
    window.__signature(path).then(sig => {
      if (!sig) return;
      // Not the sort of thing anyone signs, so the tab is not offered at
      // all. A file that is, and is not signed, gets the tab and is told
      // so: that is the reference's rule, and it is the difference between
      // "nobody signed it" and "not a question".
      const asked = sig.signable !== false;
      if (!asked) return;
      if (tab) tab.hidden = false;
      const none = $('#sig-none');
      const unsigned = !sig.signature && sig.status === 'NotSigned';
      if (none) none.hidden = !unsigned;
      const list = $('#ptab-signatures .prows');
      if (list) list.hidden = unsigned;
      const put = (id, v) => {
        const n = $('#' + id);
        if (n) n.textContent = v || '';
      };
      put('sig-status', SIGNATURE_WORDS[sig.status] || sig.status || '');
      put('sig-signer', sig.signer || 'Not stated');
      put('sig-key', sig.keyId || 'Not stated');
      put('sig-file', sig.signature ? sig.signature.split('/').pop()
                                    : 'Carried inside the file');
      put('sig-detail', sig.detail || '');
      const dh = $('#sig-detail-h');
      if (dh) dh.hidden = !(sig.detail && !unsigned);
      const note = $('#sig-note');
      if (note) {
        const words = SIGNATURE_NOTES[sig.status] || '';
        note.textContent = words;
        note.hidden = !words;
      }
    }).catch(() => {});
  }

  //: The Shortcut tab, filled from one stat. A symlink and a .desktop file are
  //: both shortcuts here; anything else hides the tab entirely.
  function fillShortcutTab(el) {
    const tab = $('#props [data-ptab="shortcut"]');
    if (tab) tab.hidden = true;
    const path = el ? (el.getAttribute('data-p') || '') : '';
    if (!path || !window.__statPath) return;
    window.__statPath(path).then(st => {
      if (!st || !st.linkKind) return;
      if (tab) tab.hidden = false;
      const put = (id, v) => {
        const n = $('#' + id);
        if (n) n.textContent = v || '';
      };
      put('lnk-kind', st.linkKind === 'desktop' ? 'Application shortcut'
                                                : 'Symbolic link');
      put('lnk-target', st.linkTarget);
      put('lnk-args', st.linkArgs || 'None');
      put('lnk-wd', st.linkWorkingDir || 'Not set');
      put('lnk-resolved', st.linkResolved);
      const note = $('#lnk-note');
      if (note) {
        note.hidden = !st.linkBroken;
        // Says what is true and what to do, and does not blame the person.
        note.textContent = st.linkBroken
          ? 'This shortcut points at something that is not there. Open the '
            + 'target location to see what moved.' : '';
      }
      const btn = $('#lnk-open');
      if (btn) btn.onclick = () => {
        const dir = st.linkWorkingDir || '';
        if (dir && window.__live && window.__live.render) {
          window.__live.render(dir);
          const dlg = document.getElementById('props');
          if (dlg) dlg.hidden = true;
        }
      };
    }).catch(() => {});
  }

  //: Customization. The Windows original points at a DLL and lists the icons
  //: inside it; there is no such file here, so the sources are the app's own
  //: drawn glyphs, listed in the grid, and any image on disk. What a folder
  //: is using is written on the folder itself, so it survives a rebuild of
  //: this page and travels with the folder rather than living in a database.
  let custTarget = '';

  function custSetNote(msg) {
    const n = $('#cust-note');
    if (!n) return;
    n.textContent = msg || '';
    n.hidden = !msg;
  }

  function custShowValue(value) {
    const v = value || '';
    const box = $('#cust-path');
    if (box) {
      box.value = !v ? 'Default icon'
        : (v.indexOf('glyph:') === 0 ? 'Built in icon: ' + v.slice(6)
                                     : v.slice(5));
    }
    $$('#cust-grid .cust-ico').forEach((b) => b.classList.toggle(
      'on', v === 'glyph:' + b.getAttribute('data-icon')));
    const rst = $('#cust-restore');
    if (rst) rst.disabled = !v;
  }

  async function custWrite(value) {
    const api = window.__api;
    if (!api || !custTarget) {
      custSetNote('A custom icon needs the live backend.');
      return;
    }
    try {
      const r = await fetch(api + '/api/icon', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: custTarget, icon: value })
      });
      const d = await r.json();
      if (!r.ok) {
        custSetNote(d.error || 'The icon could not be saved.');
        return;
      }
      custSetNote('');
      custShowValue(d.icon || '');
      if (window.__customIcons) window.__customIcons.refresh();
    } catch (err) {
      custSetNote('The icon could not be saved.');
    }
  }

  async function custUseFile(path) {
    const p = (path || '').trim();
    if (!p) { custSetNote('Type the path of an image file.'); return; }
    //: Checked before it is stored, so a path that is not there is answered
    //: here instead of becoming an icon that never draws.
    if (window.__statPath) {
      const st = await window.__statPath(p).catch(() => null);
      if (!st || st.isDirectory) {
        custSetNote('There is no image file at ' + p + '.');
        return;
      }
    }
    await custWrite('file:' + p);
  }

  function custWire() {
    const rst = $('#cust-restore');
    if (rst) rst.onclick = () => custWrite('');
    const brw = $('#cust-browse');
    const row = $('#cust-file-row');
    if (brw && row) brw.onclick = () => {
      row.hidden = !row.hidden;
      if (!row.hidden) { const f = $('#cust-file'); if (f) f.focus(); }
    };
    const app = $('#cust-file-apply');
    const fld = $('#cust-file');
    if (app && fld) app.onclick = () => custUseFile(fld.value);
    if (fld) fld.onkeydown = (e) => {
      if (e.key === 'Enter') { e.preventDefault(); custUseFile(fld.value); }
    };
    $$('#cust-grid .cust-ico').forEach((b) => {
      b.onclick = () => custWrite('glyph:' + b.getAttribute('data-icon'));
    });
  }

  //: A folder or a shortcut, the same two the reference offers the tab for.
  function fillCustomizationTab(el) {
    const tab = $('#props [data-ptab="customization"]');
    if (tab) tab.hidden = true;
    custTarget = el ? (el.getAttribute('data-p') || '') : '';
    custSetNote('');
    custShowValue('');
    custWire();
    const row = $('#cust-file-row');
    if (row) row.hidden = true;
    const fld = $('#cust-file');
    if (fld) fld.value = '';
    if (!custTarget || !window.__statPath) return;
    window.__statPath(custTarget).then((st) => {
      if (!st || (!st.isDirectory && !st.linkKind)) return;
      if (tab) tab.hidden = false;
      const api = window.__api;
      if (!api) return null;
      return fetch(api + '/api/icon?path=' + encodeURIComponent(custTarget))
        .then((r) => r.json())
        .then((d) => custShowValue(d.icon || ''))
        .catch(() => {});
    }).catch(() => {});
  }

  //: The reference's IsAudioFile and IsVideoFile, and the one video format
  //: its tag library has no writer for: the album cover flyout is offered
  //: for a file that is one of these and not for .avi.
  const COVER_AUDIO = ['mp3', 'm4a', 'ogg', 'oga', 'wav', 'wma', 'aac', 'adt', 'adts', 'cda', 'flac'];
  const COVER_VIDEO = ['mp4', 'webm', 'ogg', 'mov', 'qt', 'm4v', 'mp4v', '3g2', '3gp2', '3gp', '3gpp', 'mkv'];
  function coverOffered(name) {
    const at = String(name || '').lastIndexOf('.');
    if (at <= 0) return false;
    const ext = String(name).slice(at + 1).toLowerCase();
    return ext !== 'avi' && (COVER_AUDIO.indexOf(ext) >= 0 || COVER_VIDEO.indexOf(ext) >= 0);
  }
  window.__coverOffered = coverOffered;
  //: The window's icon is the item's own, the glyph and the picture it has in
  //: the list, in the reference's 56px card. The album cover flyout sits over
  //: it for a sound or video file, and the uncompressed size row is put away
  //: until the live layer has a number for it.
  function fillPropsIcon(el, isDir) {
    const art = $('#props-icon-art');
    const wrap = $('#props-cover-wrap');
    const unc = $('#prow-uncompressed');
    if (unc) { unc.hidden = true; }
    if (wrap) {
      wrap.hidden = true;
      wrap.classList.remove('open');
      const m = $('#m-cover');
      if (m) m.hidden = true;
    }
    if (!art) return;
    art.replaceChildren();
    const box = el ? el.querySelector('.thumb, .ricobox, .tico') : null;
    if (box && box.firstElementChild) {
      Array.from(box.children).forEach(c => {
        const copy = c.cloneNode(true);
        art.appendChild(copy.tagName === 'svg' ? uniqArtIds(copy) : copy);
      });
    } else {
      const a = takeArt(isDir ? 'folder' : 'txt', false);
      if (a) art.appendChild(a);
    }
    const name = el ? (el.getAttribute('data-n') || '') : '';
    if (wrap && el && !isDir && coverOffered(name)) wrap.hidden = false;
  }
  window.__fillPropsIcon = fillPropsIcon;

  function selectPTab(name) {
    $$('#props .ptab').forEach(t =>
      t.classList.toggle('on', t.getAttribute('data-ptab') === name));
    const g = $('#ptab-general');
    const h = $('#ptab-hashes');
    const d = $('#ptab-details');
    const s = $('#ptab-security');
    const k = $('#ptab-shortcut');
    const c = $('#ptab-customization');
    if (g) g.hidden = name !== 'general';
    if (h) h.hidden = name !== 'hashes';
    if (d) d.hidden = name !== 'details';
    if (s) s.hidden = name !== 'security';
    if (k) k.hidden = name !== 'shortcut';
    if (c) c.hidden = name !== 'customization';
  }

  //: The reference opens a picker and hashes what comes back. There is no
  //: picker here, so the path is typed into the same box the typed hash
  //: goes in, and the backend is asked for that file's hashes.
  function compareHashFile() {
    const inp = $('#hash-input'), res = $('#hash-result');
    if (!inp || !res) return;
    const other = inp.value.trim();
    res.hidden = false;
    if (!other || other.indexOf('/') < 0) {
      res.textContent = 'Type the path of a file to compare against.';
      res.className = 'hmatch';
      return;
    }
    if (!window.__hashOf) {
      res.textContent = 'Comparing a file needs the backend.';
      res.className = 'hmatch';
      return;
    }
    res.textContent = 'Calculating...';
    res.className = 'hmatch';
    window.__hashOf(other).then(h => {
      if (!h) {
        res.textContent = 'That file could not be read.';
        res.className = 'hmatch bad';
        return;
      }
      const mine = document.getElementById('h-sha256');
      const same = mine && mine.textContent
        && h.sha256 && mine.textContent.trim().toLowerCase()
           === String(h.sha256).toLowerCase();
      res.textContent = same ? 'The two files are the same (SHA-256).'
                             : 'The two files differ.';
      res.className = 'hmatch ' + (same ? 'ok' : 'bad');
    });
  }

  function compareHash() {
    const inp = $('#hash-input'), res = $('#hash-result');
    if (!inp || !res) return;
    const q = inp.value.trim().toLowerCase();
    if (!q) { res.hidden = true; return; }
    const vals = [
      ['CRC32', 'h-crc32'],
      ['MD5', 'h-md5'],
      ['SHA-1', 'h-sha1'],
      ['SHA-256', 'h-sha256'],
      ['SHA-512', 'h-sha512']
    ];
    const hit = vals.filter(([label, id]) => {
      const h = document.getElementById(id);
      return h && h.textContent && h.textContent.trim().toLowerCase() === q;
    })[0];
    res.hidden = false;
    if (hit) {
      res.textContent = 'Hashes match (' + hit[0] + ').';
      res.className = 'hmatch ok';
    } else {
      res.textContent = 'Hashes do not match.';
      res.className = 'hmatch bad';
    }
  }

  function openStorageSense(driveEl) {
    hideOverlays();
    const s = $('#storage-sense');
    if (!s) return;
    s.hidden = false;
    const label = (driveEl && driveEl.getAttribute('data-n')) || 'System (/)';
    const title = s.querySelector('.dlg-title');
    if (title) title.textContent = 'Storage - ' + label;
    const stStatus = $('#storage-status');
    if (stStatus) stStatus.hidden = true;
    const stBtn = $('#btn-storage-clean');
    if (stBtn) {
      stBtn.disabled = false;
      stBtn.textContent = 'Clean now (Free up 2.1 GB)';
    }
    const scTemp = $('#sc-temp-val');
    if (scTemp) scTemp.textContent = '2.1 GB';
    const tempBar = s.querySelector('.sm-temp');
    if (tempBar) tempBar.style.width = '2%';
  }

  function cleanStorageSense() {
    const btn = $('#btn-storage-clean');
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    btn.textContent = 'Cleaning temporary files...';
    setTimeout(() => {
      const scTemp = $('#sc-temp-val');
      if (scTemp) scTemp.textContent = '0 B';
      const tempBar = document.querySelector('#storage-sense .sm-temp');
      if (tempBar) tempBar.style.width = '0%';
      const stStatus = $('#storage-status');
      if (stStatus) {
        stStatus.textContent = 'Temporary files cleaned successfully. 2.1 GB recovered.';
        stStatus.hidden = false;
      }
      btn.textContent = 'Cleaned';
    }, 400);
  }

  function openFormatDrive(driveEl) {
    hideOverlays();
    const f = $('#format-drive');
    if (!f) return;
    f.hidden = false;
    const label = (driveEl && driveEl.getAttribute('data-n')) || 'System (/)';
    const title = $('#format-title');
    if (title) title.textContent = 'Format - ' + label;
    const labelInp = $('#fmt-label');
    if (labelInp) labelInp.value = label.replace(/[()]/g, '').trim();
    const progWrap = $('#fmt-prog-wrap');
    if (progWrap) progWrap.hidden = true;
    const pfill = $('#fmt-pfill');
    if (pfill) pfill.style.width = '0%';
    const fStatus = $('#fmt-status');
    if (fStatus) fStatus.textContent = 'Formatting...';
    const startBtn = $('#btn-format-start');
    if (startBtn) {
      startBtn.disabled = false;
      startBtn.textContent = 'Start';
    }
  }

  function startFormatDrive() {
    const btn = $('#btn-format-start');
    if (!btn) return;
    if (btn.textContent === 'Done') {
      const f = $('#format-drive');
      if (f) f.hidden = true;
      return;
    }
    btn.disabled = true;
    btn.textContent = 'Formatting...';
    const pw = $('#fmt-prog-wrap');
    if (pw) pw.hidden = false;
    const pf = $('#fmt-pfill');
    const st = $('#fmt-status');
    let p = 0;
    const iv = setInterval(() => {
      p += 25;
      if (pf) pf.style.width = Math.min(100, p) + '%';
      if (p >= 100) {
        clearInterval(iv);
        if (st) st.textContent = 'Format Complete.';
        btn.textContent = 'Done';
        btn.disabled = false;
      }
    }, 180);
  }

  let kbdFocus = null, kbdAnchor = null, typeBuf = '', typeTimer = 0;
  function setKbd(el) {
    $$('.kbd').forEach(x => x.classList.remove('kbd'));
    kbdFocus = el;
    if (el) {
      el.classList.add('kbd');
      try { el.scrollIntoView({block: 'nearest'}); } catch (err) {}
    }
  }

  // ---- Tab System ----
  const tabstrip = $("#tabstrip");
  const btnNewTab = $("#btn-newtab");
  let tabSeq = 1;
  const tabs = [];
  let activeTabId = 1;

  const winRoot = $(".win");
  const initialPath = winRoot ? (winRoot.getAttribute("data-path") || "/") : "/";
  const homeWidgetsEl = $("#home-widgets");
  const initialIsHome = !!(homeWidgetsEl && !homeWidgetsEl.hidden);
  const initialName = initialIsHome ? "Home" : (document.querySelector(".tname") ? document.querySelector(".tname").textContent : "Home");

  const tab1El = document.querySelector('.tab[data-tab-id="1"]');
  tabs.push({
    id: 1,
    name: initialName,
    path: initialPath,
    isHome: initialIsHome,
    el: tab1El,
    history: [{ name: initialName, path: initialPath, isHome: initialIsHome }],
    histIdx: 0,
    view: mode(),
    filter: "",
    sel: []
  });

  if (initialIsHome) {
    const views = $$(".grid, .rows, .list, .cards, .columns");
    views.forEach(v => { v.hidden = true; });
    if (homeWidgetsEl) homeWidgetsEl.hidden = false;
  }

  function findCatalogEntry(p, isHome) {
    const cat = window.__DIR_CATALOG || {};
    if (isHome || isHomePath(p)) {
      if (cat[homePath()]) return cat[homePath()];
      for (const k in cat) {
        if (cat[k] && cat[k].isHome) return cat[k];
      }
    }
    if (!p) return null;
    let norm = String(p);
    if (norm.startsWith("file://")) norm = norm.slice(7);
    while (norm.length > 1 && norm.endsWith("/")) norm = norm.slice(0, -1);
    if (cat[norm]) return cat[norm];

    let clean = norm;
    if (clean.startsWith("site/")) clean = clean.slice(5);

    const vals = Object.values(cat);
    for (let i = 0; i < vals.length; i++) {
      const entry = vals[i];
      if (!entry) continue;
      if (entry.path === norm || entry.name === norm) return entry;
      if (entry.href && (entry.href === clean || clean.endsWith(entry.href) || entry.href.endsWith(clean))) return entry;
    }

    const base = norm.split("/").filter(Boolean).pop();
    if (base) {
      for (let i = 0; i < vals.length; i++) {
        const entry = vals[i];
        if (!entry || !entry.path) continue;
        const entryBase = entry.path.split("/").filter(Boolean).pop();
        if (entryBase && entryBase === base) return entry;
      }
    }
    return null;
  }

  // The thumb box, filled the same way everywhere. A picture when the item has
  // one, the drawn glyph otherwise. Both render paths call this rather than
  // appending art directly, because the server rendered markup they replace
  // already had the picture in it and dropping back to a glyph on the first
  // repaint is exactly the bug this exists to prevent.
  function fillThumb(box, item, small) {
    if (!box) return;
    while (box.firstChild) box.removeChild(box.firstChild);
    //: The glyph goes in whether or not there is a picture, and the picture
    //: sits over it. That is what the server rendered markup does, so the
    //: two paths agree; it is also what makes turning thumbnails off a
    //: matter of hiding the picture rather than rebuilding the list, and
    //: what leaves a file icon behind when a data URI will not decode.
    const a = takeArt(item && item.art, small);
    if (a) box.appendChild(a);
    const uri = item && item.th;
    if (uri) {
      const img = document.createElement('img');
      img.className = 'thumbimg';
      img.alt = '';
      img.decoding = 'async';
      img.src = uri;
      box.appendChild(img);
    }
  }

  function takeArt(art, small) {
    let key = (art || "txt").toLowerCase();
    if (key === "text") key = "txt";
    const attr = small ? "data-rico" : "data-thumb";
    const otherAttr = small ? "data-thumb" : "data-rico";
    // The active set is unqualified in the artlib and every other set carries
    // data-set, so scoping the query is the whole of the icon-set switch.
    const set = document.documentElement.getAttribute("data-iconset") || "";
    const scope = (set && set !== "@@ICON_SET@@")
      ? '[data-set="' + set + '"]' : ':not([data-set])';
    const q = (s, a, k) =>
      document.querySelector('#artlib ' + s + '[' + a + '="' + k + '"] svg');
    let el = q(scope, attr, key) || q(scope, otherAttr, key) ||
             q(scope, attr, "txt") ||
             q(':not([data-set])', attr, key) ||
             q(':not([data-set])', otherAttr, key) ||
             q(':not([data-set])', attr, "txt") ||
             document.querySelector('#artlib svg');
    return el ? uniqArtIds(el.cloneNode(true)) : null;
  }

  function setRowAttrs(el, item) {
    if (!el || !item) return;
    el.setAttribute("data-n", item.name || "");
    el.setAttribute("data-k", item.kind || "");
    el.setAttribute("data-w", item.when || "");
    el.setAttribute("data-s", item.size || "");
    el.setAttribute("data-p", item.path || "");
    el.setAttribute("data-ms", String(item.ms || 0));
    el.setAttribute("data-sb", String(item.bytes !== undefined ? item.bytes : (item.sb || -1)));
    if (item.name) el.setAttribute("title", item.name);
    if (item.href) el.setAttribute("href", item.href);
    if (item.c || item.created) el.setAttribute("data-c", item.c || item.created);
    if (item.a || item.accessed) el.setAttribute("data-a", item.a || item.accessed);
    if (item.ob !== undefined) el.setAttribute("data-ob", String(item.ob));
    if (item.md5) el.setAttribute("data-md5", item.md5);
    if (item.sha1) el.setAttribute("data-sha1", item.sha1);
    if (item.sha256) el.setAttribute("data-sha256", item.sha256);
    if (item.pv) el.setAttribute("data-pv", item.pv);
    if (item.th) el.setAttribute("data-th", item.th);
  }

  function renderTabDirectory(cat) {
    const items = (cat && cat.items) || [];

    // 1. Grid (.grid)
    const gridEl = document.querySelector(".grid");
    const tplCell = $("#tpl-cell");
    if (gridEl) {
      gridEl.replaceChildren();
      items.forEach(item => {
        if (tplCell && tplCell.content && tplCell.content.firstElementChild) {
          const el = tplCell.content.firstElementChild.cloneNode(true);
          fillThumb(el.querySelector(".thumb"), item, false);
          const cn = el.querySelector(".cname");
          if (cn) {
            cn.textContent = item.name || "";
            cn.setAttribute("title", item.name || "");
          }
          setRowAttrs(el, item);
          gridEl.appendChild(el);
        }
      });
    }

    // 2. Cards (.cards)
    const cardsEl = document.querySelector(".cards");
    const tplTile = $("#tpl-tile");
    if (cardsEl) {
      cardsEl.replaceChildren();
      items.forEach(item => {
        if (tplTile && tplTile.content && tplTile.content.firstElementChild) {
          const el = tplTile.content.firstElementChild.cloneNode(true);
          fillThumb(el.querySelector(".thumb"), item, false);
          const cn = el.querySelector(".cname");
          if (cn) {
            cn.textContent = item.name || "";
            cn.setAttribute("title", item.name || "");
          }
          const ts = el.querySelector(".tsub");
          if (ts) ts.textContent = item.kind || "";
          setRowAttrs(el, item);
          cardsEl.appendChild(el);
        }
      });
    }

    // 3. List (.list)
    const listEl = document.querySelector(".list");
    const tplLrow = $("#tpl-lrow");
    if (listEl) {
      listEl.replaceChildren();
      items.forEach(item => {
        if (tplLrow && tplLrow.content && tplLrow.content.firstElementChild) {
          const el = tplLrow.content.firstElementChild.cloneNode(true);
          const rb = el.querySelector(".ricobox");
          if (rb) {
            const a = takeArt(item.art, true);
            if (a) rb.appendChild(a);
          }
          const ln = el.querySelector(".lname");
          if (ln) {
            ln.textContent = item.name || "";
            ln.setAttribute("title", item.name || "");
          }
          setRowAttrs(el, item);
          listEl.appendChild(el);
        }
      });
    }

    // 4. Details (.dbody inside .rows)
    const dbodyEl = document.querySelector(".dbody");
    const tplRow = $("#tpl-row");
    if (dbodyEl) {
      dbodyEl.replaceChildren();
      items.forEach(item => {
        if (tplRow && tplRow.content && tplRow.content.firstElementChild) {
          const el = tplRow.content.firstElementChild.cloneNode(true);
          const rb = el.querySelector(".ricobox");
          if (rb) {
            const a = takeArt(item.art, true);
            if (a) rb.appendChild(a);
          }
          const rn = el.querySelector(".rname");
          if (rn) rn.textContent = item.name || "";
          const cw = el.querySelector(".c-when");
          if (cw) cw.textContent = item.when || "";
          const ck = el.querySelector(".c-kind");
          if (ck) ck.textContent = item.kind || "";
          const cs = el.querySelector(".c-size");
          if (cs) cs.textContent = item.size || "";
          setRowAttrs(el, item);
          dbodyEl.appendChild(el);
        }
      });
    }

    // 5. Columns (.columns)
    const colsEl = document.querySelector(".columns");
    const tplCrow = $("#tpl-crow");
    if (colsEl) {
      colsEl.replaceChildren();
      const cols = document.createElement("div");
      cols.className = "cols";
      const col = document.createElement("div");
      col.className = "col";
      const colH = document.createElement("div");
      colH.className = "col-h";
      colH.textContent = (cat && cat.name) || "Folder";
      col.appendChild(colH);
      items.forEach(item => {
        if (tplCrow && tplCrow.content && tplCrow.content.firstElementChild) {
          const el = tplCrow.content.firstElementChild.cloneNode(true);
          const rb = el.querySelector(".ricobox");
          if (rb) {
            const a = takeArt(item.art, true);
            if (a) rb.appendChild(a);
          }
          const ln = el.querySelector(".lname");
          if (ln) {
            ln.textContent = item.name || "";
            ln.setAttribute("title", item.name || "");
          }
          setRowAttrs(el, item);
          col.appendChild(el);
        }
      });
      cols.appendChild(col);
      colsEl.appendChild(cols);
    }

    updateEmptyFolderIndicator(items.length, false);

    if (typeof setKbd === "function") setKbd(null);
    listItems().forEach(el => el.classList.remove("sel"));
    updateStatus();
    updateDetails(null);
  }

  function renderBreadcrumbs(cat, path, isHome) {
    const crumbsBox = $("#crumbs");
    if (!crumbsBox) return;
    crumbsBox.replaceChildren();

    if (isHome) {
      const span = document.createElement("span");
      span.className = "crumb last";
      span.setAttribute("data-p", homePath());
      const art = document.querySelector('#artlib [data-ico="Home"] svg') ||
                  document.querySelector('#artlib [data-ico="Omnibar.Path"] svg');
      if (art) span.appendChild(art.cloneNode(true));
      const lbl = document.createElement("span");
      lbl.textContent = "Home";
      span.appendChild(lbl);
      crumbsBox.appendChild(span);
      return;
    }

    const crumbsList = (cat && cat.crumbs && cat.crumbs.length) ? cat.crumbs : null;
    if (crumbsList) {
      crumbsList.forEach((crumb, idx) => {
        let cName = "", cPath = "";
        if (Array.isArray(crumb)) {
          if (typeof crumb[0] === "string" && (crumb[0].startsWith("/") || crumb[0].startsWith("file://") || crumb[0] === "~")) {
            cPath = crumb[0];
            cName = crumb[1] || cPath;
          } else {
            cName = crumb[0];
            cPath = crumb[1] || cName;
          }
        } else if (typeof crumb === "object" && crumb !== null) {
          cName = crumb.name || crumb.label || "";
          cPath = crumb.path || crumb.key || "";
        } else {
          cName = String(crumb);
          cPath = String(crumb);
        }
        if (cPath.startsWith("file://")) cPath = cPath.slice(7);

        if (idx > 0) {
          const sep = document.createElement("span");
          sep.className = "csep";
          const csepSvg = document.querySelector('#artlib [data-ico="Csep"] svg');
          if (csepSvg) sep.appendChild(csepSvg.cloneNode(true));
          crumbsBox.appendChild(sep);
        }

        const span = document.createElement("span");
        span.className = "crumb" + (idx === crumbsList.length - 1 ? " last" : "");
        span.setAttribute("data-p", cPath);

        if (idx === 0) {
          const isHomeCrumb = (cName === "Home" || isHomePath(cPath));
          const icoKey = isHomeCrumb ? "Home" : "Folder";
          const art = document.querySelector('#artlib [data-ico="' + icoKey + '"] svg') ||
                      document.querySelector('#artlib [data-ico="Omnibar.Path"] svg');
          if (art) span.appendChild(art.cloneNode(true));
        }

        const lbl = document.createElement("span");
        lbl.textContent = cName;
        span.appendChild(lbl);
        crumbsBox.appendChild(span);
      });
    } else {
      const span = document.createElement("span");
      span.className = "crumb last";
      let pNorm = path || "/";
      if (pNorm.startsWith("file://")) pNorm = pNorm.slice(7);
      span.setAttribute("data-p", pNorm);
      const art = document.querySelector('#artlib [data-ico="Folder"] svg');
      if (art) span.appendChild(art.cloneNode(true));
      const lbl = document.createElement("span");
      lbl.textContent = (cat && cat.name) || (pNorm.split("/").filter(Boolean).pop() || "Folder");
      span.appendChild(lbl);
      crumbsBox.appendChild(span);
    }
  }

  // A section header, and an expandable drive, collapse the group they own.
  // The state is on the group, not the row, because the children are its
  // subtree and the chevron is only the handle.
  document.addEventListener("click", e => {
    const row = e.target.closest(".srow.head, .srow .cslot");
    if (!row) return;
    const grp = row.closest(".sgrp");
    if (!grp) return;
    // a chevron on an item row toggles without following the link
    if (!row.classList.contains("head")) {
      e.preventDefault();
      e.stopPropagation();
    }
    grp.classList.toggle("shut");
  }, true);

  document.addEventListener("keydown", e => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const head = e.target.closest && e.target.closest(".srow.head");
    if (!head) return;
    const grp = head.closest(".sgrp");
    if (!grp) return;
    e.preventDefault();
    grp.classList.toggle("shut");
  });

  //: Live mode navigates without going through the tab machinery, and the
  //: highlight is the one thing that then still says Home.
  window.__sidebarActive = (path, isHome) => updateSidebarActive(path, isHome);

  function updateSidebarActive(path, isHome) {
    $$(".srow.item").forEach(el => {
      el.classList.remove("active");
      el.classList.remove("sel");
    });
    if (isHome) {
      const homeRow = $('.srow.item[data-root="~"]') ||
                      $('.srow.item[data-root="' + homeKey() + '"]') ||
                      $('.srow.item[data-n="Home"]');
      if (homeRow) {
        homeRow.classList.add("active");
        homeRow.classList.add("sel");
      }
      return;
    }
    if (!path) return;
    let norm = String(path);
    if (norm.startsWith("file://")) norm = norm.slice(7);
    while (norm.length > 1 && norm.endsWith("/")) norm = norm.slice(0, -1);
    const base = norm.split("/").filter(Boolean).pop() || "";

    const items = $$(".srow.item");
    let matched = null;
    for (const el of items) {
      const r = el.getAttribute("data-root") || el.getAttribute("data-p") || "";
      let rNorm = r.startsWith("file://") ? r.slice(7) : r;
      while (rNorm.length > 1 && rNorm.endsWith("/")) rNorm = rNorm.slice(0, -1);
      const n = el.getAttribute("data-n") || "";
      const h = el.getAttribute("href") || "";
      if ((rNorm && rNorm === norm) || (n && n === base) || (n && n === norm)) {
        matched = el;
        break;
      }
      if (h && (h === norm || h.endsWith(norm) || norm.endsWith(h))) {
        matched = el;
        break;
      }
    }
    if (matched) {
      matched.classList.add("active");
      matched.classList.add("sel");
    }
  }

/**
   * Helper selector shortcuts
   */
  function qs(selector, scope) {
    return (scope || document).querySelector(selector);
  }

  function qsa(selector, scope) {
    return Array.from((scope || document).querySelectorAll(selector));
  }

