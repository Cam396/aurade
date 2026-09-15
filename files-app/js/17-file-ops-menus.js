  // =========================================================================
  // Wave B: Menus, Context Menus and In-Memory File Operations
  // =========================================================================
  (function() {
/**
 * Wave B: Menus and File Operations Engine for AuraDE Files
 * Complete implementation of clipboard, rename, delete/undo, pinning,
 * open with, visual group-by, context menus, and toolbar integration.
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
    var fileOps = factory();
    root.FileOps = fileOps;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var LF = String.fromCharCode(10);
  var CR = String.fromCharCode(13);

  /* ==========================================================================
     1. SVG Helpers (Strict Trusted Types Compliant)
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
    if (fill) {
      p.setAttribute('fill', fill);
    } else {
      p.setAttribute('fill', 'none');
    }
    if (stroke) p.setAttribute('stroke', stroke);
    if (strokeWidth) p.setAttribute('stroke-width', String(strokeWidth));
    if (lineCap) p.setAttribute('stroke-linecap', lineCap);
    if (lineJoin) p.setAttribute('stroke-linejoin', lineJoin);
    return p;
  }

  function createCutSvg() {
    var art = document.querySelector('#artlib [data-ico="Cut"] svg');
    if (art) return art.cloneNode(true);
    var svg = createSvg(16, 16, '0 0 16 16');
    var p1 = createSvgPath('m3.23.08c-.23.15-.3.46-.14.69l4.4,6.73h1.19L3.92.23c-.15-.23-.46-.3-.69-.14ZM12.77.08c-.23-.15-.54-.09-.69.14l-3.48,5.33.6.91L12.92.77c.15-.23.09-.54-.14-.69Z', 'var(--ico-base, #ffffff)');
    var p2 = createSvgPath('m7.99,6.9c-.17,0-.32.09-.41.23l-2.13,3.24c-.43-.24-.93-.37-1.45-.37-1.66,0-3,1.34-3,3s1.34,3,3,3,3-1.34,3-3c0-.77-.29-1.47-.76-2l1.76-2.69,1.76,2.69c-.47.53-.76,1.23-.76,2,0,1.66,1.34,3,3,3s3-1.34,3-3-1.34-3-3-3c-.53,0-1.02.14-1.45.37l-2.13-3.24c-.09-.15-.26-.23-.43-.23Zm-3.99,8.1c-1.1,0-2-.9-2-2s.9-2,2-2,2,.9,2,2-.9,2-2,2Zm8,0c-1.1,0-2-.9-2-2s.9-2,2-2,2,.9,2,2-.9,2-2,2Z', 'var(--ico-accent, #60cdff)');
    svg.appendChild(p1);
    svg.appendChild(p2);
    return svg;
  }

  function createCopySvg() {
    var art = document.querySelector('#artlib [data-ico="Copy"] svg');
    if (art) return art.cloneNode(true);
    var svg = createSvg(16, 16, '0 0 16 16');
    var p1 = createSvgPath('m5,4.5h-1.5c-.53,0-1.04.21-1.41.59-.38.38-.59.88-.59,1.41v6c0,.53.21,1.04.59,1.41.38.38.88.59,1.41.59h4c.44,0,.87-.15,1.23-.42.35-.27.6-.65.71-1.08h-1.44c-.8,0-1.56-.32-2.12-.88-.56-.56-.88-1.33-.88-2.12v-5.5Z', 'var(--ico-alt, #fce100)');
    var p2 = createSvgPath('m8.5,2c-.4,0-.78.16-1.06.44-.28.28-.44.66-.44,1.06v6c0,.4.16.78.44,1.06.28.28.66.44,1.06.44h4c.4,0,.78-.16,1.06-.44.28-.28.44-.66.44-1.06V3.5c0-.4-.16-.78-.44-1.06-.28-.28-.66-.44-1.06-.44h-4Z', 'var(--ico-accent, #60cdff)');
    svg.appendChild(p1);
    svg.appendChild(p2);
    return svg;
  }

  function createPasteSvg() {
    var art = document.querySelector('#artlib [data-ico="Paste"] svg');
    if (art) return art.cloneNode(true);
    var svg = createSvg(16, 16, '0 0 16 16');
    var p1 = createSvgPath('m1.5,2.5c0-.55.45-1,1-1h1.59c.21,0,.4.13.47.33.14.39.51.67.94.67h3c.43,0,.81-.28.94-.67.07-.2.26-.33.47-.33h1.59c.55,0,1,.45,1,1v1.5h-4c-1.38,0-2.5,1.12-2.5,2.5v8h-3.5c-.55,0-1-.45-1-1V2.5Z', 'var(--ico-alt, #fce100)');
    var p2 = createSvgPath('m8.5,5c-.83,0-1.5.67-1.5,1.5v8c0,.83.67,1.5,1.5,1.5h5c.83,0,1.5-.67,1.5-1.5V6.5c0-.83-.67-1.5-1.5-1.5h-5Z', 'var(--ico-accent, #60cdff)');
    svg.appendChild(p1);
    svg.appendChild(p2);
    return svg;
  }

  function createRenameSvg() {
    var art = document.querySelector('#artlib [data-ico="Rename"] svg');
    if (art) return art.cloneNode(true);
    var svg = createSvg(16, 16, '0 0 16 16');
    var p1 = createSvgPath('m.5,4.5v7c0,1.1.9,2,2,2h7.5V2.5H2.5c-1.1,0-2,.9-2,2Zm13-2h-.5v11h.5c1.1,0,2-.9,2-2v-7c0-1.1-.9-2-2-2Z', 'var(--ico-contrast, #ffffff)');
    var p2 = createSvgPath('m13.5,15h-1.5V1h1.5c.28,0,.5-.22.5-.5S13.78,0,13.5,0h-4C9.22,0,9,.22,9,.5s.22.5.5.5h1.5v14h-1.5c-.28,0-.5.22-.5.5s.22.5.5.5h4c.28,0,.5-.22.5-.5s-.22-.5-.5-.5Zm-5.5-8H3c-.55,0-1,.45-1,1s.45,1,1,1h5c.55,0,1-.45,1-1s-.45-1-1-1Z', 'var(--ico-accent, #60cdff)');
    svg.appendChild(p1);
    svg.appendChild(p2);
    return svg;
  }

  function createDeleteSvg() {
    var art = document.querySelector('#artlib [data-ico="Delete"] svg');
    if (art) return art.cloneNode(true);
    var svg = createSvg(16, 16, '0 0 16 16');
    var p1 = createSvgPath('m2,2.5h12l-1.24,10.79c-.15,1.26-1.21,2.21-2.48,2.21h-4.54c-1.27,0-2.34-.95-2.48-2.21L2,2.5Z', 'var(--ico-alt, #fce100)');
    var p2 = createSvgPath('m5,2v-.5C5,.67,5.67,0,6.5,0h3C10.33,0,11,.67,11,1.5v.5h4.5c.28,0,.5.22.5.5s-.22.5-.5.5H.5c-.28,0-.5-.22-.5-.5s.22-.5.5-.5h4.5Z', 'var(--ico-accent, #60cdff)');
    svg.appendChild(p1);
    svg.appendChild(p2);
    return svg;
  }

  function createPinSvg() {
    var art = document.querySelector('#artlib [data-ico="FavoritePin"] svg') ||
              document.querySelector('#artlib [data-ico="Actions.Pinned.12"] svg');
    if (art) return art.cloneNode(true);
    var svg = createSvg(16, 16, '0 0 16 16');
    var p1 = createSvgPath('m7.55,1.22c.18-.37.71-.37.9,0l2.03,4.11.13.02,4.41.64c.41.06.57.56.28.85l-.94.92-.04-.04c-1.21-1.21-3.26-.87-4.02.67l-.8,1.65-1.1.38c-1.23.42-1.69,1.85-1.08,2.89l-3.38,1.78c-.37.19-.8-.12-.73-.53l.78-4.52L.7,6.85c-.3-.29-.13-.79.28-.85l4.54-.66L7.55,1.22Z', 'var(--ico-alt, #fce100)');
    var p2 = createSvgPath('m15.54,10.37l-1.93-1.93c-.73-.73-1.96-.52-2.41.4l-.8,1.65c-.12.24-.32.42-.57.51l-1.1.38c-.7.24-.9,1.13-.38,1.65l.95.95-1.29,1.29v.71h.71l1.29-1.29.95.95c.52.52,1.41.32,1.65-.38l.38-1.1c.09-.25.27-.46.51-.57l1.65-.8c.93-.45,1.13-1.68.4-2.41Z', 'var(--ico-accent, #60cdff)');
    svg.appendChild(p1);
    svg.appendChild(p2);
    return svg;
  }

  function createOpenWithSvg() {
    var art = document.querySelector('#artlib [data-ico="OpenWith"] svg');
    if (art) return art.cloneNode(true);
    var svg = createSvg(16, 16, '0 0 16 16');
    var p1 = createSvgPath('m1,1v3h3V1H1Zm0,8h3v-3H1v3Zm0,5h3v-3H1v3Z', 'var(--ico-alt, #fce100)');
    var p2 = createSvgPath('m6.5,11c0-1.19.47-2.34,1.32-3.18.84-.84,1.99-1.32,3.18-1.32s2.34.47,3.18,1.32c.84.84,1.32,1.99,1.32,3.18s-.47,2.34-1.32,3.18-1.99,1.32-3.18,1.32-2.34-.47-3.18-1.32c-.84-.84-1.32-1.99-1.32-3.18Z', 'var(--ico-accent, #60cdff)');
    svg.appendChild(p1);
    svg.appendChild(p2);
    return svg;
  }

  function createZipSvg() {
    var svg = createSvg(16, 16, '0 0 16 16');
    var p1 = createSvgPath('M2.5 1A1.5 1.5 0 0 0 1 2.5v11A1.5 1.5 0 0 0 2.5 15h11a1.5 1.5 0 0 0 1.5-1.5v-11A1.5 1.5 0 0 0 13.5 1h-11z', 'none', 'currentColor', 1);
    var p2 = createSvgPath('M7 2h2v1H7zm0 2h2v1H7zm0 2h2v1H7zm0 2h2v1H7zm-1 3h4v3H6z', 'currentColor');
    svg.appendChild(p1);
    svg.appendChild(p2);
    return svg;
  }

  function createPropertiesSvg() {
    var art = document.querySelector('#artlib [data-ico="Properties"] svg');
    if (art) return art.cloneNode(true);
    var svg = createSvg(16, 16, '0 0 16 16');
    var p = createSvgPath('m11.5.5c-2.21,0-4,1.79-4,4,0,.35.04.69.13,1.01L1.02,12.37c-.36.37-.52.85-.52,1.31,0,1.04.88,1.83,1.86,1.82.47,0,.95-.17,1.32-.54l6.57-6.66c.39.13.81.2,1.25.2,2.21,0,4-1.79,4-4,0-.28-.03-.56-.08-.82-.04-.18-.17-.32-.35-.38-.18-.05-.37,0-.5.13l-2.07,2.07-2-2,2.07-2.07c.13-.13.18-.32.13-.5-.05-.18-.2-.31-.38-.35-.27-.06-.54-.08-.82-.08Z', 'var(--ico-accent, #60cdff)');
    svg.appendChild(p);
    return svg;
  }

  function createToastInfoSvg() {
    var svg = createSvg(18, 18, '0 0 18 18');
    var circle = document.createElementNS(SVG_NS, 'circle');
    circle.setAttribute('cx', '9');
    circle.setAttribute('cy', '9');
    circle.setAttribute('r', '8');
    circle.setAttribute('fill', 'none');
    circle.setAttribute('stroke', 'currentColor');
    circle.setAttribute('stroke-width', '1.5');
    var tick = createSvgPath('M5.5 9.5l2.5 2.5 5-5', 'none', 'currentColor', 1.8, 'round', 'round');
    svg.appendChild(circle);
    svg.appendChild(tick);
    return svg;
  }

  /* ==========================================================================
     2. Layout Synchronization Core (Across all 5 Layout Containers)
     ========================================================================== */

  function getLayoutContainers() {
    var dbody = document.querySelector('.rows .dbody') || document.querySelector('.dbody');
    var cols = document.querySelector('.columns .cols .col:last-child') ||
               document.querySelector('.columns .col:last-child') ||
               document.querySelector('.columns');
    return [
      { type: 'grid', container: document.querySelector('.grid'), selector: '.cell' },
      { type: 'details', container: dbody, selector: '.row' },
      { type: 'list', container: document.querySelector('.list'), selector: '.lrow' },
      { type: 'cards', container: document.querySelector('.cards'), selector: '.tile' },
      { type: 'columns', container: cols, selector: '.crow' }
    ];
  }

  function findItemInContainer(containerRecord, name, path) {
    if (!containerRecord || !containerRecord.container) return null;
    var items = containerRecord.container.querySelectorAll(containerRecord.selector);
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      if (path && it.getAttribute('data-p') === path) return it;
      if (name && it.getAttribute('data-n') === name) return it;
    }
    return null;
  }

  function findMatchingElementsAcrossLayouts(name, path) {
    var results = [];
    var layouts = getLayoutContainers();
    for (var i = 0; i < layouts.length; i++) {
      var cRec = layouts[i];
      var el = findItemInContainer(cRec, name, path);
      if (el) {
        results.push({
          type: cRec.type,
          container: cRec.container,
          selector: cRec.selector,
          element: el
        });
      }
    }
    return results;
  }

  /* ==========================================================================
     3. Action Toast Singleton
     ========================================================================== */

  var toastEl = null;
  var toastTimer = null;

  function ensureActionToast() {
    if (toastEl && toastEl.parentElement) return toastEl;
    toastEl = document.querySelector('.action-toast');
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'action-toast';

      var iconSpan = document.createElement('span');
      iconSpan.className = 'action-toast-icon';
      iconSpan.appendChild(createToastInfoSvg());

      var msgSpan = document.createElement('span');
      msgSpan.className = 'action-toast-msg';

      toastEl.appendChild(iconSpan);
      toastEl.appendChild(msgSpan);
      document.body.appendChild(toastEl);
    }
    return toastEl;
  }

  //: Live mode has its own scope and its own failures to report.
  window.__toast = (message, duration) => showToast(message, duration);

  function showToast(message, duration) {
    var toast = ensureActionToast();
    if (!toast) return;
    var msgSpan = toast.querySelector('.action-toast-msg') || toast;
    msgSpan.textContent = message;
    toast.classList.add('visible');

    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toast.classList.remove('visible');
    }, duration || 2600);
  }

  /* ==========================================================================
     4. Selection and Context Target Helpers
     ========================================================================== */

  var lastContextTarget = null;

  //: A right click or a press on the background clears it: the menu that
  //: opens there is the background's, and a row of it must not reach the
  //: item that was under the pointer some clicks ago.
  document.addEventListener('contextmenu', function (e) {
    var it = e.target.closest('.cell, .row, .lrow, .tile, .crow, .wcard, .wrecent-row, .srow, [data-n], [data-p]');
    if (!e.target.closest('.ctx, .menu, .toolbar, .omnibar')) {
      lastContextTarget = it || null;
    }
  }, true);

  document.addEventListener('mousedown', function (e) {
    var it = e.target.closest('.cell, .row, .lrow, .tile, .crow, .wcard, .wrecent-row, .srow, [data-n], [data-p]');
    if (!e.target.closest('.ctx, .menu, .toolbar, .omnibar, .scrim')) {
      lastContextTarget = it || null;
    }
  }, true);

  function getActiveTargets(items) {
    if (items) {
      if (Array.isArray(items)) return items.filter(Boolean);
      return [items];
    }
    var sel = Array.from(document.querySelectorAll('.cell.sel, .row.sel, .lrow.sel, .tile.sel, .crow.sel'));
    if (sel.length > 0) {
      var seen = new Set();
      var unique = [];
      for (var i = 0; i < sel.length; i++) {
        var el = sel[i];
        var key = el.getAttribute('data-p') || el.getAttribute('data-n') || el;
        if (!seen.has(key)) {
          seen.add(key);
          unique.push(el);
        }
      }
      return unique;
    }
    if (lastContextTarget) {
      return [lastContextTarget];
    }
    return [];
  }

  /* ==========================================================================
     5. Status Bar and Toolbar Integration
     ========================================================================== */

  function updateStatusBar() {
    if (typeof window.__updateStatus === 'function') {
      try { window.__updateStatus(); } catch (err) {}
    }
  }

  function updateToolbarButtons() {
    var tbContext = document.getElementById('tb-context');
    if (!tbContext) return;

    var selItems = [].slice.call(document.querySelectorAll(
      '.cell.sel, .row.sel, .lrow.sel, .tile.sel, .crow.sel'))
      .filter(function (el) { return el.offsetParent !== null; });
    var selCount = selItems.length;
    var hasClipboard = clipboard.items && clipboard.items.length > 0;

    function setBtn(selector, enabled) {
      var btn = tbContext.querySelector(selector);
      if (!btn) return;
      btn.disabled = !enabled;
      if (enabled) {
        btn.classList.remove('dis');
        btn.removeAttribute('aria-disabled');
      } else {
        btn.classList.add('dis');
        btn.setAttribute('aria-disabled', 'true');
      }
    }

    setBtn('[data-act="cut"]', selCount > 0);
    setBtn('[data-act="copy"]', selCount > 0);
    setBtn('[data-act="paste"]', hasClipboard);
    setBtn('[data-act="rename"]', selCount === 1);
    setBtn('[data-act="trash"], [data-act="delete"]', selCount > 0);
    setBtn('[data-act="ctx-dis"]', selCount > 0);
    setBtn('[data-act="ctx-props"]', true);
  }

  // Periodic and reactive hook for toolbar and status
  document.addEventListener('click', function () {
    setTimeout(function () {
      updateToolbarButtons();
      updateStatusBar();
    }, 15);
  });
  document.addEventListener('mouseup', function () {
    setTimeout(function () {
      updateToolbarButtons();
      updateStatusBar();
    }, 15);
  });

  /* ==========================================================================
     6. Clipboard Engine
     ========================================================================== */

  var clipboard = {
    mode: null,
    items: []
  };

  function cut(items) {
    var targets = getActiveTargets(items);
    if (!targets.length) return;

    clipboard.mode = 'cut';
    clipboard.items = [];

    document.querySelectorAll('.cut').forEach(function (el) {
      el.classList.remove('cut');
    });

    for (var i = 0; i < targets.length; i++) {
      var t = targets[i];
      var name = t.getAttribute('data-n') || t.textContent.trim();
      var path = t.getAttribute('data-p') || (window.__homePath() + '/' + name);
      var kind = t.getAttribute('data-k') || 'File';
      var size = t.getAttribute('data-s') || '';
      var mod = t.getAttribute('data-w') || '';

      clipboard.items.push({
        name: name,
        path: path,
        kind: kind,
        size: size,
        modified: mod
      });

      var matches = findMatchingElementsAcrossLayouts(name, path);
      for (var m = 0; m < matches.length; m++) {
        matches[m].element.classList.add('cut');
      }
    }

    updateToolbarButtons();
    var count = clipboard.items.length;
    showToast('Cut ' + count + (count === 1 ? ' item' : ' items') + ' to clipboard');
  }

  function copy(items) {
    var targets = getActiveTargets(items);
    if (!targets.length) return;

    clipboard.mode = 'copy';
    clipboard.items = [];

    document.querySelectorAll('.cut').forEach(function (el) {
      el.classList.remove('cut');
    });

    var paths = [];
    for (var i = 0; i < targets.length; i++) {
      var t = targets[i];
      var name = t.getAttribute('data-n') || t.textContent.trim();
      var path = t.getAttribute('data-p') || (window.__homePath() + '/' + name);
      var kind = t.getAttribute('data-k') || 'File';
      var size = t.getAttribute('data-s') || '';
      var mod = t.getAttribute('data-w') || '';

      clipboard.items.push({
        name: name,
        path: path,
        kind: kind,
        size: size,
        modified: mod
      });

      paths.push(path);
    }

    if (paths.length && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      navigator.clipboard.writeText(paths.join(LF)).catch(function () {});
    }

    updateToolbarButtons();
    var count = clipboard.items.length;
    showToast('Copied ' + count + (count === 1 ? ' item' : ' items') + ' to clipboard');
  }

  function generateUniqueName(baseName, existingNames) {
    if (!existingNames.has(baseName)) return baseName;
    var dotIndex = baseName.lastIndexOf('.');
    var stem = dotIndex > 0 ? baseName.slice(0, dotIndex) : baseName;
    var ext = dotIndex > 0 ? baseName.slice(dotIndex) : '';

    var match = stem.match(/^(.*?)[ 	]*[(]([0-9]+)[)]$/);
    var rootStem = stem;
    var counter = 1;
    if (match) {
      rootStem = match[1];
      counter = parseInt(match[2], 10) + 1;
    }
    while (true) {
      var candidate = rootStem + ' (' + counter + ')' + ext;
      if (!existingNames.has(candidate)) {
        return candidate;
      }
      counter++;
    }
  }

  function paste(targetPath) {
    if (!clipboard.items || !clipboard.items.length) {
      showToast('Clipboard is empty');
      return;
    }

    var count = clipboard.items.length;
    var layouts = getLayoutContainers();

    if (clipboard.mode === 'copy') {
      var gridContainer = layouts.find(function (l) { return l.type === 'grid'; });
      var existingNames = new Set();
      if (gridContainer && gridContainer.container) {
        var existingCells = gridContainer.container.querySelectorAll(gridContainer.selector);
        for (var e = 0; e < existingCells.length; e++) {
          var n = existingCells[e].getAttribute('data-n');
          if (n) existingNames.add(n);
        }
      }

      function executeCopyPaste(itemsToPaste, resolvedNamesMap, replaceSet) {
        for (var i = 0; i < itemsToPaste.length; i++) {
          var item = itemsToPaste[i];
          var newName = (resolvedNamesMap && resolvedNamesMap[item.name]) || item.name;
          var isReplace = replaceSet && replaceSet.has(item.name);
          existingNames.add(newName);

          var basePath = targetPath || (item.path ? item.path.substring(0, item.path.lastIndexOf('/') + 1) : window.__homePath() + '/');
          if (!basePath.endsWith('/')) basePath += '/';
          var newPath = basePath + newName;

          for (var j = 0; j < layouts.length; j++) {
            var lRec = layouts[j];
            if (!lRec.container) continue;

            if (isReplace) {
              var targetEl = findItemInContainer(lRec, item.name, item.path);
              if (targetEl) {
                targetEl.setAttribute('data-w', 'Just now');
                continue;
              }
            }

            var srcEl = findItemInContainer(lRec, item.name, item.path);
            if (!srcEl) {
              var anyMatches = findMatchingElementsAcrossLayouts(item.name, item.path);
              if (anyMatches.length > 0) {
                srcEl = anyMatches[0].element;
              }
            }

            if (srcEl) {
              var clone = srcEl.cloneNode(true);
              clone.setAttribute('data-n', newName);
              if (clone.hasAttribute('data-p') || item.path) {
                clone.setAttribute('data-p', newPath);
              }
              clone.classList.remove('cut', 'sel');

              var cname = clone.querySelector('.cname');
              if (cname) {
                cname.textContent = newName;
                cname.title = newName;
              }
              var dname = clone.querySelector('.c-name > span:last-child') || clone.querySelector('.c-name');
              if (dname) {
                dname.textContent = newName;
              }
              var lname = clone.querySelector('.lname');
              if (lname) {
                lname.textContent = newName;
                lname.title = newName;
              }

              lRec.container.appendChild(clone);
            }
          }
        }

        updateStatusBar();
        updateToolbarButtons();
        showToast('Pasted ' + count + (count === 1 ? ' item' : ' items'));
      }

      var colliding = [];
      for (var ci = 0; ci < clipboard.items.length; ci++) {
        if (existingNames.has(clipboard.items[ci].name)) {
          colliding.push(clipboard.items[ci]);
        }
      }

      if (colliding.length > 0 && window.FileConflictDialog && typeof window.FileConflictDialog.show === 'function') {
        var firstColliding = colliding[0];
        var matched = findMatchingElementsAcrossLayouts(firstColliding.name, firstColliding.path);
        var targetMeta = {
          name: firstColliding.name,
          size: (matched.length > 0 ? matched[0].element.getAttribute('data-s') : null) || firstColliding.size || '1 KB',
          date: (matched.length > 0 ? matched[0].element.getAttribute('data-w') : null) || firstColliding.modified || 'Today'
        };

        window.FileConflictDialog.show({
          sourceItem: {
            name: firstColliding.name,
            size: firstColliding.size || '1 KB',
            date: firstColliding.modified || 'Today'
          },
          targetItem: targetMeta,
          existingNames: Array.from(existingNames)
        }).then(function (res) {
          if (!res || res.action === 'skip') {
            showToast('Paste skipped');
            return;
          }

          var resolvedMap = {};
          var repSet = new Set();
          if (res.action === 'keep_both') {
            resolvedMap[firstColliding.name] = res.resolvedName || generateUniqueName(firstColliding.name, existingNames);
          } else if (res.action === 'replace') {
            repSet.add(firstColliding.name);
          }

          executeCopyPaste(clipboard.items, resolvedMap, repSet);
        });
        return;
      }

      var autoMap = {};
      for (var a = 0; a < clipboard.items.length; a++) {
        var aItem = clipboard.items[a];
        if (existingNames.has(aItem.name)) {
          autoMap[aItem.name] = generateUniqueName(aItem.name, existingNames);
        } else {
          autoMap[aItem.name] = aItem.name;
        }
      }
      executeCopyPaste(clipboard.items, autoMap, new Set());
    } else if (clipboard.mode === 'cut') {
      for (var k = 0; k < clipboard.items.length; k++) {
        var cutItem = clipboard.items[k];
        var cutMatches = findMatchingElementsAcrossLayouts(cutItem.name, cutItem.path);
        for (var c = 0; c < cutMatches.length; c++) {
          var el = cutMatches[c].element;
          el.classList.remove('cut');
          if (targetPath) {
            if (el.parentNode) el.parentNode.removeChild(el);
          }
        }
      }

      clipboard.mode = null;
      clipboard.items = [];

      updateStatusBar();
      updateToolbarButtons();
      showToast('Moved ' + count + (count === 1 ? ' item' : ' items'));
    }
  }

  function pasteIntoFolder(folderPath) {
    if (!clipboard.items || !clipboard.items.length) {
      showToast('Clipboard is empty');
      return;
    }
    var fName = folderPath ? folderPath.split('/').filter(Boolean).pop() : 'folder';
    var count = clipboard.items.length;

    if (clipboard.mode === 'cut') {
      for (var i = 0; i < clipboard.items.length; i++) {
        var it = clipboard.items[i];
        var matches = findMatchingElementsAcrossLayouts(it.name, it.path);
        for (var m = 0; m < matches.length; m++) {
          var el = matches[m].element;
          if (el.parentNode) el.parentNode.removeChild(el);
        }
      }
      clipboard.mode = null;
      clipboard.items = [];
      updateStatusBar();
      updateToolbarButtons();
      showToast('Moved ' + count + (count === 1 ? ' item' : ' items') + ' to ' + fName);
    } else {
      updateToolbarButtons();
      showToast('Copied ' + count + (count === 1 ? ' item' : ' items') + ' to ' + fName);
    }
  }

  /* ==========================================================================
     7. Rename Engine
     ========================================================================== */

  var renameScrim = null;

  function ensureRenameDialog() {
    if (renameScrim && renameScrim.parentElement) return renameScrim;
    renameScrim = document.createElement('div');
    renameScrim.className = 'rename-dialog-scrim';
    renameScrim.style.position = 'fixed';
    renameScrim.style.inset = '0';
    renameScrim.style.background = 'rgba(0, 0, 0, 0.55)';
    renameScrim.style.backdropFilter = 'blur(8px)';
    renameScrim.style.display = 'none';
    renameScrim.style.alignItems = 'center';
    renameScrim.style.justifyContent = 'center';
    renameScrim.style.zIndex = '10005';

    var card = document.createElement('div');
    card.className = 'rename-card';
    card.style.background = 'var(--solid-base, #202020)';
    card.style.border = '1px solid var(--surface-stroke, rgba(255, 255, 255, 0.12))';
    card.style.borderRadius = '8px';
    card.style.padding = '20px 24px';
    card.style.width = '380px';
    card.style.maxWidth = '90vw';
    card.style.boxShadow = '0 16px 40px rgba(0, 0, 0, 0.5)';
    card.style.color = 'var(--text-1, #ffffff)';
    card.style.fontFamily = 'var(--font, Segoe UI, sans-serif)';

    var title = document.createElement('div');
    title.className = 'rename-card-title';
    title.textContent = 'Rename';
    title.style.fontSize = '16px';
    title.style.fontWeight = '600';
    title.style.marginBottom = '12px';

    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'rename-card-input';
    input.style.width = '100%';
    input.style.height = '32px';
    input.style.padding = '0 10px';
    input.style.boxSizing = 'border-box';
    input.style.borderRadius = '4px';
    input.style.border = '1px solid var(--control-stroke, rgba(255, 255, 255, 0.15))';
    input.style.background = 'var(--control-fill, rgba(255, 255, 255, 0.06))';
    input.style.color = 'var(--text-1, #ffffff)';
    input.style.outline = 'none';
    input.style.fontSize = '14px';

    var errorMsg = document.createElement('div');
    errorMsg.className = 'rename-card-error';
    errorMsg.style.color = '#ff6b6b';
    errorMsg.style.fontSize = '12px';
    errorMsg.style.marginTop = '6px';
    errorMsg.style.display = 'none';

    var btns = document.createElement('div');
    btns.style.display = 'flex';
    btns.style.justifyContent = 'flex-end';
    btns.style.gap = '8px';
    btns.style.marginTop = '18px';

    var cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.className = 'open-with-btn';

    var okBtn = document.createElement('button');
    okBtn.type = 'button';
    okBtn.textContent = 'Rename';
    okBtn.className = 'open-with-btn primary';

    btns.appendChild(cancelBtn);
    btns.appendChild(okBtn);

    card.appendChild(title);
    card.appendChild(input);
    card.appendChild(errorMsg);
    card.appendChild(btns);
    renameScrim.appendChild(card);
    document.body.appendChild(renameScrim);

    return renameScrim;
  }

  function rename(item, newName) {
    var targets = getActiveTargets(item);
    if (!targets.length) return;
    var it = targets[0];
    var oldName = it.getAttribute('data-n') || it.textContent.trim();

    if (typeof newName === 'string') {
      var clean = newName.trim();
      if (!clean || clean === oldName) return;

      var oldPath = it.getAttribute('data-p') || '';
      var newPath = '';
      if (oldPath) {
        var lastSlash = oldPath.lastIndexOf('/');
        newPath = (lastSlash >= 0 ? oldPath.substring(0, lastSlash + 1) : '') + clean;
      }

      var matches = findMatchingElementsAcrossLayouts(oldName, oldPath);
      for (var i = 0; i < matches.length; i++) {
        var el = matches[i].element;
        el.setAttribute('data-n', clean);
        if (newPath) el.setAttribute('data-p', newPath);

        var cname = el.querySelector('.cname');
        if (cname) {
          cname.textContent = clean;
          cname.title = clean;
        }
        var dname = el.querySelector('.c-name > span:last-child') || el.querySelector('.c-name');
        if (dname) {
          dname.textContent = clean;
        }
        var lname = el.querySelector('.lname');
        if (lname) {
          lname.textContent = clean;
          lname.title = clean;
        }
      }

      var detName = document.querySelector('[data-dk="Name"]');
      if (detName) detName.textContent = clean;
      var detPath = document.querySelector('[data-dk="Path"]');
      if (detPath && newPath) detPath.textContent = newPath;
      var pkName = document.querySelector('[data-pk="Name"]');
      if (pkName) pkName.textContent = clean;

      updateStatusBar();
      updateToolbarButtons();
      showToast('Renamed "' + oldName + '" to "' + clean + '"');
      return;
    }

    var scrim = ensureRenameDialog();
    var input = scrim.querySelector('.rename-card-input');
    var errorMsg = scrim.querySelector('.rename-card-error');
    var okBtn = scrim.querySelector('.open-with-btn.primary');
    var cancelBtn = scrim.querySelector('.open-with-btn:not(.primary)');

    errorMsg.style.display = 'none';
    errorMsg.textContent = '';
    input.value = oldName;
    scrim.style.display = 'flex';
    input.focus();
    var dotIdx = oldName.lastIndexOf('.');
    if (dotIdx > 0) {
      input.setSelectionRange(0, dotIdx);
    } else {
      input.select();
    }

    function closeDialog() {
      scrim.style.display = 'none';
      okBtn.onclick = null;
      cancelBtn.onclick = null;
      input.onkeydown = null;
      scrim.onclick = null;
    }

    function doSubmit() {
      var val = input.value.trim();
      if (!val) {
        errorMsg.textContent = 'Please enter a valid name';
        errorMsg.style.display = 'block';
        return;
      }
      if (/[\/:*?"<>|]/.test(val)) {
        errorMsg.textContent = 'A file name cannot contain any of the following characters: \ / : * ? " < > |';
        errorMsg.style.display = 'block';
        return;
      }
      closeDialog();
      rename(it, val);
    }

    okBtn.onclick = doSubmit;
    cancelBtn.onclick = closeDialog;
    input.onkeydown = function (ev) {
      if (ev.key === 'Enter') {
        ev.preventDefault();
        doSubmit();
      } else if (ev.key === 'Escape') {
        ev.preventDefault();
        closeDialog();
      }
    };
    scrim.onclick = function (ev) {
      if (ev.target === scrim) closeDialog();
    };
  }

  /* ==========================================================================
     8. Delete and Undo Engine
     ========================================================================== */

  window.__trashHistory = window.__trashHistory || [];

  function deleteItems(items, asked) {
    var targets = getActiveTargets(items);
    if (!targets.length) return;
    //: The reference asks through FilesystemOperationDialog when the
    //: setting says to, and this deleted without a word.
    if (!asked && window.__fsop && window.__deleteAsks && window.__deleteAsks()) {
      window.__fsop({
        kind: 'delete',
        names: targets.map(function (t) { return t.getAttribute('data-n') || 'item'; })
      }).then(function (ok) { if (ok) deleteItems(targets, true); });
      return;
    }

    var historyRecord = {
      timestamp: Date.now(),
      records: []
    };

    for (var i = 0; i < targets.length; i++) {
      var t = targets[i];
      var name = t.getAttribute('data-n') || t.textContent.trim();
      var path = t.getAttribute('data-p') || (window.__homePath() + '/' + name);

      var matches = findMatchingElementsAcrossLayouts(name, path);
      for (var m = 0; m < matches.length; m++) {
        var el = matches[m].element;
        var parent = el.parentNode;
        var nextSibling = el.nextSibling;

        historyRecord.records.push({
          element: el,
          parent: parent,
          nextSibling: nextSibling,
          name: name,
          path: path
        });

        if (parent) {
          parent.removeChild(el);
        }
      }
    }

    window.__trashHistory.push(historyRecord);

    var count = targets.length;
    if (window.StatusCenter && typeof window.StatusCenter.addTask === 'function') {
      try {
        var task = window.StatusCenter.addTask({
          title: 'Deleting ' + count + (count === 1 ? ' item' : ' items'),
          state: 'InProgress',
          progress: 50
        });
        setTimeout(function () {
          if (task && typeof task.update === 'function') {
            task.update({ state: 'Successful', progress: 100 });
          }
        }, 500);
      } catch (err) {}
    }

    updateStatusBar();
    updateToolbarButtons();
    showToast('Deleted ' + count + (count === 1 ? ' item' : ' items') + '. Press Ctrl+Z to undo.');
  }

  function undo() {
    if (!window.__trashHistory || !window.__trashHistory.length) {
      showToast('Nothing to undo');
      return;
    }

    var lastAction = window.__trashHistory.pop();
    var records = lastAction.records;
    var restoredCount = 0;
    var seen = new Set();

    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      if (r.parent && r.element) {
        if (r.nextSibling && r.nextSibling.parentNode === r.parent) {
          r.parent.insertBefore(r.element, r.nextSibling);
        } else {
          r.parent.appendChild(r.element);
        }
        if (!seen.has(r.name)) {
          seen.add(r.name);
          restoredCount++;
        }
      }
    }

    updateStatusBar();
    updateToolbarButtons();
    showToast('Restored ' + restoredCount + (restoredCount === 1 ? ' item' : ' items'));
  }

  /* ==========================================================================
     9. Pinning Engine (Sidebar and Quick Access)
     ========================================================================== */

  function getPinnedSidebar() {
    try {
      var raw = localStorage.getItem('aurade_pinned_sidebar');
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      return [];
    }
  }

  function savePinnedSidebar(list) {
    try {
      localStorage.setItem('aurade_pinned_sidebar', JSON.stringify(list));
    } catch (e) {}
  }

  function renderPinnedSidebarItem(name, path) {
    var existing = Array.from(document.querySelectorAll('.srow.item')).find(function (row) {
      return row.getAttribute('data-path') === path ||
             (row.querySelector('.lbl') && row.querySelector('.lbl').textContent.trim() === name);
    });
    if (existing) return;

    var pinnedGrp = Array.from(document.querySelectorAll('.sgrp')).find(function (g) {
      var h = g.querySelector(':scope > .srow.head');
      if (!h) return false;
      return h.textContent.indexOf('Pinned') >= 0 || h.textContent.indexOf('Favorites') >= 0;
    });
    var pinnedKids = pinnedGrp && pinnedGrp.querySelector(':scope > .skids');
    if (!pinnedKids) return;

    var a = document.createElement('a');
    a.className = 'srow item lv1';
    a.setAttribute('href', path);
    a.setAttribute('data-path', path);

    var ind = document.createElement('span');
    ind.className = 'ind';
    a.appendChild(ind);

    var cslot = document.createElement('span');
    cslot.className = 'cslot';
    a.appendChild(cslot);

    var icon = createSvg(16, 16, '0 0 16 16');
    icon.setAttribute('class', 'pg');
    var pPath = createSvgPath('M1.4 3.35A1.85 1.85 0 0 1 3.25 1.5h9.5a1.85 1.85 0 0 1 1.85 1.85v5.5a1.85 1.85 0 0 1-1.85 1.85h-9.5A1.85 1.85 0 0 1 1.4 8.85z', 'var(--pl-slate, #6c7a89)');
    icon.appendChild(pPath);
    a.appendChild(icon);

    var lbl = document.createElement('span');
    lbl.className = 'lbl';
    lbl.textContent = name;
    a.appendChild(lbl);

    var trail = document.createElement('span');
    trail.className = 'trail';
    var pinSvg = createPinSvg();
    pinSvg.setAttribute('width', '12');
    pinSvg.setAttribute('height', '12');
    trail.appendChild(pinSvg);
    a.appendChild(trail);

    pinnedKids.appendChild(a);
  }

  //: The pinned rows as the sidebar shows them, baked and added alike,
  //: and the order a person gave them, which is kept beside the pins and
  //: put back on load. Files' ReorderSidebarItemsDialog saves through its
  //: quick access service; here the sidebar is the store.
  function pinnedGroup() {
    return Array.from(document.querySelectorAll('.sgrp')).find(function (g) {
      var h = g.querySelector(':scope > .srow.head');
      return !!h && (h.textContent.indexOf('Pinned') >= 0 || h.textContent.indexOf('Favorites') >= 0);
    }) || null;
  }
  function pinnedRows() {
    var g = pinnedGroup();
    var kids = g && g.querySelector(':scope > .skids');
    return kids ? Array.from(kids.querySelectorAll(':scope > .srow.item')) : [];
  }
  function pinnedKey(row) {
    return row.getAttribute('data-path') || row.getAttribute('data-root') ||
      row.getAttribute('href') || (row.querySelector('.lbl') || row).textContent.trim();
  }
  function applyPinnedOrder(order, save) {
    var rows = pinnedRows();
    if (!rows.length || !order || !order.length) return;
    var kids = rows[0].parentNode;
    var byKey = {};
    rows.forEach(function (r) { byKey[pinnedKey(r)] = r; });
    order.forEach(function (k) { if (byKey[k]) kids.appendChild(byKey[k]); });
    if (save) {
      try { localStorage.setItem('aurade_pinned_order', JSON.stringify(order)); } catch (e) {}
    }
  }
  try {
    var keptOrder = JSON.parse(localStorage.getItem('aurade_pinned_order') || 'null');
    if (Array.isArray(keptOrder)) applyPinnedOrder(keptOrder, false);
  } catch (e) {}
  window.__pinned = {
    rows: function () {
      return pinnedRows().map(function (r) {
        return {key: pinnedKey(r), name: (r.querySelector('.lbl') || r).textContent.trim()};
      });
    },
    reorder: function (order) { applyPinnedOrder(order, true); },
    //: After the live layer has redrawn the sidebar and the Quick access
    //: cards from the daemon: the user's own pins and the order they chose
    //: go back on, the way init put them on the static page.
    restoreSidebar: function () {
      getPinnedSidebar().forEach(function (it) { renderPinnedSidebarItem(it.name, it.path); });
      try {
        var kept = JSON.parse(localStorage.getItem('aurade_pinned_order') || 'null');
        if (Array.isArray(kept)) applyPinnedOrder(kept, false);
      } catch (e) {}
    },
    restoreQuickAccess: function () {
      getPinnedQA().forEach(function (it) { renderQuickAccessCard(it.name, it.path); });
    }
  };

  function pinToSidebar(item) {
    if (!item) return;
    var name = typeof item === 'object' && item.getAttribute ? (item.getAttribute('data-n') || item.textContent.trim()) : (item.name || String(item));
    var path = typeof item === 'object' && item.getAttribute ? (item.getAttribute('data-p') || (window.__homePath() + '/' + name)) : (item.path || (window.__homePath() + '/' + name));

    var list = getPinnedSidebar();
    if (!list.some(function (p) { return p.path === path; })) {
      list.push({ name: name, path: path });
      savePinnedSidebar(list);
    }
    renderPinnedSidebarItem(name, path);
    showToast('Pinned "' + name + '" to sidebar');
  }

  function unpinFromSidebar(path) {
    if (!path) return;
    var list = getPinnedSidebar();
    list = list.filter(function (p) { return p.path !== path && p.name !== path; });
    savePinnedSidebar(list);

    var sideRows = document.querySelectorAll('.srow.item');
    sideRows.forEach(function (r) {
      if (r.getAttribute('data-path') === path || r.getAttribute('href') === path ||
          (r.querySelector('.lbl') && r.querySelector('.lbl').textContent.trim() === path)) {
        if (r.parentNode) r.parentNode.removeChild(r);
      }
    });
    showToast('Unpinned from sidebar');
  }

  function getPinnedQA() {
    try {
      var raw = localStorage.getItem('aurade_pinned_quickaccess');
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      return [];
    }
  }

  function savePinnedQA(list) {
    try {
      localStorage.setItem('aurade_pinned_quickaccess', JSON.stringify(list));
    } catch (e) {}
  }

  function renderQuickAccessCard(name, path) {
    var qaContainer = document.querySelector('.wcards.wcards-qa') ||
                      document.querySelector('.widgets .wsec:first-child .wcards') ||
                      document.querySelector('.wcards');
    if (!qaContainer) return;
    qaContainer.classList.add('wcards-qa');

    var existing = Array.from(qaContainer.querySelectorAll('.wcard')).find(function (c) {
      return c.getAttribute('data-path') === path ||
             (c.querySelector('.wt b') && c.querySelector('.wt b').textContent.trim() === name);
    });
    if (existing) return;

    var a = document.createElement('a');
    a.className = 'wcard';
    a.setAttribute('href', path);
    a.setAttribute('data-path', path);

    var svg = createSvg(16, 16, '0 0 16 16');
    svg.setAttribute('class', 'pg');
    var p1 = createSvgPath('M1.4 3.35A1.85 1.85 0 0 1 3.25 1.5h9.5a1.85 1.85 0 0 1 1.85 1.85v5.5a1.85 1.85 0 0 1-1.85 1.85h-9.5A1.85 1.85 0 0 1 1.4 8.85z', 'var(--pl-slate, #6c7a89)');
    svg.appendChild(p1);
    a.appendChild(svg);

    var wt = document.createElement('span');
    wt.className = 'wt';
    var b = document.createElement('b');
    b.textContent = name;
    var sub = document.createElement('span');
    sub.textContent = path;
    wt.appendChild(b);
    wt.appendChild(sub);
    a.appendChild(wt);

    qaContainer.appendChild(a);
  }

  function pinToQuickAccess(item) {
    if (!item) return;
    var name = typeof item === 'object' && item.getAttribute ? (item.getAttribute('data-n') || item.textContent.trim()) : (item.name || String(item));
    var path = typeof item === 'object' && item.getAttribute ? (item.getAttribute('data-p') || (window.__homePath() + '/' + name)) : (item.path || (window.__homePath() + '/' + name));

    var list = getPinnedQA();
    if (!list.some(function (p) { return p.path === path; })) {
      list.push({ name: name, path: path });
      savePinnedQA(list);
    }
    renderQuickAccessCard(name, path);
    showToast('Pinned "' + name + '" to Quick access');
  }

  function unpinFromQuickAccess(path) {
    if (!path) return;
    var list = getPinnedQA();
    list = list.filter(function (p) { return p.path !== path && p.name !== path; });
    savePinnedQA(list);

    var cards = document.querySelectorAll('.wcard');
    cards.forEach(function (c) {
      if (c.getAttribute('data-path') === path || c.getAttribute('href') === path ||
          (c.querySelector('.wt b') && c.querySelector('.wt b').textContent.trim() === path)) {
        if (c.parentNode) c.parentNode.removeChild(c);
      }
    });
    showToast('Unpinned from Quick access');
  }

  /* ==========================================================================
     10. Open With Modal Dialog Engine
     ========================================================================== */

  var openWithScrim = null;

  var AVAILABLE_APPS = [
    {
      id: 'text-editor',
      name: 'Text Editor',
      desc: 'Edit text, script, and source code files',
      exts: ['txt', 'md', 'sh', 'py', 'json', 'log', 'cpp', 'h', 'c', 'js', 'html', 'css'],
      iconColor: 'var(--ico-accent, #60cdff)'
    },
    {
      id: 'image-viewer',
      name: 'Image Viewer',
      desc: 'View images, photos, and vector graphics',
      exts: ['png', 'jpg', 'jpeg', 'gif', 'svg', 'bmp', 'webp', 'ico'],
      iconColor: 'var(--ico-alt, #fce100)'
    },
    {
      id: 'terminal',
      name: 'Terminal',
      desc: 'Run or inspect file via terminal commands',
      exts: ['sh', 'bash', 'py', 'bin'],
      iconColor: '#50e3c2'
    },
    {
      id: 'web-browser',
      name: 'Web Browser',
      desc: 'Open document or media in web browser',
      exts: ['html', 'htm', 'svg', 'pdf', 'url'],
      iconColor: '#ff9500'
    },
    {
      id: 'archive-manager',
      name: 'Archive Manager',
      desc: 'Inspect and extract archive contents',
      exts: ['zip', 'tar', 'gz', '7z', 'rar'],
      iconColor: '#b8e986'
    }
  ];

  function ensureOpenWithDialog() {
    if (openWithScrim && openWithScrim.parentElement) return openWithScrim;
    openWithScrim = document.querySelector('.open-with-scrim');
    if (!openWithScrim) {
      openWithScrim = document.createElement('div');
      openWithScrim.className = 'open-with-scrim';
      openWithScrim.hidden = true;

      var dialog = document.createElement('div');
      dialog.className = 'open-with-dialog';

      var title = document.createElement('h3');
      title.className = 'open-with-title';
      title.textContent = 'How do you want to open this file?';

      var subtitle = document.createElement('div');
      subtitle.className = 'open-with-subtitle';

      var list = document.createElement('div');
      list.className = 'open-with-list';

      var footer = document.createElement('div');
      footer.className = 'open-with-footer';

      var cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 'open-with-btn open-with-cancel';
      cancelBtn.textContent = 'Cancel';

      var okBtn = document.createElement('button');
      okBtn.type = 'button';
      okBtn.className = 'open-with-btn primary open-with-ok';
      okBtn.textContent = 'Open';

      footer.appendChild(cancelBtn);
      footer.appendChild(okBtn);

      dialog.appendChild(title);
      dialog.appendChild(subtitle);
      dialog.appendChild(list);
      dialog.appendChild(footer);
      openWithScrim.appendChild(dialog);
      document.body.appendChild(openWithScrim);
    }
    return openWithScrim;
  }

  function openWith(item) {
    var targets = getActiveTargets(item);
    if (!targets.length) return;
    var it = targets[0];
    var fileName = it.getAttribute('data-n') || it.textContent.trim();

    var scrim = ensureOpenWithDialog();
    var subtitle = scrim.querySelector('.open-with-subtitle');
    subtitle.textContent = 'Choose an app to open "' + fileName + '"';

    var list = scrim.querySelector('.open-with-list');
    list.replaceChildren();

    var dotIndex = fileName.lastIndexOf('.');
    var ext = dotIndex > 0 ? fileName.slice(dotIndex + 1).toLowerCase() : '';

    var sortedApps = AVAILABLE_APPS.slice().sort(function (a, b) {
      var aMatch = a.exts.indexOf(ext) >= 0 ? 1 : 0;
      var bMatch = b.exts.indexOf(ext) >= 0 ? 1 : 0;
      return bMatch - aMatch;
    });

    var selectedApp = sortedApps[0];

    sortedApps.forEach(function (app, index) {
      var appEl = document.createElement('div');
      appEl.className = 'open-with-app open-with-app-card' + (index === 0 ? ' selected' : '');
      appEl.tabIndex = 0;

      var iconSpan = document.createElement('span');
      iconSpan.className = 'open-with-app-icon';
      var appSvg = createSvg(28, 28, '0 0 28 28');
      var p = createSvgPath('M4 4h20v20H4z', app.iconColor);
      appSvg.appendChild(p);
      iconSpan.appendChild(appSvg);
      appEl.appendChild(iconSpan);

      var details = document.createElement('div');
      details.className = 'open-with-app-details';
      var nameEl = document.createElement('div');
      nameEl.className = 'open-with-app-name';
      nameEl.textContent = app.name;
      var descEl = document.createElement('div');
      descEl.className = 'open-with-app-desc';
      descEl.textContent = app.desc;
      details.appendChild(nameEl);
      details.appendChild(descEl);
      appEl.appendChild(details);

      appEl.addEventListener('click', function () {
        list.querySelectorAll('.open-with-app').forEach(function (el) {
          el.classList.remove('selected');
        });
        appEl.classList.add('selected');
        selectedApp = app;
      });

      appEl.addEventListener('dblclick', function () {
        closeModal();
        showToast('Opening "' + fileName + '" with ' + app.name + '...');
      });

      list.appendChild(appEl);
    });

    function closeModal() {
      scrim.hidden = true;
      scrim.classList.remove('visible');
      document.removeEventListener('keydown', onKeyDown);
    }

    function onKeyDown(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeModal();
      }
    }

    var cancelBtn = scrim.querySelector('.open-with-cancel');
    var okBtn = scrim.querySelector('.open-with-ok');

    cancelBtn.onclick = function () {
      closeModal();
    };

    okBtn.onclick = function () {
      closeModal();
      if (selectedApp) {
        showToast('Opening "' + fileName + '" with ' + selectedApp.name + '...');
      }
    };

    scrim.onclick = function (e) {
      if (e.target === scrim) closeModal();
    };

    document.addEventListener('keydown', onKeyDown);
    scrim.hidden = false;
    scrim.classList.add('visible');
  }

  function compressToZip(items) {
    var targets = getActiveTargets(items);
    if (!targets.length) return;
    var name = targets[0].getAttribute('data-n') || targets[0].textContent.trim();
    var zipName = (name.lastIndexOf('.') > 0 ? name.slice(0, name.lastIndexOf('.')) : name) + '.zip';

    if (window.StatusCenter && typeof window.StatusCenter.addTask === 'function') {
      try {
        var task = window.StatusCenter.addTask({
          title: 'Compressing to ' + zipName,
          state: 'InProgress',
          progress: 30
        });
        setTimeout(function () {
          if (task && typeof task.update === 'function') {
            task.update({ state: 'Successful', progress: 100 });
          }
        }, 600);
      } catch (err) {}
    }

    showToast('Compressed to ' + zipName);
  }

  /* ==========================================================================
     11. Visual Group By Engine
     ========================================================================== */

  var currentGroupBy = 'None';
  // Files keeps three settings for grouping, not one: what to group by, how
  // fine a date group is, and which way the groups run. GroupByDateModified
  // is the field; Year, Month and Day are the unit; Ascending and Descending
  // are the direction. Three commands each, and each of them says which of
  // the three it sets.
  var currentGroupUnit = 'year';
  var currentGroupDir = 1;

  function createGroupHeader(title, count, items) {
    var header = document.createElement('div');
    header.className = 'group-header';

    var chev = document.createElement('span');
    chev.className = 'group-chevron';
    var cSvg = createSvg(12, 12, '0 0 12 12');
    cSvg.appendChild(createSvgPath('M2.5 4.5L6 8L9.5 4.5', null, 'currentColor', 1.25, 'round', 'round'));
    chev.appendChild(cSvg);
    header.appendChild(chev);

    var tSpan = document.createElement('span');
    tSpan.className = 'group-title';
    tSpan.textContent = title;
    header.appendChild(tSpan);

    var cSpan = document.createElement('span');
    cSpan.className = 'group-count';
    cSpan.textContent = count + (count === 1 ? ' item' : ' items');
    header.appendChild(cSpan);

    var lSpan = document.createElement('span');
    lSpan.className = 'group-line';
    header.appendChild(lSpan);

    header.addEventListener('click', function () {
      var isCollapsed = header.classList.toggle('collapsed');
      items.forEach(function (it) {
        if (isCollapsed) {
          it.classList.add('group-item-hidden');
        } else {
          it.classList.remove('group-item-hidden');
        }
      });
    });

    return header;
  }

  function getGroupKey(item, field) {
    var f = field.toLowerCase();
    if (f === 'name') {
      var name = item.getAttribute('data-n') || item.textContent.trim();
      var ch = name.charAt(0).toUpperCase();
      if (ch >= 'A' && ch <= 'D') return 'A - D';
      if (ch >= 'E' && ch <= 'H') return 'E - H';
      if (ch >= 'I' && ch <= 'L') return 'I - L';
      if (ch >= 'M' && ch <= 'P') return 'M - P';
      if (ch >= 'Q' && ch <= 'T') return 'Q - T';
      if (ch >= 'U' && ch <= 'Z') return 'U - Z';
      if (ch >= '0' && ch <= '9') return '0 - 9';
      return 'Other';
    } else if (f === 'date modified' || f === 'date') {
      if (currentGroupUnit !== 'relative') return dateBucket(item, currentGroupUnit);
      var w = item.getAttribute('data-w') || '';
      if (w.indexOf('2026') >= 0 || w.indexOf('Sep') >= 0) return 'Earlier this year';
      if (w) return 'Earlier';
      return 'Date unspecified';
    } else if (f === 'size') {
      var k = item.getAttribute('data-k') || '';
      if (k === 'Folder') return 'Folders';
      var sb = parseInt(item.getAttribute('data-sb') || '-1', 10);
      if (sb < 0) return 'Folders';
      if (sb <= 16384) return 'Tiny (0 - 16 KB)';
      if (sb <= 1048576) return 'Small (16 KB - 1 MB)';
      if (sb <= 134217728) return 'Medium (1 MB - 128 MB)';
      if (sb <= 1073741824) return 'Large (128 MB - 1 GB)';
      return 'Huge (> 1 GB)';
    } else if (f === 'type') {
      return item.getAttribute('data-k') || 'Unknown';
    } else if (f === 'tag' || f === 'tags') {
      var tg = (item.getAttribute('data-tags') || '').split(',')
        .map(function (x) { return x.trim(); }).filter(Boolean);
      return tg.length ? tg[0] : 'No tag';
    } else if (f === 'folder path' || f === 'original folder') {
      var pth = item.getAttribute('data-p') || '';
      var cut = pth.lastIndexOf('/');
      return cut > 0 ? pth.slice(0, cut) : (pth || 'Unknown');
    } else if (f === 'sync status') {
      return item.getAttribute('data-sync') || 'Not synced';
    } else if (f === 'date created' || f === 'date deleted') {
      return dateBucket(item, currentGroupUnit);
    } else if (f === 'year') {
      return dateBucket(item, 'year');
    } else if (f === 'month') {
      return dateBucket(item, 'month');
    } else if (f === 'day') {
      return dateBucket(item, 'day');
    }
    return 'All items';
  }

  // Files groups dates by year, month or day, and the unit is a separate
  // choice from the field. The row carries the time it happened as an epoch
  // in data-ms, which is the only thing here that survives a locale.
  function dateBucket(item, unit) {
    var ms = parseInt(item.getAttribute('data-ms') || '0', 10);
    if (!ms) return 'Date unspecified';
    var d = new Date(ms);
    if (unit === 'year') return String(d.getFullYear());
    if (unit === 'month') {
      return d.toLocaleString(undefined, {month: 'long', year: 'numeric'});
    }
    return d.toLocaleDateString();
  }

  // Across the scope boundary, because the command registry lives in the next
  // one down and a bare setGroupBy there is a NameError at click time.
  window.__setGroupBy = function (field) { setGroupBy(field); };
  window.__groupBy = function () { return currentGroupBy; };
  window.__groupUnit = function () { return currentGroupUnit; };
  window.__groupDir = function () { return currentGroupDir; };
  window.__setGroupUnit = function (unit) {
    currentGroupUnit = unit || 'year';
    setGroupBy(currentGroupBy);
  };
  window.__setGroupDir = function (dir) {
    currentGroupDir = dir < 0 ? -1 : 1;
    document.documentElement.setAttribute(
      'data-groupdir', currentGroupDir === 1 ? 'asc' : 'desc');
    setGroupBy(currentGroupBy);
  };

  function setGroupBy(field) {
    currentGroupBy = field || 'None';
    var layouts = getLayoutContainers();

    for (var i = 0; i < layouts.length; i++) {
      var lRec = layouts[i];
      if (!lRec.container) continue;

      var existingHeaders = lRec.container.querySelectorAll('.group-header');
      existingHeaders.forEach(function (h) {
        if (h.parentNode) h.parentNode.removeChild(h);
      });

      var items = Array.from(lRec.container.querySelectorAll(lRec.selector));
      items.forEach(function (it) {
        it.classList.remove('group-item-hidden');
      });

      if (currentGroupBy.toLowerCase() === 'none') {
        continue;
      }

      var groupsMap = new Map();
      items.forEach(function (it) {
        var key = getGroupKey(it, currentGroupBy);
        if (!groupsMap.has(key)) {
          groupsMap.set(key, []);
        }
        groupsMap.get(key).push(it);
      });

      var keys = Array.from(groupsMap.keys()).sort(function (a, b) {
        return String(a).localeCompare(String(b), undefined,
          {numeric: true, sensitivity: 'base'}) * currentGroupDir;
      });
      keys.forEach(function (gKey) {
        var gItems = groupsMap.get(gKey);
        var header = createGroupHeader(gKey, gItems.length, gItems);
        lRec.container.appendChild(header);
        gItems.forEach(function (it) {
          lRec.container.appendChild(it);
        });
      });
    }

    showToast('Grouped by: ' + currentGroupBy);
  }

  /* ==========================================================================
     12. Context Menu Upgrades
     ========================================================================== */

  function createMenuItem(title, action, iconSvg, shortcutText) {
    var mi = document.createElement('div');
    mi.className = 'mi';
    if (action) mi.setAttribute('data-act', action);

    var ic = document.createElement('span');
    ic.className = 'mi-ic';
    if (iconSvg) ic.appendChild(iconSvg);
    mi.appendChild(ic);

    var t = document.createElement('span');
    t.className = 'mi-t';
    t.textContent = title;
    mi.appendChild(t);

    if (shortcutText) {
      var sc = document.createElement('span');
      sc.className = 'shortcut';
      sc.textContent = shortcutText;
      mi.appendChild(sc);
    }

    return mi;
  }

  function createSubmenuItem(title, items, iconSvg) {
    var mi = document.createElement('div');
    mi.className = 'mi mi-sub';

    var ic = document.createElement('span');
    ic.className = 'mi-ic';
    if (iconSvg) ic.appendChild(iconSvg);
    mi.appendChild(ic);

    var t = document.createElement('span');
    t.className = 'mi-t';
    t.textContent = title;
    mi.appendChild(t);

    var chev = document.createElement('span');
    chev.className = 'mchev';
    var cSvg = createSvg(12, 12, '0 0 12 12');
    cSvg.appendChild(createSvgPath('M4.5 2.5L8 6L4.5 9.5', null, 'currentColor', 1.25, 'round', 'round'));
    chev.appendChild(cSvg);
    mi.appendChild(chev);

    var sub = document.createElement('div');
    sub.className = 'ctx-sub';
    for (var i = 0; i < items.length; i++) {
      if (items[i] === 'sep') {
        var sep = document.createElement('div');
        sep.className = 'msep';
        sub.appendChild(sep);
      } else {
        sub.appendChild(items[i]);
      }
    }
    mi.appendChild(sub);

    return mi;
  }

  function upgradeContextMenus() {
    // The item and background menus used to be patched here at run time:
    // rows found by their caption and stamped with a `data-act`, and a Group
    // by submenu and a Paste row appended when the ones it looked for were
    // not found. Both menus are now generated from assets/files-menus.json
    // and carry `data-command`, so every lookup here missed and the appending
    // ran: a second Group by, empty, at the bottom of the background menu,
    // and captions rewired away from the command registry. Deleted rather
    // than taught the new attribute, because there is nothing left for it to
    // add: the generated menus already hold every row it was adding, in the
    // reference's own order.

    // 3. Upgrade #ctx-drive
    var ctxDrive = document.getElementById('ctx-drive');
    if (!ctxDrive) {
      ctxDrive = document.createElement('div');
      ctxDrive.className = 'ctx';
      ctxDrive.id = 'ctx-drive';
      ctxDrive.hidden = true;
      document.body.appendChild(ctxDrive);
    }

    var driveItems = [
      { title: 'Open', act: 'ctx-open' },
      { title: 'Open in new tab', act: 'ctx-opentab' },
      { title: 'Open in new window', act: 'ctx-openwin' },
      { title: 'Pin to sidebar', act: 'ctx-pin' },
      { title: 'Format...', act: 'format-drive' },
      { title: 'Properties', act: 'ctx-props' }
    ];

    driveItems.forEach(function (def) {
      if (!ctxDrive.querySelector('[data-act="' + def.act + '"]')) {
        ctxDrive.appendChild(createMenuItem(def.title, def.act));
      }
    });
  }

  /* ==========================================================================
     13. Action Dispatcher and window.doAct Wiring
     ========================================================================== */

  var origDoAct = window.doAct || window.__doAct;

  //: What an act works on. `el` is the row or the button that was clicked,
  //: not the item, and treating it as the item had the context menu's Delete
  //: asking about "item" and deleting nothing, and the toolbar's Cut cutting
  //: the button. The selection is the item, as in the reference, where a
  //: right click selects first and every command reads the selection. The
  //: thing under the last right click only counts for a menu that opened
  //: over what no click selects: a widget card or a sidebar row. Before,
  //: it counted first, so a command reached the last right clicked item
  //: rather than the one selected since.
  function itemsFor(el) {
    if (el && el.getAttribute && !el.closest('.mi, .tbtn, .menu, .ctx, .toolbar') &&
        (el.hasAttribute('data-n') || el.hasAttribute('data-p'))) {
      return [el];
    }
    var over = lastContextTarget;
    if (over && over.isConnected && el && el.closest && el.closest('.ctx, .menu') &&
        !over.matches('.cell, .row, .lrow, .tile, .crow')) {
      return [over];
    }
    return undefined;
  }
  function handleAction(act, el) {
    var items = itemsFor(el);
    var target = items ? items[0] : (getActiveTargets()[0] || null);
    switch (act) {
      case 'cut':
        cut(items);
        return true;
      case 'copy':
        copy(items);
        return true;
      case 'paste':
        paste();
        return true;
      //: Rename is not answered here. It was, with a second rename dialog
      //: of this engine's own, and F2 opened that one and the page's on top
      //: of each other; the page's is the one whose Rename knows about a
      //: bulk rename and whose name checks are gated.
      case 'trash':
      case 'delete':
        deleteItems(items);
        return true;
      case 'undo':
        undo();
        return true;
      case 'ctx-pin':
        pinToSidebar(target);
        return true;
      case 'ctx-pin-qa':
        pinToQuickAccess(target);
        return true;
      case 'ctx-unpin-qa':
        unpinFromQuickAccess(target ? (target.getAttribute('data-p') || target.getAttribute('data-path') || target.getAttribute('data-n')) : null);
        return true;
      case 'ctx-openwith':
        openWith(target);
        return true;
      case 'ctx-zip':
        compressToZip(target ? [target] : undefined);
        return true;
      case 'paste-folder':
        var folderPath = target ? (target.getAttribute('data-p') || target.getAttribute('data-path')) : null;
        pasteIntoFolder(folderPath);
        return true;
      case 'group-none':
        setGroupBy('None');
        return true;
      case 'group-name':
        setGroupBy('Name');
        return true;
      case 'group-date':
        setGroupBy('Date modified');
        return true;
      case 'group-size':
        setGroupBy('Size');
        return true;
      case 'group-type':
        setGroupBy('Type');
        return true;
      default:
        return false;
    }
  }

  //: With a backend up, the acts that touch files are the live layer's.
  //: This engine was answering them on the screen alone: Delete took the
  //: row out of the list and left the file on the disk, Copy and Paste
  //: cloned nodes, and the backend was never asked.
  var LIVE_OWNS = ['cut', 'copy', 'paste', 'rename', 'trash', 'delete',
                   'newfolder', 'newfile', 'newshortcut'];
  function wiredDoAct(act, el) {
    if (document.body.getAttribute('data-live') === '1' &&
        LIVE_OWNS.indexOf(act) >= 0 && typeof origDoAct === 'function') {
      return origDoAct(act, el);
    }
    var handled = handleAction(act, el);
    if (!handled && typeof origDoAct === 'function') {
      return origDoAct(act, el);
    }
  }

  window.doAct = wiredDoAct;
  window.__doAct = wiredDoAct;

  /* ==========================================================================
     14. Keyboard Shortcuts Engine
     ========================================================================== */

  document.addEventListener('keydown', function (e) {
    var tag = (e.target && e.target.tagName) ? e.target.tagName.toUpperCase() : '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target && e.target.isContentEditable)) {
      return;
    }

    var isMod = e.ctrlKey || e.metaKey;

    if (isMod && (e.key === 'c' || e.key === 'C')) {
      e.preventDefault();
      copy();
    } else if (isMod && (e.key === 'x' || e.key === 'X')) {
      e.preventDefault();
      cut();
    } else if (isMod && (e.key === 'v' || e.key === 'V')) {
      e.preventDefault();
      paste();
    } else if (isMod && (e.key === 'z' || e.key === 'Z')) {
      e.preventDefault();
      undo();
    } else if (e.key === 'Delete' || e.key === 'Del') {
      e.preventDefault();
      deleteItems();
    }
  });

  /* ==========================================================================
     14b. Breadcrumbs Dropdown Chevrons Engine
     ========================================================================== */

  function upgradeBreadcrumbChevrons() {
    var crumbsBox = document.getElementById('crumbs');
    if (!crumbsBox) return;

    var cseps = Array.from(crumbsBox.querySelectorAll('.csep'));
    cseps.forEach(function (sep) {
      if (sep.closest('.cwrap')) return;

      var prev = sep.previousElementSibling;
      while (prev && !prev.classList.contains('crumb')) {
        prev = prev.previousElementSibling;
      }
      var parentPath = prev ? prev.getAttribute('data-p') : window.__homePath();
      var cat = window.__DIR_CATALOG || {};
      var entry = cat[parentPath] || (parentPath ? cat[parentPath.replace(/\/+$/, '')] : null);
      var folders = [];

      if (!parentPath || window.__isHome(parentPath)) {
        var qa = ['Desktop', 'Documents', 'Downloads', 'Music', 'Pictures', 'Videos'];
        qa.forEach(function (f) {
          folders.push({ name: f, path: window.__homePath() + '/' + f });
        });
      } else if (entry && entry.items) {
        entry.items.forEach(function (it) {
          if (it.isDir || it.kind === 'Folder') {
            folders.push({ name: it.name, path: it.path || (parentPath + '/' + it.name) });
          }
        });
      }

      if (folders.length === 0) return;

      var cwrap = document.createElement('span');
      cwrap.className = 'cwrap';

      var btn = document.createElement('button');
      btn.className = 'cchev';
      btn.setAttribute('title', 'Show child folders');
      var svg = createSvg(8, 8, '0 0 8 8');
      svg.setAttribute('class', 'caret');
      svg.appendChild(createSvgPath('M2.75 1.5L5.25 4L2.75 6.5', null, 'currentColor', 1.2, 'round', 'round'));
      btn.appendChild(svg);
      cwrap.appendChild(btn);

      var menu = document.createElement('div');
      menu.className = 'menu';
      menu.hidden = true;

      folders.forEach(function (f) {
        var mi = document.createElement('a');
        mi.className = 'mi';
        mi.setAttribute('data-p', f.path);
        mi.setAttribute('data-n', f.name);
        var ic = document.createElement('span');
        ic.className = 'mi-ic';
        var t = document.createElement('span');
        t.className = 'mi-t';
        t.textContent = f.name;
        mi.appendChild(ic);
        mi.appendChild(t);

        mi.addEventListener('click', function (ev) {
          ev.preventDefault();
          menu.hidden = true;
          if (typeof window.navigateTo === 'function') {
            window.navigateTo(f.path, f.name, false, true);
          } else if (typeof window.navigateActiveTab === 'function') {
            window.navigateActiveTab(f.path, f.name, false);
          } else {
            var opath = document.getElementById('opath');
            if (opath) {
              opath.value = f.path;
              opath.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            }
          }
        });
        menu.appendChild(mi);
      });

      cwrap.appendChild(menu);
      if (sep.parentNode) {
        sep.parentNode.replaceChild(cwrap, sep);
      }
    });
  }

  function setupBreadcrumbObserver() {
    var crumbsBox = document.getElementById('crumbs');
    if (!crumbsBox) return;

    upgradeBreadcrumbChevrons();

    var observer = new MutationObserver(function () {
      upgradeBreadcrumbChevrons();
    });

    observer.observe(crumbsBox, { childList: true, subtree: false });
  }

  /* ==========================================================================
     15. Initialization and Persistence Hydration
     ========================================================================== */

  function init() {
    if (typeof window.navigateTo !== 'function') {
      window.navigateTo = function (path, name, isHome, pushHistory) {
        var p = path || (isHome ? '~' : window.__homePath());
        var opath = document.getElementById('opath');
        if (opath) {
          opath.value = p;
          opath.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        }
      };
    }
    if (typeof window.navigateActiveTab !== 'function') {
      window.navigateActiveTab = function (path, name, isHome) {
        window.navigateTo(path, name, isHome, true);
      };
    }
    if (typeof window.setLayout !== 'function' && typeof window.__setLayout === 'function') {
      window.setLayout = window.__setLayout;
    }

    document.addEventListener('keydown', function (e) {
      if (e.altKey && !e.ctrlKey && !e.metaKey && (e.key === 'p' || e.key === 'P')) {
        e.preventDefault();
        var b = document.getElementById('btn-pane');
        if (b) b.click();
      }
    });

    if (typeof window.openProps !== 'function') {
      window.openProps = function (target) {
        if (typeof window.doAct === 'function') {
          window.doAct('ctx-props');
        } else if (typeof window.__doAct === 'function') {
          window.__doAct('ctx-props');
        } else {
          var pb = document.querySelector('[data-act="ctx-props"]');
          if (pb) pb.click();
        }
      };
    }

    ensureActionToast();
    upgradeContextMenus();
    setupBreadcrumbObserver();

    // Hydrate pinned items
    var sidebarPinned = getPinnedSidebar();
    for (var i = 0; i < sidebarPinned.length; i++) {
      renderPinnedSidebarItem(sidebarPinned[i].name, sidebarPinned[i].path);
    }

    var qaPinned = getPinnedQA();
    for (var j = 0; j < qaPinned.length; j++) {
      renderQuickAccessCard(qaPinned[j].name, qaPinned[j].path);
    }

    updateToolbarButtons();
    updateStatusBar();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /* ==========================================================================
     16. Exposed API Surface
     ========================================================================== */

  return {
    cut: cut,
    copy: copy,
    paste: paste,
    pasteIntoFolder: pasteIntoFolder,
    rename: rename,
    delete: deleteItems,
    undo: undo,
    pinToSidebar: pinToSidebar,
    unpinFromSidebar: unpinFromSidebar,
    pinToQuickAccess: pinToQuickAccess,
    unpinFromQuickAccess: unpinFromQuickAccess,
    openWith: openWith,
    setGroupBy: setGroupBy,
    showToast: showToast,
    updateToolbar: updateToolbarButtons,
    getClipboard: function () { return clipboard; },
    upgradeBreadcrumbChevrons: upgradeBreadcrumbChevrons,
    navigateTo: function (path, name, isHome, pushHistory) {
      if (typeof window.navigateTo === 'function') {
        window.navigateTo(path, name, isHome, pushHistory);
      }
    },
    init: init
  };
});

  })();

