  function updateNavButtons(tab) {
    const nb = $("#nav-back"), nf = $("#nav-fwd");
    if (nb) nb.classList.toggle("off", tab.histIdx <= 0);
    if (nf) nf.classList.toggle("off", tab.histIdx >= tab.history.length - 1);
  }

  function updateCrumbUI(name, isHome) {
    renderBreadcrumbs(null, name, isHome);
  }

  function navigateTo(path, name, isHome, pushHistory = true) {
    const tab = tabs.find(t => t.id === activeTabId);
    if (!tab) return;
    const isH = (isHome !== undefined)
      ? !!isHome
      : (!path || window.__isHome(path));
    const cat = findCatalogEntry(path, isH);
    if (cat) {
      tab.path = cat.path;
      tab.name = cat.name || name || "Folder";
      tab.isHome = !!cat.isHome;
    } else {
      let pNorm = path || (isH ? window.__homePath() : "/");
      if (pNorm.startsWith("file://")) pNorm = pNorm.slice(7);
      while (pNorm.length > 1 && pNorm.endsWith("/")) pNorm = pNorm.slice(0, -1);
      tab.path = pNorm;
      tab.name = name || (isH ? "Home" : (pNorm.split("/").filter(Boolean).pop() || "Folder"));
      tab.isHome = isH;
    }

    if (pushHistory) {
      tab.history = tab.history.slice(0, tab.histIdx + 1);
      tab.history.push({ path: tab.path, name: tab.name, isHome: tab.isHome });
      tab.histIdx++;
    }

    if (tab.el) {
      const tn = tab.el.querySelector(".tname");
      if (tn) tn.textContent = tab.name;
      const ti = tab.el.querySelector(".tico");
      if (ti) {
        ti.replaceChildren();
        const artKey = tab.isHome ? "Home" : "Folder";
        const art = document.querySelector('#artlib [data-ico="' + artKey + '"] svg') ||
                    document.querySelector('#artlib [data-ico="Omnibar.Path"] svg');
        if (art) ti.appendChild(art.cloneNode(true));
      }
    }

    updateNavButtons(tab);

    const hw = $("#home-widgets");
    const views = $$(".grid, .rows, .list, .cards, .columns");
    if (tab.isHome) {
      if (hw) hw.hidden = false;
      views.forEach(v => { v.hidden = true; });
      renderBreadcrumbs(null, "~", true);
      updateSidebarActive("~", true);
      updateToolbarHomeGating(true);
      updateEmptyFolderIndicator(0, true);
      updateStatus();
    } else {
      if (hw) hw.hidden = true;
      renderTabDirectory(cat);
      renderBreadcrumbs(cat, tab.path, false);
      updateSidebarActive(tab.path, false);
      updateToolbarHomeGating(false);
      setLayout(tab.view || "grid");
      updateStatus();
    }
    hideOverlays();
  }

  function navigateActiveTab(path, name, isHome) {
    navigateTo(path, name, isHome, true);
  }

  function switchTab(id, forceRender = true) {
    const tab = tabs.find(t => t.id === id);
    if (!tab) return;
    activeTabId = id;
    tabs.forEach(t => {
      if (t.el) t.el.classList.toggle("active", t.id === id);
    });
    if (forceRender) {
      navigateTo(tab.path, tab.name, tab.isHome, false);
    } else {
      updateNavButtons(tab);
      updateSidebarActive(tab.path, tab.isHome);
      updateToolbarHomeGating(tab.isHome);
      if (tab.isHome) updateEmptyFolderIndicator(0, true);
    }
    updateDetails(null);
  }
  switchTab(activeTabId, false);

  function newTab(path, name, isHome, activate = true) {
    tabSeq++;
    const id = tabSeq;
    const isH = (isHome !== undefined)
      ? isHome
      : (!path || name === "Home" || window.__isHome(path));
    const tabName = name || (isH ? "Home" : "Folder");
    const tabPath = path || (isH ? "~" : "/");

    const tpl = $("#tpl-tab");
    let tabEl = null;
    if (tpl && tpl.content && tpl.content.firstElementChild) {
      tabEl = tpl.content.firstElementChild.cloneNode(true);
      tabEl.setAttribute("data-tab-id", String(id));
      const tn = tabEl.querySelector(".tname");
      if (tn) tn.textContent = tabName;
      const ti = tabEl.querySelector(".tico");
      if (ti) {
        const artKey = isH ? "Home" : "Folder";
        const art = document.querySelector('#artlib [data-ico="' + artKey + '"] svg') ||
                    document.querySelector('#artlib [data-ico="Omnibar.Path"] svg');
        if (art) ti.appendChild(art.cloneNode(true));
      }
      if (btnNewTab && btnNewTab.parentElement) {
        btnNewTab.parentElement.insertBefore(tabEl, btnNewTab);
      }
    }

    const newT = {
      id,
      name: tabName,
      path: tabPath,
      isHome: isH,
      el: tabEl,
      history: [{ name: tabName, path: tabPath, isHome: isH }],
      histIdx: 0,
      view: "grid",
      filter: "",
      sel: []
    };
    tabs.push(newT);
    if (activate) switchTab(id);
    return newT;
  }

  function closeTab(id, e) {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    const idx = tabs.findIndex(t => t.id === id);
    if (idx === -1) return;
    const tab = tabs[idx];
    if (tabs.length === 1) {
      navigateTo("~", "Home", true, false);
      tab.history = [{ name: "Home", path: "~", isHome: true }];
      tab.histIdx = 0;
      return;
    }
    if (tab.el && tab.el.parentElement) {
      tab.el.parentElement.removeChild(tab.el);
    }
    closedTabs.push({name: tab.name, path: tab.path, isHome: tab.isHome,
      at: idx});
    tabs.splice(idx, 1);
    if (activeTabId === id) {
      const nextTab = tabs[Math.min(idx, tabs.length - 1)];
      switchTab(nextTab.id);
    }
  }

  // The four tab commands that had a row in the menu and nothing behind it.
  // Reopen and Close to the right were answered by the tab strip's own
  // listener, which only ever saw a click on a row carrying a page action, so
  // neither worked from the palette or a shortcut; Close to the left and Move
  // to a new window were answered by nobody at all.
  const closedTabs = [];

  // Which tab the menu was opened over, or the one in front.
  function tabHere() {
    const said = (ctxTarget && ctxTarget.getAttribute)
      ? ctxTarget.getAttribute('data-tab-id') : null;
    return said ? parseInt(said, 10) : activeTabId;
  }

  function reopenClosedTab() {
    const last = closedTabs.pop();
    if (last) newTab(last.path, last.name, last.isHome, true);
  }

  function closeTabsToSide(id, way) {
    const at = tabs.findIndex(t => t.id === id);
    if (at < 0) return;
    const going = way < 0 ? tabs.slice(0, at) : tabs.slice(at + 1);
    //: Right to left, because closing one shortens the list under the next.
    going.reverse().forEach(t => closeTab(t.id));
  }

  function moveTabToNewWindow(id) {
    const tab = tabs.find(t => t.id === id);
    if (!tab) return;
    const opened = window.open(location.href, '_blank');
    if (opened && tabs.length > 1) closeTab(id);
  }

  function duplicateTab(id) {
    const orig = tabs.find(t => t.id === id);
    if (!orig) return;
    newTab(orig.path, orig.name, orig.isHome, true);
  }

  function closeOtherTabs(id) {
    const toClose = tabs.filter(t => t.id !== id);
    toClose.forEach(t => {
      if (t.el && t.el.parentElement) t.el.parentElement.removeChild(t.el);
    });
    tabs.splice(0, tabs.length, ...tabs.filter(t => t.id === id));
    switchTab(id);
  }

  function goNavBack() {
    const curTab = tabs.find(t => t.id === activeTabId);
    if (curTab && curTab.histIdx > 0) {
      curTab.histIdx--;
      const st = curTab.history[curTab.histIdx];
      navigateTo(st.path, st.name, st.isHome, false);
    }
  }

  function goNavForward() {
    const curTab = tabs.find(t => t.id === activeTabId);
    if (curTab && curTab.histIdx < curTab.history.length - 1) {
      curTab.histIdx++;
      const st = curTab.history[curTab.histIdx];
      navigateTo(st.path, st.name, st.isHome, false);
    }
  }

  function goNavUp() {
    const curTab = tabs.find(t => t.id === activeTabId);
    if (curTab && !curTab.isHome) {
      const cat = findCatalogEntry(curTab.path, false);
      if (cat && cat.crumbs && cat.crumbs.length > 1) {
        const parentCrumb = cat.crumbs[cat.crumbs.length - 2];
        let pName = parentCrumb[0], pPath = parentCrumb[1];
        if (pPath.startsWith("file://")) pPath = pPath.slice(7);
        const isH = (pName === "Home" || window.__isHome(pPath));
        navigateTo(pPath, pName, isH, true);
      } else {
        navigateTo("~", "Home", true, true);
      }
    }
  }
  let ctxTarget = null;
  // Half of the reference's rule cannot be applied when the menu is built.
  // `ContextMenuFlyoutItemViewModelBuilder` gives a row no visibility of its
  // own unless the factory states one, and then shows it only while the
  // command can run; a row the factory did state keeps its place and goes
  // grey. Both menus here are built from the whole list, so this is where a
  // row finds out which it is, every time the menu opens.
  function dressMenu(m) {
    m.querySelectorAll('[data-command]').forEach(row => {
      const c = COMMANDS.get(row.getAttribute('data-command'));
      if (!c) return;
      let can = true;
      try { can = !c.enabled || !!c.enabled(ctxTarget); } catch (err) { can = false; }
      const keep = row.hasAttribute('data-keep');
      row.hidden = !can && !keep;
      row.classList.toggle('dis', !can);
      if (c.unavailable) {
        row.classList.add('dis');
        row.title = c.unavailable;
      }
      const check = row.querySelector('.ck');
      if (check) {
        let on = false;
        try { on = !!(c.on && c.on()); } catch (err) { on = false; }
        check.classList.toggle('on', on);
      }
    });
    // Innermost first: a submenu whose every child has gone is itself gone,
    // and that can only be known after its children have been settled.
    const subs = Array.from(m.querySelectorAll('.mi-sub')).reverse();
    subs.forEach(sub => {
      const list = sub.querySelector('.ctx-sub');
      if (!list) return;
      const kids = Array.from(list.children).filter(
        k => !k.classList.contains('msep'));
      sub.hidden = !kids.some(k => !k.hidden);
      trimSeparators(list);
    });
    const bar = m.querySelector('.ctx-bar');
    if (bar) {
      const live = Array.from(bar.children).some(b => !b.hidden);
      bar.hidden = !live;
      if (bar.nextElementSibling &&
          bar.nextElementSibling.classList.contains('msep')) {
        bar.nextElementSibling.hidden = !live;
      }
    }
    trimSeparators(m);
  }

  // A separator earns its place by having something on both sides of it.
  // Files calls this AddSeparatorIfNeeded and asks the same question.
  function trimSeparators(list) {
    let seen = false;
    let run = null;
    Array.from(list.children).forEach(el => {
      if (el.classList.contains('ctx-bar')) {
        if (!el.hidden) { seen = true; run = null; }
        return;
      }
      if (el.classList.contains('msep')) {
        //: A separator standing in for the shell's own is not a separator
        //: this page draws. It keeps its place and stays out of sight.
        if (el.hasAttribute('data-slot')) return;
        el.hidden = !seen || run !== null;
        if (!el.hidden) run = el;
        return;
      }
      if (!el.hidden) { seen = true; run = null; }
    });
    if (run) run.hidden = true;
  }

  function openCtx(id, x, y) {
    hideOverlays();
    const m = document.getElementById(id);
    if (!m) return;
    dressMenu(m);
    m.hidden = false;
    const r = m.getBoundingClientRect();
    m.style.left = Math.max(8, Math.min(x, window.innerWidth - r.width - 8)) + 'px';
    m.style.top = Math.max(8, Math.min(y, window.innerHeight - r.height - 8)) + 'px';
  }
  function ctxHref() {
    if (!ctxTarget) return null;
    if (ctxTarget.getAttribute && ctxTarget.getAttribute('href'))
      return ctxTarget.getAttribute('href');
    const a = ctxTarget.querySelector ? ctxTarget.querySelector('a[href]') : null;
    return a ? a.getAttribute('href') : null;
  }
  window.__ctxData = (k) => ctxData(k);
  function ctxData(k) {
    if (!ctxTarget || !ctxTarget.getAttribute) return '';
    return ctxTarget.getAttribute(k) || '';
  }

