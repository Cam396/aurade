  // ---- the sidebar and the Home widgets, from what the daemon lists ------
  //
  // The static export draws both from the build machine's volumes, and a
  // shipped page has none of those (see SHIP in build_v3.py). Once the daemon
  // answers, both are redrawn from /api/volumes, /api/recent and the tag
  // index, in the shapes sidebar.py and home_page_html build, so everything
  // that already reads .srow and .wcard keeps working. Nothing here assigns
  // markup: every node is made, and every glyph is a clone from #sb-glyphs.
  const GLYPH_BY_PURPOSE = {
    home: 'home', desktop: 'desktop', documents: 'documents',
    downloads: 'downloads', music: 'music', pictures: 'pictures',
    videos: 'videos'
  };
  const GLYPH_BY_KIND = {
    removable: 'usb', system: 'drive', trash: 'trash', drive: 'cloud',
    provided: 'cloud', mtp: 'usb', archive: 'drive', android: 'usb',
    crostini: 'drive', recent: 'documents', mount: 'drive', network: 'network'
  };
  const SECTION_GLYPH = {
    Pinned: 'pin', Drives: 'drive', 'Cloud Drives': 'cloud',
    Network: 'network', Tags: 'tag'
  };
  //: The reference's order for the pinned user folders, which is neither the
  //: daemon's nor the alphabet's.
  const QUICK_ACCESS = ['desktop', 'downloads', 'documents', 'pictures', 'music', 'videos'];
  function byQuickAccess(a, b) {
    const ia = QUICK_ACCESS.indexOf(a.purpose), ib = QUICK_ACCESS.indexOf(b.purpose);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  }

  function sbGlyph(name, px) {
    const tpl = document.getElementById('sb-glyphs');
    const src = tpl && tpl.content ? tpl.content.querySelector('[data-g="' + name + '"] > *') : null;
    if (!src) return null;
    const el = src.cloneNode(true);
    if (px) {
      el.setAttribute('width', String(px));
      el.setAttribute('height', String(px));
    }
    return el;
  }
  function volumeGlyph(v) {
    return GLYPH_BY_PURPOSE[v.purpose] || GLYPH_BY_KIND[v.kind] || 'drive';
  }
  //: sidebar.py's _group_for: Home is its own row above every section.
  function groupOf(v) {
    if (v.purpose === 'home') return 'home';
    if (v.kind === 'drive' || v.kind === 'provided') return 'Cloud Drives';
    if (v.kind === 'trash' || v.purpose) return 'Pinned';
    if (v.kind === 'network') return 'Network';
    return 'Drives';
  }
  function mk(tag, cls, text) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function pathOfKey(key) {
    return String(key || '').replace(/^file:\/\//, '');
  }
  function driveData(el, v) {
    const cap = v.capacity || {};
    const total = cap.total || 0;
    const free = cap.free || 0;
    const used = Math.max(0, total - free);
    const pct = total > 0 ? Math.floor((used / total) * 100) : 0;
    el.setAttribute('data-kind', 'drive');
    el.setAttribute('data-total', String(total));
    el.setAttribute('data-free', String(free));
    el.setAttribute('data-used', String(used));
    el.setAttribute('data-pct', String(pct));
    el.setAttribute('data-fs', v.fstype || 'ext4');
    return {total: total, free: free, used: used, pct: pct};
  }

  function sbItem(node, level) {
    const row = mk('div', 'srow item lv' + level);
    row.setAttribute('tabindex', '-1');
    row.setAttribute('data-root', node.root);
    row.setAttribute('data-n', node.label);
    if (node.sec === 'Drives' && node.vol) driveData(row, node.vol);
    else row.setAttribute('data-kind', 'folder');
    row.appendChild(mk('span', 'ind'));
    const slot = mk('span', 'cslot');
    if (node.kids && node.kids.length) {
      const chev = sbGlyph('chev');
      if (chev) slot.appendChild(chev);
    }
    row.appendChild(slot);
    const g = sbGlyph(node.glyph);
    if (g) row.appendChild(g);
    row.appendChild(mk('span', 'lbl', node.label));
    if (node.trail) {
      const trail = mk('span', 'trail');
      const t = sbGlyph('trail-' + node.trail);
      if (t) trail.appendChild(t);
      row.appendChild(trail);
    }
    if (!node.kids || !node.kids.length) return row;
    //: A drive with children is a group of its own, the way sidebar.py has
    //: it, so its chevron opens onto them.
    const grp = mk('div', 'sgrp' + (node.open ? '' : ' shut'));
    grp.setAttribute('data-sec', node.label);
    grp.appendChild(row);
    const kids = mk('div', 'skids');
    node.kids.forEach(k => kids.appendChild(sbItem(k, level + 1)));
    grp.appendChild(kids);
    return grp;
  }
  function sbHead(label, kids, open) {
    const grp = mk('div', 'sgrp' + (open ? '' : ' shut'));
    grp.setAttribute('data-sec', label);
    const head = mk('div', 'srow head lv0');
    head.setAttribute('role', 'button');
    head.setAttribute('tabindex', '0');
    const slot = mk('span', 'cslot');
    if (kids.length) {
      const chev = sbGlyph('chev');
      if (chev) slot.appendChild(chev);
    }
    head.appendChild(slot);
    const g = sbGlyph(SECTION_GLYPH[label] || 'folder');
    if (g) head.appendChild(g);
    head.appendChild(mk('span', 'lbl', label));
    grp.appendChild(head);
    const box = mk('div', 'skids');
    kids.forEach(k => box.appendChild(sbItem(k, 1)));
    grp.appendChild(box);
    return grp;
  }
  //: The top level folders of a drive, capped, the way the static sidebar
  //: had them: a sidebar is not a listing.
  async function driveChildren(v) {
    try {
      const data = await apiGet('/api/list?path=' + encodeURIComponent(pathOfKey(v.root)));
      return (data.entries || [])
        .filter(e => e.isDirectory && !e.hidden && !/^\./.test(e.name))
        .sort((a, b) => a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1)
        .slice(0, 12)
        .map(e => ({label: e.name, glyph: 'folder', root: e.key, sec: 'Drives',
                    vol: null, kids: [], trail: null, open: false}));
    } catch (err) {
      return [];
    }
  }

  async function paintSidebar(volumes) {
    const list = document.querySelector('.slist');
    if (!list) return;
    const groups = {Pinned: [], Drives: [], 'Cloud Drives': [], Network: []};
    let home = null;
    for (const v of volumes) {
      const group = groupOf(v);
      const node = {label: v.label, glyph: volumeGlyph(v), root: v.root,
                    sec: group, vol: v, kids: [], trail: null, open: false};
      if (group === 'home') { home = node; continue; }
      node.trail = v.removable ? 'eject'
        : (group === 'Pinned' && v.kind !== 'trash') ? 'pin' : null;
      if (group === 'Drives') node.kids = await driveChildren(v);
      groups[group].push(node);
    }
    groups.Pinned.sort((a, b) => byQuickAccess(a.vol, b.vol));
    const frag = document.createDocumentFragment();
    if (home) frag.appendChild(sbItem(home, 0));
    ['Pinned', 'Drives', 'Cloud Drives'].forEach(name => {
      if (groups[name].length) frag.appendChild(sbHead(name, groups[name], true));
    });
    //: Real Files sections that may hold nothing here. They stay, closed,
    //: because they are places the app can reach, not decoration.
    frag.appendChild(sbHead('Network', groups.Network, groups.Network.length > 0));
    frag.appendChild(sbHead('Tags', [], false));
    list.replaceChildren(frag);
    paintTagSidebar();
    if (window.__sidebarActive) {
      const p = window.__livePath || '';
      window.__sidebarActive(p, !!(window.__isHome && window.__isHome(p)));
    }
  }

  // ---- the Home widgets ------------------------------------------------
  function wcardFolder(v) {
    const card = mk('div', 'wcard wcard-folder');
    card.setAttribute('data-path', v.root);
    card.setAttribute('data-n', v.label);
    card.setAttribute('data-kind', 'Folder');
    card.setAttribute('tabindex', '-1');
    const pin = mk('span', 'wcard-pin');
    pin.setAttribute('title', 'Pinned');
    const pinIco = sbGlyph('ico-pin');
    if (pinIco) pin.appendChild(pinIco);
    card.appendChild(pin);
    const ico = mk('div', 'wcard-ico');
    const g = sbGlyph(volumeGlyph(v), 32);
    if (g) ico.appendChild(g);
    card.appendChild(ico);
    card.appendChild(mk('div', 'wcard-name', v.label));
    return card;
  }
  function wcardDrive(v) {
    const card = mk('div', 'wcard wcard-drive');
    card.setAttribute('data-path', v.root);
    card.setAttribute('data-n', v.label);
    card.setAttribute('tabindex', '-1');
    const d = driveData(card, v);
    const ico = mk('div', 'wd-icon');
    const g = sbGlyph(volumeGlyph(v), 32);
    if (g) ico.appendChild(g);
    card.appendChild(ico);
    const info = mk('div', 'wd-info');
    info.appendChild(mk('div', 'wd-name', v.label));
    const bar = mk('div', 'wd-bar');
    const fill = mk('div', 'wd-fill');
    fill.style.width = d.pct + '%';
    bar.appendChild(fill);
    info.appendChild(bar);
    info.appendChild(mk('div', 'wd-sub',
      d.total > 0 ? human(d.free) + ' free of ' + human(d.total) : 'Ready'));
    card.appendChild(info);
    const st = mk('button', 'wd-storage');
    st.setAttribute('title', 'Open Storage Sense');
    st.setAttribute('data-act', 'storage-sense');
    const stIco = sbGlyph('ico-settings');
    if (stIco) st.appendChild(stIco);
    card.appendChild(st);
    return card;
  }
  function wnetCard(v) {
    const card = mk('div', 'wcard wnet-card');
    card.setAttribute('data-path', v.root);
    card.setAttribute('data-n', v.label);
    card.setAttribute('data-kind', 'network');
    card.setAttribute('data-protocol', v.protocol || v.fstype || '');
    card.setAttribute('tabindex', '-1');
    const ico = mk('div', 'wd-icon');
    const g = sbGlyph('network', 32);
    if (g) ico.appendChild(g);
    card.appendChild(ico);
    const info = mk('div', 'wd-info');
    info.appendChild(mk('div', 'wd-name', v.label));
    info.appendChild(mk('div', 'wd-sub',
      (v.source || '') + (v.protocol ? ' (' + v.protocol + ')' : '')));
    card.appendChild(info);
    return card;
  }
  function wnetEmpty() {
    const bar = mk('div', 'winfobar');
    bar.setAttribute('role', 'status');
    const i = sbGlyph('ico-info');
    if (i) bar.appendChild(i);
    bar.appendChild(mk('span', '', 'No network locations were found.'));
    const btn = mk('button', 'winfobar-btn', 'Disable');
    btn.setAttribute('data-act', 'toggle-widget');
    btn.setAttribute('data-widget', 'network');
    bar.appendChild(btn);
    return bar;
  }
  function wrecentRow(item) {
    const name = item.name || pathOfKey(item.key).split('/').pop() || '';
    const row = mk('div', 'wrecent-row');
    row.setAttribute('data-p', item.path);
    row.setAttribute('data-n', name);
    row.setAttribute('data-k', 'File');
    row.setAttribute('tabindex', '-1');
    const ico = mk('span', 'wrecent-ico');
    const a = takeArt(artFor(name, false)[0], true);
    if (a) ico.appendChild(a);
    row.appendChild(ico);
    row.appendChild(mk('span', 'wrecent-name', name));
    row.appendChild(mk('span', 'wrecent-path', item.path));
    return row;
  }
  function wtagCard(tag, paths) {
    const card = mk('div', 'wtag-card');
    const h = mk('div', 'wtag-h');
    const title = mk('div', 'wtag-title');
    const dot = mk('span', 'wtag-dot');
    dot.style.background = tagColor(tag.name);
    title.appendChild(dot);
    title.appendChild(mk('span', '', tag.name));
    h.appendChild(title);
    const open = mk('button', 'wtag-open');
    open.setAttribute('title', 'Open all tagged items');
    open.setAttribute('data-tagopen', tag.name);
    const o = sbGlyph('ico-open');
    if (o) open.appendChild(o);
    h.appendChild(open);
    card.appendChild(h);
    const items = mk('div', 'wtag-items');
    paths.slice(0, 6).forEach(p => {
      const name = p.split('/').pop() || p;
      const it = mk('div', 'wtag-item');
      it.setAttribute('data-p', p);
      it.setAttribute('data-n', name);
      const ico = mk('span', 'wtag-item-ico');
      const a = takeArt(artFor(name, false)[0], true);
      if (a) ico.appendChild(a);
      it.appendChild(ico);
      it.appendChild(mk('span', 'wtag-item-name', name));
      items.appendChild(it);
    });
    card.appendChild(items);
    return card;
  }

  async function paintWidgets(volumes) {
    const qa = document.querySelector('.wcards-qa');
    const drives = document.querySelector('.wcards-drives');
    const net = document.querySelector('.wcards-net');
    const recent = document.querySelector('.wrecent-list');
    const tags = document.querySelector('.wtags-grid');
    if (qa) {
      qa.replaceChildren();
      volumes.filter(v => QUICK_ACCESS.indexOf(v.purpose) >= 0).sort(byQuickAccess)
        .forEach(v => qa.appendChild(wcardFolder(v)));
    }
    if (drives) {
      drives.replaceChildren();
      //: home_page_html's rule: Home is a drive card only when the root
      //: filesystem is not listed as one of its own.
      const hasRoot = volumes.some(v => v.root === 'file:///');
      volumes.filter(v => (v.purpose === 'home' || !v.purpose)
                          && ['system', 'removable', 'mount'].indexOf(v.kind) >= 0
                          && !(v.purpose === 'home' && hasRoot))
        .forEach(v => drives.appendChild(wcardDrive(v)));
    }
    if (net) {
      net.replaceChildren();
      const shares = volumes.filter(v => v.kind === 'network');
      if (shares.length) shares.forEach(v => net.appendChild(wnetCard(v)));
      else net.appendChild(wnetEmpty());
    }
    if (recent) {
      recent.replaceChildren();
      try {
        const r = await apiGet('/api/recent?limit=20');
        (r.recent || []).forEach(item => recent.appendChild(wrecentRow(item)));
      } catch (err) {}
    }
    if (tags) {
      tags.replaceChildren();
      const byTag = {};
      Object.keys(tagIndex).forEach(p => {
        (tagIndex[p] || []).forEach(n => { (byTag[n] = byTag[n] || []).push(p); });
      });
      definedTags().filter(t => byTag[t.name])
        .forEach(t => tags.appendChild(wtagCard(t, byTag[t.name].sort())));
    }
  }

  let placesRun = 0;
  async function paintPlaces() {
    const run = ++placesRun;
    let volumes;
    try {
      volumes = (await apiGet('/api/volumes')).volumes || [];
    } catch (err) {
      return false;
    }
    if (run !== placesRun) return false;
    //: The user's own pins, and the order they gave the pinned rows, are
    //: the window's to keep; the redraw takes the static rows they were on.
    //: Each half is put back as soon as its half is drawn, since the
    //: widgets wait on the recent list and the sidebar should not.
    await paintSidebar(volumes);
    if (window.__pinned && window.__pinned.restoreSidebar) window.__pinned.restoreSidebar();
    await paintWidgets(volumes);
    if (window.__pinned && window.__pinned.restoreQuickAccess) window.__pinned.restoreQuickAccess();
    window.__places.painted = true;
    return true;
  }
  window.__places = {paint: paintPlaces, painted: false};
