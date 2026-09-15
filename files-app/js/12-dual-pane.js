  // =========================================================================
  // Wave 2: Dual Pane / Split View (P08)
  // =========================================================================
function setupDualPane(options) {
    const opts = options || {};
    const WIDTH_THRESHOLD = (typeof opts.widthThreshold === 'number') ? opts.widthThreshold : 600;

    const fileArea = (typeof opts.fileArea === 'string')
      ? document.querySelector(opts.fileArea)
      : (opts.fileArea || document.getElementById('filearea'));

    if (!fileArea) {
      return {
        toggleDualPane: function () { return false; },
        openSecondaryPane: function () { return false; },
        closeSecondaryPane: function () { return false; },
        focusOtherPane: function () {},
        isDualPaneActive: function () { return false; },
        getActivePane: function () { return 'left'; },
        getLeftPane: function () { return null; },
        getRightPane: function () { return null; },
        getSplitter: function () { return null; },
        destroy: function () {}
      };
    }

    let isDualPane = false;
    let activePane = 'left';
    let wasDualPaneBeforeCollapse = false;
    let savedSecondaryPath = null;

    let dualPaneContainer = null;
    let leftPane = null;
    let rightPane = null;
    let splitter = null;
    let leftContent = null;
    let rightContent = null;

    const leftPaneState = {
      path: '~',
      isHome: true
    };

    const rightPaneState = {
      path: 'Home',
      isHome: false
    };

    function isDualPaneActive() {
      return isDualPane;
    }

    function getLeftPath() {
      if (typeof opts.getCurrentPath === 'function') {
        return opts.getCurrentPath();
      }
      const lastCrumb = document.querySelector('#crumbs .crumb.last, .crumbs [data-p]:last-child');
      if (lastCrumb) {
        const p = lastCrumb.getAttribute('data-p') || lastCrumb.textContent.trim();
        if (p) return p;
      }
      return '~';
    }

    function isPathHome(p) {
      if (typeof opts.isHome === 'function') {
        return opts.isHome();
      }
      return (!p || window.__isHome(p));
    }

    function resolveSecondaryPath(customPath) {
      if (typeof customPath === 'string' && customPath.trim().length > 0) {
        return customPath.trim();
      }
      const curLeftPath = getLeftPath();
      const leftHome = isPathHome(curLeftPath);
      if (leftHome) {
        return (opts.defaultSecondaryPath && opts.defaultSecondaryPath !== 'Home' && opts.defaultSecondaryPath !== '~')
          ? opts.defaultSecondaryPath
          : curLeftPath;
      }
      return 'Home';
    }

    function getActivePaneInfo() {
      const isLeft = (activePane === 'left');
      const currentState = isLeft ? leftPaneState : rightPaneState;
      const currentElement = isLeft ? leftPane : rightPane;
      const otherState = isLeft ? rightPaneState : leftPaneState;
      const otherElement = isLeft ? rightPane : leftPane;

      return {
        pane: activePane,
        element: currentElement,
        otherElement: otherElement,
        path: currentState.path,
        isHome: currentState.isHome,
        isDualPane: isDualPane,
        leftPath: leftPaneState.path,
        rightPath: isDualPane ? rightPaneState.path : null
      };
    }

    function notifyActivePaneChange() {
      const info = getActivePaneInfo();
      if (typeof opts.onActivePaneChange === 'function') {
        opts.onActivePaneChange(info);
      }
    }

    function setActivePane(paneId) {
      if (paneId !== 'left' && paneId !== 'right') return;
      if (!isDualPane) return;
      if (activePane === paneId) return;

      activePane = paneId;

      if (paneId === 'left') {
        leftPane.classList.add('active-pane');
        leftPane.classList.remove('inactive-pane');
        rightPane.classList.remove('active-pane');
        rightPane.classList.add('inactive-pane');
        if (rightContent) {
          const selItems = rightContent.querySelectorAll('.sel');
          selItems.forEach(function (el) { el.classList.remove('sel'); });
        }
      } else {
        rightPane.classList.add('active-pane');
        rightPane.classList.remove('inactive-pane');
        leftPane.classList.remove('active-pane');
        leftPane.classList.add('inactive-pane');
        if (leftContent) {
          const selItems = leftContent.querySelectorAll('.sel');
          selItems.forEach(function (el) { el.classList.remove('sel'); });
        }
      }

      notifyActivePaneChange();
    }

    function focusOtherPane() {
      if (!isDualPane) return;
      const nextPane = (activePane === 'left') ? 'right' : 'left';
      setActivePane(nextPane);
      const targetEl = (nextPane === 'left') ? leftPane : rightPane;
      if (targetEl) {
        targetEl.focus();
      }
    }

    function renderPane(paneEl, path, isHome) {
      if (typeof opts.renderPane === 'function') {
        opts.renderPane(paneEl, path, isHome);
        return;
      }
      const content = paneEl.querySelector('.pane-content');
      if (!content) return;
      content.replaceChildren();

      const isH = (window.__isHome(path) || isHome);
      const catalog = (typeof window !== 'undefined' && window.__DIR_CATALOG) ? window.__DIR_CATALOG : {};
      let catEntry = null;

      if (isH) {
        catEntry = catalog[window.__homePath()] || null;
      } else if (catalog[path]) {
        catEntry = catalog[path];
      } else {
        for (const k in catalog) {
          if (catalog[k] && (catalog[k].path === path || catalog[k].name === path)) {
            catEntry = catalog[k];
            break;
          }
        }
      }

      const items = (catEntry && catEntry.items) ? catEntry.items : [];

      if (items.length === 0) {
        const emptyMsg = document.createElement('div');
        emptyMsg.className = 'statemsg empty-folder-state';
        emptyMsg.setAttribute('role', 'status');

        const titleEl = document.createElement('div');
        titleEl.className = 'statetitle';
        titleEl.textContent = 'This folder is empty.';

        emptyMsg.appendChild(titleEl);
        content.appendChild(emptyMsg);
        return;
      }

      const grid = document.createElement('div');
      grid.className = 'grid';

      const tplCell = document.getElementById('tpl-cell');

      items.forEach(function (item) {
        let cellEl;
        if (tplCell && tplCell.content && tplCell.content.firstElementChild) {
          cellEl = tplCell.content.firstElementChild.cloneNode(true);
          const thumb = cellEl.querySelector('.thumb');
          if (thumb && item.th) {
            // A picture beats a glyph. This path rebuilds the grid from the
            // catalog, so without this the first repaint drops every baked
            // thumbnail back to a file icon.
            const pic = document.createElement('img');
            pic.className = 'thumbimg';
            pic.alt = '';
            pic.decoding = 'async';
            pic.src = item.th;
            thumb.replaceChildren(pic);
          } else if (thumb) {
            const artLib = document.getElementById('artlib');
            let iconSvg = null;
            if (artLib) {
              const key = (item.art || 'txt').toLowerCase();
              const found = artLib.querySelector('[data-thumb="' + key + '"] svg') ||
                            artLib.querySelector('[data-rico="' + key + '"] svg') ||
                            artLib.querySelector('svg');
              if (found) iconSvg = found.cloneNode(true);
            }
            if (iconSvg) {
              thumb.replaceChildren(iconSvg);
            }
          }
          if (item.th) cellEl.setAttribute('data-th', item.th);
          const cname = cellEl.querySelector('.cname');
          if (cname) {
            cname.textContent = item.name || '';
            cname.setAttribute('title', item.name || '');
          }
        } else {
          cellEl = document.createElement('div');
          cellEl.className = 'cell';
          cellEl.setAttribute('tabindex', '0');

          const thumb = document.createElement('div');
          thumb.className = 'thumb';
          cellEl.appendChild(thumb);

          const cname = document.createElement('div');
          cname.className = 'cname';
          cname.textContent = item.name || '';
          cellEl.appendChild(cname);
        }

        cellEl.setAttribute('data-n', item.name || '');
        cellEl.setAttribute('data-k', item.kind || 'File');
        cellEl.setAttribute('data-w', item.when || '');
        cellEl.setAttribute('data-s', item.size || '');
        cellEl.setAttribute('data-p', item.path || (path + '/' + item.name));

        cellEl.addEventListener('click', function (e) {
          e.stopPropagation();
          const paneKey = paneEl.getAttribute('data-pane') || 'right';
          setActivePane(paneKey);
          const allCells = grid.querySelectorAll('.cell');
          allCells.forEach(function (c) { c.classList.remove('sel'); });
          cellEl.classList.add('sel');
        });

        if (item.kind === 'Folder' || !item.size) {
          cellEl.addEventListener('dblclick', function (e) {
            e.stopPropagation();
            const targetPath = item.path || (path + '/' + item.name);
            paneEl.setAttribute('data-path', targetPath);
            if (paneEl === rightPane) {
              rightPaneState.path = targetPath;
              rightPaneState.isHome = false;
            } else {
              leftPaneState.path = targetPath;
              leftPaneState.isHome = false;
            }
            renderPane(paneEl, targetPath, false);
            notifyActivePaneChange();
          });
        }

        grid.appendChild(cellEl);
      });

      content.appendChild(grid);
    }

    function setupSplitterEvents(splitterEl, containerEl, leftPaneEl, rightPaneEl) {
      let isDragging = false;
      let startX = 0;
      let startLeftWidth = 0;
      let containerWidth = 0;

      function onPointerDown(e) {
        if (e.button !== 0) return;
        isDragging = true;
        startX = e.clientX;
        const leftRect = leftPaneEl.getBoundingClientRect();
        const contRect = containerEl.getBoundingClientRect();
        startLeftWidth = leftRect.width;
        containerWidth = contRect.width;

        splitterEl.classList.add('dragging');
        document.body.classList.add('dual-pane-resizing');

        try {
          splitterEl.setPointerCapture(e.pointerId);
        } catch (err) {
          // Ignore
        }

        e.preventDefault();
        e.stopPropagation();
      }

      function onPointerMove(e) {
        if (!isDragging) return;
        const deltaX = e.clientX - startX;
        const minWidth = 120;
        const splitterWidth = splitterEl.offsetWidth || 4;
        const maxLeftWidth = containerWidth - minWidth - splitterWidth;

        let targetLeftWidth = startLeftWidth + deltaX;
        if (targetLeftWidth < minWidth) targetLeftWidth = minWidth;
        if (targetLeftWidth > maxLeftWidth) targetLeftWidth = maxLeftWidth;

        const leftPercent = (targetLeftWidth / containerWidth) * 100;
        const rightPercent = 100 - leftPercent - ((splitterWidth / containerWidth) * 100);

        leftPaneEl.style.flex = leftPercent + ' 1 0%';
        rightPaneEl.style.flex = Math.max(0, rightPercent) + ' 1 0%';
        e.preventDefault();
      }

      function onPointerUp(e) {
        if (!isDragging) return;
        isDragging = false;
        splitterEl.classList.remove('dragging');
        document.body.classList.remove('dual-pane-resizing');

        try {
          splitterEl.releasePointerCapture(e.pointerId);
        } catch (err) {
          // Ignore
        }
        e.preventDefault();
      }

      function onDblClick(e) {
        e.preventDefault();
        leftPaneEl.style.flex = '1 1 0%';
        rightPaneEl.style.flex = '1 1 0%';
      }

      splitterEl.addEventListener('pointerdown', onPointerDown);
      window.addEventListener('pointermove', onPointerMove);
      window.addEventListener('pointerup', onPointerUp);
      splitterEl.addEventListener('dblclick', onDblClick);
    }

    function openSecondaryPane(requestedPath) {
      const currentWidth = window.innerWidth || (document.documentElement ? document.documentElement.clientWidth : 0);
      if (currentWidth < WIDTH_THRESHOLD) {
        return false;
      }

      if (isDualPane) {
        if (requestedPath && requestedPath !== rightPaneState.path) {
          rightPaneState.path = requestedPath;
          rightPaneState.isHome = isPathHome(requestedPath);
          rightPane.setAttribute('data-path', rightPaneState.path);
          renderPane(rightPane, rightPaneState.path, rightPaneState.isHome);
        }
        setActivePane('right');
        return true;
      }

      leftPaneState.path = getLeftPath();
      leftPaneState.isHome = isPathHome(leftPaneState.path);
      rightPaneState.path = resolveSecondaryPath(requestedPath);
      rightPaneState.isHome = isPathHome(rightPaneState.path);

      dualPaneContainer = document.createElement('div');
      dualPaneContainer.className = 'dual-pane-container';

      leftPane = document.createElement('div');
      leftPane.className = 'shell-pane pane-left active-pane';
      leftPane.setAttribute('data-pane', 'left');
      leftPane.setAttribute('data-path', leftPaneState.path);
      leftPane.setAttribute('tabindex', '0');
      leftPane.setAttribute('role', 'region');
      leftPane.setAttribute('aria-label', 'Primary Pane');

      leftContent = document.createElement('div');
      leftContent.className = 'pane-content';

      while (fileArea.firstChild) {
        leftContent.appendChild(fileArea.firstChild);
      }
      leftPane.appendChild(leftContent);

      splitter = document.createElement('div');
      splitter.className = 'pane-splitter';
      splitter.setAttribute('role', 'separator');
      splitter.setAttribute('aria-orientation', 'vertical');
      splitter.setAttribute('tabindex', '0');
      splitter.setAttribute('title', 'Double-click to reset split ratio');

      rightPane = document.createElement('div');
      rightPane.className = 'shell-pane pane-right inactive-pane';
      rightPane.setAttribute('data-pane', 'right');
      rightPane.setAttribute('data-path', rightPaneState.path);
      rightPane.setAttribute('tabindex', '0');
      rightPane.setAttribute('role', 'region');
      rightPane.setAttribute('aria-label', 'Secondary Pane');

      rightContent = document.createElement('div');
      rightContent.className = 'pane-content';
      rightPane.appendChild(rightContent);

      dualPaneContainer.appendChild(leftPane);
      dualPaneContainer.appendChild(splitter);
      dualPaneContainer.appendChild(rightPane);
      fileArea.appendChild(dualPaneContainer);
      fileArea.classList.add('dual-pane-active');

      isDualPane = true;
      activePane = 'left';

      renderPane(rightPane, rightPaneState.path, rightPaneState.isHome);

      function onLeftPointerDown() {
        setActivePane('left');
      }
      function onRightPointerDown() {
        setActivePane('right');
      }
      leftPane.addEventListener('pointerdown', onLeftPointerDown);
      rightPane.addEventListener('pointerdown', onRightPointerDown);
      leftPane.addEventListener('focusin', onLeftPointerDown);
      rightPane.addEventListener('focusin', onRightPointerDown);

      setupSplitterEvents(splitter, dualPaneContainer, leftPane, rightPane);

      notifyActivePaneChange();
      if (typeof opts.onDualPaneToggle === 'function') {
        opts.onDualPaneToggle(true);
      }
      return true;
    }

    function closeSecondaryPane(isCollapse) {
      if (!isDualPane) return false;

      if (leftContent) {
        while (leftContent.firstChild) {
          fileArea.appendChild(leftContent.firstChild);
        }
      }

      if (dualPaneContainer && dualPaneContainer.parentNode) {
        dualPaneContainer.parentNode.removeChild(dualPaneContainer);
      }

      fileArea.classList.remove('dual-pane-active');

      isDualPane = false;
      activePane = 'left';
      dualPaneContainer = null;
      leftPane = null;
      rightPane = null;
      splitter = null;
      leftContent = null;
      rightContent = null;

      if (!isCollapse) {
        wasDualPaneBeforeCollapse = false;
        savedSecondaryPath = null;
      }

      notifyActivePaneChange();
      if (typeof opts.onDualPaneToggle === 'function') {
        opts.onDualPaneToggle(false);
      }
      return true;
    }

    function toggleDualPane() {
      if (isDualPane) {
        return closeSecondaryPane(false);
      } else {
        return openSecondaryPane();
      }
    }

    function handleKeyDown(e) {
      if (e.key === 'F3') {
        e.preventDefault();
        toggleDualPane();
        return;
      }
      if (e.altKey && e.shiftKey && (e.key === 'D' || e.key === 'd' || e.code === 'KeyD')) {
        e.preventDefault();
        toggleDualPane();
        return;
      }
      if (e.key === 'F6' && isDualPane) {
        e.preventDefault();
        focusOtherPane();
        return;
      }
    }

    function handleWindowResize() {
      const currentWidth = window.innerWidth || (document.documentElement ? document.documentElement.clientWidth : 0);
      if (currentWidth < WIDTH_THRESHOLD) {
        if (isDualPaneActive()) {
          wasDualPaneBeforeCollapse = true;
          savedSecondaryPath = rightPaneState.path;
          closeSecondaryPane(true);
        }
      } else {
        if (wasDualPaneBeforeCollapse) {
          const pathToRestore = savedSecondaryPath || 'Home';
          wasDualPaneBeforeCollapse = false;
          savedSecondaryPath = null;
          openSecondaryPane(pathToRestore);
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('resize', handleWindowResize);

    function destroy() {
      closeSecondaryPane(false);
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('resize', handleWindowResize);
    }

    return {
      toggleDualPane: toggleDualPane,
      openSecondaryPane: openSecondaryPane,
      closeSecondaryPane: closeSecondaryPane,
      focusOtherPane: focusOtherPane,
      isDualPaneActive: isDualPaneActive,
      getActivePane: function () { return activePane; },
      getLeftPane: function () { return leftPane; },
      getRightPane: function () { return rightPane; },
      getSplitter: function () { return splitter; },
      destroy: destroy
    };
  }

