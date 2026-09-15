  // =========================================================================
  // 1. Editable Address Bar
  // =========================================================================

  /**
   * Ensures #opath element exists inside #omnibar.
   * If not present in static HTML, creates it with Trusted Types compliant DOM calls.
   */
  function ensurePathInput() {
    let opath = qs('#opath');
    if (opath) return opath;

    const omnibar = qs('#omnibar');
    if (!omnibar) return null;

    opath = document.createElement('input');
    opath.id = 'opath';
    opath.className = 'opath';
    opath.hidden = true;
    opath.setAttribute('placeholder', 'Enter a path');
    opath.setAttribute('aria-label', 'Address');
    opath.setAttribute('autocomplete', 'off');
    opath.setAttribute('spellcheck', 'false');

    // Inline styles to match .osearch and design tokens perfectly
    opath.style.flex = '1';
    opath.style.minWidth = '0';
    opath.style.height = '28px';
    opath.style.margin = '0 6px';
    opath.style.padding = '0 10px';
    opath.style.font = 'inherit';
    opath.style.fontSize = '14px';
    opath.style.color = 'var(--text-1)';
    opath.style.background = 'var(--control-fill)';
    opath.style.border = '1px solid var(--control-stroke)';
    opath.style.borderRadius = 'var(--r-ctl, 4px)';
    opath.style.outline = 'none';
    opath.style.display = 'none';

    // Insert before .omodes or append
    const omodes = qs('.omodes', omnibar);
    if (omodes) {
      omnibar.insertBefore(opath, omodes);
    } else {
      omnibar.appendChild(opath);
    }

    return opath;
  }

  /**
   * Starts editing path in #opath.
   * @param {string} [customPath] - Path to display in input. Defaults to active tab path.
   */
  function startAddressEdit(customPath) {
    const opath = ensurePathInput();
    const crumbs = qs('#crumbs');
    const osearch = qs('#osearch');
    const omnibar = qs('#omnibar');
    if (!opath || !crumbs) return;

    // Exit search mode if active
    if (osearch && !osearch.hidden) {
      osearch.hidden = true;
      osearch.value = '';
      const btnSearch = qs('#btn-search');
      if (btnSearch) btnSearch.setAttribute('aria-pressed', 'false');
    }

    let pathVal = '';
    if (typeof customPath === 'string') {
      pathVal = customPath;
    } else if (typeof window.__getActiveTabPath === 'function') {
      pathVal = window.__getActiveTabPath();
    } else {
      // Look for active tab or win data-path
      const activeTab = qs('.tab.active');
      const win = qs('.win');
      if (activeTab && activeTab.getAttribute('data-tab-path')) {
        pathVal = activeTab.getAttribute('data-tab-path');
      } else if (win && win.getAttribute('data-path')) {
        pathVal = win.getAttribute('data-path');
      } else {
        const lastCrumb = qs('.crumbs .crumb.last');
        pathVal = (lastCrumb && lastCrumb.getAttribute('data-p')) || '~';
      }
    }

    crumbs.hidden = true;
    opath.hidden = false;
    opath.style.display = 'block';
    opath.value = pathVal;

    // Focus and select all text
    opath.focus();
    opath.select();
  }

  /**
   * Cancels address bar editing and restores breadcrumb display.
   */
  function cancelAddressEdit() {
    const opath = qs('#opath');
    const crumbs = qs('#crumbs');
    if (!opath || !crumbs) return;

    opath.hidden = true;
    opath.style.display = 'none';
    crumbs.hidden = false;
  }

  /**
   * Commits the edited address bar text and navigates.
   * @param {Function} [navCallback] - Navigation function (e.g. navigateTo or navigateActiveTab).
   */
  function commitAddressEdit(navCallback) {
    const opath = qs('#opath');
    if (!opath) return;

    const raw = opath.value.trim();
    cancelAddressEdit();

    if (!raw) return;

    const isHome = window.__isHome(raw);
    const name = isHome ? 'Home' : (raw.split('/').filter(Boolean).pop() || 'Folder');

    if (typeof navCallback === 'function') {
      navCallback(raw, name, isHome, true);
    } else if (typeof window.navigateTo === 'function') {
      window.navigateTo(raw, name, isHome, true);
    } else if (typeof window.navigateActiveTab === 'function') {
      window.navigateActiveTab(raw, name, isHome);
    }
  }

  /**
   * Initializes address bar event listeners:
   * - Ctrl+L / Cmd+L shortcut to enter edit mode.
   * - Click-to-edit on omnibar / crumbs background.
   * - Enter to navigate in #opath.
   * - Escape to cancel in #opath.
   * - Blur to revert cleanly when clicking away.
   * @param {Object} [options]
   * @param {Function} [options.navigateTo] - Function to call on navigation.
   * @param {Function} [options.getActivePath] - Function returning current path.
   */
  function setupEditableAddressBar(options) {
    const opts = options || {};
    const opath = ensurePathInput();
    if (!opath) return;

    // Keyboard navigation inside #opath
    opath.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        e.stopPropagation();
        commitAddressEdit(opts.navigateTo);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        cancelAddressEdit();
      }
    });

    // Cancel on blur if clicking outside omnibar
    opath.addEventListener('blur', function () {
      setTimeout(function () {
        if (document.activeElement !== opath && !opath.hidden) {
          cancelAddressEdit();
        }
      }, 150);
    });

    // Global shortcut Ctrl+L / Cmd+L
    document.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'l' || e.key === 'L')) {
        e.preventDefault();
        startAddressEdit(opts.getActivePath ? opts.getActivePath() : undefined);
      }
    });

    // Click-to-edit on omnibar:
    // Clicking empty space in #crumbs, or clicking #omnibar outside action buttons starts edit mode.
    const omnibar = qs('#omnibar');
    if (omnibar) {
      omnibar.addEventListener('click', function (e) {
        // Ignore clicks on search mode buttons, command palette button, or inside search input
        if (e.target.closest('.omodes, .omode, #btn-palette, #btn-search, #osearch, #opath')) {
          return;
        }

        // If clicking an ancestor breadcrumb, let standard navigation handle it
        const ancestorCrumb = e.target.closest('.crumb:not(.last)');
        if (ancestorCrumb) {
          return;
        }

        // Clicking the current folder crumb or the empty background space enters edit mode
        const clickedLastCrumb = e.target.closest('.crumb.last');
        const clickedCrumbsArea = e.target.closest('#crumbs') || e.target === omnibar;

        if (clickedLastCrumb || clickedCrumbsArea) {
          startAddressEdit(opts.getActivePath ? opts.getActivePath() : undefined);
        }
      });
    }
  }

  // =========================================================================
  // 2. Toolbar Home Gating
  // =========================================================================

  /**
   * Ensures the toolbar context commands container #tb-context exists.
   * If #tb-context is already present in static HTML, returns it.
   * If not, automatically groups context buttons (Cut, Copy, Paste, Rename, Share, Delete, Properties)
   * after the first separator into a <div id="tb-context"> container.
   */
  function ensureToolbarContextContainer() {
    let tbContext = qs('#tb-context');
    if (tbContext) return tbContext;

    const tbGroup = qs('.toolbar .tbgroup');
    if (!tbGroup) return null;

    // Look for separator after New button
    const sep = qs('.tsep', tbGroup);
    if (!sep) return null;

    // Collect all sibling buttons after separator
    const contextButtons = [];
    let next = sep.nextElementSibling;
    while (next) {
      const current = next;
      next = next.nextElementSibling;
      if (current.tagName === 'BUTTON' || current.classList.contains('tbtn')) {
        contextButtons.push(current);
      }
    }

    if (contextButtons.length === 0) return null;

    tbContext = document.createElement('div');
    tbContext.id = 'tb-context';
    tbContext.className = 'tb-context';
    tbContext.style.display = 'inline-flex';
    tbContext.style.alignItems = 'center';
    tbContext.style.gap = '4px';

    tbGroup.appendChild(tbContext);
    contextButtons.forEach(function (btn) {
      tbContext.appendChild(btn);
    });

    return tbContext;
  }

  /**
   * Updates toolbar gating based on whether active tab is Home.
   * Hides #tb-context on Home; displays it on folders.
   * @param {boolean} isHome - True if currently on Home view.
   */
  function updateToolbarHomeGating(isHome) {
    const tbContext = ensureToolbarContextContainer();
    if (!tbContext) return;

    if (isHome) {
      tbContext.hidden = true;
      tbContext.style.display = 'none';
      tbContext.setAttribute('hidden', '');
    } else {
      tbContext.hidden = false;
      tbContext.style.display = '';
      tbContext.removeAttribute('hidden');
    }
  }

  // =========================================================================
  // 3. Empty Folder Indicator
  // =========================================================================

  /**
   * Updates empty folder indicator state in #filearea.
   * Shows 'This folder is empty.' when 0 items exist in a folder.
   * Hides indicator when folder has items or when on Home.
   * Complies strictly with Trusted Types (uses createElement and textContent).
   * @param {number} itemCount - Number of items currently in folder.
   * @param {boolean} isHome - True if currently on Home view.
   */
  function updateEmptyFolderIndicator(itemCount, isHome) {
    const filearea = qs('#filearea');
    if (!filearea) return;

    let statemsg = qs('#filearea > .statemsg');

    // On Home, never show empty folder indicator
    if (isHome) {
      if (statemsg) {
        statemsg.hidden = true;
        statemsg.style.display = 'none';
      }
      return;
    }

    if (itemCount === 0) {
      if (!statemsg) {
        statemsg = document.createElement('div');
        statemsg.className = 'statemsg';

        const body = document.createElement('div');
        body.className = 'statebody';
        body.textContent = 'This folder is empty.';
        statemsg.appendChild(body);

        filearea.appendChild(statemsg);
      } else {
        // Clean any leftover error title or warning glyph
        const title = qs('.statetitle', statemsg);
        if (title && title.parentNode) title.parentNode.removeChild(title);

        const glyph = qs('.stateglyph', statemsg);
        if (glyph && glyph.parentNode) glyph.parentNode.removeChild(glyph);

        let body = qs('.statebody', statemsg);
        if (!body) {
          body = document.createElement('div');
          body.className = 'statebody';
          statemsg.appendChild(body);
        }
        body.textContent = 'This folder is empty.';
      }

      statemsg.hidden = false;
      statemsg.style.display = '';
    } else {
      if (statemsg) {
        statemsg.hidden = true;
        statemsg.style.display = 'none';
      }
    }
  }

  // =========================================================================
  // 4. Marquee / Rubberband Selection
  // =========================================================================

  /**
   * Configures marquee / rubberband drag selection within #filearea.
   * Supports real-time item intersection detection with Ctrl/Shift modifiers.
   * - Normal drag: deselects items outside marquee; selects items inside marquee.
   * - Ctrl drag: toggles selection state of items intersecting marquee.
   * - Shift drag: adds intersecting items to existing selection.
   * @param {Object} [options]
   * @param {Function} [options.getItems] - Returns array of item elements.
   * @param {Function} [options.updateStatus] - Callback to update status bar.
   * @param {Function} [options.updateDetails] - Callback to update details pane.
   * @param {Function} [options.isHome] - Callback returning boolean if on Home.
   */
  function setupMarqueeSelection(options) {
    const opts = options || {};
    const filearea = qs('#filearea');
    if (!filearea) return;

    const DRAG_THRESHOLD = 4;
    let isMouseDown = false;
    let isDragging = false;
    let startClientX = 0;
    let startClientY = 0;
    let marqueeEl = null;
    let initialSelectedSet = new Set();
    let isCtrlMode = false;
    let isShiftMode = false;

    function getTargetItems() {
      if (typeof opts.getItems === 'function') {
        return opts.getItems();
      }
      // Default: find visible items in active layout
      const activeLayout = qs('.grid:not([hidden]), .rows:not([hidden]), .list:not([hidden]), .cards:not([hidden]), .columns:not([hidden])');
      if (!activeLayout) return [];
      return qsa('.cell, .row, .lrow, .tile, .crow', activeLayout).filter(function (el) {
        return el.style.display !== 'none';
      });
    }

    function createMarqueeBox() {
      if (marqueeEl) return marqueeEl;
      marqueeEl = document.createElement('div');
      marqueeEl.className = 'rubberband-selection';
      marqueeEl.style.position = 'absolute';
      marqueeEl.style.pointerEvents = 'none';
      marqueeEl.style.zIndex = '999';
      marqueeEl.style.border = '1px solid var(--accent, #0078d4)';
      marqueeEl.style.background = 'color-mix(in srgb, var(--accent, #0078d4) 20%, transparent)';
      marqueeEl.style.borderRadius = '2px';
      filearea.appendChild(marqueeEl);
      return marqueeEl;
    }

    function removeMarqueeBox() {
      if (marqueeEl && marqueeEl.parentNode) {
        marqueeEl.parentNode.removeChild(marqueeEl);
      }
      marqueeEl = null;
    }

    function onMouseDown(e) {
      // Primary mouse button only
      if (e.button !== 0) return;

      // Do not run marquee on Home widgets
      if (opts.isHome && opts.isHome()) return;
      const homeWidgets = qs('#home-widgets');
      if (homeWidgets && !homeWidgets.hidden) return;

      // Do not start drag on interactive items, buttons, inputs, scrollbar, or context menus
      if (e.target.closest('.cell, .row, .lrow, .tile, .crow, .wcard, .wsec, .wrecent-row, button, input, .menu, .ctx, .dhead, .col-h')) {
        return;
      }

      // Check if clicking inside scrollbar area
      const faRect = filearea.getBoundingClientRect();
      if (e.clientX >= faRect.left + filearea.clientWidth || e.clientY >= faRect.top + filearea.clientHeight) {
        return;
      }

      isMouseDown = true;
      isDragging = false;
      startClientX = e.clientX;
      startClientY = e.clientY;
      isCtrlMode = e.ctrlKey || e.metaKey;
      isShiftMode = e.shiftKey;

      // Snapshot current selection
      const items = getTargetItems();
      initialSelectedSet = new Set(items.filter(function (el) {
        return el.classList.contains('sel');
      }));

      // In normal mode (no Ctrl/Shift), clear selection on empty space click
      if (!isCtrlMode && !isShiftMode) {
        items.forEach(function (el) {
          el.classList.remove('sel');
        });
        if (typeof opts.updateStatus === 'function') opts.updateStatus();
        if (typeof opts.updateDetails === 'function') opts.updateDetails(null);
      }

      window.addEventListener('mousemove', onMouseMove, true);
      window.addEventListener('mouseup', onMouseUp, true);
    }

    function onMouseMove(e) {
      if (!isMouseDown) return;

      const deltaX = e.clientX - startClientX;
      const deltaY = e.clientY - startClientY;
      const distance = Math.hypot(deltaX, deltaY);

      if (!isDragging) {
        if (distance < DRAG_THRESHOLD) return;
        isDragging = true;
        createMarqueeBox();
      }

      // Position visual marquee box relative to #filearea coordinate space
      const faRect = filearea.getBoundingClientRect();
      const currentScrollLeft = filearea.scrollLeft;
      const currentScrollTop = filearea.scrollTop;

      const viewportMinX = Math.min(startClientX, e.clientX);
      const viewportMaxX = Math.max(startClientX, e.clientX);
      const viewportMinY = Math.min(startClientY, e.clientY);
      const viewportMaxY = Math.max(startClientY, e.clientY);

      const boxLeft = viewportMinX - faRect.left + currentScrollLeft;
      const boxTop = viewportMinY - faRect.top + currentScrollTop;
      const boxWidth = viewportMaxX - viewportMinX;
      const boxHeight = viewportMaxY - viewportMinY;

      if (marqueeEl) {
        marqueeEl.style.left = boxLeft + 'px';
        marqueeEl.style.top = boxTop + 'px';
        marqueeEl.style.width = boxWidth + 'px';
        marqueeEl.style.height = boxHeight + 'px';
      }

      // Viewport-based intersection test with each item
      const items = getTargetItems();
      items.forEach(function (item) {
        const itemRect = item.getBoundingClientRect();
        const intersects = !(
          itemRect.right < viewportMinX ||
          itemRect.left > viewportMaxX ||
          itemRect.bottom < viewportMinY ||
          itemRect.top > viewportMaxY
        );

        const wasSelected = initialSelectedSet.has(item);

        if (isCtrlMode) {
          // Toggle intersection with initial selection
          item.classList.toggle('sel', intersects ? !wasSelected : wasSelected);
        } else if (isShiftMode) {
          // Union intersection with initial selection
          item.classList.toggle('sel', wasSelected || intersects);
        } else {
          // Normal drag selection
          item.classList.toggle('sel', intersects);
        }
      });

      if (typeof opts.updateStatus === 'function') {
        opts.updateStatus();
      }
    }

    function onMouseUp() {
      if (!isMouseDown) return;

      isMouseDown = false;
      window.removeEventListener('mousemove', onMouseMove, true);
      window.removeEventListener('mouseup', onMouseUp, true);

      if (isDragging) {
        removeMarqueeBox();
        isDragging = false;

        const items = getTargetItems();
        const sel = items.filter(function (el) {
          return el.classList.contains('sel');
        });

        if (typeof opts.updateDetails === 'function') {
          opts.updateDetails(sel.length === 1 ? sel[0] : null);
        }
        if (typeof opts.updateStatus === 'function') {
          opts.updateStatus();
        }
      }
    }

    filearea.addEventListener('mousedown', onMouseDown);
  }

  // =========================================================================
  // All-in-One Wave 1 Initializer
  // =========================================================================

  /**
   * Initializes all Wave 1 features in one single call.
   * @param {Object} [ctx] - Runtime context passing navigation, status, and details handlers.
   */
  function initWave1Features(ctx) {
    const context = ctx || {};

    // 1. Setup address bar
    setupEditableAddressBar({
      navigateTo: context.navigateTo,
      getActivePath: context.getActivePath
    });

    // 2. Setup marquee selection
    setupMarqueeSelection({
      getItems: context.getItems,
      updateStatus: context.updateStatus,
      updateDetails: context.updateDetails,
      isHome: context.isHome
    });

    // 3. Initial gating and empty folder check
    const isHome = typeof context.isHome === 'function' ? context.isHome() : true;
    updateToolbarHomeGating(isHome);

    const itemCount = typeof context.getItemCount === 'function' ? context.getItemCount() : 0;
    updateEmptyFolderIndicator(itemCount, isHome);
  }


