  // Live mode: when backend.py answers on localhost, the static export
  // upgrades to a real file browser. Rows are cloned from <template> and
  // filled with textContent; art is cloned from #artlib. No HTML string is
  // ever assigned to an element. Without a backend nothing here runs and the
  // page behaves exactly as before.
  const API = 'http://127.0.0.1:8902';
  window.__api = API;
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const live = () => !!window.__livePath;

  //: Mica. Three things decide what the backdrop looks like: the sample, the
  //: material, and where the window sits on the screen. The last one is what
  //: makes it read as the wallpaper rather than as a texture: the sample is
  //: positioned by the window's own screen offset, so moving the window
  //: slides the backdrop the way a real one would.
  const MICA_SLUG = {
    'Solid': 'solid', 'Mica': 'mica', 'Acrylic': 'acrylic',
    'Mica Alt': 'micaalt'
  };
  let micaSample = '@@MICA_SAMPLE_URI@@';

  function applyMicaSample(uri) {
    micaSample = uri || '';
    document.documentElement.style.setProperty(
      '--mica-sample', micaSample ? 'url("' + micaSample + '")' : 'none');
  }

  function applyMaterial(name) {
    const slug = MICA_SLUG[name] || 'mica';
    document.documentElement.setAttribute('data-material', slug);
  }

  //: Where the window is, as a fraction of the screen, so the sample is
  //: sampled at the window's position rather than always at its middle. With
  //: no screen to ask, the middle is the honest answer.
  function positionMica() {
    const sw = (window.screen && window.screen.width) || 0;
    const sh = (window.screen && window.screen.height) || 0;
    let x = 50, y = 50;
    if (sw > 0 && sh > 0) {
      const ox = typeof window.screenX === 'number' ? window.screenX : 0;
      const oy = typeof window.screenY === 'number' ? window.screenY : 0;
      const room = sw - window.innerWidth;
      const roomY = sh - window.innerHeight;
      //: A window that fills the screen has nowhere to be, and dividing by
      //: the couple of pixels left over would swing the backdrop from edge
      //: to edge on a one pixel move. The middle is the answer there.
      if (room > 32) x = Math.min(100, Math.max(0, (ox / room) * 100));
      if (roomY > 32) y = Math.min(100, Math.max(0, (oy / roomY) * 100));
    }
    const root = document.documentElement.style;
    root.setProperty('--mica-x', x.toFixed(1) + '%');
    root.setProperty('--mica-y', y.toFixed(1) + '%');
  }

  async function refreshWallpaper() {
    if (!live()) return false;
    try {
      const r = await fetch(API + '/api/wallpaper');
      const d = await r.json();
      if (d && d.found && d.uri) { applyMicaSample(d.uri); return true; }
    } catch (err) { /* the baked sample stays */ }
    return false;
  }

  window.__mica = {
    material: applyMaterial,
    sample: applyMicaSample,
    refresh: refreshWallpaper,
    position: positionMica,
    current: () => micaSample
  };
  applyMicaSample(micaSample);
  positionMica();
  //: This scope loads after the one that owns the preferences, so the boot
  //: there cannot reach window.__mica yet. Read the pref from here instead.
  applyMaterial(window.__getPref ? window.__getPref('backdropMaterial') : 'Mica');
  window.addEventListener('resize', positionMica);


  //: File tags. The truth for one file is the freedesktop xattr the backend
  //: writes, so a tag survives a move and other programs can read it. The
  //: page keeps a path to names map, refreshed from the backend's index,
  //: because painting a list must not be one request per row.
  const TAG_DEFAULTS_MAIN = __BUILD("TAG_DEFAULTS_JSON");
  const TAGS_STORE_KEY = 'aurade-tags';
  let tagIndex = {};

  function definedTags() {
    try {
      const raw = localStorage.getItem(TAGS_STORE_KEY);
      const v = raw ? JSON.parse(raw) : null;
      if (Array.isArray(v) && v.length) return v;
    } catch (err) { /* a cleared or corrupt store falls back */ }
    return TAG_DEFAULTS_MAIN;
  }

  function tagColor(name) {
    const list = definedTags();
    for (let i = 0; i < list.length; i++) {
      if (list[i].name === name) return list[i].color;
    }
    return 'var(--text-3)';
  }

  function tagDot(name) {
    const d = document.createElement('span');
    d.className = 'tagdot';
    d.style.background = tagColor(name);
    d.title = name;
    return d;
  }

  function paintTags() {
    document.querySelectorAll('[data-p]').forEach((row) => {
      const names = tagIndex[row.getAttribute('data-p')] || [];
      //: Set on every row, not only the ones with a Tag column, so a test
      //: and a filter can read a row's tags in any layout.
      if (names.length) row.setAttribute('data-tags', names.join(','));
      else row.removeAttribute('data-tags');
      //: The details view has a column for them. Every other layout gets a
      //: small cluster of dots on the item itself.
      let box = row.querySelector('.c-tag') || row.querySelector('.tagdots');
      if (!box && names.length && row.classList.contains('cell')) {
        box = document.createElement('span');
        box.className = 'tagdots';
        row.appendChild(box);
      }
      if (!box) return;
      while (box.firstChild) box.removeChild(box.firstChild);
      names.forEach((n) => box.appendChild(tagDot(n)));
    });
  }

  async function refreshTagIndex() {
    if (!live()) { tagIndex = {}; paintTags(); return tagIndex; }
    try {
      const r = await fetch(API + '/api/tags/all');
      const d = await r.json();
      const byPath = {};
      Object.keys(d.tags || {}).forEach((name) => {
        (d.tags[name] || []).forEach((p) => {
          if (!byPath[p]) byPath[p] = [];
          byPath[p].push(name);
        });
      });
      tagIndex = byPath;
    } catch (err) { tagIndex = {}; }
    paintTags();
    if (typeof paintTagSidebar === 'function') paintTagSidebar();
    return tagIndex;
  }

  async function toggleTag(path, name) {
    if (!path || !live()) return null;
    const have = (tagIndex[path] || []).slice();
    const at = have.indexOf(name);
    if (at === -1) have.push(name); else have.splice(at, 1);
    try {
      const r = await fetch(API + '/api/tags', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: path, tags: have })
      });
      const d = await r.json();
      if (d && Array.isArray(d.tags)) {
        if (d.tags.length) tagIndex[path] = d.tags;
        else delete tagIndex[path];
      }
    } catch (err) { return null; }
    paintTags();
    if (typeof paintTagSidebar === 'function') paintTagSidebar();
    return tagIndex[path] || [];
  }

  //: The submenu is built when the menu opens rather than at build time,
  //: because a person can add and rename tags and the six that shipped are
  //: only a starting point.
  function fillTagsSub(path) {
    const sub = document.getElementById('sub-tags');
    if (!sub) return;
    while (sub.firstChild) sub.removeChild(sub.firstChild);
    const have = tagIndex[path] || [];
    const list = definedTags();
    if (!list.length) {
      const empty = document.createElement('div');
      empty.className = 'mi dis';
      const t = document.createElement('span');
      t.className = 'mi-t';
      t.textContent = 'No tags defined yet';
      empty.appendChild(t);
      sub.appendChild(empty);
      return;
    }
    list.forEach((tag) => {
      const row = document.createElement('div');
      row.className = 'mi' + (live() ? '' : ' dis');
      row.setAttribute('data-tagname', tag.name);
      const ic = document.createElement('span');
      ic.className = 'mi-ic';
      ic.appendChild(tagDot(tag.name));
      row.appendChild(ic);
      const lbl = document.createElement('span');
      lbl.className = 'mi-t';
      lbl.textContent = tag.name;
      row.appendChild(lbl);
      const ck = document.createElement('span');
      ck.className = 'mi-tagck';
      ck.textContent = have.indexOf(tag.name) === -1
        ? '' : String.fromCharCode(10003);
      row.appendChild(ck);
      sub.appendChild(row);
    });
  }

  document.addEventListener('click', (e) => {
    const row = e.target.closest ? e.target.closest('[data-tagname]') : null;
    if (!row || row.classList.contains('dis')) return;
    e.stopPropagation();
    const path = window.__ctxData ? window.__ctxData('data-p') : '';
    toggleTag(path, row.getAttribute('data-tagname')).then(() => {
      fillTagsSub(path);
    });
  }, true);

  window.__tags = {
    index: () => tagIndex,
    openTag: (t) => renderTagView(t),
    sidebar: () => paintTagSidebar(),
    refresh: refreshTagIndex,
    toggle: toggleTag,
    defined: definedTags,
    fillSub: fillTagsSub,
    paint: paintTags
  };


  const ITEMS = '.cell,.row,.lrow,.tile,.crow';

  function human(n) {
    n = Math.max(0, n);
    if (n < 1024) return n + ' B';
    const u = ['KB', 'MB', 'GB', 'TB'];
    let i = -1;
    do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
    return n.toFixed(1) + ' ' + u[i];
  }
  function fmtWhen(ms) {
    if (!ms) return '';
    const d = new Date(ms);
    const M = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug',
               'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()];
    const p2 = n => (n < 10 ? '0' : '') + n;
    return d.getDate() + ' ' + M + ' ' + d.getFullYear() + ' ' +
           p2(d.getHours()) + ':' + p2(d.getMinutes());
  }
  // Generated from icons.ART_BY_EXT, which is the one table. A second copy
  // maintained by hand is how live mode ended up calling a PDF a File while
  // the static build called it a PDF document.
  const ART_FOR_EXT = __BUILD("ART_FOR_EXT_JSON");
  function artFor(name, isDir) {
    if (isDir) return ['folder', 'Folder'];
    const dot = name.lastIndexOf('.');
    const hit = dot >= 0 ? ART_FOR_EXT[name.slice(dot).toLowerCase()] : null;
    return hit || ['txt', 'File'];
  }

  async function apiGet(path) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 8000);
    try {
      const r = await fetch(API + path, {signal: ctl.signal});
      if (!r.ok) throw new Error('http ' + r.status);
      return await r.json();
    } finally {
      clearTimeout(t);
    }
  }
  async function apiPost(path, body, ms) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), ms || 15000);
    try {
      const r = await fetch(API + path, {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body), signal: ctl.signal});
      const j = await r.json();
      if (!r.ok) {
        const err = new Error(j.error || ('http ' + r.status));
        // The stable code, carried through. Without it a caller wanting to
        // tell "this archive wants a password" from "that path is gone" has
        // to match on prose, which is how a message becomes an interface.
        err.code = j.code || '';
        err.status = r.status;
        throw err;
      }
      return j;
    } finally {
      clearTimeout(t);
    }
  }

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
  function cloneTpl(id) {
    const t = document.getElementById(id);
    return t.content.firstElementChild.cloneNode(true);
  }
  //: Which rebuild is current. A thumbnail that lands after the user has
  //: navigated away must not paint, and comparing the epoch is cheaper than
  //: tracking every outstanding request.
  let thumbEpoch = 0;
  //: Per rebuild, so a directory of ten thousand photographs does not open ten
  //: thousand requests. The ones past the budget keep their glyph.
  let thumbLeft = 0;
  const THUMB_LIVE_BUDGET = 80;
  const THUMB_RE = /\.(png|jpe?g|gif|bmp|webp|tiff?|ico|avif|pdf|mp4|mkv|mov|webm|avi|m4v|mpg|mpeg|ogv|mp3|flac|ogg|oga|opus|m4a|m4b|wav|aiff?|ape|wv|mpc|aac)$/i;

  function liveThumb(box, o) {
    // A live entry carries no picture, so ask the backend for one. The glyph
    // is already in the box and stays there until a thumbnail actually
    // arrives, which is also what happens when the file will not decode.
    if (!box || !o || !o.path || !THUMB_RE.test(o.name || '')) return;
    if (thumbLeft <= 0 || !window.__fetchThumb) return;
    thumbLeft -= 1;
    const my = thumbEpoch;
    window.__fetchThumb(o.path).then(uri => {
      if (my !== thumbEpoch || !uri || !box.isConnected) return;
      const img = document.createElement('img');
      img.className = 'thumbimg';
      img.alt = '';
      img.decoding = 'async';
      img.src = uri;
      //: Over the glyph that is already in the box, not instead of it.
      box.querySelectorAll('.thumbimg').forEach(function (gone) {
        gone.remove();
      });
      box.appendChild(img);
      const row = box.closest('[data-n]');
      if (row) row.setAttribute('data-th', uri);
    }).catch(() => {});
  }

  // A live entry carries no thumbnail, so the one the page was built with is
  // restored from the element by backfill and read back off it here. Without
  // this the first live rebuild drops every baked picture to a glyph, which
  // looks exactly like the thumbnails never having worked.
  function thumbOf(o, el) {
    return {art: o.art, th: o.th || (el && el.getAttribute('data-th')) || ''};
  }

  function setRowAttrs(el, o) {
    el.setAttribute('data-n', o.name);
    el.setAttribute('data-k', o.kind);
    el.setAttribute('data-w', o.when);
    el.setAttribute('data-s', o.size);
    el.setAttribute('data-p', o.path);
    el.setAttribute('data-ms', String(o.ms));
    el.setAttribute('data-sb', String(o.bytes));
    if (o.th) el.setAttribute('data-th', o.th);
    if (o.broken) el.setAttribute('data-broken', '1');
    else el.removeAttribute('data-broken');
    el.setAttribute('title', o.name);
  }
  function shapeOf(e, meta) {
    const m = (meta && meta[e.key]) || {};
    const ms = m.modificationTime || 0;
    const bytes = (typeof m.size === 'number') ? m.size : -1;
    const [art, kind] = artFor(e.name, e.isDirectory);
    return {name: e.name, art, kind,
      when: fmtWhen(ms), size: bytes >= 0 ? human(bytes) : '',
      path: (e.key || '').replace(/^file:\/\//, ''), ms, bytes,
      broken: e.broken === true};
  }

  function clearRoot(root) {
    while (root.firstChild) root.removeChild(root.firstChild);
  }

  function buildRows(data) {
    thumbEpoch += 1;
    thumbLeft = THUMB_LIVE_BUDGET;
    const items = (data.entries || []).map(e => shapeOf(e, data.meta));
    // Live entries carry no hashes or embedded previews, so preserve the
    // static hash/preview attributes across live rebuilds by matching path.
    const keepAttrs = ['data-md5', 'data-sha1', 'data-sha256', 'data-pv',
                       'data-th'];
    const kept = {};
    document.querySelectorAll('.grid .cell, .cards .tile, .list .lrow, .dbody .row, .columns .crow').forEach(oldEl => {
      const p = oldEl.getAttribute('data-p') || '';
      const n = oldEl.getAttribute('data-n') || '';
      const got = {};
      let any = false;
      keepAttrs.forEach(k => {
        const v = oldEl.getAttribute(k);
        if (v) { got[k] = v; any = true; }
      });
      if (any) {
        if (p) kept[p] = Object.assign(kept[p] || {}, got);
        if (n) kept['n:' + n] = Object.assign(kept['n:' + n] || {}, got);
      }
    });
    const backfill = (el, o) => {
      const src = (o.path && kept[o.path]) || (o.name && kept['n:' + o.name]);
      if (!src) return;
      keepAttrs.forEach(k => {
        if (!el.getAttribute(k) && src[k]) el.setAttribute(k, src[k]);
      });
    };
    const grid = $('.grid'), cards = $('.cards'), list = $('.list'),
          dbody = $('.dbody'), cols = $('.columns');
    if (grid) {
      clearRoot(grid);
      items.forEach(o => {
        const el = cloneTpl('tpl-cell');
        setRowAttrs(el, o);
        backfill(el, o);
        fillThumb($('.thumb', el), thumbOf(o, el), false);
        if (!el.getAttribute('data-th')) liveThumb($('.thumb', el), o);
        $('.cname', el).textContent = o.name;
        grid.appendChild(el);
      });
    }
    if (cards) {
      clearRoot(cards);
      items.forEach(o => {
        const el = cloneTpl('tpl-tile');
        setRowAttrs(el, o);
        backfill(el, o);
        fillThumb($('.thumb', el), thumbOf(o, el), false);
        if (!el.getAttribute('data-th')) liveThumb($('.thumb', el), o);
        $('.cname', el).textContent = o.name;
        $('.tsub', el).textContent = o.kind;
        cards.appendChild(el);
      });
    }
    if (list) {
      clearRoot(list);
      items.forEach(o => {
        const el = cloneTpl('tpl-lrow');
        const art = takeArt(o.art, true);
        if (art) $('.ricobox', el).replaceChildren(art);
        $('.lname', el).textContent = o.name;
        setRowAttrs(el, o);
        backfill(el, o);
        list.appendChild(el);
      });
    }
    if (dbody) {
      clearRoot(dbody);
      items.forEach(o => {
        const el = cloneTpl('tpl-row');
        const art = takeArt(o.art, true);
        if (art) $('.ricobox', el).replaceChildren(art);
        $('.rname', el).textContent = o.name;
        $('.c-when', el).textContent = o.when;
        $('.c-kind', el).textContent = o.kind;
        $('.c-size', el).textContent = o.size;
        setRowAttrs(el, o);
        backfill(el, o);
        dbody.appendChild(el);
      });
    }
    if (cols) {
      clearRoot(cols);
      const col = document.createElement('div');
      col.className = 'col';
      const head = document.createElement('div');
      head.className = 'col-h';
      head.textContent = data.name || data.path;
      col.appendChild(head);
      items.forEach(o => {
        const el = cloneTpl('tpl-crow');
        const art = takeArt(o.art, true);
        if (art) $('.ricobox', el).replaceChildren(art);
        $('.lname', el).textContent = o.name;
        setRowAttrs(el, o);
        backfill(el, o);
        col.appendChild(el);
      });
      cols.appendChild(col);
    }
    // The folder changed, so the rule gets to look again.
    if (window.__relayoutAdaptive) window.__relayoutAdaptive();
    //: A rebuild replaces every row, so the tag cells are empty again. The
    //: index is already in memory, so catching them up costs no request.
    if (window.__tags) window.__tags.paint();
    //: Same reason, same moment: the art the rows were just given is the
    //: default art, and a folder with an icon of its own has to get it back.
    if (window.__customIcons) window.__customIcons.sync();
    if (window.__git) window.__git.sync();
    return items.length;
  }

  //: Custom folder icons. The index is one request per folder rather than one
  //: per row, and it is painted after every rebuild for the same reason the
  //: tag cells are: a rebuild replaces the rows, and their art with them.
  let iconIndex = {};
  let iconIndexPath = null;

  function paintCustomIcons() {
    document.querySelectorAll('[data-p]').forEach((row) => {
      const value = iconIndex[row.getAttribute('data-p')] || '';
      const box = row.querySelector('.thumb') || row.querySelector('.rico') ||
                  row.querySelector('.ricobox');
      if (!box) return;
      if (!value) { row.removeAttribute('data-customicon'); return; }
      //: A rebuild clears the marker with the row, so this only skips work
      //: for a row that is still carrying the art it was given.
      if (row.getAttribute('data-customicon') === value) return;
      row.setAttribute('data-customicon', value);
      const small = !box.classList.contains('thumb');
      if (value.indexOf('file:') === 0) {
        if (!window.__fetchThumb) return;
        window.__fetchThumb(value.slice(5)).then((uri) => {
          if (!uri) return;
          if (row.getAttribute('data-customicon') !== value) return;
          while (box.firstChild) box.removeChild(box.firstChild);
          const img = document.createElement('img');
          img.className = 'thumbimg';
          img.alt = '';
          img.decoding = 'async';
          img.src = uri;
          box.appendChild(img);
        }).catch(() => {});
        return;
      }
      const art = takeArt(value.slice(6), small);
      if (!art) return;
      while (box.firstChild) box.removeChild(box.firstChild);
      box.appendChild(art);
    });
  }

  async function refreshIconIndex(force) {
    const path = (live() && window.__live) ? (window.__live.path || '') : '';
    if (!path) {
      iconIndex = {};
      iconIndexPath = null;
      paintCustomIcons();
      return iconIndex;
    }
    //: A sort or a layout change rebuilds the same folder. Asking again for
    //: an answer that cannot have changed is the request worth not making.
    if (!force && path === iconIndexPath) { paintCustomIcons(); return iconIndex; }
    try {
      const r = await fetch(API + '/api/icon/dir?path=' +
                            encodeURIComponent(path));
      const d = await r.json();
      iconIndex = (r.ok && d.icons) ? d.icons : {};
      iconIndexPath = path;
    } catch (err) { iconIndex = {}; iconIndexPath = null; }
    paintCustomIcons();
    return iconIndex;
  }

  window.__customIcons = {
    index: () => iconIndex,
    refresh: () => refreshIconIndex(true),
    sync: () => refreshIconIndex(false),
    paint: paintCustomIcons
  };

  //: The Shelf. A holding place that outlives navigation, which is the whole
  //: of its point: things can be gathered from several folders before
  //: anything is decided about them. Putting something here copies nothing.
  //: The shelf holds paths, and the batch actions are what act on them.
  let shelfItems = [];
  const shelfSel = new Set();

  function shelfToggle(on) {
    const pane = $('#shelf');
    if (!pane) return false;
    pane.hidden = (on === undefined) ? !pane.hidden : !on;
    const btn = $('#btn-shelf');
    if (btn) btn.setAttribute('aria-pressed', String(!pane.hidden));
    return !pane.hidden;
  }

  function shelfAdd(list) {
    let added = 0;
    (list || []).forEach((entry) => {
      const path = String((entry && entry.path) || entry || '').trim();
      if (!path) return;
      if (shelfItems.some((it) => it.path === path)) return;
      const name = path.split('/').filter(Boolean).pop() || path;
      const kind = String((entry && entry.kind) || '').toLowerCase();
      shelfItems.push({
        path: path, name: name,
        isDir: !!(entry && entry.isDir) || kind.indexOf('folder') !== -1
      });
      added += 1;
    });
    if (added) shelfRender();
    return added;
  }

  function shelfRemove(path) {
    const before = shelfItems.length;
    shelfItems = shelfItems.filter((it) => it.path !== path);
    shelfSel.delete(path);
    if (shelfItems.length !== before) shelfRender();
  }

  function shelfClear() {
    shelfItems = [];
    shelfSel.clear();
    shelfRender();
  }

  function shelfSelected() {
    return shelfItems.filter((it) => shelfSel.has(it.path))
                     .map((it) => it.path);
  }

  //: Copy and cut load the same clipboard the file list uses, so something
  //: gathered here is pasted with the ordinary Paste. Delete is the only one
  //: that touches the disk, and it goes to the trash like every other delete.
  async function shelfBatch(op) {
    const paths = shelfSelected();
    if (!paths.length) return 0;
    if (op === 'copy' || op === 'cut') {
      clip = { mode: op, paths: paths };
      markCut();
    } else if (op === 'delete') {
      await apiPost('/api/trash', { paths: paths });
      paths.forEach((p) => {
        shelfItems = shelfItems.filter((it) => it.path !== p);
        shelfSel.delete(p);
      });
      if (window.__livePath) await renderLive(window.__livePath);
    }
    shelfRender();
    return paths.length;
  }

  function shelfRow(item) {
    const row = document.createElement('div');
    row.className = 'shelf-item' + (shelfSel.has(item.path) ? ' sel' : '');
    row.setAttribute('role', 'listitem');
    row.setAttribute('data-sp', item.path);
    row.title = item.path;
    row.tabIndex = 0;
    const ico = document.createElement('span');
    ico.className = 'shelf-ico';
    //: artFor answers with [art key, kind label]; takeArt wants the key.
    const art = takeArt(artFor(item.name, item.isDir)[0], true);
    if (art) ico.appendChild(art);
    const name = document.createElement('span');
    name.className = 'shelf-name';
    name.textContent = item.name;
    const rm = document.createElement('button');
    rm.className = 'shelf-x';
    rm.title = 'Remove from shelf';
    rm.setAttribute('aria-label', 'Remove ' + item.name + ' from the shelf');
    rm.textContent = String.fromCharCode(215);
    rm.onclick = (e) => { e.stopPropagation(); shelfRemove(item.path); };
    row.onclick = () => {
      if (shelfSel.has(item.path)) shelfSel.delete(item.path);
      else shelfSel.add(item.path);
      shelfRender();
    };
    row.appendChild(ico);
    row.appendChild(name);
    row.appendChild(rm);
    return row;
  }

  function shelfRender() {
    const list = $('#shelf-list');
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    shelfItems.forEach((item) => list.appendChild(shelfRow(item)));
    const empty = $('#shelf-empty');
    if (empty) empty.hidden = shelfItems.length > 0;
    const foot = $('#shelf-foot');
    if (foot) foot.hidden = shelfItems.length === 0;
    //: The batch link is offered only once something is picked, the same way
    //: the reference reveals it on the first selection.
    const batch = $('#shelf-batch-wrap');
    if (batch) batch.hidden = shelfSel.size === 0;
    const menu = $('#m-shelf');
    if (menu && shelfSel.size === 0) menu.hidden = true;
  }

  function shelfWire() {
    const pane = $('#shelf');
    if (!pane || pane.getAttribute('data-wired')) return;
    pane.setAttribute('data-wired', '1');
    pane.addEventListener('dragover', (e) => {
      if (!e.dataTransfer) return;
      const types = Array.from(e.dataTransfer.types || []);
      if (types.indexOf('application/x-aurade-files') === -1) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'link';
      pane.classList.add('drop');
    });
    pane.addEventListener('dragleave', (e) => {
      if (e.target === pane) pane.classList.remove('drop');
    });
    pane.addEventListener('drop', (e) => {
      pane.classList.remove('drop');
      if (!e.dataTransfer) return;
      const raw = e.dataTransfer.getData('application/x-aurade-files');
      if (!raw) return;
      e.preventDefault();
      try { shelfAdd(JSON.parse(raw)); } catch (err) {}
    });
    const clear = $('#shelf-clear');
    if (clear) clear.onclick = shelfClear;
    const batch = $('#shelf-batch');
    const menu = $('#m-shelf');
    if (batch && menu) batch.onclick = (e) => {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
    };
    document.querySelectorAll('#m-shelf [data-shelf-op]').forEach((mi) => {
      mi.onclick = () => {
        if (menu) menu.hidden = true;
        shelfBatch(mi.getAttribute('data-shelf-op'));
      };
    });
    const btn = $('#btn-shelf');
    if (btn) btn.onclick = () => shelfToggle();
    shelfRender();
  }

  window.__shelf = {
    items: () => shelfItems.slice(),
    add: shelfAdd,
    remove: shelfRemove,
    clear: shelfClear,
    select: (path) => { shelfSel.add(path); shelfRender(); },
    selected: shelfSelected,
    batch: shelfBatch,
    toggle: shelfToggle,
    render: shelfRender
  };

  //: Git. The reference shows a repository in two places, and both are fed
  //: from the same answer: the branch in the status bar, and per item state
  //: in the details view. Neither appears outside a repository, which is why
  //: the column is hidden rather than empty when there is nothing to say.
  const GIT_WORDS = {
    M: 'Modified', A: 'Added', D: 'Deleted', R: 'Renamed',
    U: 'Conflict', '?': 'Untracked'
  };
  let gitInfo = { repo: false };
  let gitInfoPath = null;

  function paintGitRows() {
    document.querySelectorAll('[data-p]').forEach((row) => {
      const cell = row.querySelector('.c-git');
      if (!cell) return;
      const code = (gitInfo.status || {})[row.getAttribute('data-p')] || '';
      cell.textContent = code ? (GIT_WORDS[code] || code) : '';
      if (code) cell.setAttribute('data-git', code);
      else cell.removeAttribute('data-git');
    });
  }

  function paintGitBar() {
    const wrap = document.getElementById('git-wrap');
    if (wrap) wrap.hidden = !gitInfo.repo;
    const name = document.getElementById('git-branch');
    if (name) name.textContent = gitInfo.branch || '';
    const stat = document.getElementById('git-status-btn');
    const bits = [];
    if (gitInfo.ahead) bits.push('ahead ' + gitInfo.ahead);
    if (gitInfo.behind) bits.push('behind ' + gitInfo.behind);
    const text = bits.join(', ');
    if (stat) {
      stat.hidden = !text;
      stat.title = text;
      const span = stat.querySelector('span');
      if (span) span.textContent = text;
    }
    const menu = document.getElementById('m-git');
    if (menu) {
      while (menu.firstChild) menu.removeChild(menu.firstChild);
      const names = gitInfo.branches || [];
      if (!names.length) {
        const dis = document.createElement('div');
        dis.className = 'mi dis';
        const t = document.createElement('span');
        t.className = 'mi-t';
        t.textContent = 'No branches';
        dis.appendChild(t);
        menu.appendChild(dis);
        return;
      }
      //: The reference's flyout has Create branch above the list, as a
      //: button in its header: StatusBar.xaml, NewBranchButton. Offered only
      //: by a backend that can make one.
      if (can('git-branch')) {
        const add = document.createElement('div');
        add.className = 'mi';
        add.setAttribute('data-git', 'new-branch');
        const ic = document.createElement('span');
        ic.className = 'mi-ic';
        add.appendChild(ic);
        const t = document.createElement('span');
        t.className = 'mi-t';
        t.textContent = 'Create branch';
        add.appendChild(t);
        menu.appendChild(add);
        const sep = document.createElement('div');
        sep.className = 'msep';
        menu.appendChild(sep);
      }
      names.forEach((b) => {
        const mi = document.createElement('div');
        mi.className = 'mi';
        const ic = document.createElement('span');
        ic.className = 'mi-ic';
        const ck = document.createElement('span');
        ck.className = 'ck' + (b === gitInfo.branch ? ' on' : '');
        ic.appendChild(ck);
        const t = document.createElement('span');
        t.className = 'mi-t';
        t.textContent = b;
        mi.onclick = () => { menu.hidden = true; gitCheckout(b); };
        mi.appendChild(ic);
        mi.appendChild(t);
        menu.appendChild(mi);
      });
    }
  }

  //: Making a branch, through the reference's AddBranchDialog, and then
  //: switching to it when the box says to, which it does by default.
  async function gitNewBranch() {
    const path = window.__livePath;
    if (!path || !gitInfo.repo) return false;
    const asked = await window.__askBranch(gitInfo.branch, gitInfo.branches || []);
    if (!asked || !asked.name) return false;
    try {
      const r = await fetch(API + '/api/git/branch', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: path, name: asked.name, from: asked.from,
                              switch: asked.switchTo})
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        if (window.__toast) window.__toast(data.error || 'The branch could not be made.');
        return false;
      }
    } catch (err) {
      if (window.__toast) window.__toast('The branch could not be made.');
      return false;
    }
    await renderLive(path, false);
    await refreshGit(true);
    if (window.__toast) window.__toast('Created ' + asked.name);
    return true;
  }
  document.addEventListener('click', e => {
    const row = e.target.closest('#m-git [data-git="new-branch"]');
    if (!row) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    document.querySelectorAll('.menu').forEach(m => { m.hidden = true; });
    gitNewBranch();
  }, true);
  //: Switching branches, which is what the reference's flyout does. Local
  //: only: pull, push and sync reach the network and are not here.
  async function gitCheckout(branch) {
    const path = window.__livePath || '';
    if (!path || !branch || branch === gitInfo.branch) return false;
    let data = null;
    try {
      const r = await fetch(API + '/api/git/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: path, branch: branch })
      });
      data = await r.json();
      if (!r.ok) {
        //: Git refuses a checkout that would overwrite uncommitted work, and
        //: that refusal is the useful thing to say.
        if (window.__toast) {
          window.__toast(data.error || 'The branch could not be switched.');
        }
        return false;
      }
    } catch (err) {
      if (window.__toast) window.__toast('The branch could not be switched.');
      return false;
    }
    await renderLive(path, false);
    await refreshGit(true);
    if (window.__toast) window.__toast('Switched to ' + (data.branch || branch));
    return true;
  }

  function applyGit() {
    document.documentElement.setAttribute('data-git',
      gitInfo.repo ? '1' : '0');
    paintGitBar();
    paintGitRows();
  }

  async function refreshGit(force) {
    //: With no backend the page keeps what the build baked in. The export is
    //: one folder and that folder's branch is still the true answer for it,
    //: so blanking the bar here would be replacing a fact with nothing. In
    //: live mode there is always a path, which is what live() means.
    if (!live()) return gitInfo;
    const path = window.__livePath;
    if (!force && path === gitInfoPath) { applyGit(); return gitInfo; }
    try {
      const r = await fetch(API + '/api/git?path=' + encodeURIComponent(path));
      const d = await r.json();
      gitInfo = r.ok ? d : { repo: false };
      gitInfoPath = path;
    } catch (err) { gitInfo = { repo: false }; gitInfoPath = null; }
    applyGit();
    return gitInfo;
  }

  window.__git = {
    info: () => gitInfo,
    checkout: gitCheckout,
    refresh: () => refreshGit(true),
    sync: () => refreshGit(false),
    paint: applyGit
  };

  function paintCrumbs(path) {
    const box = $('#crumbs');
    if (!box) return;
    const oldIcon = box.querySelector('svg');
    const parts = path.replace(/\/+$/, '').split('/').filter(Boolean);
    clearRoot(box);
    let acc = '';
    const mk = (label, p, last, withIcon) => {
      const el = document.createElement('span');
      el.className = last ? 'crumb last' : 'crumb';
      el.setAttribute('data-p', p);
      if (withIcon && oldIcon) el.appendChild(oldIcon.cloneNode(true));
      const s = document.createElement('span');
      s.textContent = label;
      el.appendChild(s);
      box.appendChild(el);
    };
    mk(parts.length ? '' : '/', path, parts.length === 0, true);
    parts.forEach((part, i) => {
      acc += '/' + part;
      const sep = document.createElement('span');
      sep.className = 'csep';
      box.appendChild(sep);
      mk(part, acc, i === parts.length - 1, false);
    });
    const tn = document.querySelector('.tname');
    if (tn) {
      let label = parts.length ? parts[parts.length - 1] : '/';
      try {
        const cat = window.__DIR_CATALOG || {};
        const entry = cat[path] || cat[path.replace(/\/+$/, '')];
        if (entry && entry.name) label = entry.name;
        else if (!parts.length || (parts.length === 1 && parts[0] === 'root')) label = 'Home';
      } catch (err) {}
      tn.textContent = label;
    }
  }

  function paintStatus(n) {
    if (typeof window.__updateStatus === 'function') {
      try { window.__updateStatus(n); } catch (err) {}
    }
  }

  async function paintFolderDetails(path, count) {
    let meta = null;
    try { meta = await apiGet('/api/stat?path=' + encodeURIComponent(path)); }
    catch (err) { return; }
    const set = (k, v) => {
      const c = document.querySelector('[data-dk="' + k + '"]');
      if (c) c.textContent = v;
    };
    const base = path.replace(/\/+$/, '').split('/').pop() || '/';
    set('Name', base);
    set('Date Modified', fmtWhen(meta.modified));
    set('Item count', count + (count === 1 ? ' item' : ' items'));
    set('Item Path', path);
  }

  let searching = '';
  async function renderLive(path, push = true) {
    let data;
    try {
      const showH = window.__getPref && window.__getPref('showHidden') ? '&hidden=1' : '';
      data = await apiGet('/api/list?path=' + encodeURIComponent(path) + showH);
    } catch (err) {
      return false;
    }
    data.name = data.path.replace(/\/+$/, '').split('/').pop() || '/';
    window.__livePath = data.path;
    //: Navigating leaves Home. A click that goes through the tab machinery
    //: already does this; a navigation that starts here has to say so too, or
    //: the breadcrumb names a folder while the widgets are still on screen
    //: and the list is built into a container nobody can see. The boot prime
    //: passes push=false and is not a navigation, so Home stays.
    if (push) {
      const hw = document.getElementById('home-widgets');
      if (hw && !hw.hidden) {
        hw.hidden = true;
        if (window.__setLayout && window.__mode) {
          window.__setLayout(window.__mode());
        }
      }
      if (window.__sidebarActive) window.__sidebarActive(data.path, false);
    }
    searching = '';
    const n = buildRows(data);
    paintCrumbs(data.path);
    paintStatus(n);
    paintFolderDetails(data.path, n);
    if (push) {
      try { history.pushState({p: data.path}, '', location.pathname + location.search); }
      catch (err) {}
    }
    return true;
  }

  //: A tag in the sidebar is a place you can open, the way the reference has
  //: it. The listing comes from the backend's index rather than a disk walk,
  //: and every path in it is stat'd there, so what arrives is what still
  //: exists.
  async function renderTagView(tag) {
    let data;
    try {
      data = await apiGet('/api/tags/list?tag=' + encodeURIComponent(tag));
    } catch (err) {
      return false;
    }
    data.name = tag;
    searching = '';
    const n = buildRows(data);
    paintStatus(n);
    return true;
  }

  //: The section ships as a closed group with no children, because the tags
  //: are the person's and not the build's. Filled here, and refilled whenever
  //: the index changes. A group with nothing in it stays closed and has no
  //: chevron, which is how the served sidebar draws an empty section.
  function paintTagSidebar() {
    const grp = document.querySelector('.sgrp[data-sec="Tags"]');
    if (!grp) return;
    const head = grp.querySelector(':scope > .srow.head');
    let kids = grp.querySelector(':scope > .skids');
    if (!kids) {
      kids = document.createElement('div');
      kids.className = 'skids';
      grp.appendChild(kids);
    }
    while (kids.firstChild) kids.removeChild(kids.firstChild);
    const counts = {};
    Object.keys(tagIndex).forEach((p) => {
      (tagIndex[p] || []).forEach((n) => { counts[n] = (counts[n] || 0) + 1; });
    });
    const list = definedTags().filter((t) => counts[t.name]);
    list.forEach((t) => {
      const row = document.createElement('div');
      row.className = 'srow item lv1';
      row.setAttribute('data-tagopen', t.name);
      row.setAttribute('tabindex', '-1');
      row.setAttribute('title', t.name + ', ' + counts[t.name] + ' items');
      const slot = document.createElement('span');
      slot.className = 'cslot';
      row.appendChild(slot);
      const ic = document.createElement('span');
      ic.className = 'sb-tagic';
      ic.appendChild(tagDot(t.name));
      row.appendChild(ic);
      const lbl = document.createElement('span');
      lbl.className = 'lbl';
      lbl.textContent = t.name;
      row.appendChild(lbl);
      const cnt = document.createElement('span');
      cnt.className = 'sb-tagcount';
      cnt.textContent = String(counts[t.name]);
      row.appendChild(cnt);
      kids.appendChild(row);
    });
    //: An empty section is closed and has nothing to open. One with tags in
    //: it gets the chevron the other sections have.
    const slot = head ? head.querySelector('.cslot') : null;
    if (slot) {
      const had = slot.querySelector('.chev');
      if (list.length && !had) {
        const src = document.querySelector('.sgrp .srow.head .chev');
        if (src) slot.appendChild(src.cloneNode(true));
      } else if (!list.length && had) {
        had.remove();
      }
    }
    //: Opened when it has something in it, closed when it does not. Only
    //: adding the class left a filled section that could never be opened.
    grp.classList.toggle('shut', !list.length);
  }

  document.addEventListener('click', (e) => {
    const row = e.target.closest ? e.target.closest('[data-tagopen]') : null;
    if (!row) return;
    e.preventDefault();
    renderTagView(row.getAttribute('data-tagopen'));
  });

  let searchTimer = null;
  async function renderSearch(root, q) {
    let data;
    try {
      data = await apiGet('/api/search?root=' + encodeURIComponent(root) +
                          '&q=' + encodeURIComponent(q));
    } catch (err) {
      return;
    }
    searching = q;
    data.entries = data.results || [];
    data.meta = {};
    data.name = 'Search results';
    paintStatus(buildRows(data));
  }

  async function enterLive() {
    const win = document.querySelector('.win');
    const start = win ? win.getAttribute('data-path') : null;
    if (!start) return;
    let ok = false;
    for (let tries = 0; tries < 4 && !ok; tries += 1) {
      if (tries) await new Promise(go => setTimeout(go, 700));
      try {
        const r = await fetch(API + '/api/health', {
          signal: AbortSignal.timeout(1500)});
        ok = r.ok;
      } catch (err) {
        ok = false;
      }
    }
    if (!ok) return;
    window.__livePath = start;
    document.body.setAttribute('data-live', '1');
    $$('[data-live]').forEach(el => {
      const t = el.getAttribute('title') || '';
      el.setAttribute('title', t.replace(' (needs backend)', '')
                                .replace('Needs backend', ''));
    });
    try {
      history.replaceState({p: start}, '', location.pathname + location.search);
    } catch (err) {}
    //: What the backend can do, asked once here rather than the first time
    //: something needed to know. Every git command's enabled test and the
    //: branch flyout's Create branch read window.__caps, and until Properties
    //: or Compress had been opened it was null, so Pull, Push and Clone sat
    //: greyed against a backend that answers all three.
    await capabilities();
    //: The sidebar and the Home widgets, from this machine rather than the
    //: one the page was built on. Alongside the first listing, not before
    //: it: the widgets wait on the recent list, which is a walk, and the
    //: first listing must not queue behind that.
    const places = paintPlaces().catch(() => false);
    await renderLive(start, false);
    await places;
  }

  let clip = null;
  // On screen, not merely in the document. Every layout keeps its own
  // container, and the four that are not showing keep whatever was selected in
  // them: a query across all five can return a row nobody can see. That is the
  // wrong set to delete, and the wrong file to describe in a dialog.
  function onScreen(el) {
    return !!(el && (el.offsetWidth || el.offsetHeight ||
                     el.getClientRects().length));
  }
  function liveSelEls() {
    return Array.from(document.querySelectorAll(
      '.grid .sel, .dbody .sel, .list .sel, .cards .sel, .columns .sel'))
      .filter(onScreen);
  }
  function liveSelPaths() {
    return liveSelEls().map(el => el.getAttribute('data-p')).filter(Boolean);
  }
  //: Every name in a folder, hidden ones included, as the backend lists it.
  async function namesIn(dir) {
    try {
      const data = await apiGet('/api/list?path=' + encodeURIComponent(dir) + '&hidden=1');
      return new Set((data.entries || []).map(e => e.name));
    } catch (err) {
      return new Set();
    }
  }
  function markCut() {
    $$('.cut').forEach(el => el.classList.remove('cut'));
    if (clip && clip.mode === 'cut') {
      const set = new Set(clip.paths);
      $$('.cell, .row, .lrow, .tile, .crow').forEach(el => {
        if (set.has(el.getAttribute('data-p'))) el.classList.add('cut');
      });
    }
  }
  let nameCb = null;
  function showNameRow(initial, cb) {
    const row = $('#nrow'), inp = $('#ninput');
    if (!row || !inp) return;
    nameCb = cb;
    inp.value = initial || '';
    row.hidden = false;
    setTimeout(() => { inp.focus(); inp.select(); }, 0);
  }
  function hideNameRow() {
    const row = $('#nrow');
    if (row) row.hidden = true;
    nameCb = null;
  }

  // What the backend behind this page can do. The Python prototype and the
  // Rust service answer the same routes for everything the page already used,
  // and the newer commands exist on one of them only, so the page asks rather
  // than assuming and offers what is actually there.
  let caps = null;
  window.__caps = null;
  async function capabilities() {
    if (caps) return caps;
    try {
      const sys = await apiGet('/api/system');
      if (window.__setHome) window.__setHome(sys.home);
      caps = {
        names: Array.isArray(sys.capabilities) ? sys.capabilities : [],
        levels: [], encrypt: [], mediaProbe: sys.mediaProbe === true,
        // Whether Run with PowerShell is a command here or a row that says
        // why not. Asked rather than assumed: pwsh is a real program on this
        // system and it is not installed on every one.
        powershell: sys.powershell === true
      };
      try {
        const formats = await apiGet('/api/archive-formats');
        caps.levels = Array.isArray(formats.levels) ? formats.levels : [];
        caps.encrypt = Array.isArray(formats.encrypt) ? formats.encrypt : [];
        caps.archive = Array.isArray(formats.archive) ? formats.archive : [];
        // Which formats can be written in parts, and what part sizes there
        // are. Both come from the backend so the two cannot disagree about a
        // name; a backend that says nothing gets no split box at all.
        caps.split = Array.isArray(formats.split) ? formats.split : [];
        caps.splits = Array.isArray(formats.splits) ? formats.splits : [];
        // The LZMA2 knobs and where each reaches a codec, the sizes each
        // offers, and the encodings the Extract dialog lists; all from the
        // backend so the page never offers a value the backend refuses.
        caps.dictionary = Array.isArray(formats.dictionary) ? formats.dictionary : [];
        caps.wordSize = Array.isArray(formats.word_size) ? formats.word_size : [];
        caps.threads = Array.isArray(formats.threads) ? formats.threads : [];
        caps.dictionaries = Array.isArray(formats.dictionaries) ? formats.dictionaries : [];
        caps.wordSizes = Array.isArray(formats.word_sizes) ? formats.word_sizes : [];
        caps.encodings = Array.isArray(formats.encodings) ? formats.encodings : [];
      } catch (err) {}
    } catch (err) {
      caps = {names: [], levels: [], encrypt: [], archive: [],
              split: [], splits: [], dictionary: [], wordSize: [], threads: [],
              dictionaries: [], wordSizes: [], encodings: [],
              mediaProbe: false, powershell: false};
    }
    window.__caps = caps;
    return caps;
  }
  function can(name) { return !!(caps && caps.names.indexOf(name) >= 0); }

  // ---- long operations, reported rather than guessed -------------------
  //
  // The Status Center card in the prototype fills itself on a timer with
  // numbers it made up: a copy that had not started already claimed 28.4 MB/s
  // and half of a total worked out as ten megabytes per item. This drives the
  // same card off /api/job, so the counts are what the backend says it has
  // done, the rate is measured between two answers, and the card's Cancel
  // stops the work rather than only the card.
  const JOB_POLL_MS = 200;
  const MEGABYTE = 1024 * 1024;

  function human(bytes) {
    const n = Number(bytes) || 0;
    if (n < 1024) return n + ' B';
    const units = ['KB', 'MB', 'GB', 'TB'];
    let scaled = n / 1024, at = 0;
    while (scaled >= 1024 && at < units.length - 1) { scaled /= 1024; at++; }
    return scaled.toFixed(1) + ' ' + units[at];
  }
  function baseName(path) {
    return String(path || '').split('/').pop() || '';
  }
  function startTask(title, subtitle, iconKind) {
    if (!window.StatusCenter ||
        typeof window.StatusCenter.addTask !== 'function') return null;
    try {
      return window.StatusCenter.addTask({
        title: title, subtitle: subtitle || '', kind: 'file',
        iconKind: iconKind || 'copy', progress: 0, state: 'InProgress',
        // None of this can be paused, so the button that would claim it can
        // is not offered.
        isPausable: false, isCancelable: true,
        currentItem: '', processedBytes: '', speed: '0.0 MB/s'
      });
    } catch (err) {
      return null;
    }
  }
  // Run one operation as a job, reporting it while it goes. Hands back what
  // the operation itself returned and throws what it threw, so a caller reads
  // exactly as it did when this was a plain call.
  async function runJob(route, body, label, iconKind, ms) {
    const joined = route + (route.indexOf('?') < 0 ? '?job=1' : '&job=1');
    const answer = await apiPost(joined, body, ms || 300000);
    // A backend without jobs did the work outright and handed back the
    // result: there is nothing to poll and nothing to report.
    if (!answer || !answer.job) return answer;
    const id = String(answer.job);
    const task = startTask(label.title, label.subtitle, iconKind);
    let lastBytes = 0;
    let lastAt = Date.now();
    let asked = false;
    for (;;) {
      await new Promise(done => setTimeout(done, JOB_POLL_MS));
      let snap;
      try {
        snap = await apiGet('/api/job?id=' + encodeURIComponent(id));
      } catch (err) {
        if (task) task.fail(String(err && err.message ? err.message : err));
        throw err;
      }
      // The card's Cancel is the only cancel a person can press, and on its
      // own it changes the card and nothing else. Reading it here is what
      // reaches the work.
      if (task && task.state === 'Canceled' && !asked) {
        asked = true;
        try { await apiPost('/api/job/cancel', {id: id}); } catch (err) {}
      }
      const totalBytes = Number(snap.totalBytes || 0);
      const doneBytes = Number(snap.doneBytes || 0);
      const totalItems = Number(snap.totalItems || snap.total || 0);
      const doneItems = Number(snap.doneItems || snap.processed || 0);
      if (task && task.state !== 'Canceled') {
        const now = Date.now();
        const seconds = (now - lastAt) / 1000;
        const rate = seconds > 0 ? (doneBytes - lastBytes) / seconds : 0;
        lastBytes = doneBytes;
        lastAt = now;
        task.update({
          progress: totalBytes > 0
            ? Math.round(doneBytes * 100 / totalBytes)
            : totalItems > 0 ? Math.round(doneItems * 100 / totalItems) : 0,
          // A backend that does not know a total gets a bar that says so,
          // rather than one sitting at zero for the whole of it.
          isIndeterminate: !(totalBytes > 0 || totalItems > 0),
          currentItem: baseName(snap.current),
          processedBytes: totalBytes > 0
            ? human(doneBytes) + ' of ' + human(totalBytes)
            : doneItems + ' of ' + totalItems,
          speed: (rate > 0 ? rate / MEGABYTE : 0).toFixed(1) + ' MB/s'
        });
      }
      const state = snap.state || (snap.done ? 'done' : 'running');
      if (state === 'running') continue;
      if (state === 'cancelled' || snap.cancelled) {
        if (task) task.cancel();
        return snap.result || {cancelled: true};
      }
      if (state === 'error' || snap.error) {
        const message = (snap.error && snap.error.error) ||
          String(snap.error || 'the job failed');
        if (task) task.fail(message);
        const failed = new Error(message);
        // The same stable code a plain call would have carried, so a caller
        // can still tell a locked archive from a missing one.
        failed.code = snap.errorCode ||
          (snap.error && snap.error.code) || '';
        throw failed;
      }
      if (task) task.complete();
      return snap.result || {};
    }
  }
  window.__runJob = runJob;

  function arcNote(text, bad) {
    const note = $('#arc-note');
    if (!note) return;
    note.textContent = text || '';
    note.classList.toggle('bad', !!bad);
  }
  function hideArcRow() {
    if (window.__dialog.which() === 'dlg-createarchive') {
      window.__dialog.close('close');
    }
    arcNote('');
  }
  //: Files asks for all of this in CreateArchiveDialog rather than in a bar
  //: across the window, so the name, the format, the level, the split and
  //: the password are one question with one answer.
  //: Files' CompressSkippedItemsDialog: an item that cannot go into an
  //: archive, which here is a link whose far end is gone, is named before
  //: anything starts, and Skip goes on without it while Cancel stops. The
  //: reference asks for the same reason, see its #16240.
  async function dropUnarchivable(paths) {
    const gone = liveSelEls().filter(el => el.getAttribute('data-broken') === '1'
      && paths.indexOf(el.getAttribute('data-p')) >= 0);
    if (!gone.length) return paths;
    const list = $('#skipped-names');
    list.replaceChildren();
    gone.forEach(el => {
      const line = document.createElement('div');
      line.textContent = el.getAttribute('data-n') || '';
      list.appendChild(line);
    });
    const answer = await window.__dialog.open('dlg-compress-skipped');
    if (answer !== 'primary') return null;
    const skip = new Set(gone.map(el => el.getAttribute('data-p')));
    return paths.filter(p => !skip.has(p));
  }
  async function showArcRow(paths, dir) {
    const row = $('#dlg-createarchive');
    if (!row) return;
    await capabilities();
    paths = await dropUnarchivable(paths);
    if (!paths || !paths.length) return;
    // A level box that does nothing is worse than no level box, so it is only
    // shown when the backend said which levels it takes.
    const levelSel = $('#arc-level');
    if (levelSel) levelSel.parentElement.hidden = caps.levels.length === 0;
    const first = paths[0].split('/').pop() || 'archive';
    const stem = first.lastIndexOf('.') > 0 ? first.slice(0, first.lastIndexOf('.')) : first;
    $('#arc-name').value = paths.length === 1 ? stem : 'archive';
    $('#arc-password').value = '';
    fillArcSplit();
    fillArcLzma();
    syncArcPassword();
    syncArcLzma();
    arcNote(paths.length + (paths.length === 1 ? ' item' : ' items'));
    row.dataset.paths = JSON.stringify(paths);
    row.dataset.dir = dir;
    const answer = await window.__dialog.open('dlg-createarchive');
    if (answer !== 'primary') return;
    await runCompress(paths, dir);
  }
  // A tar has nowhere to keep a password, so the box says so rather than
  // taking one and losing it.
  function syncArcPassword() {
    const box = $('#arc-password');
    const fmt = $('#arc-format');
    if (!box || !fmt) return;
    const takes = !caps || caps.encrypt.length === 0
      ? false : caps.encrypt.indexOf(fmt.value) >= 0;
    box.disabled = !takes;
    box.placeholder = takes ? 'Password (optional)' : 'No password for ' + fmt.value;
    if (!takes) box.value = '';
  }
  // The sizes come from the backend rather than being written here twice, so
  // a name the page offers is always a name the backend takes.
  function fillArcSplit() {
    const box = $('#arc-split');
    if (!box) return;
    const sizes = (caps && caps.splits) || [];
    const keep = box.value;
    box.replaceChildren();
    if (!sizes.length) {
      const only = document.createElement('option');
      only.value = 'none';
      only.textContent = 'Do not split';
      box.appendChild(only);
    } else {
      sizes.forEach(size => {
        const item = document.createElement('option');
        item.value = size.name;
        item.textContent = size.label || size.name;
        box.appendChild(item);
      });
    }
    box.value = Array.from(box.options).some(o => o.value === keep) ? keep : 'none';
    syncArcSplit();
  }
  // Only 7z is written in parts. For every other format the box is greyed,
  // which is the reference's IsEnabled bound to CanSplit, rather than left
  // set to a size that would be dropped.
  function syncArcSplit() {
    const box = $('#arc-split');
    const fmt = $('#arc-format');
    if (!box || !fmt) return;
    const sizes = (caps && caps.splits) || [];
    const formats = (caps && caps.split) || [];
    const takes = sizes.length > 0 && formats.indexOf(fmt.value) >= 0;
    box.disabled = !takes;
    if (!takes) box.value = 'none';
  }
  //: Bytes the way the dialog and the backend say them: KB, MB and GB in
  //: powers of two, which is how the reference's list of dictionaries counts.
  function sizeText(bytes) {
    const k = 1024;
    if (bytes >= k * k * k) return (bytes / (k * k * k)).toFixed(1) + ' GB';
    if (bytes >= k * k) return Math.round(bytes / (k * k)) + ' MB';
    if (bytes >= k) return Math.round(bytes / k) + ' KB';
    return bytes + ' bytes';
  }
  //: The dictionary and word size lists come from the backend, so a size the
  //: page offers is one the backend takes, and the last choice is kept the
  //: way the reference keeps ArchiveDictionarySizesOption and
  //: ArchiveWordSizesOption in its settings.
  function fillArcLzma() {
    const dict = $('#arc-dict');
    const word = $('#arc-word');
    if (!dict || !word) return;
    const fill = (box, values, label, pref) => {
      box.replaceChildren();
      const auto = document.createElement('option');
      auto.value = '';
      auto.textContent = 'Auto';
      box.appendChild(auto);
      values.forEach(v => {
        const item = document.createElement('option');
        item.value = String(v);
        item.textContent = label(v);
        box.appendChild(item);
      });
      const kept = window.__getPref ? window.__getPref(pref) : null;
      box.value = kept && Array.from(box.options).some(o => o.value === String(kept))
        ? String(kept) : '';
    };
    fill(dict, (caps && caps.dictionaries) || [], sizeText, 'archiveDictionary');
    fill(word, (caps && caps.wordSizes) || [], v => String(v), 'archiveWordSize');
  }
  //: Which run of the estimate is the current one; a slower earlier answer
  //: must not land on top of a later choice.
  let arcEstimateRun = 0;
  //: The three knobs are greyed for a format whose codec has none of them,
  //: the reference's IsEnabled bound to CanSplit, and the memory card shows
  //: for the format that has them. The estimate is the backend's own, from
  //: the options the write itself would use, so the number read here is the
  //: number a refusal would quote.
  async function syncArcLzma() {
    const fmt = $('#arc-format');
    const dict = $('#arc-dict');
    const word = $('#arc-word');
    const threads = $('#arc-threads');
    const card = $('#arc-memory');
    if (!fmt || !dict || !word || !threads || !card) return;
    const has = list => !!(caps && Array.isArray(list) && list.indexOf(fmt.value) >= 0);
    dict.disabled = !has(caps && caps.dictionary) || dict.options.length < 2;
    word.disabled = !has(caps && caps.wordSize) || word.options.length < 2;
    threads.disabled = !has(caps && caps.threads);
    const shown = !dict.disabled;
    card.hidden = !shown;
    if (!shown) return;
    const run = ++arcEstimateRun;
    const level = $('#arc-level') ? $('#arc-level').value : 'normal';
    const q = '/api/archive-estimate?level=' + encodeURIComponent(level)
      + '&dictionary=' + encodeURIComponent(dict.value)
      + '&word_size=' + encodeURIComponent(word.value)
      + '&threads=' + encodeURIComponent(threads.value || '1');
    try {
      const est = await apiGet(q);
      if (run !== arcEstimateRun) return;
      //: The box runs from one to the machine's cores, and starts at all of
      //: them, as the reference's NumberBox does.
      if (est.cpus && Number(threads.max) !== est.cpus) {
        threads.max = String(est.cpus);
        if (!threads.dataset.touched) threads.value = String(est.cpus);
      }
      $('#arc-mem-est').textContent = 'Estimated memory usage: ' + sizeText(est.bytes || 0);
      $('#arc-mem-avail').textContent = est.available == null ? ''
        : 'Available memory: ' + sizeText(est.available);
    } catch (err) {
      if (run !== arcEstimateRun) return;
      $('#arc-mem-est').textContent = '';
      $('#arc-mem-avail').textContent = '';
    }
  }
  async function runCompress(paths, dir) {
    const row = $('#dlg-createarchive');
    if (!paths) {
      try { paths = JSON.parse((row && row.dataset.paths) || '[]'); }
      catch (err) { paths = []; }
    }
    if (!paths.length) return;
    dir = dir || (row && row.dataset.dir) || window.__livePath;
    const fmt = $('#arc-format').value;
    const name = ($('#arc-name').value || 'archive').trim();
    const body = {
      paths: paths, base: dir, format: fmt,
      dest: dir.replace(/\/+$/, '') + '/' + name + '.' + fmt
    };
    const levelSel = $('#arc-level');
    if (levelSel && !levelSel.parentElement.hidden) body.level = levelSel.value;
    const splitSel = $('#arc-split');
    if (splitSel && !splitSel.disabled && splitSel.value !== 'none') {
      body.split = splitSel.value;
    }
    const password = $('#arc-password').value;
    if (password && !$('#arc-password').disabled) body.password = password;
    //: The LZMA2 knobs, for the format whose codec has them; a greyed box
    //: sends nothing, and Auto is the level's own.
    const dict = $('#arc-dict');
    if (dict && !dict.disabled && dict.value) body.dictionary = Number(dict.value);
    const word = $('#arc-word');
    if (word && !word.disabled && word.value) body.word_size = Number(word.value);
    const threads = $('#arc-threads');
    if (threads && !threads.disabled) {
      const n = Math.max(1, Math.floor(Number(threads.value) || 1));
      body.threads = Math.min(n, Number(threads.max) || n);
    }
    arcNote('Compressing...');
    try {
      const out = await runJob('/api/compress', body, {
        title: 'Compressing to ' + name + '.' + fmt,
        subtitle: paths.length + (paths.length === 1 ? ' item' : ' items')
      }, 'compress');
      hideArcRow();
      // A split archive is not at the name that was typed: that file is gone
      // and the numbered parts stand in its place, so the message names what
      // is actually in the folder.
      const parts = (out && Array.isArray(out.parts)) ? out.parts : [];
      if (parts.length) {
        const first = parts[0].split('/').pop();
        showToast(parts.length === 1
          ? 'Compressed to ' + first
          : 'Compressed to ' + parts.length + ' parts, ' + first + ' first');
      } else {
        showToast('Compressed to ' + name + '.' + fmt);
      }
      await renderLive(dir);
    } catch (err) {
      //: The dialog answered and closed, so the note inside it is nowhere
      //: to be read: a failure has to be said out here.
      showToast(String(err && err.message ? err.message : err));
    }
  }

  //: The link itself, from what the dialog answered.
  async function makeShortcut(made, dir) {
    await apiPost('/api/mksymlink', {
      target: made.target,
      link: dir.replace(/\/+$/, '') + '/' + made.name});
    await renderLive(dir);
  }
  //: The folder and item picker behind every Browse button. On the
  //: reference's platform that is the system's FolderPicker or
  //: FileOpenPicker; here it is a list read through /api/list, with Up, a
  //: path box, and the folders first.
  //: The file type box, when the caller gave the picker types: the
  //: reference's FileOpenDialog filter, one entry a row, the first chosen.
  function pickerTypes(types) {
    const card = $('#pk-filter-card');
    const box = $('#pk-filter');
    if (!card || !box) return;
    box.replaceChildren();
    card.hidden = !(types && types.length);
    (types || []).forEach((t, i) => {
      const item = document.createElement('option');
      item.value = String(i);
      item.textContent = t.label + ' (' + t.exts.map(x => '*.' + x).join(';') + ')';
      box.appendChild(item);
    });
    box.value = '0';
    box.dataset.types = JSON.stringify(types || []);
  }
  function pickerExts() {
    const box = $('#pk-filter');
    const card = $('#pk-filter-card');
    if (!box || !card || card.hidden) return null;
    let types = [];
    try { types = JSON.parse(box.dataset.types || '[]'); } catch (err) { types = []; }
    const chosen = types[Number(box.value) || 0];
    return chosen ? chosen.exts.map(x => String(x).toLowerCase()) : null;
  }
  async function pickerFill(dir, foldersOnly) {
    const list = $('#pk-list');
    if (!list) return;
    list.replaceChildren();
    $('#pk-path').value = dir;
    let data;
    try { data = await apiGet('/api/list?path=' + encodeURIComponent(dir)); }
    catch (err) { return; }
    const exts = pickerExts();
    const extOf = n => { const at = String(n).lastIndexOf('.'); return at > 0 ? String(n).slice(at + 1).toLowerCase() : ''; };
    const entries = (data.entries || []).filter(e => !foldersOnly || e.isDirectory)
      .filter(e => e.isDirectory || !exts || exts.indexOf(extOf(e.name)) >= 0);
    entries.sort((a, b) => ((b.isDirectory ? 1 : 0) - (a.isDirectory ? 1 : 0))
      || a.name.localeCompare(b.name));
    entries.forEach(e => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'cdlg-item';
      b.setAttribute('data-path', (e.key || '').replace(/^file:\/\//, ''));
      b.setAttribute('data-dir', e.isDirectory ? '1' : '0');
      const t = document.createElement('span');
      t.textContent = e.name;
      b.appendChild(t);
      list.appendChild(b);
    });
  }
  async function browse(start, foldersOnly, types) {
    const d = $('#dlg-picker');
    if (!d) return null;
    $('#dlg-picker-t').textContent = foldersOnly ? 'Select a folder' : 'Select an item';
    d.dataset.folders = foldersOnly ? '1' : '0';
    d.dataset.picked = '';
    pickerTypes(types || []);
    await pickerFill(start || window.__livePath || '/', foldersOnly);
    const answer = await window.__dialog.open('dlg-picker');
    if (answer !== 'primary') return null;
    return d.dataset.picked || $('#pk-path').value.trim();
  }
  document.addEventListener('click', async e => {
    if (!live()) return;
    //: The two Browse buttons, each of which reopens its own dialog with
    //: what was picked once the picker has closed.
    if (e.target.closest('#ex-browse')) {
      const was = $('#ex-path').value.trim();
      const keep = {password: $('#ex-password').value, open: $('#ex-open').checked};
      const picked = await browse(was || window.__livePath, true);
      if (picked !== null) $('#ex-path').value = picked;
      $('#ex-password').value = keep.password;
      $('#ex-open').checked = keep.open;
      await reopenExtract();
      return;
    }
    if (e.target.closest('#cs-browse')) {
      const keep = {path: $('#cs-path').value, name: $('#cs-name').value};
      const picked = await browse(window.__livePath, false);
      if (picked !== null) keep.path = picked;
      if (picked !== null && !keep.name) keep.name = picked.split('/').pop() || '';
      const made = await window.__askShortcut(keep.path, keep.name);
      if (made) await makeShortcut(made, window.__livePath);
      return;
    }
    const d = $('#dlg-picker');
    if (!d || d.hidden) return;
    if (e.target.closest('#pk-up')) {
      const cur = $('#pk-path').value.replace(/\/+$/, '');
      const up = cur.slice(0, cur.lastIndexOf('/')) || '/';
      d.dataset.picked = '';
      await pickerFill(up, d.dataset.folders === '1');
      return;
    }
    const row = e.target.closest('#pk-list .cdlg-item');
    if (!row) return;
    const p = row.getAttribute('data-path');
    if (row.getAttribute('data-dir') === '1') {
      d.dataset.picked = '';
      await pickerFill(p, d.dataset.folders === '1');
    } else {
      d.dataset.picked = p;
      d.querySelectorAll('#pk-list .cdlg-item').forEach(r =>
        r.classList.toggle('sel', r === row));
    }
  });

  //: Files' DecompressArchiveDialog. Extract asks for the path, the
  //: password, and whether to open the folder afterwards; the three
  //: shortcuts ask nothing unless the archive asks for a password, and then
  //: ask through the same dialog with the path row put away:
  //: DecompressArchiveAction, BaseDecompressArchiveAction.
  let extractAsk = null;
  async function askExtract(path, dir, wantPath, opts) {
    opts = opts || {};
    const d = $('#dlg-extract');
    if (!d) return null;
    const first = path.split('/').pop() || 'archive';
    const stem = first.lastIndexOf('.') > 0 ? first.slice(0, first.lastIndexOf('.')) : first;
    const pathCard = $('#ex-path').closest('.cdlg-card');
    pathCard.hidden = !wantPath;
    if (!opts.keep) {
      $('#ex-path').value = wantPath ? dir.replace(/\/+$/, '') + '/' + stem : '';
      $('#ex-password').value = '';
      $('#ex-open').checked = false;
      await fillExtractEncoding(path);
    }
    //: What the backend said about the last try, which is the only thing
    //: worth saying: the reference has no string of its own for it here.
    $('#ex-note').textContent = opts.note || '';
    extractAsk = {path: path, dir: dir, wantPath: wantPath};
    const answer = await window.__dialog.open('dlg-extract', el => {
      //: The password box is what a person came for when the path is put
      //: away, so that is where the caret goes.
      if (!wantPath) setTimeout(() => $('#ex-password').focus(), 0);
    });
    if (answer !== 'primary') return null;
    const encodingCard = $('#ex-encoding-card');
    return {
      dest: $('#ex-path').value.trim(),
      password: $('#ex-password').value,
      open: $('#ex-open').checked,
      encoding: encodingCard && !encodingCard.hidden ? $('#ex-encoding').value : ''
    };
  }
  //: The Encoding row, for a zip whose names were written without the UTF-8
  //: flag: the reference shows it only then, IsArchiveEncodingUndetermined,
  //: with the backend's guess first and marked "(detected)", then Default
  //: and the list. Anything else has nothing to ask and the row stays away.
  async function fillExtractEncoding(path) {
    const card = $('#ex-encoding-card');
    const box = $('#ex-encoding');
    if (!card || !box) return;
    card.hidden = true;
    box.replaceChildren();
    const add = (value, text) => {
      const o = document.createElement('option');
      o.value = value;
      o.textContent = text;
      box.appendChild(o);
    };
    add('', 'Default');
    if (!/\.zip$/i.test(path)) return;
    let names = null;
    try {
      const listed = await apiGet('/api/archive-list?path=' + encodeURIComponent(path));
      names = listed && listed.names ? listed.names : null;
    } catch (err) {}
    if (!names || !names.undetermined) return;
    box.replaceChildren();
    if (names.detected && names.detected.name) {
      add(names.detected.name, names.detected.label + ' (detected)');
    }
    add('', 'Default');
    (((caps && caps.encodings) || [])).forEach(e => add(e.name, e.label));
    box.value = names.detected && names.detected.name ? names.detected.name : '';
    card.hidden = false;
  }
  //: Browse closed the extract dialog to open the picker, so it is opened
  //: again with what it had, and the answer goes where it was going.
  async function reopenExtract() {
    if (!extractAsk) return;
    const ask = extractAsk;
    const asked = await askExtract(ask.path, ask.dir, ask.wantPath, {keep: true});
    if (!asked) return;
    await runExtract(ask.path, ask.dir, 'here', asked);
  }
  async function runExtract(path, dir, where, asked) {
    let password = asked && asked.password ? asked.password : null;
    const dest = asked && asked.dest ? asked.dest : dir;
    const mode = asked ? 'here' : (where || 'smart');
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const body = {archive: path, dest: dest, destination: mode};
        if (password) body.password = password;
        if (asked && asked.encoding) body.encoding = asked.encoding;
        await runJob('/api/extract', body, {
          title: 'Extracting ' + (path.split('/').pop() || 'archive'),
          subtitle: 'To ' + (dest.split('/').pop() || dest)
        }, 'extract');
        //: Open destination folder when complete, or stay where the archive
        //: is and show what arrived beside it.
        await renderLive(asked && asked.open ? dest : dir);
        showToast('Extracted');
        return;
      } catch (err) {
        // 401 is the archive asking for a password, which is a question and
        // not a failure. Anything else is the end of it.
        if (err && err.code === 'needs-password' && attempt < 2) {
          const more = await askExtract(path, dir, false,
            {keep: attempt > 0, note: attempt > 0 ? String(err.message || err) : ''});
          if (!more || !more.password) return;
          password = more.password;
          continue;
        }
        showToast(String(err && err.message ? err.message : err));
        return;
      }
    }
  }

  window.__liveOp = async function(op) {
    if (!live()) return;
    const dir = window.__livePath;
    try {
      if (op === 'cut' || op === 'copy') {
        const paths = liveSelPaths();
        if (!paths.length) return;
        clip = {mode: op, paths};
        markCut();
      } else if (op === 'paste') {
        if (!clip || !clip.paths.length) return;
        const moving = clip.mode === 'cut';
        //: What the folder already holds, by name and hidden files included,
        //: so a taken name is a question asked before the copy rather than
        //: answered during it by the backend's default. Files asks through
        //: FilesystemOperationDialog with one choice per conflicting item.
        const taken = await namesIn(dir);
        const clashing = clip.paths.filter(p => taken.has(p.split('/').pop()));
        const modeOf = {};
        const nameOf = {};
        if (clashing.length) {
          const asked = await window.__fsop({
            kind: 'conflict',
            conflicts: clashing.map(p => p.split('/').pop()),
            others: clip.paths.length - clashing.length
          });
          if (!asked) return;
          clashing.forEach((p, i) => {
            modeOf[p] = asked.choices[i];
            //: A name typed in the row is the name it lands under.
            if (asked.names && asked.names[i]) nameOf[p] = asked.names[i];
          });
        }
        //: One request per answer, since a request carries one conflict
        //: rule: the items with a taken name go by what was chosen for them,
        //: the rest as they are, and Skip sends nothing at all.
        const groups = new Map();
        clip.paths.forEach(p => {
          const mode = modeOf[p] || '';
          if (mode === 'skip') return;
          if (!groups.has(mode)) groups.set(mode, []);
          groups.get(mode).push(p);
        });
        for (const [mode, paths] of groups) {
          const count = paths.length;
          const label = {
            title: (moving ? 'Moving ' : 'Copying ') + (count === 1
              ? (paths[0].split('/').pop() || 'item')
              : count + ' items'),
            subtitle: 'To ' + (dir.split('/').pop() || dir)
          };
          const body = {paths: paths, dest: dir};
          if (mode) body.conflict = mode;
          const named = paths.filter(p => nameOf[p]);
          if (named.length) {
            body.names = {};
            named.forEach(p => { body.names[p] = nameOf[p]; });
          }
          await runJob(moving ? '/api/move' : '/api/copy', body,
                       label, moving ? 'move' : 'copy');
        }
        clip = null;
        markCut();
        await renderLive(dir);
      } else if (op === 'trash' || op === 'delete') {
        const paths = liveSelPaths();
        if (!paths.length) return;
        //: The reference asks through FilesystemOperationDialog when the
        //: setting says to, with Permanently delete ticked for the command
        //: that means it; ticked, the item goes rather than to the trash.
        let permanent = op === 'delete';
        if (window.__deleteAsks && window.__deleteAsks()) {
          const asked = await window.__fsop({
            kind: 'delete', permanent: permanent,
            names: liveSelEls().map(el => el.getAttribute('data-n') || 'item')
          });
          if (!asked) return;
          permanent = asked.permanent;
        }
        await apiPost(permanent ? '/api/delete' : '/api/trash', {paths});
        await renderLive(dir);
      } else if (op === 'rename') {
        const paths = liveSelPaths();
        if (!paths.length) return;
        //: More than one selected is Bulk rename: every item takes the name
        //: that was typed and keeps its own extension, and a clash makes a
        //: new name rather than refusing, which is what Files asks for with
        //: NameCollisionOption.GenerateUniqueName.
        if (paths.length > 1) {
          const stem = await window.__askBulkName();
          if (!stem) return;
          for (const el of liveSelEls()) {
            const path = el.getAttribute('data-p');
            if (!path) continue;
            const was = el.getAttribute('data-n') || '';
            const folder = el.getAttribute('data-k') === 'Folder';
            await apiPost('/api/rename', {
              path: path, name: stem + window.__extensionOf(was, folder),
              conflict: 'keep-both'});
          }
          await renderLive(dir);
          return;
        }
        //: The same visible row the path came from, so the box opens with the
        //: name of the file that is about to be renamed.
        const el = liveSelEls()[0];
        showNameRow(el ? el.getAttribute('data-n') : '', async v => {
          if (!v) return;
          //: One rename is FailIfExists in the reference, which is the
          //: opposite of the bulk one: renaming onto a name that is taken is
          //: a question, not something to answer by inventing a name.
          await apiPost('/api/rename',
                        {path: paths[0], name: v, conflict: 'fail'});
          await renderLive(dir);
        });
      } else if (op === 'newfolder') {
        showNameRow('', async v => {
          if (!v) return;
          await apiPost('/api/mkdir', {
            path: dir.replace(/\/+$/, '') + '/' + v});
          await renderLive(dir);
        });
      } else if (op === 'newshortcut') {
        //: doAct has handed this to the live layer since the layer existed
        //: and the layer had no branch for it, so New shortcut against a
        //: backend did nothing at all and said nothing either.
        const made = await window.__askShortcut('');
        if (!made) return;
        await makeShortcut(made, dir);
      } else if (op === 'newfile') {
        showNameRow('', async v => {
          if (!v) return;
          await apiPost('/api/mkfile', {
            path: dir.replace(/\/+$/, '') + '/' + v});
          await renderLive(dir);
        });
      } else if (op === 'compress') {
        const paths = liveSelPaths();
        if (!paths.length) return;
        hideNameRow();
        await showArcRow(paths, dir);
      } else if (op === 'ctx-zip' || op === 'compress-7z') {
        // The two shortcuts: no bar, no questions, the format in the name of
        // the command and everything else left at its default.
        const paths = liveSelPaths();
        if (!paths.length) return;
        const fmt = op === 'ctx-zip' ? 'zip' : '7z';
        const first = (paths[0].split('/').pop() || 'archive');
        const stem = first.lastIndexOf('.') > 0
          ? first.slice(0, first.lastIndexOf('.')) : first;
        const name = (paths.length === 1 ? stem : 'archive') + '.' + fmt;
        try {
          await runJob('/api/compress', {
            paths: paths, base: dir, format: fmt,
            dest: dir.replace(/\/+$/, '') + '/' + name
          }, {
            title: 'Compressing to ' + name,
            subtitle: paths.length + (paths.length === 1 ? ' item' : ' items')
          }, 'compress');
          showToast('Compressed to ' + name);
          await renderLive(dir);
        } catch (err) {
          showToast(String(err && err.message ? err.message : err));
        }
      } else if (op === 'extract' || op === 'extract-smart' ||
                  op === 'extract-here' || op === 'extract-child') {
        const paths = liveSelPaths();
        if (paths.length !== 1) return;
        if (op === 'extract') {
          const asked = await askExtract(paths[0], dir, true);
          if (!asked || !asked.dest) return;
          await runExtract(paths[0], dir, 'here', asked);
          return;
        }
        const where = op === 'extract-here' ? 'here'
          : op === 'extract-child' ? 'folder' : 'smart';
        await runExtract(paths[0], dir, where);
      } else if (op === 'rotate-left' || op === 'rotate-right') {
        await capabilities();
        if (!can('rotate')) return;
        const paths = liveSelPaths();
        if (!paths.length) return;
        try {
          const out = await apiPost('/api/rotate', {
            paths: paths, turn: op === 'rotate-left' ? 'left' : 'right'
          }, 120000);
          const turned = (out && out.turned) || [];
          // Worth saying which happened: a turn that moved no pixels is the
          // one a photographer wants, and it is not obvious that it happened.
          const cheap = turned.filter(t => t.lossless).length;
          showToast(turned.length === 1
            ? (cheap ? 'Turned without re-encoding' : 'Turned')
            : ('Turned ' + turned.length + ' pictures'));
          await renderLive(dir);
        } catch (err) {
          showToast(String(err && err.message ? err.message : err));
        }
      }
    } catch (err) {
      // Paste, trash, rename and the two new item commands have no catch of
      // their own, and an empty one here meant a refusal from the backend
      // left the page looking as though nothing had been asked for.
      showToast(String(err && err.message ? err.message : err));
    }
  };

  // The archive and picture commands, taken in the capture phase. The menu's
  // own dispatcher handles several of these names already, with a fake that
  // shows a toast and compresses nothing, and it returns "handled" so nothing
  // downstream ever runs. Stopping here is what makes the real one the only one.
  const LIVE_ACTS = [
    'compress', 'ctx-zip', 'compress-7z', 'extract', 'extract-smart',
    'extract-here', 'extract-child', 'rotate-left', 'rotate-right'
  ];
  document.addEventListener('click', e => {
    if (!live()) return;
    const mi = e.target.closest('[data-act], [data-command]');
    if (!mi) return;
    const act = actOf(mi);
    if (LIVE_ACTS.indexOf(act) < 0) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    //: The menu is closed here, because stopping the event in the capture
    //: phase also stops whatever normally closes it.
    document.querySelectorAll('.ctx, .menu').forEach(m => { m.hidden = true; });
    window.__liveOp(act);
  }, true);

  //: A menu row names the reference's command; the toolbar and the older
  //: rows name this page's action. Both end at the same nine operations.
  function actOf(el) {
    const act = el.getAttribute('data-act');
    if (act) return act;
    const known = window.__commands
      && window.__commands.get(el.getAttribute('data-command'));
    return known ? known.act : null;
  }

  // The same nine, whoever asks for them. The listener above catches a click
  // on a row; this catches the palette, a keyboard shortcut and anything else
  // that calls the dispatcher directly and never makes a click for a listener
  // to see. Without it those routes reached the prototype's stand-in, which
  // shows a toast and compresses nothing, and did so with a real backend
  // running and a real archive one call away.
  const beforeLive = window.__doAct;
  window.__doAct = window.doAct = function (act, el) {
    if (live() && LIVE_ACTS.indexOf(act) >= 0) {
      document.querySelectorAll('.ctx, .menu').forEach(m => {
        m.hidden = true;
      });
      return window.__liveOp(act);
    }
    return beforeLive ? beforeLive(act, el) : undefined;
  };
  document.addEventListener('change', e => {
    if (e.target && e.target.id === 'pk-filter') {
      const d = $('#dlg-picker');
      if (d && !d.hidden) {
        d.dataset.picked = '';
        pickerFill($('#pk-path').value.trim() || '/', d.dataset.folders === '1');
      }
      return;
    }
    if (e.target && e.target.id === 'arc-format') {
      syncArcPassword();
      syncArcSplit();
      syncArcLzma();
    } else if (e.target && (e.target.id === 'arc-level' || e.target.id === 'arc-threads')) {
      if (e.target.id === 'arc-threads') e.target.dataset.touched = '1';
      syncArcLzma();
    } else if (e.target && (e.target.id === 'arc-dict' || e.target.id === 'arc-word')) {
      if (window.__setPref) {
        window.__setPref(e.target.id === 'arc-dict' ? 'archiveDictionary' : 'archiveWordSize',
                         e.target.value);
      }
      syncArcLzma();
    }
  });

  // Which run of the dialog is the current one. Opening properties for a
  // second file before the first has finished is easy to do, and every write
  // below lands in the one dialog: without this, the slower earlier run
  // finishes last and puts the previous file's answers on the screen.
  let propsRun = 0;
  async function enhanceProps() {
    const nameEl = document.querySelector('[data-gk="Name"]');
    if (!nameEl || !nameEl.textContent) return;
    const sel = liveSelEls()[0];
    const path = sel ? sel.getAttribute('data-p') : window.__livePath;
    if (!path) return;
    const run = ++propsRun;
    const set = (k, v) => {
      if (run !== propsRun) return;
      const c = document.querySelector('[data-gk="' + k + '"]');
      if (c) c.textContent = v;
    };
    try {
      const st = await apiGet('/api/stat?path=' + encodeURIComponent(path));
      set('Created', fmtWhen(st.created));
      set('Accessed', fmtWhen(st.accessed));
      set('Modified', fmtWhen(st.modified));
      if (!st.isDirectory) {
        set('Size', human(st.size));
        set('Size on disk', human(st.onDisk));
      }
      if (!st.isDirectory && st.size <= 1048576) {
        const busy = $('#h-calc');
        if (busy) busy.hidden = false;
        const h = await apiGet('/api/hash?path=' + encodeURIComponent(path));
        if (busy) busy.hidden = true;
        const map = [['h-md5', h.md5], ['h-sha1', h.sha1],
                     ['h-sha256', h.sha256]];
        map.forEach(([id, v]) => {
          const el = document.getElementById(id);
          if (el) el.textContent = v;
        });
        const note = $('#h-note');
        if (note) note.textContent = '';
      }
    } catch (err) {
      const busy = $('#h-calc');
      if (busy) busy.hidden = true;
    }
    await enhanceAttributes(path, run);
    await enhanceDetails(path, run);
    await enhanceCover(path, run);
    await enhanceUncompressed(path, run);
  }

  // ---- the album cover ------------------------------------------------
  //
  // The reference keeps the choice in the window until OK or Apply: the icon
  // shows the picked picture, or the plain icon after Remove, and the file is
  // written when the window is confirmed. Cancel forgets it.
  let coverEdit = null;
  const COVER_TYPES = [
    {label: 'Image Files', exts: ['bmp', 'jpg', 'jpeg', 'png']},
    {label: 'Bitmap Files', exts: ['bmp']},
    {label: 'JPEG', exts: ['jpg', 'jpeg']},
    {label: 'PNG', exts: ['png']}
  ];
  function propsArt() { return document.getElementById('props-icon-art'); }
  function showCoverPicture(uri) {
    const art = propsArt();
    if (!art) return;
    art.querySelectorAll('.thumbimg').forEach(old => old.remove());
    if (!uri) return;
    const img = document.createElement('img');
    img.className = 'thumbimg';
    img.alt = '';
    img.src = uri;
    art.appendChild(img);
  }
  async function enhanceCover(path, run) {
    const wrap = document.getElementById('props-cover-wrap');
    if (!wrap) return;
    coverEdit = null;
    await capabilities();
    if (run !== propsRun) return;
    // Whether the flyout is offered was decided once, by the filler, from
    // the reference's extension lists: for a sound or video file, whether
    // or not this backend can write one. What the backend cannot do it says
    // when asked, with the file's name, rather than the row going missing.
    // Deciding it here again would let a wrong answer there go unnoticed.
    if (wrap.hidden) return;
    coverEdit = {path: path, image: undefined};
    // The icon is the cover when there is one, the same picture the row got.
    if (!window.__fetchThumb) return;
    const uri = await window.__fetchThumb(path);
    if (run !== propsRun || !uri) return;
    showCoverPicture(uri);
  }
  window.__albumCover = async function(what) {
    if (!coverEdit) return;
    const edit = coverEdit;
    if (what === 'remove') {
      edit.image = null;
      //: ReturnIconOnly in the reference: the plain icon, the picture gone.
      showCoverPicture('');
      return;
    }
    const dir = edit.path.slice(0, edit.path.lastIndexOf('/')) || '/';
    const picked = await browse(dir, false, COVER_TYPES);
    if (!picked || coverEdit !== edit) return;
    edit.image = picked;
    const uri = window.__fetchThumb ? await window.__fetchThumb(picked) : '';
    if (coverEdit !== edit) return;
    showCoverPicture(uri || '');
  };
  //: On OK and Apply, the way GeneralPage.SaveChangesAsync writes it.
  async function commitCover() {
    const edit = coverEdit;
    if (!edit || edit.image === undefined) return false;
    const body = {path: edit.path};
    if (edit.image === null) body.remove = true;
    else body.image = edit.image;
    try {
      await apiPost('/api/album-cover', body);
      edit.image = undefined;
      await renderLive(window.__livePath);
      return true;
    } catch (err) {
      showToast(String(err && err.message ? err.message : err));
      return false;
    }
  }
  window.__commitCover = commitCover;
  document.addEventListener('click', e => {
    if (!live()) return;
    if (e.target.closest('#props-ok, #props-apply')) { commitCover(); return; }
    if (e.target.closest('#props-close, #props-cancel')) coverEdit = null;
  });

  // ---- the uncompressed size ------------------------------------------
  //
  // FileProperties sums the archive's files for the formats it browses.
  const BROWSABLE_ZIP = ['zip', '7z', 'rar', 'tar', 'gz', 'lzh', 'mrpack', 'jar'];
  function longSize(n) {
    return human(n) + ' (' + Number(n).toLocaleString('en-US') + ' bytes)';
  }
  async function enhanceUncompressed(path, run) {
    const row = document.getElementById('prow-uncompressed');
    if (!row) return;
    row.hidden = true;
    const name = (path.split('/').pop() || '').toLowerCase();
    if (!BROWSABLE_ZIP.some(ext => name.endsWith('.' + ext))) return;
    //: Asked rather than gated on a capability: both backends list an
    //: archive, and one that cannot answers with an error, which leaves
    //: the row where it was.
    let out = null;
    try { out = await apiGet('/api/archive-list?path=' + encodeURIComponent(path)); }
    catch (err) { return; }
    if (run !== propsRun) return;
    const total = (out.entries || []).filter(e => !e.isDirectory)
      .reduce((sum, e) => sum + (Number(e.size) || 0), 0);
    const cell = row.querySelector('[data-gk="Uncompressed size"]');
    if (cell) cell.textContent = longSize(total);
    row.hidden = false;
  }

  // The two boxes on the General tab. They are checkboxes rather than a mode,
  // so each one is sent on its own the moment it changes: a dialog that saved
  // both on close would write back the value it read a minute ago.
  async function enhanceAttributes(path, run) {
    const ro = document.getElementById('prop-readonly');
    const hid = document.getElementById('prop-hidden');
    if (!ro || !hid) return;
    await capabilities();
    if (run !== propsRun) return;
    const row = ro.closest('.prow');
    if (!can('attributes')) {
      if (row) row.hidden = true;
      return;
    }
    if (row) row.hidden = false;
    let attrs = null;
    try {
      attrs = (await apiGet('/api/attributes?path=' + encodeURIComponent(path))).attributes;
    } catch (err) { return; }
    if (run !== propsRun) return;
    ro.checked = !!attrs.readOnly;
    hid.checked = !!attrs.hidden;
    // A file called .bashrc is hidden by its name, everywhere, by every
    // program. Unchecking that would mean renaming it, which would break
    // whatever points at it, so the box says what it is and does not offer.
    hid.disabled = !!attrs.hiddenByName;
    hid.title = attrs.hiddenByName
      ? 'Hidden by its name. Rename it to show it.' : '';
    const send = async (key, box) => {
      const body = {path: path};
      body[key] = box.checked;
      try {
        const out = await apiPost('/api/attributes', body);
        ro.checked = !!out.attributes.readOnly;
        hid.checked = !!out.attributes.hidden;
        await renderLive(window.__livePath);
      } catch (err) {
        // Put the box back where it was: a checkbox that stays ticked after a
        // refusal is a lie about the file.
        box.checked = !box.checked;
        showToast(String(err && err.message ? err.message : err));
      }
    };
    ro.onchange = () => send('readOnly', ro);
    hid.onchange = () => send('hidden', hid);
  }

  // The Camera and Audio and video sections. Both stay hidden unless the file
  // actually has something to put in them.
  async function enhanceDetails(path, run) {
    const camera = document.getElementById('det-camera');
    const media = document.getElementById('det-media');
    if (!camera || !media) return;
    camera.hidden = true;
    media.hidden = true;
    await capabilities();
    if (!can('details') || run !== propsRun) return;
    let out = null;
    try {
      out = await apiGet('/api/details?path=' + encodeURIComponent(path));
    } catch (err) { return; }
    if (run !== propsRun) return;
    const put = (key, value) => {
      const el = document.querySelector('[data-detk="' + key + '"]');
      if (!el) return false;
      el.textContent = value == null ? '' : String(value);
      const row = el.closest('.det-row');
      if (row) row.hidden = value == null || value === '';
      return value != null && value !== '';
    };
    const photo = out.photo || {};
    const size = out.width && out.height ? out.width + ' x ' + out.height : '';
    let any = false;
    any = put('Dimensions', size) || any;
    any = put('Camera', photo.camera) || any;
    any = put('Lens', photo.lens) || any;
    any = put('Taken', photo.taken) || any;
    any = put('Exposure', photo.exposure) || any;
    any = put('Aperture', photo.aperture) || any;
    any = put('Iso', photo.iso ? 'ISO ' + photo.iso : '') || any;
    any = put('FocalLength', photo.focalLength) || any;
    any = put('Gps', photo.latitude == null ? ''
      : photo.latitude.toFixed(5) + ', ' + photo.longitude.toFixed(5)) || any;
    camera.hidden = !any;

    const m = out.media || {};
    let anyMedia = false;
    anyMedia = put('Duration', m.duration == null ? '' : clock(m.duration)) || anyMedia;
    anyMedia = put('FrameSize', m.width ? m.width + ' x ' + m.height : '') || anyMedia;
    anyMedia = put('FrameRate', m.frameRate == null ? ''
      : m.frameRate.toFixed(2).replace(/\.00$/, '') + ' fps') || anyMedia;
    anyMedia = put('Bitrate', m.bitrate == null ? ''
      : Math.round(m.bitrate / 1000) + ' kbps') || anyMedia;
    anyMedia = put('VideoCodec', m.videoCodec) || anyMedia;
    anyMedia = put('AudioCodec', m.audioCodec) || anyMedia;
    anyMedia = put('Channels', m.channels) || anyMedia;
    anyMedia = put('SampleRate', m.sampleRate ? m.sampleRate + ' Hz' : '') || anyMedia;
    media.hidden = !anyMedia;

    // Title, artist and album belong in Description, which already has rows
    // for the first of them.
    const title = document.querySelector('[data-detk="Title"]');
    if (title && m.title) title.textContent = m.title;
    const authors = document.querySelector('[data-detk="Authors"]');
    if (authors && (m.artist || photo.artist)) {
      authors.textContent = m.artist || photo.artist;
    }
    const copyright = document.querySelector('[data-detk="Copyright"]');
    if (copyright && photo.copyright) copyright.textContent = photo.copyright;
  }

  // Seconds as a person reads a running time.
  function clock(seconds) {
    const whole = Math.round(seconds);
    const h = Math.floor(whole / 3600);
    const m = Math.floor((whole % 3600) / 60);
    const s = whole % 60;
    const pad = n => (n < 10 ? '0' : '') + n;
    return h ? h + ':' + pad(m) + ':' + pad(s) : m + ':' + pad(s);
  }
  const propsEl = document.getElementById('props');
  if (propsEl) new MutationObserver(() => {
    if (!live() || propsEl.hidden) return;
    enhanceProps();
  }).observe(propsEl, {attributes: true, attributeFilter: ['hidden']});

  document.addEventListener('click', e => {
    if (!live()) return;
    if (e.target.closest('#btn-search, #btn-filter, #btn-palette, #btn-pane, #btn-sc')) return;
    const nav = e.target.closest('.srow.item[data-root], .crumbs [data-p]');
    if (nav) {
      e.preventDefault();
      let p = nav.getAttribute('data-p');
      if (!p) p = (nav.getAttribute('data-root') || '').replace(/^file:\/\//, '');
      if (p) renderLive(p);
      return;
    }
  });
  document.addEventListener('dblclick', e => {
    if (!live()) return;
    const it = e.target.closest(ITEMS);
    if (it && it.getAttribute('data-k') === 'Folder') {
      const p = it.getAttribute('data-p');
      if (p) renderLive(p);
    }
  });
  document.addEventListener('click', e => {
    if (!live()) return;
    const r = e.target.closest('[data-act="ctx-refresh"]');
    if (r) {
      e.preventDefault();
      e.stopImmediatePropagation();
      renderLive(window.__livePath);
    }
  }, true);
  document.addEventListener('keydown', e => {
    if (!live()) return;
    const t = e.target || {};
    if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA') {
      if (t.id === 'ninput') {
        if (e.key === 'Enter' && nameCb) {
          const cb = nameCb;
          hideNameRow();
          cb(t.value.trim());
        } else if (e.key === 'Escape') {
          hideNameRow();
        }
        e.stopPropagation();
      } else if (t.id === 'osearch') {
        if (e.key === 'Enter' && t.value.trim().length >= 2 && live()) {
          renderSearch(window.__livePath, t.value.trim());
        } else if (e.key === 'Escape' && live() && searching) {
          renderLive(window.__livePath);
        }
      }
      return;
    }
    if (e.key === 'Delete' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      //: The question is asked inside the operation, once, whichever way
      //: it was reached. This used to look for window.__openDeleteConfirm,
      //: which nothing defined, and fall through to deleting unasked.
      window.__liveOp(e.shiftKey ? 'delete' : 'trash');
    } else if (e.key === 'F2') {
      e.preventDefault();
      window.__liveOp('rename');
    }
  });
  window.addEventListener('popstate', e => {
    if (live() && e.state && e.state.p) renderLive(e.state.p, false);
  });

  window.__live = {
    get path() { return window.__livePath || null; },
    render: path => renderLive(path),
  };
  //: Ask once when the page comes up. Without a backend this clears the map
  //: and paints nothing, which is the right answer rather than an error.
  if (window.__tags) window.__tags.refresh();
  shelfWire();
  refreshGit(true);
  if (window.__mica) window.__mica.refresh();
  window.__fetchPreview = async function(path) {
    try {
      const j = await apiGet('/api/preview?path=' + encodeURIComponent(path));
      if (j && !j.binary && j.text) return j.text;
    } catch (err) {}
    return '';
  };
  //: One thumbnail. "" covers both "not an image" and "would not decode",
  //: because the caller does the same thing either way.
  //: One stat, for anything that needs a fact the row does not carry.
  window.__statPath = async function(path) {
    try {
      return await apiGet('/api/stat?path=' + encodeURIComponent(path));
    } catch (err) {
      return null;
    }
  };
  //: A backend with no gpg on it answers with an error rather than a verdict,
  //: and no verdict is not the same as "not signed", so nothing is shown.
  window.__signature = async function(path) {
    try {
      return await apiGet('/api/signature?path=' + encodeURIComponent(path));
    } catch (err) {
      return null;
    }
  };
  //: Owner, group and mode. A backend that cannot answer returns nothing,
  //: and nothing is what the Security tab then says: the tab used to list
  //: three Windows principals with every box ticked whatever the file was.
  window.__props = async function(path) {
    try {
      return await apiGet('/api/props?path=' + encodeURIComponent(path));
    } catch (err) {
      return null;
    }
  };
  window.__chmod = async function(path, mode) {
    try {
      return await apiPost('/api/chmod', {path: path, mode: mode});
    } catch (err) {
      return null;
    }
  };
  window.__hashOf = async function(path) {
    try {
      return await apiGet('/api/hash?path=' + encodeURIComponent(path));
    } catch (err) {
      return null;
    }
  };
  window.__fetchThumb = async function(path) {
    try {
      const j = await apiGet('/api/thumb?path=' + encodeURIComponent(path));
      if (j && j.supported && typeof j.uri === 'string') return j.uri;
    } catch (err) {}
    return '';
  };
