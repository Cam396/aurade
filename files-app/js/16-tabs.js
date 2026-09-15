  // =========================================================================
  // Wave A: Rock-Solid Multi-Tab System
  // =========================================================================
  (function() {
/**
 * Wave A: Tabs (P09) for AuraDE Files
 * WinUI 3 Fluent tabstrip controller and TabEngine implementation.
 *
 * Requirements:
 * 1. ZERO em dashes and ZERO en dashes.
 * 2. Strict Trusted Types: ZERO assignments to DOM injection sinks.
 * 3. String escaping safety: DO NOT use literal newlines in regex or strings.
 */

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    var engine = factory();
    root.TabEngine = engine;
    root.switchTab = engine.switchTab;
    root.newTab = engine.newTab;
    root.closeTab = engine.closeTab;
    root.duplicateTab = engine.duplicateTab;
    root.closeOtherTabs = engine.closeOtherTabs;
    root.closeTabsToRight = engine.closeTabsToRight;
    root.reopenClosedTab = engine.reopenClosedTab;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';

  /* ==========================================================================
     1. SVG Helpers (Strict Trusted Types compliant)
     ========================================================================== */

  function createSvg(width, height, viewBox) {
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('width', String(width));
    svg.setAttribute('height', String(height));
    svg.setAttribute('viewBox', viewBox || ('0 0 ' + width + ' ' + height));
    svg.setAttribute('aria-hidden', 'true');
    return svg;
  }

  function createSvgPath(d, fill, stroke, strokeWidth, lineCap, lineJoin) {
    var p = document.createElementNS(SVG_NS, 'path');
    p.setAttribute('d', d);
    if (fill) p.setAttribute('fill', fill);
    else p.setAttribute('fill', 'none');
    if (stroke) p.setAttribute('stroke', stroke);
    if (strokeWidth) p.setAttribute('stroke-width', String(strokeWidth));
    if (lineCap) p.setAttribute('stroke-linecap', lineCap);
    if (lineJoin) p.setAttribute('stroke-linejoin', lineJoin);
    return p;
  }

  function createCloseSvg() {
    var svg = createSvg(10, 10, '0 0 10 10');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1');
    var p = createSvgPath('M1 1l8 8M9 1L1 9');
    svg.appendChild(p);
    return svg;
  }

  function createHomeSvg() {
    var art = document.querySelector('#artlib [data-ico="Omnibar.Path"] svg') ||
              document.querySelector('#artlib [data-ico="Home"] svg');
    if (art) return art.cloneNode(true);
    var svg = createSvg(16, 16, '0 0 16 16');
    var p = createSvgPath(
      'M8.52 1.72a.82.82 0 0 0-1.04 0L1.86 6.36a1.05 1.05 0 0 0-.39.81v5.98A1.35 1.35 0 0 0 2.82 14.5h2.63V9.98a.86.86 0 0 1 .86-.86h3.38a.86.86 0 0 1 .86.86V14.5h2.63a1.35 1.35 0 0 0 1.35-1.35V7.17a1.05 1.05 0 0 0-.39-.81z',
      'var(--tab-accent, #0078d4)'
    );
    svg.appendChild(p);
    return svg;
  }

  function createFolderSvg() {
    var art = document.querySelector('#artlib [data-ico="Folder"] svg');
    if (art) return art.cloneNode(true);
    var svg = createSvg(16, 16, '0 0 16 16');
    var p1 = createSvgPath('m7.5,2.5l-1.71,1.71c-.19.19-.44.29-.71.29H.5v6c0,1.1.9,2,2,2h3.59c-.06-.32-.09-.66-.09-1,0-3.04,2.46-5.5,5.5-5.5,1.11,0,2.14.33,3,.89v-2.39c0-1.1-.9-2-2-2h-5Z', 'var(--ico-alt, #fce100)');
    var p2 = createSvgPath('m5.79.79l1.71,1.71-1.71,1.71c-.19.19-.44.29-.71.29H.5v-2C.5,1.4,1.4.5,2.5.5h2.59c.27,0,.52.11.71.29Z', 'var(--ico-base, #e5b900)');
    svg.appendChild(p1);
    svg.appendChild(p2);
    return svg;
  }

  function updateTabIcon(tabEl, isHome) {
    if (!tabEl) return;
    var ti = tabEl.querySelector('.tico');
    if (!ti) return;
    ti.replaceChildren();
    if (isHome) {
      ti.appendChild(createHomeSvg());
    } else {
      ti.appendChild(createFolderSvg());
    }
  }

  /* ==========================================================================
     2. Tab State Storage and Schema
     ========================================================================== */

  var tabs = [];
  var activeTabId = 1;
  var tabSeq = 1;
  var recentlyClosedTabs = []; // LIFO stack, max 25
  var MAX_RECENTLY_CLOSED = 25;

  var dragSourceTabId = null;
  var tabHoverTimer = null;
  var tabHoverTargetId = null;
  var ctxTargetTabId = null;

  function pushRecentlyClosed(tab) {
    if (!tab) return;
    var copy = {
      name: tab.name,
      path: tab.path,
      isHome: tab.isHome,
      view: tab.view,
      scrollTop: tab.scrollTop,
      selectedPaths: new Set(tab.selectedPaths || []),
      leadSelectedPath: tab.leadSelectedPath,
      history: (tab.history || []).map(function (h) {
        return { path: h.path, name: h.name, isHome: h.isHome };
      }),
      histIdx: tab.histIdx,
      filterQuery: tab.filterQuery || '',
      searchActive: !!tab.searchActive,
      dualPaneState: tab.dualPaneState ? Object.assign({}, tab.dualPaneState) : null
    };
    recentlyClosedTabs.push(copy);
    if (recentlyClosedTabs.length > MAX_RECENTLY_CLOSED) {
      recentlyClosedTabs.shift();
    }
  }

  function clearTabHoverTimer() {
    if (tabHoverTimer) {
      clearTimeout(tabHoverTimer);
      tabHoverTimer = null;
    }
    tabHoverTargetId = null;
  }

  /* ==========================================================================
     3. State Capture and Restoration
     ========================================================================== */

  function saveTabState(tab) {
    if (!tab) return;
    var fileArea = document.getElementById('filearea');
    if (fileArea) {
      tab.scrollTop = fileArea.scrollTop;
    }

    var selSet = new Set();
    var leadPath = null;
    var selEls = document.querySelectorAll('#filearea .sel, .content .sel, .dbody .sel, .grid .sel');
    for (var i = 0; i < selEls.length; i++) {
      var el = selEls[i];
      var p = el.getAttribute('data-p') || el.getAttribute('data-path') || el.getAttribute('data-n');
      if (p) {
        selSet.add(p);
        if (i === selEls.length - 1) leadPath = p;
      }
    }
    tab.selectedPaths = selSet;
    tab.leadSelectedPath = leadPath;

    if (typeof window.__mode === 'function') {
      tab.view = window.__mode();
    } else if (typeof window.__currentLayout === 'string') {
      tab.view = window.__currentLayout;
    } else if (document.documentElement && document.documentElement.dataset && document.documentElement.dataset.layout) {
      tab.view = document.documentElement.dataset.layout;
    } else {
      tab.view = 'grid';
    }

    var osearch = document.getElementById('osearch');
    var fquery = document.getElementById('f-query') || document.getElementById('finput') || document.querySelector('.frow input');
    if (osearch && !osearch.hidden) {
      tab.filterQuery = osearch.value || '';
      tab.searchActive = true;
    } else if (fquery && fquery.value) {
      tab.filterQuery = fquery.value || '';
      tab.searchActive = false;
    } else {
      tab.filterQuery = '';
      tab.searchActive = false;
    }

    if (window.__dualPane && typeof window.__dualPane.isDualPaneActive === 'function') {
      tab.dualPaneState = {
        active: window.__dualPane.isDualPaneActive(),
        activePane: (typeof window.__dualPane.getActivePane === 'function') ? window.__dualPane.getActivePane() : 'left'
      };
    }
  }

  function restoreTabState(tab) {
    if (!tab) return;

    // 1. Navigation / View rendering
    if (typeof window.navigateTo === 'function') {
      window.navigateTo(tab.path, tab.name, tab.isHome, false);
    } else {
      var hw = document.getElementById('home-widgets');
      var views = document.querySelectorAll('.grid, .rows, .list, .cards, .columns');
      if (tab.isHome) {
        if (hw) hw.hidden = false;
        views.forEach(function (v) { v.hidden = true; });
      } else {
        if (hw) hw.hidden = true;
        views.forEach(function (v) { v.hidden = false; });
      }
    }

    // 2. Layout / View mode
    if (tab.view) {
      if (typeof window.__setLayout === 'function') {
        window.__setLayout(tab.view);
      } else if (typeof window.setLayout === 'function') {
        window.setLayout(tab.view);
      }
    }

    // 3. Scroll position restoration on #filearea
    var fileArea = document.getElementById('filearea');
    if (fileArea) {
      fileArea.scrollTop = tab.scrollTop || 0;
      requestAnimationFrame(function () {
        if (fileArea) fileArea.scrollTop = tab.scrollTop || 0;
      });
      setTimeout(function () {
        if (fileArea) fileArea.scrollTop = tab.scrollTop || 0;
      }, 0);
    }

    // 4. Selections restoration
    var items = document.querySelectorAll('#filearea .cell, #filearea .row, #filearea .lrow, #filearea .crow, #filearea .tile, .content .cell, .content .row, .grid .cell, .dbody .row');
    var leadEl = null;
    items.forEach(function (item) {
      var p = item.getAttribute('data-p') || item.getAttribute('data-path') || item.getAttribute('data-n');
      if (p && tab.selectedPaths && tab.selectedPaths.has(p)) {
        item.classList.add('sel');
        if (p === tab.leadSelectedPath) leadEl = item;
      } else {
        item.classList.remove('sel');
      }
    });

    if (typeof window.updateStatus === 'function') {
      window.updateStatus();
    }

    if (typeof window.updateDetails === 'function') {
      window.updateDetails(leadEl);
    }

    // 5. Search / Filter query
    var osearch = document.getElementById('osearch');
    var crumbs = document.getElementById('crumbs');
    var btnSearch = document.getElementById('btn-search');
    var finput = document.getElementById('finput') || document.getElementById('f-query') || document.querySelector('.frow input');

    if (tab.searchActive && tab.filterQuery) {
      if (osearch) {
        osearch.hidden = false;
        osearch.value = tab.filterQuery;
        if (crumbs) crumbs.hidden = true;
        if (btnSearch) btnSearch.setAttribute('aria-pressed', 'true');
        osearch.dispatchEvent(new Event('input', { bubbles: true }));
      }
    } else if (tab.filterQuery && finput) {
      finput.value = tab.filterQuery;
      if (osearch) {
        osearch.hidden = true;
        osearch.value = '';
        if (crumbs) crumbs.hidden = false;
        if (btnSearch) btnSearch.setAttribute('aria-pressed', 'false');
      }
      finput.dispatchEvent(new Event('input', { bubbles: true }));
    } else {
      if (osearch) {
        osearch.hidden = true;
        osearch.value = '';
        if (crumbs) crumbs.hidden = false;
        if (btnSearch) btnSearch.setAttribute('aria-pressed', 'false');
      }
      if (finput) {
        finput.value = '';
      }
    }

    if (typeof window.applyFilter === 'function') {
      window.applyFilter();
    }

    // 6. Dual pane state restoration
    if (tab.dualPaneState && window.__dualPane) {
      var currentDual = window.__dualPane.isDualPaneActive();
      if (tab.dualPaneState.active && !currentDual) {
        if (typeof window.__dualPane.toggleDualPane === 'function') window.__dualPane.toggleDualPane();
      } else if (!tab.dualPaneState.active && currentDual) {
        if (typeof window.__dualPane.closeSecondaryPane === 'function') window.__dualPane.closeSecondaryPane();
      }
    }

    updateNavButtons(tab);
  }

  function updateNavButtons(tab) {
    var nb = document.getElementById('nav-back');
    var nf = document.getElementById('nav-fwd');
    if (nb) nb.classList.toggle('off', !tab || tab.histIdx <= 0);
    if (nf) nf.classList.toggle('off', !tab || tab.histIdx >= tab.history.length - 1);
  }

  /* ==========================================================================
     4. Tab DOM Element Construction and Listeners
     ========================================================================== */

  function attachTabElementListeners(tabEl, tab) {
    tabEl.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      if (e.target.closest('.x')) {
        closeTab(tab.id);
        return;
      }
      switchTab(tab.id);
    }, true);

    tabEl.addEventListener('auxclick', function (e) {
      if (e.button === 1) {
        e.preventDefault();
        e.stopPropagation();
        closeTab(tab.id);
      }
    });

    tabEl.addEventListener('contextmenu', function (e) {
      e.preventDefault();
      e.stopPropagation();
      openTabContextMenu(tab.id, e.clientX, e.clientY);
    });

    tabEl.addEventListener('dragstart', function (e) {
      if (e.target.closest('.x')) {
        e.preventDefault();
        return;
      }
      dragSourceTabId = tab.id;
      tabEl.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      try {
        e.dataTransfer.setData('application/x-aurade-tab', String(tab.id));
        e.dataTransfer.setData('text/plain', String(tab.id));
      } catch (err) {
        // Ignore
      }
    });

    tabEl.addEventListener('dragover', function (e) {
      e.preventDefault();

      if (dragSourceTabId !== null) {
        e.dataTransfer.dropEffect = 'move';
        var rect = tabEl.getBoundingClientRect();
        var isRight = e.clientX > (rect.left + rect.width / 2);
        tabEl.classList.toggle('drag-over-right', isRight);
        tabEl.classList.toggle('drag-over-left', !isRight);
      } else {
        // File hover activation (500ms)
        if (tab.id !== activeTabId) {
          if (tabHoverTargetId !== tab.id) {
            clearTabHoverTimer();
            tabHoverTargetId = tab.id;
            tabHoverTimer = setTimeout(function () {
              if (tabHoverTargetId === tab.id && tab.id !== activeTabId) {
                switchTab(tab.id);
              }
            }, 500);
          }
        }
      }
    });

    tabEl.addEventListener('dragleave', function () {
      tabEl.classList.remove('drag-over-left', 'drag-over-right');
      if (tabHoverTargetId === tab.id) {
        clearTabHoverTimer();
      }
    });

    tabEl.addEventListener('drop', function (e) {
      e.preventDefault();
      tabEl.classList.remove('drag-over-left', 'drag-over-right');
      clearTabHoverTimer();

      var sourceId = dragSourceTabId;
      if (sourceId === null) {
        try {
          var raw = e.dataTransfer.getData('application/x-aurade-tab') || e.dataTransfer.getData('text/plain');
          if (raw) sourceId = parseInt(raw, 10);
        } catch (err) {
          // Ignore
        }
      }

      if (sourceId !== null && !isNaN(sourceId) && sourceId !== tab.id) {
        var rect = tabEl.getBoundingClientRect();
        var insertAfter = e.clientX > (rect.left + rect.width / 2);
        reorderTab(sourceId, tab.id, insertAfter);
      }
      dragSourceTabId = null;
    });

    tabEl.addEventListener('dragend', function () {
      tabEl.classList.remove('dragging', 'drag-over-left', 'drag-over-right');
      dragSourceTabId = null;
      clearTabHoverTimer();
      document.querySelectorAll('.tab').forEach(function (el) {
        el.classList.remove('dragging', 'drag-over-left', 'drag-over-right');
      });
    });
  }

  function createTabElement(tab) {
    var tabEl = document.createElement('div');
    tabEl.className = 'tab' + (tab.id === activeTabId ? ' active' : '');
    tabEl.setAttribute('data-tab-id', String(tab.id));
    tabEl.setAttribute('tabindex', '-1');
    tabEl.setAttribute('draggable', 'true');
    tabEl.setAttribute('title', tab.name);

    var ti = document.createElement('span');
    ti.className = 'tico';
    if (tab.isHome) {
      ti.appendChild(createHomeSvg());
    } else {
      ti.appendChild(createFolderSvg());
    }
    tabEl.appendChild(ti);

    var tn = document.createElement('span');
    tn.className = 'tname';
    tn.textContent = tab.name;
    tn.setAttribute('title', tab.name);
    tabEl.appendChild(tn);

    var x = document.createElement('span');
    x.className = 'x';
    x.setAttribute('title', 'Close tab (Ctrl+W)');
    x.appendChild(createCloseSvg());
    tabEl.appendChild(x);

    attachTabElementListeners(tabEl, tab);
    return tabEl;
  }

  /* ==========================================================================
     5. Context Menu (#ctx-tab)
     ========================================================================== */

  function ensureTabContextMenu() {
    var ctx = document.getElementById('ctx-tab');
    if (!ctx) {
      ctx = document.createElement('div');
      ctx.id = 'ctx-tab';
      ctx.className = 'ctx';
      ctx.hidden = true;
      document.body.appendChild(ctx);
    } else if (ctx.__tabEngineAttached) {
      var cleanCtx = ctx.cloneNode(false);
      if (ctx.parentNode) {
        ctx.parentNode.replaceChild(cleanCtx, ctx);
        ctx = cleanCtx;
      }
    }

    // The rows used to be built here, by looking for a page action on each
    // and appending one when it was not found. `#ctx-tab` is generated from
    // assets/files-menus.json now and its rows carry the reference's command
    // names, so every lookup missed and six duplicate rows with placeholder
    // squares for icons were appended under the seven real ones.

    if (!ctx.__tabEngineAttached) {
      ctx.__tabEngineAttached = true;
      ctx.addEventListener('click', function (e) {
        var mi = e.target.closest('.mi');
        if (!mi || mi.classList.contains('disabled')) return;
        var act = mi.getAttribute('data-act');
        hideTabContextMenu();
        var targetId = ctxTargetTabId || activeTabId;
        if (act === 'tab-new') {
          newTab('~', 'Home', true, true);
        } else if (act === 'tab-dup') {
          duplicateTab(targetId);
        } else if (act === 'tab-reopen') {
          reopenClosedTab();
        } else if (act === 'tab-close') {
          closeTab(targetId);
        } else if (act === 'tab-close-others') {
          closeOtherTabs(targetId);
        } else if (act === 'tab-close-right') {
          closeTabsToRight(targetId);
        }
      });
    }
  }

  function openTabContextMenu(tabId, x, y) {
    ensureTabContextMenu();
    var ctx = document.getElementById('ctx-tab');
    if (!ctx) return;

    ctxTargetTabId = tabId;
    var idx = tabs.findIndex(function (t) { return t.id === tabId; });

    var miCloseOthers = ctx.querySelector('.mi[data-act="tab-close-others"]');
    if (miCloseOthers) {
      miCloseOthers.classList.toggle('disabled', tabs.length <= 1);
    }

    var miCloseRight = ctx.querySelector('.mi[data-act="tab-close-right"]');
    if (miCloseRight) {
      miCloseRight.classList.toggle('disabled', idx === -1 || idx >= tabs.length - 1);
    }

    var miReopen = ctx.querySelector('.mi[data-act="tab-reopen"]');
    if (miReopen) {
      miReopen.classList.toggle('disabled', recentlyClosedTabs.length === 0);
    }

    ctx.hidden = false;
    var rect = ctx.getBoundingClientRect();
    var posX = Math.max(8, Math.min(x, window.innerWidth - rect.width - 8));
    var posY = Math.max(8, Math.min(y, window.innerHeight - rect.height - 8));
    ctx.style.left = posX + 'px';
    ctx.style.top = posY + 'px';
  }

  function hideTabContextMenu() {
    var ctx = document.getElementById('ctx-tab');
    if (ctx) ctx.hidden = true;
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest('#ctx-tab')) {
      hideTabContextMenu();
    }
  });

  /* ==========================================================================
     6. Navigation Hooking
     ========================================================================== */

  function hookWindowNavigateTo() {
    if (typeof window.navigateTo === 'function') {
      var originalNavigateTo = window.navigateTo.__tabEngineOriginal || window.navigateTo;
      var wrapped = function (path, name, isHome, pushHistory) {
        var curTab = getActiveTab();
        if (curTab) {
          curTab.path = path;
          if (name) curTab.name = name;
          if (isHome !== undefined) curTab.isHome = !!isHome;
          var shouldPush = (pushHistory !== undefined) ? !!pushHistory : true;
          if (shouldPush) {
            curTab.history = curTab.history.slice(0, curTab.histIdx + 1);
            curTab.history.push({ path: curTab.path, name: curTab.name, isHome: curTab.isHome });
            curTab.histIdx++;
          }
          if (curTab.el) {
            var tn = curTab.el.querySelector('.tname');
            if (tn && curTab.name) {
              tn.textContent = curTab.name;
              tn.setAttribute('title', curTab.name);
            }
            curTab.el.setAttribute('title', curTab.name);
            updateTabIcon(curTab.el, curTab.isHome);
          }
          const liveTn = document.querySelector('.tab.active .tname') || document.querySelector('.tname');
          if (liveTn && curTab.name) liveTn.textContent = curTab.name;
          updateNavButtons(curTab);
        }
        var ret = originalNavigateTo.apply(this, arguments);
        if (curTab) {
          const liveTn = document.querySelector('.tab.active .tname') || document.querySelector('.tname');
          if (liveTn && curTab.name) liveTn.textContent = curTab.name;
        }
        return ret;
      };
      wrapped.__tabEngineWrapped = true;
      wrapped.__tabEngineOriginal = originalNavigateTo;
      window.navigateTo = wrapped;
    }
  }

  /* ==========================================================================
     7. Core TabEngine Methods
     ========================================================================== */

  function newTab(path, name, isHome, activate) {
    if (activate === undefined) activate = true;
    tabSeq++;
    var id = tabSeq;
    var isH = (isHome !== undefined)
      ? !!isHome
      : (!path || name === 'Home' || window.__isHome(path));
    var tabName = name || (isH ? 'Home' : (path ? path.split('/').filter(Boolean).pop() : 'Folder')) || 'Folder';
    var tabPath = path || (isH ? '~' : '/');

    var currentView = 'grid';
    if (typeof window.__mode === 'function') {
      currentView = window.__mode();
    } else if (typeof window.__currentLayout === 'string') {
      currentView = window.__currentLayout;
    } else if (document.documentElement && document.documentElement.dataset && document.documentElement.dataset.layout) {
      currentView = document.documentElement.dataset.layout;
    }

    var tabObj = {
      id: id,
      name: tabName,
      path: tabPath,
      isHome: isH,
      view: currentView,
      scrollTop: 0,
      selectedPaths: new Set(),
      leadSelectedPath: null,
      history: [{ path: tabPath, name: tabName, isHome: isH }],
      histIdx: 0,
      filterQuery: '',
      searchActive: false,
      dualPaneState: null,
      el: null
    };

    var tabEl = createTabElement(tabObj);
    tabObj.el = tabEl;

    var tabstrip = document.getElementById('tabstrip');
    var btnNewTab = document.getElementById('btn-newtab');
    if (tabstrip) {
      if (btnNewTab && btnNewTab.parentElement === tabstrip) {
        tabstrip.insertBefore(tabEl, btnNewTab);
      } else {
        tabstrip.appendChild(tabEl);
      }
    }

    tabs.push(tabObj);

    if (activate) {
      switchTab(id);
    }

    return tabObj;
  }

  function switchTab(id) {
    var nextTab = tabs.find(function (t) { return t.id === id; });
    if (!nextTab) return;

    if (activeTabId && activeTabId !== id) {
      var curTab = tabs.find(function (t) { return t.id === activeTabId; });
      if (curTab) {
        saveTabState(curTab);
      }
    }

    activeTabId = id;

    tabs.forEach(function (t) {
      if (t.el) {
        t.el.classList.toggle('active', t.id === id);
      }
    });

    restoreTabState(nextTab);

    var curTab = getActiveTab();
    const liveTn = document.querySelector('.tab.active .tname') || document.querySelector('.tname');
    if (liveTn && curTab && curTab.name) liveTn.textContent = curTab.name;

    if (nextTab.el && typeof nextTab.el.scrollIntoView === 'function') {
      try {
        nextTab.el.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
      } catch (err) {
        // Ignore
      }
    }
  }

  function closeTab(id) {
    var idx = tabs.findIndex(function (t) { return t.id === id; });
    if (idx === -1) return;
    var tab = tabs[idx];

    if (tab.id === activeTabId) {
      saveTabState(tab);
    }

    if (tabs.length === 1) {
      tab.isHome = true;
      tab.name = 'Home';
      tab.path = '~';
      tab.history = [{ path: '~', name: 'Home', isHome: true }];
      tab.histIdx = 0;
      tab.scrollTop = 0;
      tab.selectedPaths.clear();
      tab.leadSelectedPath = null;
      tab.filterQuery = '';
      tab.searchActive = false;
      tab.dualPaneState = null;
      if (tab.el) {
        var tn = tab.el.querySelector('.tname');
        if (tn) tn.textContent = 'Home';
        tab.el.setAttribute('title', 'Home');
        updateTabIcon(tab.el, true);
      }
      if (typeof window.navigateTo === 'function') {
        window.navigateTo('~', 'Home', true, false);
      }
      switchTab(tab.id);
      return;
    }

    pushRecentlyClosed(tab);

    if (tab.el && tab.el.parentElement) {
      tab.el.parentElement.removeChild(tab.el);
    }

    tabs.splice(idx, 1);

    if (activeTabId === id) {
      var nextIdx = Math.min(idx, tabs.length - 1);
      switchTab(tabs[nextIdx].id);
    }
  }

  function closeOtherTabs(id) {
    var remainingTab = tabs.find(function (t) { return t.id === id; });
    if (!remainingTab) return;

    var curTab = tabs.find(function (t) { return t.id === activeTabId; });
    if (curTab) {
      saveTabState(curTab);
    }

    var toClose = tabs.filter(function (t) { return t.id !== id; });
    toClose.forEach(function (t) {
      pushRecentlyClosed(t);
      if (t.el && t.el.parentElement) {
        t.el.parentElement.removeChild(t.el);
      }
    });

    tabs = [remainingTab];
    if (activeTabId !== id) {
      switchTab(id);
    }
  }

  function closeTabsToRight(id) {
    var idx = tabs.findIndex(function (t) { return t.id === id; });
    if (idx === -1 || idx === tabs.length - 1) return;

    var curTab = tabs.find(function (t) { return t.id === activeTabId; });
    if (curTab) {
      saveTabState(curTab);
    }

    var toClose = tabs.slice(idx + 1);
    toClose.forEach(function (t) {
      pushRecentlyClosed(t);
      if (t.el && t.el.parentElement) {
        t.el.parentElement.removeChild(t.el);
      }
    });

    var activeWasClosed = toClose.some(function (t) { return t.id === activeTabId; });
    tabs = tabs.slice(0, idx + 1);

    if (activeWasClosed) {
      switchTab(id);
    }
  }

  function duplicateTab(id) {
    var origTab = tabs.find(function (t) { return t.id === id; });
    if (!origTab) return null;
    if (origTab.id === activeTabId) {
      saveTabState(origTab);
    }
    var idx = tabs.indexOf(origTab);

    tabSeq++;
    var newId = tabSeq;

    var dupObj = {
      id: newId,
      name: origTab.name,
      path: origTab.path,
      isHome: origTab.isHome,
      view: origTab.view || 'grid',
      scrollTop: origTab.scrollTop || 0,
      selectedPaths: new Set(origTab.selectedPaths),
      leadSelectedPath: origTab.leadSelectedPath,
      history: origTab.history.map(function (h) {
        return { path: h.path, name: h.name, isHome: h.isHome };
      }),
      histIdx: origTab.histIdx,
      filterQuery: origTab.filterQuery || '',
      searchActive: origTab.searchActive || false,
      dualPaneState: origTab.dualPaneState ? Object.assign({}, origTab.dualPaneState) : null,
      el: null
    };

    var tabEl = createTabElement(dupObj);
    dupObj.el = tabEl;

    tabs.splice(idx + 1, 0, dupObj);

    if (origTab.el && origTab.el.parentElement) {
      if (origTab.el.nextSibling) {
        origTab.el.parentElement.insertBefore(tabEl, origTab.el.nextSibling);
      } else {
        origTab.el.parentElement.appendChild(tabEl);
      }
    }

    switchTab(newId);
    return dupObj;
  }

  function reopenClosedTab() {
    if (recentlyClosedTabs.length === 0) return null;
    var state = recentlyClosedTabs.pop();

    tabSeq++;
    var newId = tabSeq;

    var restoredObj = {
      id: newId,
      name: state.name,
      path: state.path,
      isHome: state.isHome,
      view: state.view || 'grid',
      scrollTop: state.scrollTop || 0,
      selectedPaths: new Set(state.selectedPaths),
      leadSelectedPath: state.leadSelectedPath,
      history: (state.history && state.history.length > 0)
        ? state.history.map(function (h) { return { path: h.path, name: h.name, isHome: h.isHome }; })
        : [{ path: state.path, name: state.name, isHome: state.isHome }],
      histIdx: state.histIdx || 0,
      filterQuery: state.filterQuery || '',
      searchActive: state.searchActive || false,
      dualPaneState: state.dualPaneState ? Object.assign({}, state.dualPaneState) : null,
      el: null
    };

    var tabEl = createTabElement(restoredObj);
    restoredObj.el = tabEl;

    var tabstrip = document.getElementById('tabstrip');
    var btnNewTab = document.getElementById('btn-newtab');
    if (tabstrip) {
      if (btnNewTab && btnNewTab.parentElement === tabstrip) {
        tabstrip.insertBefore(tabEl, btnNewTab);
      } else {
        tabstrip.appendChild(tabEl);
      }
    }

    tabs.push(restoredObj);
    switchTab(newId);
    return restoredObj;
  }

  function reorderTab(sourceId, targetId, insertAfter) {
    if (sourceId === targetId) return false;
    var srcIdx = tabs.findIndex(function (t) { return t.id === sourceId; });
    var tgtIdx = tabs.findIndex(function (t) { return t.id === targetId; });
    if (srcIdx === -1 || tgtIdx === -1) return false;

    var srcTab = tabs[srcIdx];
    var tgtTab = tabs[tgtIdx];

    if (srcTab.el && tgtTab.el && tgtTab.el.parentElement) {
      var parent = tgtTab.el.parentElement;
      if (insertAfter) {
        if (tgtTab.el.nextSibling) {
          parent.insertBefore(srcTab.el, tgtTab.el.nextSibling);
        } else {
          parent.appendChild(srcTab.el);
        }
      } else {
        parent.insertBefore(srcTab.el, tgtTab.el);
      }
    }

    tabs.splice(srcIdx, 1);
    var newTgtIdx = tabs.findIndex(function (t) { return t.id === targetId; });
    var insertAt = insertAfter ? newTgtIdx + 1 : newTgtIdx;
    tabs.splice(insertAt, 0, srcTab);

    return true;
  }

  function getActiveTab() {
    return tabs.find(function (t) { return t.id === activeTabId; }) || null;
  }

  /* ==========================================================================
     8. Event Handlers (Middle-click, Keyboard Shortcuts, New Tab Button)
     ========================================================================== */

  function handleFolderMiddleClick(e, explicitTarget) {
    if (e.button !== 1) return;
    var target = explicitTarget || e.target;
    if (!target || typeof target.closest !== 'function') return;
    var folderEl = target.closest(
      '.wcard-folder, [data-k="Folder"], [data-kind="folder"], .cell[data-k="Folder"], .row[data-k="Folder"], .srow[data-k="Folder"]'
    );
    if (!folderEl) {
      var candidate = target.closest('.cell, .row, .srow, .tile');
      if (candidate) {
        var kind = candidate.getAttribute('data-k') || candidate.getAttribute('data-kind');
        if (kind && kind.toLowerCase().indexOf('folder') !== -1) {
          folderEl = candidate;
        }
      }
    }

    if (folderEl) {
      e.preventDefault();
      e.stopPropagation();
      var p = folderEl.getAttribute('data-p') || folderEl.getAttribute('data-path');
      var n = folderEl.getAttribute('data-n') || folderEl.getAttribute('data-name');
      if (!n) {
        var nameEl = folderEl.querySelector('.cname, .rname, .lname, .wcard-title');
        if (nameEl) n = nameEl.textContent.trim();
      }
      if (p) {
        newTab(p, n || 'Folder', false, false);
      }
    }
  }

  function attachFolderMiddleClickListener() {
    document.addEventListener('auxclick', handleFolderMiddleClick, true);

    document.addEventListener('mousedown', function (e) {
      if (e.button === 1) {
        var folderEl = e.target.closest(
          '.wcard-folder, [data-k="Folder"], [data-kind="folder"], .cell[data-k="Folder"], .row[data-k="Folder"]'
        );
        if (folderEl) {
          e.preventDefault();
        }
      }
    });

    window.__activeFolderMiddleClick = handleFolderMiddleClick;
    if (!EventTarget.prototype.__tabEngineAuxDispatchHooked) {
      EventTarget.prototype.__tabEngineAuxDispatchHooked = true;
      var origEventTargetDispatch = EventTarget.prototype.dispatchEvent;
      EventTarget.prototype.dispatchEvent = function (e) {
        if (e && e.type === 'auxclick' && e.button === 1 && typeof window.__activeFolderMiddleClick === 'function') {
          window.__activeFolderMiddleClick(e, this);
          if (e.defaultPrevented) return false;
        }
        return origEventTargetDispatch.apply(this, arguments);
      };
    }
  }

  function handleKeyboardShortcut(e) {
    var isCtrl = e.ctrlKey || e.metaKey;
    if (!isCtrl) return;

    if (e.shiftKey && (e.key === 'T' || e.key === 't')) {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      reopenClosedTab();
      return;
    }

    if (!e.shiftKey && (e.key === 't' || e.key === 'T')) {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      newTab('~', 'Home', true, true);
      return;
    }

    if (!e.shiftKey && (e.key === 'w' || e.key === 'W')) {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      closeTab(activeTabId);
      return;
    }

    if (e.key === 'Tab') {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      if (tabs.length <= 1) return;
      var curIdx = tabs.findIndex(function (t) { return t.id === activeTabId; });
      if (curIdx === -1) curIdx = 0;
      var step = e.shiftKey ? -1 : 1;
      var nextIdx = (curIdx + step + tabs.length) % tabs.length;
      switchTab(tabs[nextIdx].id);
      return;
    }

    if (e.key === 'PageDown') {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      if (tabs.length <= 1) return;
      var cIdx = tabs.findIndex(function (t) { return t.id === activeTabId; });
      if (cIdx === -1) cIdx = 0;
      var nIdx = (cIdx + 1) % tabs.length;
      switchTab(tabs[nIdx].id);
      return;
    }

    if (e.key === 'PageUp') {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      if (tabs.length <= 1) return;
      var cuIdx = tabs.findIndex(function (t) { return t.id === activeTabId; });
      if (cuIdx === -1) cuIdx = 0;
      var prIdx = (cuIdx - 1 + tabs.length) % tabs.length;
      switchTab(tabs[prIdx].id);
      return;
    }

    if (!e.shiftKey && e.key >= '1' && e.key <= '8') {
      var targetIdx = parseInt(e.key, 10) - 1;
      if (targetIdx < tabs.length) {
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        switchTab(tabs[targetIdx].id);
      }
      return;
    }

    if (!e.shiftKey && e.key === '9') {
      if (tabs.length > 0) {
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        switchTab(tabs[tabs.length - 1].id);
      }
      return;
    }
  }

  function attachKeyboardShortcuts() {
    window.addEventListener('keydown', handleKeyboardShortcut, true);

    window.__activeTabEngineKeydown = handleKeyboardShortcut;
    if (!window.__tabEngineDispatchHooked) {
      window.__tabEngineDispatchHooked = true;
      var originalDispatch = window.dispatchEvent;
      window.dispatchEvent = function (e) {
        if (e && e.type === 'keydown' && typeof window.__activeTabEngineKeydown === 'function') {
          window.__activeTabEngineKeydown(e);
          if (e.defaultPrevented) {
            return false;
          }
        }
        return originalDispatch.apply(this, arguments);
      };
    }
  }

  function attachNewTabButton() {
    var btn = document.getElementById('btn-newtab');
    if (btn) {
      btn.__tabEngineAttached = true;
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        newTab('~', 'Home', true, true);
      }, true);
    }
  }

  /* ==========================================================================
     9. Initial Setup and DOM Preservation
     ========================================================================== */

  function initTabsFromDOM() {
    var tabstrip = document.getElementById('tabstrip');
    if (!tabstrip) return;

    if (tabstrip.__tabstripEngineAttached) {
      var cloned = tabstrip.cloneNode(true);
      if (tabstrip.parentNode) {
        tabstrip.parentNode.replaceChild(cloned, tabstrip);
        tabstrip = cloned;
      }
    }

    tabstrip.__tabstripEngineAttached = true;
    tabstrip.addEventListener('click', function (e) {
        var closeBtn = e.target.closest('.x');
        if (closeBtn) {
          var tEl = closeBtn.closest('.tab');
          if (tEl) {
            var rawId = tEl.getAttribute('data-tab-id');
            var id = rawId ? parseInt(rawId, 10) : null;
            if (id !== null) {
              e.preventDefault();
              e.stopPropagation();
              e.stopImmediatePropagation();
              closeTab(id);
              return;
            }
          }
        }
        var newBtn = e.target.closest('#btn-newtab, .newtab');
        if (newBtn) {
          e.preventDefault();
          e.stopPropagation();
          e.stopImmediatePropagation();
          newTab('~', 'Home', true, true);
          return;
        }
        var tabEl = e.target.closest('.tab');
        if (tabEl) {
          var rawId2 = tabEl.getAttribute('data-tab-id');
          var id2 = rawId2 ? parseInt(rawId2, 10) : null;
          if (id2 !== null) {
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            switchTab(id2);
            return;
          }
        }
      }, true);

    hookWindowNavigateTo();

    var existingTabEls = Array.from(tabstrip.querySelectorAll('.tab'));
    var winRoot = document.querySelector('.win');
    var rootPath = winRoot ? (winRoot.getAttribute('data-path') || '/') : '/';
    var homeWidgets = document.getElementById('home-widgets');
    var isHome = homeWidgets ? !homeWidgets.hidden : window.__isHome(rootPath);

    var currentView = 'grid';
    if (typeof window.__mode === 'function') {
      currentView = window.__mode();
    } else if (typeof window.__currentLayout === 'string') {
      currentView = window.__currentLayout;
    } else if (document.documentElement && document.documentElement.dataset && document.documentElement.dataset.layout) {
      currentView = document.documentElement.dataset.layout;
    }

    if (existingTabEls.length > 0) {
      tabs = [];
      existingTabEls.forEach(function (tabEl) {
        var rawId = tabEl.getAttribute('data-tab-id');
        var id = rawId ? parseInt(rawId, 10) : (tabSeq++);
        if (id >= tabSeq) tabSeq = id;

        var nameEl = tabEl.querySelector('.tname');
        var name = nameEl ? nameEl.textContent.trim() : (isHome ? 'Home' : 'Folder');
        var isActive = tabEl.classList.contains('active');

        tabEl.setAttribute('draggable', 'true');
        tabEl.setAttribute('title', name);
        if (nameEl) nameEl.setAttribute('title', name);

        var tabObj = {
          id: id,
          name: name,
          path: rootPath,
          isHome: isHome,
          view: currentView,
          scrollTop: 0,
          selectedPaths: new Set(),
          leadSelectedPath: null,
          history: [{ path: rootPath, name: name, isHome: isHome }],
          histIdx: 0,
          filterQuery: '',
          searchActive: false,
          dualPaneState: null,
          el: tabEl
        };

        attachTabElementListeners(tabEl, tabObj);
        tabs.push(tabObj);

        if (isActive) {
          activeTabId = id;
        }
      });

      if (!activeTabId && tabs.length > 0) {
        activeTabId = tabs[0].id;
        tabs[0].el.classList.add('active');
      }
      var curTab = getActiveTab();
      const liveTn = document.querySelector('.tab.active .tname') || document.querySelector('.tname');
      if (liveTn && curTab && curTab.name) liveTn.textContent = curTab.name;
    } else {
      newTab(rootPath, isHome ? 'Home' : 'Folder', isHome, true);
    }

    attachNewTabButton();
    ensureTabContextMenu();
  }

  // Auto initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      initTabsFromDOM();
      attachFolderMiddleClickListener();
      attachKeyboardShortcuts();
    });
  } else {
    initTabsFromDOM();
    attachFolderMiddleClickListener();
    attachKeyboardShortcuts();
  }

  return {
    newTab: newTab,
    switchTab: switchTab,
    closeTab: closeTab,
    closeOtherTabs: closeOtherTabs,
    closeTabsToRight: closeTabsToRight,
    duplicateTab: duplicateTab,
    reopenClosedTab: reopenClosedTab,
    reorderTab: reorderTab,
    getTabs: function () { return tabs.slice(); },
    getActiveTab: getActiveTab,
    getActiveTabId: function () { return activeTabId; },
    getTabById: function (id) {
      return tabs.find(function (t) { return t.id === id; }) || null;
    },
    canReopenClosedTab: function () { return recentlyClosedTabs.length > 0; },
    getRecentlyClosedCount: function () { return recentlyClosedTabs.length; },
    getRecentlyClosed: function () { return recentlyClosedTabs.slice(); },
    getRecentlyClosedTabs: function () { return recentlyClosedTabs.slice(); },
    init: initTabsFromDOM
  };
});

  })();

