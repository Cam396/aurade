  // =========================================================================
  // Wave 5: Drag and Drop (P11) and WinUI 3 File Conflict Dialog (P12)
  // =========================================================================
  (function() {
/**
 * Wave 5: Drag and Drop (P11) and WinUI 3 File Conflict Dialog (P12)
 * For AuraDE Files Fluent Design System.
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
    var exports = factory();
    root.Wave5DnD = exports;
    root.setupDragAndDropAndConflict = exports.setupDragAndDropAndConflict;
    root.FileConflictDialog = exports.FileConflictDialog;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';

  /* ==========================================================================
     1. SVG Helpers (Trusted Types compliant)
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

  function createFileIcon() {
    var svg = createSvg(24, 24, '0 0 24 24');
    var doc = createSvgPath('M6 2a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6H6z', 'rgba(255,255,255,0.15)', 'currentColor', 1.2);
    var fold = createSvgPath('M14 2v6h6', 'none', 'currentColor', 1.2);
    var line1 = createSvgPath('M8 12h8', 'none', 'currentColor', 1.2, 'round');
    var line2 = createSvgPath('M8 15h8', 'none', 'currentColor', 1.2, 'round');
    var line3 = createSvgPath('M8 18h5', 'none', 'currentColor', 1.2, 'round');
    svg.appendChild(doc);
    svg.appendChild(fold);
    svg.appendChild(line1);
    svg.appendChild(line2);
    svg.appendChild(line3);
    return svg;
  }

  function createFolderIcon() {
    var svg = createSvg(24, 24, '0 0 24 24');
    var f = createSvgPath('M2 6a2 2 0 0 1 2-2h5l2 2h9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6z', 'color-mix(in srgb, var(--accent, #60cdff) 25%, transparent)', 'var(--accent, #60cdff)', 1.2);
    svg.appendChild(f);
    return svg;
  }

  /* ==========================================================================
     2. Unique Name Generator Helper
     ========================================================================== */

  function parseNameAndExtension(filename) {
    var dotIdx = filename.lastIndexOf('.');
    if (dotIdx <= 0) {
      return { base: filename, ext: '' };
    }
    return {
      base: filename.slice(0, dotIdx),
      ext: filename.slice(dotIdx)
    };
  }

  function generateUniqueName(name, existingNames) {
    var set = new Set();
    if (Array.isArray(existingNames)) {
      for (var i = 0; i < existingNames.length; i++) {
        set.add(existingNames[i]);
      }
    } else if (existingNames instanceof Set) {
      set = existingNames;
    }
    if (!set.has(name)) {
      return name;
    }
    var parsed = parseNameAndExtension(name);
    var base = parsed.base;
    var ext = parsed.ext;

    var match = base.match(/^(.+) [(]([0-9]+)[)]$/);
    var stem = base;
    var counter = 1;
    if (match) {
      stem = match[1];
      counter = parseInt(match[2], 10) + 1;
    }
    while (true) {
      var candidate = stem + ' (' + counter + ')' + ext;
      if (!set.has(candidate)) {
        return candidate;
      }
      counter++;
    }
  }

  /* ==========================================================================
     3. Drag Ghost Thumbnail Helper
     ========================================================================== */

  function createDragGhost(items) {
    var ghost = document.createElement('div');
    ghost.className = 'dnd-ghost drag-ghost';

    var iconWrap = document.createElement('span');
    iconWrap.className = 'dnd-ghost-icon';
    var isAnyFolder = items.some(function (it) {
      return it.kind === 'Folder' || it.kind === 'folder';
    });
    iconWrap.appendChild(isAnyFolder ? createFolderIcon() : createFileIcon());
    ghost.appendChild(iconWrap);

    var label = document.createElement('span');
    label.className = 'dnd-ghost-label';
    if (items.length === 1) {
      label.textContent = items[0].name || 'File';
    } else {
      label.textContent = String(items.length) + ' items';
    }
    ghost.appendChild(label);

    var badge = document.createElement('span');
    badge.className = 'dnd-ghost-badge';
    badge.textContent = String(items.length);
    ghost.appendChild(badge);

    return ghost;
  }

  /* ==========================================================================
     4. WinUI 3 File Conflict Dialog Controller
     ========================================================================== */

  var activeDialogBackdrop = null;
  var activeDialogResolve = null;

  var FileConflictDialog = {
    show: function (options) {
      options = options || {};
      FileConflictDialog.hide();

      return new Promise(function (resolve) {
        activeDialogResolve = resolve;

        var sourceItem = options.sourceItem || {
          name: 'source_file.txt',
          size: '12 KB',
          date: 'Today',
          kind: 'File'
        };
        var targetItem = options.targetItem || options.destinationItem || {
          name: sourceItem.name,
          size: '15 KB',
          date: 'Yesterday',
          kind: sourceItem.kind || 'File'
        };
        var conflictIndex = options.conflictIndex || 1;
        var totalConflicts = options.totalConflicts || 1;
        var existingNames = options.existingNames || [targetItem.name];
        var onResolve = options.onResolve;

        var backdrop = document.createElement('div');
        backdrop.className = 'conflict-dialog-backdrop';
        backdrop.setAttribute('role', 'presentation');

        var dialog = document.createElement('div');
        dialog.className = 'conflict-dialog';
        dialog.setAttribute('role', 'dialog');
        dialog.setAttribute('aria-modal', 'true');
        dialog.setAttribute('aria-labelledby', 'conflict-dialog-title');

        /* Header */
        var header = document.createElement('div');
        header.className = 'conflict-dialog-header';

        var title = document.createElement('h2');
        title.id = 'conflict-dialog-title';
        title.className = 'conflict-dialog-title';
        title.textContent = options.title || 'There is already a file with the same name in this location';
        header.appendChild(title);

        var subtitle = document.createElement('div');
        subtitle.className = 'conflict-dialog-subtitle';
        var subText;
        if (totalConflicts > 1) {
          subText = 'Conflict ' + conflictIndex + ' of ' + totalConflicts + ': A file named "' + sourceItem.name + '" already exists in destination.';
        } else {
          subText = 'A file named "' + sourceItem.name + '" already exists in this folder. Which file do you want to keep?';
        }
        subtitle.textContent = subText;
        header.appendChild(subtitle);
        dialog.appendChild(header);

        /* Comparison Grid */
        var grid = document.createElement('div');
        grid.className = 'conflict-comparison-grid';

        function buildCard(item, isSource) {
          var card = document.createElement('div');
          card.className = 'conflict-card ' + (isSource ? 'conflict-card-source' : 'conflict-card-target');

          var cardH = document.createElement('div');
          cardH.className = 'conflict-card-header';

          var badge = document.createElement('span');
          badge.className = 'conflict-badge';
          badge.textContent = isSource ? 'Source' : 'Destination';
          cardH.appendChild(badge);
          card.appendChild(cardH);

          var preview = document.createElement('div');
          preview.className = 'conflict-card-preview';

          var iconBox = document.createElement('div');
          iconBox.className = 'conflict-card-icon';
          var isF = (item.kind === 'Folder' || item.kind === 'folder');
          iconBox.appendChild(isF ? createFolderIcon() : createFileIcon());
          preview.appendChild(iconBox);

          var info = document.createElement('div');
          info.className = 'conflict-card-info';

          var nameEl = document.createElement('div');
          nameEl.className = 'conflict-card-name';
          nameEl.textContent = item.name || 'Unnamed';
          nameEl.setAttribute('title', item.name || '');
          info.appendChild(nameEl);

          var meta = document.createElement('div');
          meta.className = 'conflict-card-meta';

          var sizeEl = document.createElement('div');
          sizeEl.className = 'conflict-card-size';
          sizeEl.textContent = item.size ? ('Size: ' + item.size) : 'Size: Unknown';
          meta.appendChild(sizeEl);

          var dateEl = document.createElement('div');
          dateEl.className = 'conflict-card-date';
          dateEl.textContent = item.date ? ('Modified: ' + item.date) : 'Modified: Unknown';
          meta.appendChild(dateEl);

          info.appendChild(meta);
          preview.appendChild(info);
          card.appendChild(preview);

          return card;
        }

        grid.appendChild(buildCard(sourceItem, true));
        grid.appendChild(buildCard(targetItem, false));
        dialog.appendChild(grid);

        /* Options list */
        var optionsList = document.createElement('div');
        optionsList.className = 'conflict-options-list';
        optionsList.setAttribute('role', 'radiogroup');

        var generatedName = generateUniqueName(sourceItem.name, existingNames);
        var selectedAction = options.defaultAction || 'replace';

        var optionDefs = [
          {
            action: 'replace',
            title: 'Replace the file in destination',
            desc: 'Overwrite the existing file'
          },
          {
            action: 'keep_both',
            title: 'Generate a new name: ' + generatedName,
            desc: 'Keep both files and rename the incoming file to ' + generatedName
          },
          {
            action: 'skip',
            title: 'Do not copy this file',
            desc: 'Leave existing file unchanged'
          }
        ];

        var optionCards = [];

        optionDefs.forEach(function (def) {
          var card = document.createElement('div');
          card.className = 'conflict-option-card' + (def.action === selectedAction ? ' selected' : '');
          card.setAttribute('role', 'radio');
          card.setAttribute('tabindex', '0');
          card.setAttribute('data-action', def.action);
          card.setAttribute('aria-checked', def.action === selectedAction ? 'true' : 'false');

          var radio = document.createElement('div');
          radio.className = 'conflict-option-radio';
          var dot = document.createElement('div');
          dot.className = 'conflict-option-radio-dot';
          radio.appendChild(dot);
          card.appendChild(radio);

          var textWrap = document.createElement('div');
          textWrap.className = 'conflict-option-text';

          var titleEl = document.createElement('div');
          titleEl.className = 'conflict-option-title';
          titleEl.textContent = def.title;
          textWrap.appendChild(titleEl);

          var descEl = document.createElement('div');
          descEl.className = 'conflict-option-desc';
          descEl.textContent = def.desc;
          textWrap.appendChild(descEl);

          card.appendChild(textWrap);

          card.addEventListener('click', function () {
            selectedAction = def.action;
            optionCards.forEach(function (c) {
              var isCur = (c === card);
              if (isCur) c.classList.add('selected');
              else c.classList.remove('selected');
              c.setAttribute('aria-checked', isCur ? 'true' : 'false');
            });
          });

          card.addEventListener('keydown', function (e) {
            if (e.key === ' ' || e.key === 'Enter') {
              e.preventDefault();
              card.click();
            }
          });

          optionCards.push(card);
          optionsList.appendChild(card);
        });
        dialog.appendChild(optionsList);

        /* Apply to all conflicts checkbox */
        var applyAllRow = document.createElement('div');
        applyAllRow.className = 'conflict-apply-all-row';

        var applyAllCheckbox = document.createElement('input');
        applyAllCheckbox.type = 'checkbox';
        applyAllCheckbox.id = 'conflict-apply-all-checkbox';
        applyAllCheckbox.className = 'conflict-apply-all-checkbox';
        applyAllCheckbox.checked = !!options.applyToAll;
        applyAllRow.appendChild(applyAllCheckbox);

        var applyAllLabel = document.createElement('label');
        applyAllLabel.setAttribute('for', 'conflict-apply-all-checkbox');
        applyAllLabel.className = 'conflict-apply-all-label';
        applyAllLabel.textContent = 'Apply to all conflicts';
        applyAllRow.appendChild(applyAllLabel);

        dialog.appendChild(applyAllRow);

        /* Footer buttons */
        var footer = document.createElement('div');
        footer.className = 'conflict-dialog-footer';

        var cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'conflict-btn-secondary';
        cancelBtn.textContent = 'Cancel';

        var primaryBtn = document.createElement('button');
        primaryBtn.type = 'button';
        primaryBtn.className = 'conflict-btn-primary';
        primaryBtn.textContent = options.primaryButtonText || 'Continue';

        footer.appendChild(cancelBtn);
        footer.appendChild(primaryBtn);
        dialog.appendChild(footer);

        backdrop.appendChild(dialog);
        document.body.appendChild(backdrop);
        activeDialogBackdrop = backdrop;

        function closeWithResult(action, applyToAllVal, resolvedNameVal) {
          FileConflictDialog.hide();
          if (typeof onResolve === 'function') {
            onResolve(action, applyToAllVal, resolvedNameVal);
          }
          if (activeDialogResolve) {
            var cb = activeDialogResolve;
            activeDialogResolve = null;
            cb({
              action: action,
              applyToAll: applyToAllVal,
              resolvedName: resolvedNameVal
            });
          }
        }

        primaryBtn.addEventListener('click', function () {
          var apply = applyAllCheckbox.checked;
          var resolved;
          if (selectedAction === 'keep_both') {
            resolved = generatedName;
          } else if (selectedAction === 'replace') {
            resolved = targetItem.name;
          } else {
            resolved = null;
          }
          closeWithResult(selectedAction, apply, resolved);
        });

        cancelBtn.addEventListener('click', function () {
          closeWithResult('cancel', false, null);
        });

        backdrop.addEventListener('click', function (e) {
          if (e.target === backdrop) {
            closeWithResult('cancel', false, null);
          }
        });

        dialog.addEventListener('keydown', function (e) {
          if (e.key === 'Escape') {
            e.preventDefault();
            closeWithResult('cancel', false, null);
          }
        });
      });
    },

    hide: function () {
      if (activeDialogBackdrop && activeDialogBackdrop.parentNode) {
        activeDialogBackdrop.parentNode.removeChild(activeDialogBackdrop);
      }
      activeDialogBackdrop = null;
    },

    isOpen: function () {
      return !!(activeDialogBackdrop && document.body.contains(activeDialogBackdrop));
    }
  };

  /* ==========================================================================
     5. Drag and Drop Orchestration
     ========================================================================== */

  function setupDragAndDropAndConflict(options) {
    var opts = options || {};
    var rootEl = (typeof opts.container === 'string')
      ? document.querySelector(opts.container)
      : (opts.container || document.body || document);

    var activeDragItems = [];
    var currentDropTarget = null;

    function extractItemData(el) {
      if (!el || !(el instanceof Element)) return null;
      var name = el.getAttribute('data-n');
      if (!name) {
        var nameEl = el.querySelector('.cname, .lname, .wcard-name, .c-name span:last-child, .lbl');
        name = nameEl ? nameEl.textContent.trim() : (el.textContent.trim() || 'file');
      }
      var path = el.getAttribute('data-p') || el.getAttribute('data-path') || el.getAttribute('href') || ('/' + name);
      var kind = el.getAttribute('data-k') || el.getAttribute('data-kind');
      if (!kind) {
        if (el.classList.contains('wcard-folder')) kind = 'Folder';
        else kind = 'File';
      }
      var size = el.getAttribute('data-s') || '';
      if (!size) {
        var sizeEl = el.querySelector('.c-size');
        if (sizeEl) size = sizeEl.textContent.trim();
      }
      var date = el.getAttribute('data-w') || '';
      if (!date) {
        var dateEl = el.querySelector('.c-when');
        if (dateEl) date = dateEl.textContent.trim();
      }
      return {
        element: el,
        name: name,
        path: path,
        kind: kind,
        size: size,
        date: date
      };
    }

    function makeDraggable() {
      var items = rootEl.querySelectorAll('.cell, .row, .lrow, .tile, .crow, .wcard');
      for (var i = 0; i < items.length; i++) {
        if (!items[i].hasAttribute('draggable')) {
          items[i].setAttribute('draggable', 'true');
        }
      }
    }
    makeDraggable();

    var observer = new MutationObserver(function () {
      makeDraggable();
    });
    observer.observe(rootEl, { childList: true, subtree: true });

    function findDropTarget(el) {
      if (!el || !(el instanceof Element)) return null;

      // 1. Folder item
      var item = el.closest('.cell, .row, .lrow, .tile, .crow, .wcard');
      if (item) {
        var k = item.getAttribute('data-k') || item.getAttribute('data-kind');
        var isF = (k === 'Folder' || k === 'folder' || item.classList.contains('wcard-folder'));
        if (isF) return item;
        return null;
      }

      // 2. Breadcrumb
      var crumb = el.closest('.crumb');
      if (crumb) return crumb;

      // 3. Sidebar navigation item
      var sitem = el.closest('.srow.item, .srow[data-root], .sitem');
      if (sitem) return sitem;

      // 4. Dual pane or pane content
      var pane = el.closest('.pane-content, .pane');
      if (pane) return pane;

      // 5. Filearea container
      var area = el.closest('.filearea');
      if (area) return area;

      return null;
    }

    function clearActiveDropTargets() {
      var list = document.querySelectorAll('.drop-target-active');
      for (var i = 0; i < list.length; i++) {
        list[i].classList.remove('drop-target-active');
      }
      currentDropTarget = null;
    }

    function getExistingFileNamesForTarget(target, destPath) {
      var names = new Set();

      if (typeof opts.getExistingNames === 'function') {
        var custom = opts.getExistingNames(destPath, target);
        if (Array.isArray(custom)) {
          for (var i = 0; i < custom.length; i++) names.add(custom[i]);
        }
      }

      if (window.__existingFiles) {
        if (Array.isArray(window.__existingFiles)) {
          for (var j = 0; j < window.__existingFiles.length; j++) names.add(window.__existingFiles[j]);
        } else if (typeof window.__existingFiles[destPath] === 'object') {
          var arr = window.__existingFiles[destPath];
          for (var k = 0; k < arr.length; k++) names.add(arr[k]);
        }
      }

      if (target && target.__existingFiles) {
        for (var l = 0; l < target.__existingFiles.length; l++) names.add(target.__existingFiles[l]);
      }

      var attr = target ? target.getAttribute('data-existing') : null;
      if (attr) {
        var parts = attr.split(',');
        for (var m = 0; m < parts.length; m++) {
          var trimmed = parts[m].trim();
          if (trimmed) names.add(trimmed);
        }
      }

      if (target) {
        var container = target.classList.contains('pane') || target.classList.contains('pane-content') || target.classList.contains('filearea')
          ? target
          : null;
        if (container) {
          var domItems = container.querySelectorAll('.cell[data-n], .row[data-n], .lrow[data-n], .tile[data-n], .crow[data-n]');
          for (var n = 0; n < domItems.length; n++) {
            var fn = domItems[n].getAttribute('data-n');
            if (fn) names.add(fn);
          }
        }
      }

      return names;
    }

    /* Drag Event Listeners */

    function onDragStart(e) {
      var itemEl = e.target.closest('.cell, .row, .lrow, .tile, .crow, .wcard');
      if (!itemEl) return;

      var clickedItem = extractItemData(itemEl);
      var items = [];

      if (itemEl.classList.contains('sel')) {
        var container = itemEl.parentElement || rootEl;
        var selEls = container.querySelectorAll('.cell.sel, .row.sel, .lrow.sel, .tile.sel, .crow.sel, .wcard.sel');
        for (var i = 0; i < selEls.length; i++) {
          var d = extractItemData(selEls[i]);
          if (d) items.push(d);
        }
      }
      if (items.length === 0) {
        items = [clickedItem];
      }

      activeDragItems = items;

      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = 'copyMove';
        try {
          var payload = items.map(function (it) {
            return {
              name: it.name,
              path: it.path,
              kind: it.kind,
              size: it.size,
              date: it.date
            };
          });
          e.dataTransfer.setData('application/x-aurade-files', JSON.stringify(payload));
          var plainText = items.map(function (it) { return it.name; }).join(String.fromCharCode(10));
          e.dataTransfer.setData('text/plain', plainText);
        } catch (err) {}

        var ghost = createDragGhost(items);
        document.body.appendChild(ghost);
        if (typeof e.dataTransfer.setDragImage === 'function') {
          e.dataTransfer.setDragImage(ghost, 16, 16);
        }
        setTimeout(function () {
          if (ghost.parentNode) {
            ghost.parentNode.removeChild(ghost);
          }
        }, 0);
      }
    }

    function onDragOver(e) {
      var target = findDropTarget(e.target);
      if (!target) {
        if (currentDropTarget) {
          currentDropTarget.classList.remove('drop-target-active');
          currentDropTarget = null;
        }
        return;
      }

      var isSelf = activeDragItems.some(function (it) {
        return it.element === target;
      });
      if (isSelf) {
        if (currentDropTarget) {
          currentDropTarget.classList.remove('drop-target-active');
          currentDropTarget = null;
        }
        return;
      }

      e.preventDefault();
      var dropEffect = e.ctrlKey ? 'copy' : 'move';
      if (e.dataTransfer) {
        e.dataTransfer.dropEffect = dropEffect;
      }

      if (currentDropTarget && currentDropTarget !== target) {
        currentDropTarget.classList.remove('drop-target-active');
      }
      target.classList.add('drop-target-active');
      currentDropTarget = target;
    }

    function onDragEnter(e) {
      var target = findDropTarget(e.target);
      if (target) {
        var isSelf = activeDragItems.some(function (it) {
          return it.element === target;
        });
        if (!isSelf) {
          e.preventDefault();
          target.classList.add('drop-target-active');
          currentDropTarget = target;
        }
      }
    }

    function onDragLeave(e) {
      if (currentDropTarget) {
        if (!e.relatedTarget || !currentDropTarget.contains(e.relatedTarget)) {
          currentDropTarget.classList.remove('drop-target-active');
          currentDropTarget = null;
        }
      }
    }

    function onDragEnd() {
      clearActiveDropTargets();
      activeDragItems = [];
    }

    function onDrop(e) {
      var target = findDropTarget(e.target);
      clearActiveDropTargets();

      if (!target) return;
      e.preventDefault();

      var destPath = target.getAttribute('data-p') || target.getAttribute('data-root') || target.getAttribute('data-path') || target.getAttribute('data-n') || '/destination';
      var destName = target.getAttribute('data-n') || target.textContent.trim() || 'Folder';

      var items = activeDragItems.slice();
      if (items.length === 0 && e.dataTransfer) {
        var raw = e.dataTransfer.getData('application/x-aurade-files');
        if (raw) {
          try {
            items = JSON.parse(raw);
          } catch (err) {}
        }
      }
      if (items.length === 0) return;

      var isCopy = !!e.ctrlKey;
      var operation = isCopy ? 'copy' : 'move';
      var existingNames = getExistingFileNamesForTarget(target, destPath);

      processDropBatch(items, destPath, destName, existingNames, operation, opts);
      activeDragItems = [];
    }

    function processDropBatch(items, destPath, destName, existingNames, operation, configOpts) {
      var collisions = [];
      for (var i = 0; i < items.length; i++) {
        if (existingNames.has(items[i].name)) {
          collisions.push({ index: i, item: items[i] });
        }
      }

      var proceedingItems = [];
      var rememberedAction = null;
      var applyToAllRemembered = false;

      function handleNext(itemIdx) {
        if (itemIdx >= items.length) {
          finishBatch();
          return;
        }

        var item = items[itemIdx];
        var isCollision = existingNames.has(item.name);

        if (!isCollision) {
          proceedingItems.push({
            name: item.name,
            sourcePath: item.path,
            destPath: destPath + '/' + item.name,
            size: item.size
          });
          existingNames.add(item.name);
          handleNext(itemIdx + 1);
          return;
        }

        if (applyToAllRemembered && rememberedAction) {
          applyAction(rememberedAction, item, null);
          handleNext(itemIdx + 1);
          return;
        }

        var targetItem = {
          name: item.name,
          size: '15.4 KB',
          date: 'Yesterday',
          kind: item.kind
        };
        var targetEl = document.querySelector('[data-n="' + item.name + '"]');
        if (targetEl) {
          targetItem.size = targetEl.getAttribute('data-s') || targetItem.size;
          targetItem.date = targetEl.getAttribute('data-w') || targetItem.date;
        }

        var curConflictIdx = 1;
        for (var c = 0; c < collisions.length; c++) {
          if (collisions[c].index === itemIdx) {
            curConflictIdx = c + 1;
            break;
          }
        }

        FileConflictDialog.show({
          sourceItem: item,
          targetItem: targetItem,
          conflictIndex: curConflictIdx,
          totalConflicts: collisions.length,
          existingNames: existingNames,
          onResolve: function (action, applyToAll, resolvedName) {
            if (action === 'cancel') {
              return;
            }
            if (applyToAll) {
              applyToAllRemembered = true;
              rememberedAction = action;
            }
            applyAction(action, item, resolvedName);
            handleNext(itemIdx + 1);
          }
        });
      }

      function applyAction(action, item, resolvedName) {
        if (action === 'replace') {
          proceedingItems.push({
            name: item.name,
            sourcePath: item.path,
            destPath: destPath + '/' + item.name,
            size: item.size,
            replaced: true
          });
        } else if (action === 'keep_both') {
          var newName = resolvedName || generateUniqueName(item.name, existingNames);
          existingNames.add(newName);
          proceedingItems.push({
            name: newName,
            sourcePath: item.path,
            destPath: destPath + '/' + newName,
            size: item.size,
            renamedFrom: item.name
          });
        }
      }

      function finishBatch() {
        if (proceedingItems.length === 0) return;

        if (window.StatusCenter && typeof window.StatusCenter.addTask === 'function') {
          var count = proceedingItems.length;
          var title = (operation === 'copy' ? 'Copying ' : 'Moving ') + (count === 1 ? proceedingItems[0].name : (String(count) + ' items'));
          var task = window.StatusCenter.addTask({
            title: title,
            subtitle: 'To ' + destName,
            kind: 'file',
            iconKind: operation,
            progress: 0,
            currentItem: proceedingItems[0].name,
            processedBytes: '0 MB of ' + String(count * 10) + ' MB (0%)',
            speed: '28.4 MB/s',
            isPausable: true,
            isCancelable: true
          });

          if (task && typeof task.update === 'function') {
            task.update({
              progress: 50,
              processedBytes: String(count * 5) + ' MB of ' + String(count * 10) + ' MB (50%)'
            });
            setTimeout(function () {
              task.update({
                progress: 100,
                processedBytes: String(count * 10) + ' MB of ' + String(count * 10) + ' MB (100%)'
              });
              if (typeof task.complete === 'function') {
                task.complete();
              }
            }, 120);
          }
        }

        if (typeof configOpts.onDropComplete === 'function') {
          configOpts.onDropComplete({
            operation: operation,
            destination: destPath,
            items: proceedingItems
          });
        }
      }

      handleNext(0);
    }

    document.addEventListener('dragstart', onDragStart);
    document.addEventListener('dragover', onDragOver);
    document.addEventListener('dragenter', onDragEnter);
    document.addEventListener('dragleave', onDragLeave);
    document.addEventListener('dragend', onDragEnd);
    document.addEventListener('drop', onDrop);

    return {
      destroy: function () {
        observer.disconnect();
        document.removeEventListener('dragstart', onDragStart);
        document.removeEventListener('dragover', onDragOver);
        document.removeEventListener('dragenter', onDragEnter);
        document.removeEventListener('dragleave', onDragLeave);
        document.removeEventListener('dragend', onDragEnd);
        document.removeEventListener('drop', onDrop);
      },
      getActiveDragItems: function () {
        return activeDragItems.slice();
      },
      getCurrentDropTarget: function () {
        return currentDropTarget;
      }
    };
  }

  return {
    setupDragAndDropAndConflict: setupDragAndDropAndConflict,
    FileConflictDialog: FileConflictDialog,
    generateUniqueName: generateUniqueName,
    createDragGhost: createDragGhost
  };
});

  })();


