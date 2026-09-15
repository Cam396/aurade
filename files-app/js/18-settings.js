  // =========================================================================
  // Wave C: WinUI 3 Settings Dialog Overhaul
  // =========================================================================
  (function() {
/* Wave C: Comprehensive WinUI 3 Settings Dialog Overhaul for AuraDE Files */
/* Strict typography constraint: zero em dashes and zero en dashes. */

(function() {
  'use strict';

  var LF = String.fromCharCode(10);
  var CR = String.fromCharCode(13);

  var PREFS_KEY = 'aurade-prefs';
  var THEME_KEY = 'aurade-theme';
  var TAGS_KEY = 'aurade-tags';
  var SHORTCUTS_KEY = 'aurade-shortcuts';
  var STARTUP_PAGES_KEY = 'aurade-startup-pages';

  var DEFAULT_PREFS = {
    startup: 'home',
    startupPages: ['/home'],
    startupExistingInstance: true,
    alwaysSwitchNewTab: false,
    language: 'default',
    dateFormat: 'default',
    'widgets.qa': true,
    'widgets.drives': true,
    'widgets.network': true,
    'widgets.tags': true,
    'widgets.recent': true,
    dualPaneNewTab: false,
    dualPaneSplit: 'Horizontal',
    'contextMenu.openInNewTab': true,
    'contextMenu.openInNewWindow': true,
    'contextMenu.openInNewPane': true,
    'contextMenu.copyPath': true,
    'contextMenu.createFolderWithSelection': true,
    'contextMenu.createAlternateDataStream': false,
    'contextMenu.createShortcut': true,
    'contextMenu.pinToSidebar': true,
    'contextMenu.compressionOptions': true,
    'contextMenu.sendTo': true,
    'contextMenu.openTerminal': true,
    'contextMenu.editTags': true,
    smoothScrolling: true,
    theme: 'dark',
    backdropMaterial: 'Mica',
    appBgColor: '#202020',
    bgImagePath: '',
    bgImageOpacity: 0.5,
    bgImageFit: 'UniformToFill',
    fontFamily: 'default',
    statusCenterVisibility: 'Active tasks only',
    defLayout: 'grid',
    syncFolderPrefs: false,
    groupByProperty: 'None',
    groupByDesc: false,
    groupByDateUnit: 'Month',
    'columns.autoSize': true,
    'columns.tag': true,
    'columns.size': true,
    'columns.type': true,
    'columns.dateModified': true,
    'columns.dateCreated': false,
    showHidden: false,
    showDotFiles: false,
    showSystemFiles: false,
    showThumbnails: true,
    showCheckboxes: true,
    singleClickFiles: false,
    singleClickFolders: false,
    singleClickColumns: false,
    confirmDeletePolicy: 'Always',
    warnExtensionChange: true,
    calcFolderSizes: false,
    sizeFormat: 'Binary',
    statusIde: 'None',
    ideName: 'VS Code',
    idePath: '/usr/bin/code',
    openOnStartup: false,
    leaveRunningInBackground: false,
    expReplaceExplorer: false,
    expReplaceOpenDialog: false,
    thumbnailCacheSizeMb: 500,
    'contextMenu.flattenOptions': true,
    'toolbar.default': null,
    'toolbar.compact': null,
    contextMenuOverflow: true,
    reverseTabScroll: false,
    showExt: true,
    openNewTab: false,
    selectOnHover: false,
    dblclickUp: false,
    scrollToPreviousFolder: true,
    showTrayIcon: false,
    bgImageVAlign: 'Center',
    bgImageHAlign: 'Center',
    showTabActions: true,
    showSCBtn: true,
    showStatusbar: true,
    showPaneBtn: true,
    showToolbar: true,
    showShelfBtn: true,
    thumbnailCache: true
  };

  var DEFAULT_TAGS = [
    { id: 'tag-work', name: 'Work', color: '#3584e4' },
    { id: 'tag-personal', name: 'Personal', color: '#33d17a' },
    { id: 'tag-important', name: 'Important', color: '#e01b24' },
    { id: 'tag-project', name: 'Project', color: '#f6d32d' }
  ];

  var DEFAULT_SHORTCUTS = [
    { id: 'new-tab', name: 'New tab', keys: 'Ctrl+T' },
    { id: 'close-tab', name: 'Close tab', keys: 'Ctrl+W' },
    { id: 'search', name: 'Search', keys: 'Ctrl+F' },
    { id: 'select-all', name: 'Select all', keys: 'Ctrl+A' },
    { id: 'refresh', name: 'Refresh', keys: 'F5' },
    { id: 'rename', name: 'Rename', keys: 'F2' },
    { id: 'delete', name: 'Move to trash', keys: 'Delete' },
    { id: 'parent-folder', name: 'Go to parent folder', keys: 'Alt+Up' },
    { id: 'open-item', name: 'Open folder / item', keys: 'Enter' }
  ];

  var COMMANDS_LIST = [
    { id: 'new-tab', name: 'New tab' },
    { id: 'close-tab', name: 'Close tab' },
    { id: 'search', name: 'Search' },
    { id: 'select-all', name: 'Select all' },
    { id: 'refresh', name: 'Refresh' },
    { id: 'rename', name: 'Rename' },
    { id: 'delete', name: 'Move to trash' },
    { id: 'parent-folder', name: 'Go to parent folder' },
    { id: 'open-item', name: 'Open folder / item' },
    { id: 'dup-tab', name: 'Duplicate tab' },
    { id: 'new-window', name: 'New window' },
    { id: 'pin-sidebar', name: 'Pin to sidebar' },
    { id: 'copy-path', name: 'Copy path' },
    { id: 'properties', name: 'Properties' },
    { id: 'toggle-preview', name: 'Toggle preview pane' },
    { id: 'toggle-dualpane', name: 'Toggle dual pane' }
  ];

  var COLOR_PRESETS = [
    '#202020', '#1b1b1f', '#282828', '#1e2638',
    '#1a2e26', '#2d1f3d', '#332211', '#3c3c3c'
  ];

  var TAG_COLORS = [
    '#3584e4', '#33d17a', '#e01b24', '#f6d32d',
    '#9141ac', '#e66100', '#21a179', '#c01c28'
  ];

  var THIRD_PARTY_LIBS = [
    { name: 'ChromiumOS Ash', license: 'BSD-3-Clause', desc: 'The shell AuraDE is built on. Chromium and ChromiumOS marks belong to their owners.' },
    { name: 'Files (files-community)', license: 'MIT and MPL-2.0', desc: 'The design this file manager is drawn against. No code is taken; the layout and behaviour are the reference.' },
    { name: 'Pillow', license: 'MIT-CMU', desc: 'Decodes and scales image thumbnails.' },
    { name: 'Poppler', license: 'GPL-2.0-or-later', desc: 'Renders the first page of a PDF for its thumbnail. Called as a program, not linked.' },
    { name: 'FFmpeg', license: 'LGPL-2.1-or-later', desc: 'Pulls a single frame from a video for its thumbnail. Called as a program, not linked.' },
    { name: 'Breeze icons', license: 'LGPL-3.0', desc: 'Optional icon set, read from this computer only when chosen.' },
    { name: 'Adwaita icon theme', license: 'CC-BY-SA-3.0 and LGPL-3.0', desc: 'Optional icon set, read from this computer only when chosen.' }
  ];

  var prefs = Object.assign({}, DEFAULT_PREFS);
  var tags = [];
  var shortcuts = [];
  var activeCategory = 'general';
  var rootContainer = null;

  function loadAllData() {
    try {
      var saved = localStorage.getItem(PREFS_KEY);
      if (saved) {
        Object.assign(prefs, JSON.parse(saved));
      }
    } catch (e) {}

    try {
      var savedTags = localStorage.getItem(TAGS_KEY);
      if (savedTags) {
        tags = JSON.parse(savedTags);
      } else {
        tags = JSON.parse(JSON.stringify(DEFAULT_TAGS));
      }
    } catch (e) {
      tags = JSON.parse(JSON.stringify(DEFAULT_TAGS));
    }

    try {
      var savedShortcuts = localStorage.getItem(SHORTCUTS_KEY);
      if (savedShortcuts) {
        shortcuts = JSON.parse(savedShortcuts);
      } else {
        shortcuts = JSON.parse(JSON.stringify(DEFAULT_SHORTCUTS));
      }
    } catch (e) {
      shortcuts = JSON.parse(JSON.stringify(DEFAULT_SHORTCUTS));
    }
  }

  function savePrefs() {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    } catch (e) {}
  }

  function saveTags() {
    try {
      localStorage.setItem(TAGS_KEY, JSON.stringify(tags));
    } catch (e) {}
  }

  function saveShortcuts() {
    try {
      localStorage.setItem(SHORTCUTS_KEY, JSON.stringify(shortcuts));
    } catch (e) {}
  }

  function getPref(key) {
    return (key in prefs) ? prefs[key] : DEFAULT_PREFS[key];
  }

  function setPref(key, value) {
    prefs[key] = value;
    savePrefs();
    applyPref(key, value);
    syncDOMControl(key, value);
    return value;
  }

  function getPrefs() {
    return Object.assign({}, prefs);
  }

  function resetPrefs() {
    prefs = Object.assign({}, DEFAULT_PREFS);
    savePrefs();
    for (var k in prefs) {
      applyPref(k, prefs[k]);
    }
    if (rootContainer) {
      render(rootContainer);
    }
    return getPrefs();
  }

  function applyPref(key, value) {
    if (key === 'theme') {
      applyTheme(value);
    } else if (key === 'appBgColor') {
      if (value) {
        document.documentElement.style.setProperty('--solid-base', value);
        document.documentElement.style.setProperty('--desktop', value);
      }
    } else if (key === 'fontFamily') {
      if (value && value !== 'default') {
        document.documentElement.style.setProperty('--font', value);
      } else {
        document.documentElement.style.removeProperty('--font');
      }
    } else if (key === 'calcFolderSizes') {
      var infobar = document.getElementById('calc-folder-sizes-infobar');
      if (infobar) {
        infobar.hidden = !value;
      }
    } else if (key === 'startup') {
      var pagesCard = document.getElementById('startup-pages-card');
      if (pagesCard) {
        pagesCard.hidden = (value !== 'specific');
      }
    }

    if (typeof window.__setPref === 'function' && window.__setPref !== setPref) {
      try {
        window.__setPref(key, value);
      } catch (e) {}
    }
  }

  function applyTheme(theme) {
    var docEl = document.documentElement;
    var body = document.body;
    if (theme === 'light') {
      docEl.dataset.theme = 'light';
      if (body) {
        body.classList.remove('dark-theme');
        body.classList.add('light-theme');
      }
    } else if (theme === 'dark') {
      delete docEl.dataset.theme;
      docEl.removeAttribute('data-theme');
      if (body) {
        body.classList.remove('light-theme');
        body.classList.add('dark-theme');
      }
    } else {
      var isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      if (isDark) {
        delete docEl.dataset.theme;
        docEl.removeAttribute('data-theme');
        if (body) {
          body.classList.remove('light-theme');
          body.classList.add('dark-theme');
        }
      } else {
        docEl.dataset.theme = 'light';
        if (body) {
          body.classList.remove('dark-theme');
          body.classList.add('light-theme');
        }
      }
    }

    var isLight = docEl.dataset.theme === 'light';
    var darkChecks = document.querySelectorAll('#ck-dark');
    for (var d = 0; d < darkChecks.length; d++) {
      darkChecks[d].classList.toggle('on', !isLight);
    }
    var lightChecks = document.querySelectorAll('#ck-light');
    for (var l = 0; l < lightChecks.length; l++) {
      lightChecks[l].classList.toggle('on', isLight);
    }

    var themeSelects = document.querySelectorAll('select[data-pref="theme"], .ssel[data-pref="theme"]');
    for (var s = 0; s < themeSelects.length; s++) {
      if (themeSelects[s].value !== theme) {
        themeSelects[s].value = theme;
      }
    }

    prefs.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch (e) {}
    savePrefs();
  }

  function syncDOMControl(key, value) {
    if (!rootContainer) return;
    var sw = rootContainer.querySelector('.sw[data-pref="' + key + '"]');
    if (sw) {
      var boolVal = Boolean(value);
      sw.classList.toggle('on', boolVal);
      sw.setAttribute('aria-checked', boolVal ? 'true' : 'false');
    }
    var sel = rootContainer.querySelector('.ssel[data-pref="' + key + '"]');
    if (sel && sel.value !== String(value)) {
      sel.value = String(value);
    }
    var sld = rootContainer.querySelector('.sslider[data-pref="' + key + '"]');
    if (sld) {
      sld.value = String(value);
    }
  }

  function el(tag, attrs) {
    var elem = document.createElement(tag);
    if (attrs) {
      for (var k in attrs) {
        if (k === 'className' || k === 'class') {
          elem.className = attrs[k];
        } else if (k === 'text') {
          elem.textContent = attrs[k];
        } else if (k.indexOf('on') === 0 && typeof attrs[k] === 'function') {
          elem.addEventListener(k.substring(2).toLowerCase(), attrs[k]);
        } else if (k === 'dataset' && typeof attrs[k] === 'object') {
          for (var dk in attrs[k]) {
            elem.dataset[dk] = attrs[k][dk];
          }
        } else if (typeof attrs[k] === 'boolean') {
          //: An HTML boolean attribute is on when present, whatever its
          //: value, so disabled:false and hidden:false used to mean the
          //: opposite of what they read as.
          if (attrs[k]) elem.setAttribute(k, '');
          else elem.removeAttribute(k);
        } else {
          elem.setAttribute(k, attrs[k]);
        }
      }
    }
    for (var i = 2; i < arguments.length; i++) {
      var child = arguments[i];
      if (child === null || child === undefined) continue;
      if (typeof child === 'string' || typeof child === 'number') {
        elem.appendChild(document.createTextNode(String(child)));
      } else if (child instanceof Node) {
        elem.appendChild(child);
      } else if (Array.isArray(child)) {
        for (var j = 0; j < child.length; j++) {
          if (child[j] instanceof Node) {
            elem.appendChild(child[j]);
          } else if (child[j] !== null && child[j] !== undefined) {
            elem.appendChild(document.createTextNode(String(child[j])));
          }
        }
      }
    }
    return elem;
  }

  function svgEl(tag, attrs) {
    var elem = document.createElementNS('http://www.w3.org/2000/svg', tag);
    if (attrs) {
      for (var k in attrs) {
        elem.setAttribute(k, attrs[k]);
      }
    }
    for (var i = 2; i < arguments.length; i++) {
      var child = arguments[i];
      if (child instanceof Node) {
        elem.appendChild(child);
      }
    }
    return elem;
  }

  function clearElem(node) {
    while (node && node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function createSvgIcon(name, size) {
    var sz = size || 16;
    var s = svgEl('svg', {
      width: String(sz),
      height: String(sz),
      viewBox: '0 0 16 16',
      fill: 'currentColor',
      'aria-hidden': 'true'
    });

    if (name === 'general' || name === 'settings') {
      s.appendChild(svgEl('path', {
        d: 'M8 4.75a3.25 3.25 0 1 0 0 6.5 3.25 3.25 0 0 0 0-6.5zm-4.25 3.25a4.25 4.25 0 1 1 8.5 0 4.25 4.25 0 0 1-8.5 0z'
      }));
      s.appendChild(svgEl('path', {
        d: 'M7.1.5h1.8l.3 1.8c.4.1.8.3 1.2.6l1.6-.9 1.3 1.3-.9 1.6c.3.4.5.8.6 1.2l1.8.3v1.8l-1.8.3c-.1.4-.3.8-.6 1.2l.9 1.6-1.3 1.3-1.6-.9c-.4.3-.8.5-1.2.6l-.3 1.8H7.1l-.3-1.8c-.4-.1-.8-.3-1.2-.6l-1.6.9-1.3-1.3.9-1.6c-.3-.4-.5-.8-.6-1.2l-1.8-.3V7.1l1.8-.3c.1-.4.3-.8.6-1.2l-.9-1.6 1.3-1.3 1.6.9c.4-.3.8-.5 1.2-.6L7.1.5z'
      }));
    } else if (name === 'icons') {
      // A framed picture, which is what this page is about.
      s.appendChild(svgEl('path', {
        d: 'M2 3.5A1.5 1.5 0 0 1 3.5 2h9A1.5 1.5 0 0 1 14 3.5v9a1.5 1.5 0 0 1'
           + '-1.5 1.5h-9A1.5 1.5 0 0 1 2 12.5v-9zm1.5-.5a.5.5 0 0 0-.5.5v9a.5'
           + '.5 0 0 0 .5.5h9a.5.5 0 0 0 .5-.5v-9a.5.5 0 0 0-.5-.5h-9z'
      }));
      s.appendChild(svgEl('circle', { cx: '6', cy: '6', r: '1.2' }));
      s.appendChild(svgEl('path', {
        d: 'M3 11.5l2.8-2.8 2 2L10.5 8 13 10.5V12H3v-.5z'
      }));
    } else if (name === 'appearance') {
      s.appendChild(svgEl('path', {
        d: 'M8 0a8 8 0 1 0 0 16 2.5 2.5 0 0 0 2.5-2.5c0-.6-.2-1.1-.6-1.5-.4-.4-.6-.9-.6-1.5 0-1.1.9-2 2-2H13a3 3 0 0 0 3-3C16 2.5 12.4 0 8 0zM3.5 8a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm3-3a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm5 0a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3z'
      }));
    } else if (name === 'toolbar') {
      s.appendChild(svgEl('path', {
        d: 'M1.5 2h13A1.5 1.5 0 0 1 16 3.5v3A1.5 1.5 0 0 1 14.5 8h-13A1.5 1.5 0 0 1 0 6.5v-3A1.5 1.5 0 0 1 1.5 2zm0 1a.5.5 0 0 0-.5.5v3a.5.5 0 0 0 .5.5h13a.5.5 0 0 0 .5-.5v-3a.5.5 0 0 0-.5-.5h-13zM3 4h2v2H3V4zm3.5 0h3v2h-3V4zM11 4h2v2h-2V4zM1 10.5A.5.5 0 0 1 1.5 10h13a.5.5 0 0 1 0 1h-13a.5.5 0 0 1-.5-.5zm0 3a.5.5 0 0 1 .5-.5h8a.5.5 0 0 1 0 1h-8a.5.5 0 0 1-.5-.5z'
      }));
    } else if (name === 'layout') {
      s.appendChild(svgEl('path', {
        d: 'M1 2.5A1.5 1.5 0 0 1 2.5 1h11A1.5 1.5 0 0 1 15 2.5v11a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 1 13.5v-11zM2.5 2a.5.5 0 0 0-.5.5V6h5V2H2.5zm6 0v4h5.5V2.5a.5.5 0 0 0-.5-.5H8.5zm5.5 5H8.5v7H13a.5.5 0 0 0 .5-.5V7zM7 14V7H2v6.5a.5.5 0 0 0 .5.5H7z'
      }));
    } else if (name === 'folders') {
      s.appendChild(svgEl('path', {
        d: 'M1 3.5C1 2.67 1.67 2 2.5 2h3.2c.45 0 .88.2 1.17.55L8.1 4H13.5c.83 0 1.5.67 1.5 1.5V12.5c0 .83-.67 1.5-1.5 1.5h-11C1.67 14 1 13.33 1 12.5v-9zM2 5v7.5c0 .28.22.5.5.5h11c.28 0 .5-.22.5-.5V5.5c0-.28-.22-.5-.5-.5H7.7l-1.5-1.5H2.5c-.28 0-.5.22-.5.5V5z'
      }));
    } else if (name === 'actions') {
      s.appendChild(svgEl('path', {
        d: 'M14 2H2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2zM2 3h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zm1 2v2h2V5H3zm3 0v2h2V5H6zm3 0v2h2V5H9zm3 0v2h2V5h-2zM3 8v2h2V8H3zm3 0v2h4V8H6zm5 0v2h2V8h-2z'
      }));
    } else if (name === 'tags') {
      s.appendChild(svgEl('path', {
        d: 'M2 2a1 1 0 0 1 1-1h4.59a2 2 0 0 1 1.41.59l6.71 6.7a2 2 0 0 1 0 2.83l-4.59 4.59a2 2 0 0 1-2.83 0L1.59 9.41A2 2 0 0 1 1 8V3a1 1 0 0 1 1-1zm3.5 3a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z'
      }));
    } else if (name === 'devtools') {
      s.appendChild(svgEl('path', {
        d: 'M5.7 4.3a1 1 0 0 0-1.4-1.4l-4 4a1 1 0 0 0 0 1.4l4 4a1 1 0 0 0 1.4-1.4L2.4 7.6l3.3-3.3zm4.6 0a1 1 0 0 1 1.4-1.4l4 4a1 1 0 0 1 0 1.4l-4 4a1 1 0 0 1-1.4-1.4l3.3-3.3-3.3-3.3z'
      }));
    } else if (name === 'advanced') {
      s.appendChild(svgEl('path', {
        d: 'M14.7 12.3l-3.5-3.5a5 5 0 0 0-6.4-6.4l2.8 2.8-1.4 1.4-2.8-2.8a5 5 0 0 0 6.4 6.4l3.5 3.5a1 1 0 0 0 1.4 0l1.4-1.4a1 1 0 0 0 0-1.4z'
      }));
    } else if (name === 'about') {
      s.appendChild(svgEl('path', {
        d: 'M8 15A7 7 0 1 0 8 1a7 7 0 0 0 0 14zm0 1A8 8 0 1 1 8 0a8 8 0 0 1 0 16zm-.75-9.5h1.5v5.25h-1.5V6.5zm0-2.25a.75.75 0 1 1 1.5 0 .75.75 0 0 1-1.5 0z'
      }));
    } else if (name === 'chevron-down') {
      s.appendChild(svgEl('path', {
        d: 'M3.5 6l4.5 4.5L12.5 6',
        fill: 'none',
        stroke: 'currentColor',
        'stroke-width': '1.5',
        'stroke-linecap': 'round',
        'stroke-linejoin': 'round'
      }));
    } else if (name === 'close') {
      s.appendChild(svgEl('path', {
        d: 'M3 3l10 10M13 3L3 13',
        fill: 'none',
        stroke: 'currentColor',
        'stroke-width': '1.5',
        'stroke-linecap': 'round'
      }));
    } else if (name === 'trash') {
      s.appendChild(svgEl('path', {
        d: 'M2.5 4h11M5.5 4V2.5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V4m2 0v9.5a1.5 1.5 0 0 1-1.5 1.5h-6A1.5 1.5 0 0 1 3.5 13.5V4h9z'
      }));
    } else if (name === 'edit') {
      s.appendChild(svgEl('path', {
        d: 'M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z'
      }));
    } else if (name === 'warning') {
      s.appendChild(svgEl('path', {
        d: 'M7.1 2.3a1 1 0 0 1 1.8 0l6.1 10.5A1 1 0 0 1 14.1 14H1.9a1 1 0 0 1-.9-1.2l6.1-10.5zM8 5.5v4M8 11.5h.01',
        fill: 'none',
        stroke: 'currentColor',
        'stroke-width': '1.5',
        'stroke-linecap': 'round'
      }));
    } else {
      s.appendChild(svgEl('circle', { cx: '8', cy: '8', r: '6' }));
    }

    return s;
  }

  function createSwitch(prefKey, defaultVal) {
    var isChecked = Boolean(getPref(prefKey) !== undefined ? getPref(prefKey) : defaultVal);
    var sw = el('button', {
      className: 'sw' + (isChecked ? ' on' : ''),
      role: 'switch',
      'aria-checked': isChecked ? 'true' : 'false',
      title: 'Toggle',
      dataset: { pref: prefKey },
      onclick: function(e) {
        e.stopPropagation();
        var next = !sw.classList.contains('on');
        sw.classList.toggle('on', next);
        sw.setAttribute('aria-checked', next ? 'true' : 'false');
        setPref(prefKey, next);
      }
    }, el('span', { className: 'knob' }));
    return sw;
  }

  function createSelect(prefKey, options, defaultVal, onChange) {
    var curVal = getPref(prefKey) !== undefined ? getPref(prefKey) : defaultVal;
    var sel = el('select', {
      className: 'ssel',
      dataset: { pref: prefKey },
      onchange: function() {
        setPref(prefKey, sel.value);
        if (typeof onChange === 'function') onChange(sel.value);
      }
    });

    for (var i = 0; i < options.length; i++) {
      var opt = options[i];
      var val = (typeof opt === 'object' && opt !== null) ? opt.value : opt;
      var txt = (typeof opt === 'object' && opt !== null) ? opt.text : opt;
      var optEl = el('option', { value: val, text: txt });
      if (String(val) === String(curVal)) {
        optEl.selected = true;
      }
      sel.appendChild(optEl);
    }
    return sel;
  }

  function createCard(title, desc, control, iconName) {
    var card = el('div', { className: 'scard' });
    if (iconName) {
      card.appendChild(el('div', { className: 'scard-icon' }, createSvgIcon(iconName, 18)));
    }
    var tBox = el('div', { className: 'scard-t' },
      el('div', { className: 'scard-h', text: title })
    );
    if (desc) {
      tBox.appendChild(el('div', { className: 'scard-d', text: desc }));
    }
    card.appendChild(tBox);
    if (control) {
      card.appendChild(el('div', { className: 'scard-c' }, control));
    }
    return card;
  }

  function createExpander(title, desc, drawerContent, defaultExpanded) {
    var exp = el('div', {
      className: 'settings-expander' + (defaultExpanded ? ' expanded' : ''),
      'aria-expanded': defaultExpanded ? 'true' : 'false'
    });

    var header = el('button', {
      className: 'expander-header',
      type: 'button',
      onclick: function() {
        var isExp = exp.classList.toggle('expanded');
        exp.setAttribute('aria-expanded', isExp ? 'true' : 'false');
      }
    });

    var tBox = el('div', { className: 'scard-t' },
      el('div', { className: 'scard-h', text: title })
    );
    if (desc) {
      tBox.appendChild(el('div', { className: 'scard-d', text: desc }));
    }
    header.appendChild(tBox);
    header.appendChild(el('div', { className: 'expander-chevron' }, createSvgIcon('chevron-down', 14)));
    exp.appendChild(header);

    var drawer = el('div', { className: 'expander-drawer' });
    if (drawerContent) {
      if (Array.isArray(drawerContent)) {
        for (var i = 0; i < drawerContent.length; i++) {
          drawer.appendChild(drawerContent[i]);
        }
      } else {
        drawer.appendChild(drawerContent);
      }
    }
    exp.appendChild(drawer);
    return exp;
  }

  function createNestedCard(title, desc, control) {
    var card = el('div', { className: 'scard-nested' });
    var tBox = el('div', { className: 'scard-t' },
      el('div', { className: 'scard-h', text: title })
    );
    if (desc) {
      tBox.appendChild(el('div', { className: 'scard-d', text: desc }));
    }
    card.appendChild(tBox);
    if (control) {
      card.appendChild(el('div', { className: 'scard-c' }, control));
    }
    return card;
  }

  function createSectionHeader(title) {
    return el('div', { className: 'ssec', text: title });
  }

  function highlightMatchInNode(textNode, query) {
    var text = textNode.nodeValue;
    var q = query.toLowerCase();
    var idx = text.toLowerCase().indexOf(q);
    if (idx === -1) return false;

    var parent = textNode.parentNode;
    var before = text.substring(0, idx);
    var match = text.substring(idx, idx + query.length);
    var after = text.substring(idx + query.length);

    var frag = document.createDocumentFragment();
    if (before) frag.appendChild(document.createTextNode(before));
    frag.appendChild(el('span', { className: 'highlight-match', text: match }));
    if (after) frag.appendChild(document.createTextNode(after));

    parent.replaceChild(frag, textNode);
    return true;
  }

  function removeHighlights(container) {
    var marks = container.querySelectorAll('.highlight-match');
    for (var i = 0; i < marks.length; i++) {
      var mark = marks[i];
      var parent = mark.parentNode;
      if (parent) {
        parent.replaceChild(document.createTextNode(mark.textContent), mark);
        parent.normalize();
      }
    }
  }

  function renderGeneralPane() {
    var pane = el('div', { className: 'spane', id: 'spane-general' },
      el('div', { className: 'spane-title', text: 'General' })
    );

    pane.appendChild(createSectionHeader('Startup'));

    var startupSelect = createSelect('startup', [
      { value: 'home', text: 'Open new tab' },
      { value: 'last', text: 'Continue where you left off' },
      { value: 'specific', text: 'Open specific page' }
    ], 'home', function(val) {
      var pCard = document.getElementById('startup-pages-card');
      if (pCard) pCard.hidden = (val !== 'specific');
    });

    pane.appendChild(createCard('On startup', 'Which page or folders open when launching AuraDE Files.', startupSelect));

    var pagesCard = el('div', {
      className: 'scard',
      id: 'startup-pages-card'
    });
    pagesCard.hidden = (getPref('startup') !== 'specific');

    var pagesT = el('div', { className: 'scard-t' },
      el('div', { className: 'scard-h', text: 'Specific startup pages' }),
      el('div', { className: 'scard-d', text: 'Manage the list of directories to display on start.' })
    );
    pagesCard.appendChild(pagesT);

    var pagesListContainer = el('div', { className: 'startup-pages-list' });

    function refreshStartupPages() {
      clearElem(pagesListContainer);
      var pages = getPref('startupPages') || ['/home'];
      for (var i = 0; i < pages.length; i++) {
        (function(pagePath, index) {
          var row = el('div', { className: 'startup-page-row' },
            el('span', { className: 'startup-page-path', text: pagePath }),
            el('button', {
              className: 'startup-page-remove-btn',
              title: 'Remove page',
              onclick: function() {
                var cur = (getPref('startupPages') || []).slice();
                cur.splice(index, 1);
                setPref('startupPages', cur);
                refreshStartupPages();
              }
            }, createSvgIcon('close', 12))
          );
          pagesListContainer.appendChild(row);
        })(pages[i], i);
      }
    }
    refreshStartupPages();

    var addInput = el('input', { className: 'sinput', placeholder: '/path/to/folder' });
    var addBtn = el('button', {
      className: 'btn-dlg',
      text: 'Add page',
      onclick: function() {
        var val = addInput.value.trim();
        if (val) {
          var cur = (getPref('startupPages') || []).slice();
          cur.push(val);
          setPref('startupPages', cur);
          addInput.value = '';
          refreshStartupPages();
        }
      }
    });
    var addRow = el('div', { className: 'startup-page-add-row' }, addInput, addBtn);

    var pagesControls = el('div', { style: 'display:flex; flex-direction:column; width:100%; gap:8px;' },
      pagesListContainer,
      addRow
    );
    pagesCard.appendChild(el('div', { className: 'scard-c', style: 'width:100%; max-width:400px;' }, pagesControls));
    pane.appendChild(pagesCard);

    pane.appendChild(createCard('Open in existing instance', 'Re-use active window when opening files from other applications.', createSwitch('startupExistingInstance', true)));
    pane.appendChild(createCard('Always switch to new tab', 'Automatically activate tabs when they are created.', createSwitch('alwaysSwitchNewTab', false)));

    pane.appendChild(createSectionHeader('Preferences and Localization'));
    pane.appendChild(createCard('Language', 'Interface display language for AuraDE Files.', createSelect('language', [
      { value: 'default', text: 'System default' },
      { value: 'en', text: 'English' },
      { value: 'es', text: 'Spanish' },
      { value: 'fr', text: 'French' },
      { value: 'de', text: 'German' },
      { value: 'zh', text: 'Chinese' },
      { value: 'ja', text: 'Japanese' }
    ], 'default')));

    var dateSample = el('div', {
      className: 'date-format-preview',
      style: 'font-size:12px; color:var(--text-3); margin-top:4px;'
    });
    function updateDateSample(format) {
      var d = new Date();
      var yr = d.getFullYear();
      var mo = String(d.getMonth() + 1).padStart(2, '0');
      var da = String(d.getDate()).padStart(2, '0');
      var formatted = yr + '-' + mo + '-' + da;
      if (format === 'MM/DD/YYYY') formatted = mo + '/' + da + '/' + yr;
      else if (format === 'DD/MM/YYYY') formatted = da + '/' + mo + '/' + yr;
      else if (format === 'YYYY-MM-DD') formatted = yr + '-' + mo + '-' + da;
      dateSample.textContent = 'Sample: ' + formatted;
    }
    updateDateSample(getPref('dateFormat'));

    var dateSelect = createSelect('dateFormat', [
      { value: 'default', text: 'System default' },
      { value: 'MM/DD/YYYY', text: 'MM/DD/YYYY' },
      { value: 'DD/MM/YYYY', text: 'DD/MM/YYYY' },
      { value: 'YYYY-MM-DD', text: 'YYYY-MM-DD' }
    ], 'default', updateDateSample);

    var dateContainer = el('div', { style: 'display:flex; flex-direction:column; align-items:flex-end;' },
      dateSelect,
      dateSample
    );
    pane.appendChild(createCard('Date format', 'How modification and creation timestamps appear in lists.', dateContainer));

    pane.appendChild(createCard('Long context menus', 'What happens to the items below the ones listed above when the menu runs out of room.', createSelect('contextMenuOverflow', [
      { value: 'submenu', text: 'Move them into a submenu' },
      { value: 'scroll', text: 'Keep one list and scroll' }
    ], 'submenu')));

    pane.appendChild(createSectionHeader('Tabs'));
    pane.appendChild(createCard('Reverse tab scroll direction', 'Scrolling down over the tab strip moves to the tab on the left instead of the right.', createSwitch('reverseTabScroll', false)));

    pane.appendChild(createSectionHeader('Home Widgets'));
    pane.appendChild(createCard('Quick access', 'Pinned favorite folders on the home screen.', createSwitch('widgets.qa', true)));
    pane.appendChild(createCard('Drives', 'Mounted storage partitions and system volumes.', createSwitch('widgets.drives', true)));
    pane.appendChild(createCard('Network', 'Network locations, shared volumes, and servers.', createSwitch('widgets.network', true)));
    pane.appendChild(createCard('Tags', 'Color tags widget on the home screen.', createSwitch('widgets.tags', true)));
    pane.appendChild(createCard('Recent files', 'Recently opened and modified documents list.', createSwitch('widgets.recent', true)));

    pane.appendChild(createSectionHeader('Dual Pane'));
    pane.appendChild(createCard('Always open dual pane in new tab', 'Open split view inside a dedicated tab container.', createSwitch('dualPaneNewTab', false)));
    pane.appendChild(createCard('Split direction', 'Arrangement layout orientation for secondary pane.', createSelect('dualPaneSplit', [
      'Horizontal',
      'Vertical'
    ], 'Horizontal')));

    pane.appendChild(createSectionHeader('Context Menu'));
    var ctxMenuToggles = [
      { key: 'contextMenu.openInNewTab', title: 'Open in new tab', desc: 'Display shortcut to open folder in a new tab.' },
      { key: 'contextMenu.openInNewWindow', title: 'Open in new window', desc: 'Display shortcut to spawn a separate window instance.' },
      { key: 'contextMenu.openInNewPane', title: 'Open in new pane', desc: 'Display action to view path in opposite split pane.' },
      { key: 'contextMenu.copyPath', title: 'Copy path', desc: 'Copy absolute filesystem path to clipboard.' },
      { key: 'contextMenu.createFolderWithSelection', title: 'Create folder with selection', desc: 'Group selected items into a new subfolder.' },
      { key: 'contextMenu.createAlternateDataStream', title: 'Create alternate data stream', desc: 'Access extended NTFS alternate data streams.' },
      { key: 'contextMenu.createShortcut', title: 'Create shortcut', desc: 'Generate symbolic or shell shortcut link.' },
      { key: 'contextMenu.flattenOptions', title: 'Flatten options', desc: 'Show the action that lists a folder tree as one flat list.' },
      { key: 'contextMenu.pinToSidebar', title: 'Pin to sidebar', desc: 'Add selected directory to the navigation rail.' },
      { key: 'contextMenu.compressionOptions', title: 'Compression options', desc: 'Archive and extraction submenus.' },
      { key: 'contextMenu.sendTo', title: 'Send to', desc: 'Display auxiliary destination shortcuts.' },
      { key: 'contextMenu.openTerminal', title: 'Open in terminal', desc: 'Launch terminal emulator at current directory.' },
      { key: 'contextMenu.editTags', title: 'Edit tags', desc: 'Assign or modify colored classification tags.' }
    ];

    var nestedItems = [];
    for (var j = 0; j < ctxMenuToggles.length; j++) {
      var item = ctxMenuToggles[j];
      nestedItems.push(createNestedCard(item.title, item.desc, createSwitch(item.key, item.key !== 'contextMenu.createAlternateDataStream')));
    }
    pane.appendChild(createExpander('Context menu items', 'Select which items appear when right-clicking files and folders.', nestedItems, false));

    pane.appendChild(createSectionHeader('Scrolling'));
    pane.appendChild(createCard('Smooth scrolling', 'Enable smooth interpolation when scrolling lists and grids.', createSwitch('smoothScrolling', true)));

    return pane;
  }

  function renderAppearancePane() {
    var pane = el('div', { className: 'spane', id: 'spane-appearance', hidden: true },
      el('div', { className: 'spane-title', text: 'Appearance' })
    );

    var themeGroup = el('div', { className: 'theme-group', style: 'margin-bottom:12px;' },
      el('div', { className: 'mhead', text: 'Theme' }),
      el('div', {
        className: 'mi',
        dataset: { theme: 'dark' },
        onclick: function() { applyTheme('dark'); }
      },
        el('span', { className: 'mi-ic' }, el('span', { className: 'ck', id: 'ck-dark' })),
        el('span', { className: 'mi-t', text: 'Dark' })
      ),
      el('div', {
        className: 'mi',
        dataset: { theme: 'light' },
        onclick: function() { applyTheme('light'); }
      },
        el('span', { className: 'mi-ic' }, el('span', { className: 'ck', id: 'ck-light' })),
        el('span', { className: 'mi-t', text: 'Light' })
      )
    );
    var isCurrentLight = document.documentElement.dataset.theme === 'light';
    var ckDark = themeGroup.querySelector('#ck-dark');
    var ckLight = themeGroup.querySelector('#ck-light');
    if (ckDark) ckDark.classList.toggle('on', !isCurrentLight);
    if (ckLight) ckLight.classList.toggle('on', isCurrentLight);
    pane.appendChild(themeGroup);

    pane.appendChild(createSectionHeader('Theme and Styling'));
    var themeSelect = createSelect('theme', [
      { value: 'dark', text: 'Dark' },
      { value: 'light', text: 'Light' },
      { value: 'system', text: 'System' }
    ], 'dark', function(val) {
      applyTheme(val);
    });
    pane.appendChild(createCard('App theme', 'Choose Dark, Light, or follow your operating system appearance.', themeSelect));

    pane.appendChild(createCard('Backdrop material', 'Background translucency and blur materials.', createSelect('backdropMaterial', [
      'Solid', 'Mica', 'Acrylic', 'Mica Alt'
    ], 'Mica')));

    pane.appendChild(createSectionHeader('Background Customization'));

    var swatchesGrid = el('div', { className: 'color-swatches-grid' });
    var colorPicker = el('input', {
      type: 'color',
      value: getPref('appBgColor') || '#202020',
      style: 'width:32px; height:32px; border:none; background:transparent; cursor:pointer;',
      onchange: function() {
        setPref('appBgColor', colorPicker.value);
        updateSwatchActive();
      }
    });

    function updateSwatchActive() {
      var cur = getPref('appBgColor');
      var buttons = swatchesGrid.querySelectorAll('.color-swatch');
      for (var i = 0; i < buttons.length; i++) {
        var b = buttons[i];
        b.classList.toggle('active', b.dataset.color.toLowerCase() === cur.toLowerCase());
      }
    }

    for (var i = 0; i < COLOR_PRESETS.length; i++) {
      (function(c) {
        var btn = el('button', {
          className: 'color-swatch' + (getPref('appBgColor') === c ? ' active' : ''),
          style: 'background-color:' + c + ';',
          dataset: { color: c },
          title: c,
          onclick: function() {
            setPref('appBgColor', c);
            colorPicker.value = c;
            updateSwatchActive();
          }
        });
        swatchesGrid.appendChild(btn);
      })(COLOR_PRESETS[i]);
    }
    swatchesGrid.appendChild(colorPicker);
    pane.appendChild(createCard('App background color', 'Custom color palette tint for the main window canvas.', swatchesGrid));

    var bgPathInput = el('input', {
      className: 'sinput',
      placeholder: '/path/to/wallpaper.png',
      value: getPref('bgImagePath') || '',
      style: 'width:180px;',
      onchange: function() { setPref('bgImagePath', bgPathInput.value); }
    });
    var bgBrowseBtn = el('button', { className: 'btn-dlg', text: 'Browse' });
    var bgRemoveBtn = el('button', {
      className: 'btn-dlg btn-danger',
      text: 'Remove',
      onclick: function() {
        bgPathInput.value = '';
        setPref('bgImagePath', '');
      }
    });
    var bgControls = el('div', { style: 'display:flex; align-items:center; gap:6px;' },
      bgPathInput, bgBrowseBtn, bgRemoveBtn
    );
    pane.appendChild(createCard('App background image', 'Display custom artwork or desktop wallpaper behind files.', bgControls));

    var opacityVal = el('span', {
      text: Math.round((getPref('bgImageOpacity') || 0.5) * 100) + '%',
      style: 'font-size:12px; width:40px; text-align:right;'
    });
    var opacitySlider = el('input', {
      type: 'range',
      className: 'sslider',
      min: '0.1',
      max: '1.0',
      step: '0.05',
      value: String(getPref('bgImageOpacity') || 0.5),
      dataset: { pref: 'bgImageOpacity' },
      oninput: function() {
        opacityVal.textContent = Math.round(parseFloat(opacitySlider.value) * 100) + '%';
        setPref('bgImageOpacity', parseFloat(opacitySlider.value));
      }
    });
    pane.appendChild(createCard('Background image opacity', 'Opacity level for custom background artwork.', el('div', { style: 'display:flex; align-items:center; gap:8px;' }, opacitySlider, opacityVal)));

    pane.appendChild(createCard('Background image vertical placement', 'Where the image sits when it is smaller than the window.', createSelect('bgImageVAlign', [
      'Top', 'Center', 'Bottom'
    ], 'Center')));
    pane.appendChild(createCard('Background image horizontal placement', 'Where the image sits across the width of the window.', createSelect('bgImageHAlign', [
      'Left', 'Center', 'Right'
    ], 'Center')));
    pane.appendChild(createCard('Background image fit', 'How background image scales within the application boundary.', createSelect('bgImageFit', [
      'Fill', 'Uniform', 'UniformToFill', 'None'
    ], 'UniformToFill')));

    pane.appendChild(createSectionHeader('Typography'));
    pane.appendChild(createCard('Font family', 'Primary typography used across titles, file items, and menus.', createSelect('fontFamily', [
      { value: 'default', text: 'System default' },
      { value: 'Segoe UI Variable', text: 'Segoe UI Variable' },
      { value: 'Segoe UI', text: 'Segoe UI' },
      { value: 'Aptos', text: 'Aptos' },
      { value: 'Cascadia Code', text: 'Cascadia Code' },
      { value: 'Arial', text: 'Arial' }
    ], 'default')));

    pane.appendChild(createSectionHeader('Window Chrome'));
    pane.appendChild(createCard('Show tab actions', 'The new tab button and the tab strip controls.', createSwitch('showTabActions', true)));
    pane.appendChild(createCard('Show the toolbar', 'The row of buttons above the file list.', createSwitch('showToolbar', true)));
    pane.appendChild(createCard('Show the shelf pane toggle', 'The address bar button that opens and closes the shelf.', createSwitch('showShelfBtn', true)));
    pane.appendChild(createCard('Show the preview pane button', 'The toolbar button that opens and closes the preview pane.', createSwitch('showPaneBtn', true)));
    pane.appendChild(createCard('Show the Status Center button', 'The toolbar button that opens the list of running operations.', createSwitch('showSCBtn', true)));
    pane.appendChild(createCard('Show the status bar', 'The strip along the bottom with the item count and selection size.', createSwitch('showStatusbar', true)));

    pane.appendChild(createCard('Customize the toolbar',
      'Choose which buttons are on the toolbar and what order they sit in.',
      el('button', {
        className: 'btn-dlg', type: 'button', id: 'go-toolbar', text: 'Customize',
        onclick: function() { selectCategory('toolbar'); }
      })));

    pane.appendChild(createSectionHeader('Status Center'));
    pane.appendChild(createCard('Status Center visibility', 'Control when background tasks and operations badge displays in toolbar.', createSelect('statusCenterVisibility', [
      'Always', 'Active tasks only', 'Never'
    ], 'Active tasks only')));

    return pane;
  }

  //: The Icons page. The chooser moved here off the Appearance card, because
  //: a setting with a preview of twenty nine glyphs is a page, not a row, and
  //: the reference gives anything with that much surface its own page.
  //: Toolbar customization. The reference gives this its own page because it
  //: is two lists and a preview, not a row. What can be on the bar is data
  //: (TB_CATALOG), what is on it is a preference, and the bar itself carries
  //: the same ids, so applying a change is a reorder rather than a rebuild.
  var TB_CATALOG = __BUILD("TOOLBAR_CATALOG_JSON");
  var TB_DEFAULT = __BUILD("TOOLBAR_DEFAULT_JSON");
  var TB_CONTEXTS = [
    { id: 'default', title: 'Main toolbar', pref: 'toolbar.default' },
    { id: 'compact', title: 'Compact toolbar', pref: 'toolbar.compact' }
  ];

  function tbLabel(id) {
    for (var i = 0; i < TB_CATALOG.length; i++) {
      if (TB_CATALOG[i].id === id) return TB_CATALOG[i].label;
    }
    return id;
  }

  function tbIcon(id) {
    var src = document.querySelector('#tbicons [data-tbico="' + id + '"] svg');
    return src ? src.cloneNode(true) : el('span', { className: 'tb-noico' });
  }

  function renderToolbarPane() {
    var pane = el('div', { className: 'spane', id: 'spane-toolbar', hidden: true },
      el('div', { className: 'spane-title', text: 'Toolbar' })
    );

    var ctxId = 'default';
    function prefKey() {
      for (var i = 0; i < TB_CONTEXTS.length; i++) {
        if (TB_CONTEXTS[i].id === ctxId) return TB_CONTEXTS[i].pref;
      }
      return 'toolbar.default';
    }
    function current() {
      var v = getPref(prefKey());
      return Array.isArray(v) && v.length ? v.slice() : TB_DEFAULT.slice();
    }
    function commit(ids) {
      setPref(prefKey(), ids);
      paint();
    }

    var preview = el('div', { className: 'tb-preview', id: 'tb-preview' });
    var addedList = el('div', { className: 'tb-list', id: 'tb-added' });
    var availList = el('div', { className: 'tb-list', id: 'tb-avail' });
    var search = el('input', {
      className: 'sinput', id: 'tb-search', type: 'search',
      placeholder: 'Search buttons',
      oninput: function () { paint(); }
    });

    function paint() {
      var ids = current();
      clearElem(preview);
      for (var p = 0; p < ids.length; p++) {
        preview.appendChild(el('span', { className: 'tb-preview-btn',
                                         title: tbLabel(ids[p]) },
                               tbIcon(ids[p])));
      }
      if (!ids.length) {
        preview.appendChild(el('span', { className: 'tb-empty',
          text: 'Nothing on the toolbar. It will be a blank strip.' }));
      }

      clearElem(addedList);
      for (var i = 0; i < ids.length; i++) {
        (function (id, idx) {
          var row = el('div', { className: 'tb-row', dataset: { tbrow: id } },
            el('span', { className: 'tb-row-ico' }, tbIcon(id)),
            el('span', { className: 'tb-row-lbl', text: tbLabel(id) }),
            el('button', {
              className: 'tb-row-btn', type: 'button', title: 'Move up',
              text: 'Up',
              disabled: idx === 0,
              onclick: function () {
                var next = current();
                var t = next[idx - 1]; next[idx - 1] = next[idx]; next[idx] = t;
                commit(next);
              }
            }),
            el('button', {
              className: 'tb-row-btn', type: 'button', title: 'Move down',
              text: 'Down',
              disabled: idx === ids.length - 1,
              onclick: function () {
                var next = current();
                var t = next[idx + 1]; next[idx + 1] = next[idx]; next[idx] = t;
                commit(next);
              }
            }),
            el('button', {
              className: 'tb-row-btn tb-row-rm', type: 'button',
              title: 'Remove from the toolbar', text: 'Remove',
              onclick: function () {
                commit(current().filter(function (x) { return x !== id; }));
              }
            })
          );
          addedList.appendChild(row);
        })(ids[i], i);
      }

      var q = (search.value || '').trim().toLowerCase();
      clearElem(availList);
      var shown = 0;
      for (var j = 0; j < TB_CATALOG.length; j++) {
        (function (item) {
          if (ids.indexOf(item.id) !== -1) return;
          if (q && item.label.toLowerCase().indexOf(q) === -1) return;
          shown = shown + 1;
          availList.appendChild(el('div', { className: 'tb-row',
                                            dataset: { tbavail: item.id } },
            el('span', { className: 'tb-row-ico' }, tbIcon(item.id)),
            el('span', { className: 'tb-row-lbl', text: item.label }),
            el('button', {
              className: 'tb-row-btn tb-row-add', type: 'button',
              title: 'Add to the toolbar', text: 'Add',
              onclick: function () { commit(current().concat([item.id])); }
            })
          ));
        })(TB_CATALOG[j]);
      }
      if (!shown) {
        availList.appendChild(el('div', { className: 'tb-empty',
          text: q ? 'No button matches that.' : 'Everything is on the toolbar.' }));
      }
    }

    var ctxSelect = el('select', { className: 'ssel', id: 'tb-context-sel',
      onchange: function () { ctxId = ctxSelect.value; paint(); } });
    for (var c = 0; c < TB_CONTEXTS.length; c++) {
      ctxSelect.appendChild(el('option', { value: TB_CONTEXTS[c].id,
                                           text: TB_CONTEXTS[c].title }));
    }

    pane.appendChild(createCard('Which toolbar',
      'The main toolbar is the one at the top of every window. The compact one '
      + 'is used when the window is too narrow for all of it.', ctxSelect));

    pane.appendChild(createSectionHeader('Preview'));
    pane.appendChild(el('div', { className: 'scard tb-preview-card' }, preview));

    pane.appendChild(createSectionHeader('On the toolbar'));
    pane.appendChild(el('div', { className: 'scard tb-list-card' }, addedList));

    pane.appendChild(createSectionHeader('Available'));
    pane.appendChild(el('div', { className: 'scard tb-search-card' }, search));
    pane.appendChild(el('div', { className: 'scard tb-list-card' }, availList));

    pane.appendChild(createCard('Start over',
      'Put every button back where it was and in the order it shipped in.',
      el('button', {
        className: 'btn-dlg', type: 'button', id: 'tb-reset', text: 'Reset',
        onclick: function () { commit(TB_DEFAULT.slice()); }
      })));

    paint();
    return pane;
  }

  function renderIconsPane() {
    var pane = el('div', { className: 'spane', id: 'spane-icons', hidden: true },
      el('div', { className: 'spane-title', text: 'Icons' })
    );

    var sets = window.__iconSets || {};
    var names = Object.keys(sets);
    if (!names.length) names = ['@@ICON_SET@@'];

    var note = el('div', { className: 'scard-d', style: 'margin-top:2px;' });
    var sheet = el('div', { className: 'iconsheet' });

    //: Every category, at the size the file list uses, with the name under it.
    //: A set is chosen by looking at it, so the page shows all of it rather
    //: than a strip of six.
    var KEYS = __BUILD("ICON_KEYS_JSON");

    function paintSheet(setName) {
      var active = sets[setName] ? setName : '@@ICON_SET@@';
      note.textContent = (sets[active] && sets[active].note) || '';
      clearElem(sheet);
      var prev = document.documentElement.getAttribute('data-iconset');
      document.documentElement.setAttribute('data-iconset', active);
      for (var i = 0; i < KEYS.length; i++) {
        var cell = el('div', { className: 'iconsheet-cell' });
        var box = el('div', { className: 'iconsheet-art' });
        var art = window.__takeArt ? window.__takeArt(KEYS[i][0], false) : null;
        if (art) {
          art.removeAttribute('class');
          art.setAttribute('width', '40');
          art.setAttribute('height', '40');
          box.appendChild(art);
        }
        cell.appendChild(box);
        cell.appendChild(el('div', { className: 'iconsheet-lbl',
                                     text: KEYS[i][1] }));
        sheet.appendChild(cell);
      }
      if (prev) document.documentElement.setAttribute('data-iconset', prev);
      else document.documentElement.removeAttribute('data-iconset');
    }

    var select = createSelect('iconSet', names.map(function (k) {
      return { value: k, text: (sets[k] && sets[k].title) || k };
    }), '@@ICON_SET@@', function (val) {
      //: setPref already routes iconSet through applyPref, so the file list
      //: repaints on its own. This only has to catch the sheet up.
      paintSheet(val);
    });

    pane.appendChild(createSectionHeader('Icon set'));
    //: The card says what the setting is. The note under it says what the
    //: chosen set is, and Adding a set says where the others come from, so
    //: none of the three repeats another.
    var card = createCard('File icons',
      'The artwork the file list uses for each kind of file.', select);
    var body = card.querySelector('.scard-t');
    if (body) body.appendChild(note);
    pane.appendChild(card);

    pane.appendChild(createSectionHeader('What each kind looks like'));
    pane.appendChild(sheet);

    pane.appendChild(createSectionHeader('Adding a set'));
    pane.appendChild(el('div', { className: 'scard-d',
      style: 'padding:0 2px 8px; line-height:18px;',
      text: 'Sets come from the icon themes installed on this computer, under '
        + '/usr/share/icons. Install a theme with your package manager and it '
        + 'appears in this list the next time AuraDE starts. A theme that has '
        + 'no icon for a kind of file keeps the AuraDE one, so a partial theme '
        + 'is a partial change rather than a page of blanks.' }));

    paintSheet(getPref('iconSet') || '@@ICON_SET@@');
    return pane;
  }

  function renderLayoutPane() {
    var pane = el('div', { className: 'spane', id: 'spane-layout', hidden: true },
      el('div', { className: 'spane-title', text: 'Layout' })
    );

    pane.appendChild(createSectionHeader('Default View'));
    pane.appendChild(createCard('Default layout', 'Initial layout mode applied when opening directories without saved view preferences.', createSelect('defLayout', [
      { value: 'details', text: 'Details' },
      { value: 'grid', text: 'Grid' },
      { value: 'list', text: 'List' },
      { value: 'cards', text: 'Cards' },
      { value: 'columns', text: 'Columns' },
      { value: 'adaptive', text: 'Adaptive' }
    ], 'grid')));

    pane.appendChild(createCard('Sync folder preferences across directories', 'Apply standard sorting and column layout globally to all folders.', createSwitch('syncFolderPrefs', false)));

    pane.appendChild(createSectionHeader('Default Sorting'));
    pane.appendChild(createCard('Sort by', 'Which column a folder is sorted on before you choose otherwise.', createSelect('sortBy', [
      'Name', 'Date modified', 'Date created', 'Size', 'Type'
    ], 'Name')));
    pane.appendChild(createCard('Sort in descending order', 'Start with the largest, the newest or the last name rather than the first.', createSwitch('sortDesc', false)));

    pane.appendChild(createSectionHeader('Grouping and Sorting'));

    var groupDrawer = [
      createNestedCard('Group by property', 'Categorize files by name, modification date, size, or tags.', createSelect('groupByProperty', [
        'None', 'Name', 'Date modified', 'Date created', 'Size', 'Type', 'Tag'
      ], 'None')),
      createNestedCard('Descending order', 'Sort grouped sections in reverse alphabetical or chronological order.', createSwitch('groupByDesc', false)),
      createNestedCard('Group by date unit', 'Resolution for date-based categorization headers.', createSelect('groupByDateUnit', [
        'Year', 'Month', 'Day'
      ], 'Month'))
    ];
    pane.appendChild(createExpander('True Group By settings', 'Organize listings into collapsible section headers based on properties.', groupDrawer, false));

    pane.appendChild(createCard('Sort priority', 'Relative arrangement of folders compared to standard files.', createSelect('groupBy', [
      { value: 'first', text: 'Folders first' },
      { value: 'last', text: 'Files first' },
      { value: 'together', text: 'Mixed together' }
    ], 'first')));

    pane.appendChild(createSectionHeader('Details View Columns'));
    var colDrawer = [
      createNestedCard('Auto-size columns', 'Automatically scale column widths to fit cell contents.', createSwitch('columns.autoSize', true)),
      createNestedCard('Tag column', 'Display assigned color tag pill badge column.', createSwitch('columns.tag', true)),
      createNestedCard('Size column', 'Display file byte or item count size column.', createSwitch('columns.size', true)),
      createNestedCard('Type column', 'Display descriptive file type classification column.', createSwitch('columns.type', true)),
      createNestedCard('Date modified column', 'Display last modification timestamp column.', createSwitch('columns.dateModified', true)),
      createNestedCard('Date created column', 'Display initial creation timestamp column.', createSwitch('columns.dateCreated', false))
    ];
    pane.appendChild(createExpander('Details view column customizer', 'Show or hide columns and enable auto-fit sizing in Details view.', colDrawer, false));

    return pane;
  }

  function renderFoldersPane() {
    var pane = el('div', { className: 'spane', id: 'spane-folders', hidden: true },
      el('div', { className: 'spane-title', text: 'Folders' })
    );

    pane.appendChild(createSectionHeader('Hidden Files and Protection'));
    pane.appendChild(createCard('Show hidden files', 'Display items marked with the hidden attribute.', createSwitch('showHidden', false)));
    pane.appendChild(createCard('Show dot files', 'Display UNIX dotfiles and configuration directories.', createSwitch('showDotFiles', false)));
    pane.appendChild(createCard('Show protected system files', 'Display critical operating system and kernel files.', createSwitch('showSystemFiles', false)));

    pane.appendChild(createSectionHeader('Item Appearance and Selection'));
    pane.appendChild(createCard('Show file extensions', 'Display the part of a name after the last dot.', createSwitch('showExt', true)));
    pane.appendChild(createCard('Show thumbnails', 'Display thumbnail previews for images, video clips, and documents.', createSwitch('showThumbnails', true)));
    pane.appendChild(createCard('Show checkboxes', 'Display selection checkboxes beside items on hover and focus.', createSwitch('showCheckboxes', true)));
    pane.appendChild(createCard('Select on hover', 'Resting the pointer on an item selects it, without a click.', createSwitch('selectOnHover', false)));

    pane.appendChild(createSectionHeader('Single-Click Navigation'));
    pane.appendChild(createCard('Single-click to open files', 'Open document files with a single click instead of double-click.', createSwitch('singleClickFiles', false)));
    pane.appendChild(createCard('Single-click to open folders', 'Traverse into folders with a single click.', createSwitch('singleClickFolders', false)));
    pane.appendChild(createCard('Single-click in columns view', 'Expand subfolders immediately on single click in columns layout.', createSwitch('singleClickColumns', false)));

    pane.appendChild(createSectionHeader('Navigation'));
    pane.appendChild(createCard('Open folders in a new tab', 'Opening a folder puts it in a new tab rather than replacing the current one.', createSwitch('openNewTab', false)));
    pane.appendChild(createCard('Double-click empty space to go up', 'Double-clicking the background of a folder navigates to its parent.', createSwitch('dblclickUp', false)));
    pane.appendChild(createCard('Return to the folder you came from', 'Going up selects and scrolls to the folder you just left, rather than the top of the list.', createSwitch('scrollToPreviousFolder', true)));

    pane.appendChild(createSectionHeader('Operations and Warnings'));
    pane.appendChild(createCard('Delete confirmation policy', 'Specify when safety confirmation dialogs appear before deletion.', createSelect('confirmDeletePolicy', [
      'Always', 'Permanent only', 'Never'
    ], 'Always')));

    pane.appendChild(createCard('File extension warning', 'Warn before changing a file extension during item rename.', createSwitch('warnExtensionChange', true)));

    var calcCard = createCard('Calculate folder sizes', 'Scan subfolder contents to compute aggregate folder byte sizes.', createSwitch('calcFolderSizes', false));
    pane.appendChild(calcCard);

    var infobar = el('div', {
      className: 'infobar infobar-warning',
      id: 'calc-folder-sizes-infobar'
    });
    infobar.hidden = !getPref('calcFolderSizes');
    infobar.appendChild(el('div', { className: 'infobar-icon' }, createSvgIcon('warning', 16)));
    var ibContent = el('div', { className: 'infobar-content' },
      el('div', { className: 'infobar-title', text: 'Performance notice' }),
      el('div', { className: 'infobar-message', text: 'Calculating folder sizes requires recursively scanning directory trees, which may impact filesystem responsiveness on large directories.' })
    );
    infobar.appendChild(ibContent);
    pane.appendChild(infobar);

    pane.appendChild(createCard('Size format', 'Choose between binary (1024 KiB/MiB) and decimal (1000 KB/MB) base notation.', createSelect('sizeFormat', [
      'Binary', 'Decimal'
    ], 'Binary')));

    pane.appendChild(createSectionHeader('File Tags'));
    pane.appendChild(el('div', { className: 'scard', style: 'display:flex; justify-content:space-between; align-items:center;' },
      el('div', null,
        el('div', { style: 'font-weight:500;', text: 'Manage File Tags' }),
        el('div', { style: 'font-size:12px; color:var(--text-secondary);', text: 'Configure custom tags and color labels' })
      ),
      el('button', {
        className: 'btn-dlg',
        text: 'Manage Tags...',
        onclick: function() { selectCategory('tags'); }
      })
    ));

    return pane;
  }

  function renderActionsPane() {
    var pane = el('div', { className: 'spane', id: 'spane-actions', hidden: true },
      el('div', { className: 'spane-title', text: 'Actions' })
    );

    pane.appendChild(createSectionHeader('Keyboard Shortcuts'));

    var filterInput = el('input', {
      className: 'sinput actions-filter',
      placeholder: 'Filter shortcuts by command name...',
      style: 'width:100%; box-sizing:border-box; margin-bottom:8px;',
      oninput: function() {
        refreshShortcutsUI(filterInput.value);
      }
    });
    pane.appendChild(filterInput);

    var cmdSelect = el('select', { className: 'ssel cmd-picker' });
    for (var i = 0; i < COMMANDS_LIST.length; i++) {
      cmdSelect.appendChild(el('option', { value: COMMANDS_LIST[i].id, text: COMMANDS_LIST[i].name }));
    }

    var captureInput = el('input', {
      className: 'sinput key-capture-input',
      placeholder: 'Press keys...',
      readOnly: true
    });

    var recordedKeys = '';
    captureInput.addEventListener('keydown', function(e) {
      e.preventDefault();
      e.stopPropagation();
      var parts = [];
      if (e.ctrlKey) parts.push('Ctrl');
      if (e.shiftKey) parts.push('Shift');
      if (e.altKey) parts.push('Alt');
      if (e.metaKey) parts.push('Meta');

      var key = e.key;
      if (key && key !== 'Control' && key !== 'Shift' && key !== 'Alt' && key !== 'Meta') {
        if (key === ' ') key = 'Space';
        else if (key.length === 1) key = key.toUpperCase();
        parts.push(key);
        recordedKeys = parts.join('+');
        captureInput.value = recordedKeys;
      } else if (parts.length > 0) {
        captureInput.value = parts.join('+') + '+...';
      }
    });

    var addBtn = el('button', {
      className: 'btn-dlg btn-accent',
      text: 'Add shortcut',
      onclick: function() {
        if (recordedKeys) {
          setShortcut(cmdSelect.value, recordedKeys);
          captureInput.value = '';
          recordedKeys = '';
          refreshShortcutsUI(filterInput.value);
        }
      }
    });

    var resetBtn = el('button', {
      className: 'btn-dlg',
      text: 'Reset defaults',
      onclick: function() {
        resetShortcuts();
        refreshShortcutsUI(filterInput.value);
      }
    });

    var addRow = el('div', {
      className: 'scard',
      style: 'display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:12px;'
    }, cmdSelect, captureInput, addBtn, resetBtn);
    pane.appendChild(addRow);

    var tableContainer = el('div', { className: 'actions-table', id: 'shortcuts-table' });
    pane.appendChild(tableContainer);

    refreshShortcutsDOM();

    return pane;
  }

  function renderTagsPane() {
    var pane = el('div', { className: 'spane', id: 'spane-tags', hidden: true },
      el('div', { className: 'spane-title', text: 'Tags' })
    );

    pane.appendChild(createSectionHeader('Create Tag'));

    var tagNameInput = el('input', {
      className: 'sinput tag-new-name',
      placeholder: 'Tag name (e.g. Work, Review)...',
      style: 'width:200px;'
    });

    var selectedColor = TAG_COLORS[0];
    var tagSwatches = el('div', { className: 'color-swatches-grid' });
    var tagColorPicker = el('input', {
      type: 'color',
      className: 'tag-color-input',
      value: selectedColor,
      style: 'width:28px; height:28px; border:none; background:transparent; cursor:pointer;',
      onchange: function() {
        selectedColor = tagColorPicker.value;
        updateActiveTagSwatch();
      }
    });

    function updateActiveTagSwatch() {
      var btns = tagSwatches.querySelectorAll('.color-swatch');
      for (var i = 0; i < btns.length; i++) {
        btns[i].classList.toggle('active', btns[i].dataset.color.toLowerCase() === selectedColor.toLowerCase());
      }
    }

    for (var i = 0; i < TAG_COLORS.length; i++) {
      (function(col) {
        var btn = el('button', {
          className: 'color-swatch' + (col === selectedColor ? ' active' : ''),
          style: 'background-color:' + col + ';',
          dataset: { color: col },
          onclick: function() {
            selectedColor = col;
            tagColorPicker.value = col;
            updateActiveTagSwatch();
          }
        });
        tagSwatches.appendChild(btn);
      })(TAG_COLORS[i]);
    }
    tagSwatches.appendChild(tagColorPicker);

    var addTagBtn = el('button', {
      className: 'btn-dlg btn-accent',
      id: 'btn-add-tag',
      text: 'Add tag',
      onclick: function() {
        var name = tagNameInput.value.trim();
        if (name) {
          addTag({ name: name, color: selectedColor });
          tagNameInput.value = '';
          refreshTagsUI();
        }
      }
    });

    var createCardEl = el('div', {
      className: 'scard',
      style: 'display:flex; flex-wrap:wrap; gap:12px; align-items:center;'
    }, tagNameInput, tagSwatches, addTagBtn);
    pane.appendChild(createCardEl);

    pane.appendChild(createSectionHeader('Defined Tags'));

    var tagsListEl = el('div', { className: 'tag-pills-list', id: 'tags-pills-container' });
    pane.appendChild(el('div', {
      className: 'scard',
      style: 'padding:16px;'
    }, tagsListEl));

    function refreshTagsUI() {
      clearElem(tagsListEl);
      var currentTags = getTags();
      for (var j = 0; j < currentTags.length; j++) {
        (function(tagItem) {
          var pill = el('div', { className: 'tag-pill' });
          pill.appendChild(el('span', {
            className: 'tag-dot',
            style: 'background-color:' + tagItem.color + ';'
          }));
          var nameSpan = el('span', { className: 'tag-name', text: tagItem.name });
          pill.appendChild(nameSpan);

          var editBtn = el('button', {
            className: 'tag-btn-edit',
            title: 'Edit tag',
            text: 'Edit',
            onclick: function() {
              var newName = prompt('Enter new tag name:', tagItem.name);
              if (newName && newName.trim()) {
                updateTag(tagItem.id, { name: newName.trim() });
                refreshTagsUI();
              }
            }
          });
          pill.appendChild(editBtn);

          var delBtn = el('button', {
            className: 'tag-btn-delete',
            title: 'Delete tag',
            text: 'x',
            onclick: function() {
              removeTag(tagItem.id);
              refreshTagsUI();
            }
          });
          pill.appendChild(delBtn);

          tagsListEl.appendChild(pill);
        })(currentTags[j]);
      }
    }
    refreshTagsUI();

    return pane;
  }

  function renderDevToolsPane() {
    var pane = el('div', { className: 'spane', id: 'spane-devtools', hidden: true },
      el('div', { className: 'spane-title', text: 'DevTools' })
    );

    pane.appendChild(createSectionHeader('IDE Integration'));
    pane.appendChild(createCard('Open IDE in status bar', 'Choose your preferred external development environment launcher.', createSelect('statusIde', [
      'None', 'VS Code', 'Visual Studio', 'Cursor', 'Sublime Text', 'IntelliJ IDEA'
    ], 'None')));

    var ideCard = el('div', { className: 'ide-config-card' });
    ideCard.appendChild(el('div', { className: 'scard-h', text: 'IDE configuration editor' }));
    ideCard.appendChild(el('div', { className: 'scard-d', text: 'Manage path and verify connectivity to your installed code editor.' }));

    var nameInput = el('input', { className: 'ide-config-input', value: getPref('ideName') || 'VS Code' });
    ideCard.appendChild(el('div', { className: 'ide-config-row' },
      el('span', { className: 'ide-config-label', text: 'Editor name' }),
      nameInput
    ));

    var pathInput = el('input', { className: 'ide-config-input', value: getPref('idePath') || '/usr/bin/code' });
    var browseBtn = el('button', { className: 'btn-dlg', text: 'Browse' });
    var statusBadge = el('span', { className: 'test-status-badge connected', text: 'Connected' });
    var testBtn = el('button', {
      className: 'btn-dlg',
      text: 'Test',
      onclick: function() {
        statusBadge.className = 'test-status-badge testing';
        statusBadge.textContent = 'Testing...';
        setTimeout(function() {
          statusBadge.className = 'test-status-badge connected';
          statusBadge.textContent = 'Connected';
        }, 500);
      }
    });

    ideCard.appendChild(el('div', { className: 'ide-config-row' },
      el('span', { className: 'ide-config-label', text: 'Executable path' }),
      pathInput, browseBtn, testBtn, statusBadge
    ));

    var saveBtn = el('button', {
      className: 'btn-dlg btn-accent',
      text: 'Save configuration',
      onclick: function() {
        setPref('ideName', nameInput.value.trim());
        setPref('idePath', pathInput.value.trim());
      }
    });
    var cancelBtn = el('button', {
      className: 'btn-dlg',
      text: 'Cancel',
      onclick: function() {
        nameInput.value = getPref('ideName') || 'VS Code';
        pathInput.value = getPref('idePath') || '/usr/bin/code';
      }
    });

    ideCard.appendChild(el('div', { className: 'ide-config-row', style: 'margin-top:4px;' },
      saveBtn, cancelBtn
    ));
    pane.appendChild(ideCard);

    pane.appendChild(createSectionHeader('GitHub Account'));

    var ghBadge = el('span', {
      className: 'test-status-badge disconnected',
      id: 'gh-state',
      text: 'Not connected'
    });
    var ghConnectBtn = el('button', {
      className: 'btn-dlg btn-accent',
      id: 'btn-gh-connect',
      text: 'Connect to GitHub',
      title: 'Needs a backend that can hold a credential',
      disabled: true
    });
    var ghDisconnectBtn = el('button', {
      className: 'btn-dlg btn-danger',
      id: 'btn-gh-disconnect',
      text: 'Disconnect',
      disabled: true,
      onclick: function() {
        ghBadge.className = 'test-status-badge disconnected';
        ghBadge.textContent = 'Not connected';
        ghConnectBtn.disabled = true;
        ghDisconnectBtn.disabled = true;
      }
    });
    //: Nothing in this build can hold a credential, and connecting to
    //: GitHub means holding one, so the row says so and the buttons are
    //: disabled with the reason on them. It read "Connected as
    //: aurade-developer" before, about an account that does not exist, and
    //: the Connect button beside it had no handler at all.

    var ghControls = el('div', { style: 'display:flex; align-items:center; gap:8px;' },
      ghBadge, ghConnectBtn, ghDisconnectBtn
    );
    pane.appendChild(createCard('GitHub account connection', 'Sync repositories, branch history, and open issues inside AuraDE Files.', ghControls));

    return pane;
  }

  function renderAdvancedPane() {
    var pane = el('div', { className: 'spane', id: 'spane-advanced', hidden: true },
      el('div', { className: 'spane-title', text: 'Advanced' })
    );

    pane.appendChild(createSectionHeader('Settings JSON Editor'));

    var jsonEditor = el('div', { className: 'json-editor' });
    var textarea = el('textarea', {
      className: 'json-textarea',
      spellcheck: 'false'
    });
    textarea.value = JSON.stringify(getPrefs(), null, 2);

    var formatBtn = el('button', {
      className: 'btn-dlg',
      text: 'Format JSON',
      onclick: function() {
        try {
          var parsed = JSON.parse(textarea.value);
          textarea.value = JSON.stringify(parsed, null, 2);
        } catch (e) {
          alert('Invalid JSON: ' + e.message);
        }
      }
    });

    var saveJsonBtn = el('button', {
      className: 'btn-dlg btn-accent',
      text: 'Save JSON',
      onclick: function() {
        try {
          var parsed = JSON.parse(textarea.value);
          importSettings({ prefs: parsed });
          alert('Preferences saved successfully.');
        } catch (e) {
          alert('Failed to save invalid JSON: ' + e.message);
        }
      }
    });

    var resetJsonBtn = el('button', {
      className: 'btn-dlg',
      text: 'Reset view',
      onclick: function() {
        textarea.value = JSON.stringify(getPrefs(), null, 2);
      }
    });

    var toolbar = el('div', { className: 'json-toolbar' }, formatBtn, resetJsonBtn, saveJsonBtn);
    jsonEditor.appendChild(toolbar);
    jsonEditor.appendChild(textarea);
    pane.appendChild(jsonEditor);

    pane.appendChild(createSectionHeader('System and Lifecycle'));
    pane.appendChild(createCard('Open on startup', 'Launch AuraDE Files automatically on user session login.', createSwitch('openOnStartup', false)));
    pane.appendChild(createCard('Leave running in background', 'Maintain background daemon for instant window restoration.', createSwitch('leaveRunningInBackground', false)));
    pane.appendChild(createCard('Show a system tray icon', 'Keep an icon in the tray while the program is running in the background.', createSwitch('showTrayIcon', false)));

    pane.appendChild(createSectionHeader('Experimental Features'));
    pane.appendChild(createCard('Replace File Explorer', 'Register as primary shell file manager handler.', createSwitch('expReplaceExplorer', false)));
    pane.appendChild(createCard('Replace Open File Dialog', 'Provide common open and save picker dialog replacement.', createSwitch('expReplaceOpenDialog', false)));

    var cacheInput = el('input', {
      type: 'number',
      className: 'sinput',
      min: '50',
      max: '10000',
      step: '50',
      value: String(getPref('thumbnailCacheSizeMb') || 500),
      dataset: { pref: 'thumbnailCacheSizeMb' },
      style: 'width:100px;',
      onchange: function() { setPref('thumbnailCacheSizeMb', parseInt(cacheInput.value, 10)); }
    });
    //: This used to alert that the cache was cleared without clearing one.
    //: The cache that exists on this platform is the XDG thumbnail directory,
    //: so that is what the button empties, and it reports what it removed.
    var clearCacheBtn = el('button', {
      className: 'btn-dlg btn-danger',
      id: 'btn-clear-thumbs',
      text: 'Clear cache',
      onclick: function() {
        var was = clearCacheBtn.textContent;
        if (!window.__api) { clearCacheBtn.textContent = 'Nothing cached'; }
        else {
          clearCacheBtn.textContent = 'Clearing';
          fetch(window.__api + '/api/thumb-cache/clear', { method: 'POST' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
              clearCacheBtn.textContent = d.removed
                ? ('Removed ' + d.removed) : 'Nothing cached';
            })
            .catch(function () { clearCacheBtn.textContent = 'Not connected'; });
        }
        setTimeout(function () { clearCacheBtn.textContent = was; }, 2400);
      }
    });
    var cacheControls = el('div', { style: 'display:flex; align-items:center; gap:8px;' },
      cacheInput, el('span', { text: 'MB', style: 'font-size:12px;' }), clearCacheBtn
    );
    pane.appendChild(createCard('Cache thumbnails', 'Keep image and media previews on disk so a folder draws at once the second time.', createSwitch('thumbnailCache', true)));
    pane.appendChild(createCard('Thumbnail caching', 'Cache image and media previews on disk for high performance rendering.', cacheControls));

    pane.appendChild(createSectionHeader('Backup and Restore'));
    var exportBtn = el('button', {
      className: 'btn-dlg',
      id: 'btn-prefs-export',
      text: 'Export settings',
      onclick: function() {
        var bundleStr = exportSettings();
        var blob = new Blob([bundleStr], { type: 'application/json' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = 'aurade-settings.json';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }
    });
    pane.appendChild(createCard('Export settings', 'Save all preferences, tags, and custom shortcuts to a JSON file.', exportBtn));

    var fileInput = el('input', {
      type: 'file',
      accept: 'application/json',
      style: 'display:none;',
      onchange: function() {
        if (fileInput.files && fileInput.files[0]) {
          var reader = new FileReader();
          reader.onload = function(e) {
            importSettings(e.target.result);
          };
          reader.readAsText(fileInput.files[0]);
        }
      }
    });
    pane.appendChild(fileInput);

    var importBtn = el('button', {
      className: 'btn-dlg',
      id: 'btn-prefs-import',
      text: 'Import settings',
      onclick: function() {
        fileInput.click();
      }
    });
    pane.appendChild(createCard('Import settings', 'Restore configuration bundle from an exported JSON file.', importBtn));

    var clearBtn = el('button', {
      className: 'btn-dlg btn-danger',
      id: 'btn-prefs-clear',
      text: 'Reset all',
      onclick: function() {
        if (confirm('Reset all preferences to factory defaults?')) {
          resetPrefs();
        }
      }
    });
    pane.appendChild(createCard('Reset all preferences', 'Revert all application settings to their original state.', clearBtn));

    return pane;
  }

  //: The mark is the real artwork, not a redraw of it. It is a raster, so
  //: there is no vector geometry to reveal; what sits behind it instead is
  //: the aurora from the greeter's brand.py, the same three fields of light
  //: at the same positions, which is where the name comes from.
  function auradeMark(size) {
    const wrap = el('span', { className: 'aurade-mark' });
    const glow = el('span', { className: 'mark-aurora' });
    const fields = document.documentElement.dataset.theme === 'light'
      ? __BUILD("AURORA_LIGHT") : __BUILD("AURORA_DARK");
    fields.forEach(function (f) {
      glow.appendChild(el('span', {
        className: 'mark-field',
        style: 'background:' + f[0] + '; left:' + f[1] + '%; top:' + f[2] + '%;'
      }));
    });
    wrap.appendChild(glow);
    wrap.appendChild(el('img', {
      className: 'mark-img', src: '@@MARK_URI@@', width: size, height: size,
      alt: 'AuraDE'
    }));
    return wrap;
  }

  function renderAboutPane() {
    var pane = el('div', { className: 'spane', id: 'spane-about', hidden: true },
      el('div', { className: 'spane-title', text: 'About' })
    );

    var appLine = 'AuraDE Files @@FILES_VER@@';
    var buildLine = 'Build @@BUILD_ID@@, @@BUILD_DATE@@';
    var deskLine = 'AuraDE @@AURADE_VER@@';
    var sysLine = 'Reading the system';

    //: The build host is not the target, so the system line is asked for at
    //: run time rather than baked. With no backend there is nothing to read
    //: and the card says so instead of guessing.
    var sysEl = el('span', { text: sysLine });
    (function readSystem() {
      if (!window.__api) { sysEl.textContent = 'System: not connected'; return; }
      try {
        fetch(window.__api + '/api/system').then(function (r) { return r.json(); })
          .then(function (d) {
            sysEl.textContent = 'System: ' + (d.os || 'Unknown') + ', kernel ' + (d.kernel || '?');
          }).catch(function () { sysEl.textContent = 'System: not connected'; });
      } catch (err) { sysEl.textContent = 'System: not connected'; }
    })();

    //: Seven clicks on the mark, and shift-click for the geometry. Both are
    //: on the mark itself so nothing about the page hints at them.
    var markSvg = auradeMark(72);
    var credits = el('div', { className: 'about-credits', hidden: true });
    credits.appendChild(el('div', { className: 'about-credits-h', text: 'Made in the open' }));
    credits.appendChild(el('div', { className: 'about-credits-b',
      text: 'Every icon in this file manager was drawn for it. The mark is one '
        + 'unbroken ribbon, and the light behind it is the same aurora the '
        + 'greeter paints: hold shift and click to bring it up. Thank you for '
        + 'reading the About page. Almost nobody does.' }));

    var auroraNote = el('div', { className: 'about-note', hidden: true,
      text: 'Aurora. It is in the name.' });

    var eggClicks = 0;
    var eggTimer = null;
    var markBtn = el('button', {
      className: 'about-mark-btn',
      type: 'button',
      title: 'AuraDE',
      onclick: function (e) {
        if (e.shiftKey) {
          markSvg.classList.toggle('bloom-on');
          return;
        }
        eggClicks = eggClicks + 1;
        if (eggTimer) clearTimeout(eggTimer);
        eggTimer = setTimeout(function () { eggClicks = 0; }, 1500);
        if (eggClicks >= 7) {
          eggClicks = 0;
          credits.hidden = !credits.hidden;
        }
      }
    }, markSvg);

    var KONAMI = ['arrowup', 'arrowup', 'arrowdown', 'arrowdown', 'arrowleft',
                  'arrowright', 'arrowleft', 'arrowright', 'b', 'a'];
    var kIdx = 0;
    document.addEventListener('keydown', function (e) {
      if (pane.hidden) { kIdx = 0; return; }
      var k = String(e.key || '').toLowerCase();
      if (k === KONAMI[kIdx]) { kIdx = kIdx + 1; }
      else { kIdx = (k === KONAMI[0]) ? 1 : 0; }
      if (kIdx === KONAMI.length) {
        kIdx = 0;
        markSvg.classList.remove('aurora-on');
        markSvg.getBoundingClientRect();
        markSvg.classList.add('aurora-on');
        auroraNote.hidden = false;
      }
    });

    var copyFlyout = el('div', { className: 'copy-flyout', hidden: true });
    function everything() {
      return appLine + LF + buildLine + LF + deskLine + LF + sysEl.textContent;
    }
    var flyoutItems = [
      { text: 'App version', get: function () { return appLine + LF + buildLine; } },
      { text: 'Desktop version', get: function () { return deskLine; } },
      { text: 'System', get: function () { return sysEl.textContent; } },
      { text: 'Everything', get: everything }
    ];
    for (var i = 0; i < flyoutItems.length; i++) {
      (function (it) {
        copyFlyout.appendChild(el('button', {
          className: 'copy-flyout-item',
          type: 'button',
          text: it.text,
          onclick: function () {
            if (navigator.clipboard) navigator.clipboard.writeText(it.get());
            copyFlyout.hidden = true;
          }
        }));
      })(flyoutItems[i]);
    }
    var copyBtn = el('button', {
      className: 'btn-dlg',
      type: 'button',
      text: 'Copy',
      style: 'position:relative;',
      onclick: function (e) {
        e.stopPropagation();
        copyFlyout.hidden = !copyFlyout.hidden;
      }
    });
    copyBtn.appendChild(copyFlyout);
    document.addEventListener('click', function () {
      if (copyFlyout && !copyFlyout.hidden) copyFlyout.hidden = true;
    });

    var hero = el('div', { className: 'about-hero' },
      markBtn,
      el('div', { className: 'about-hero-t' },
        el('div', { className: 'about-hero-h', text: 'AuraDE Files' }),
        el('div', { className: 'about-hero-d', text: appLine + '. ' + buildLine + '.' }),
        el('div', { className: 'about-hero-d' }, sysEl)
      ),
      el('div', { className: 'about-hero-c' }, copyBtn)
    );
    pane.appendChild(hero);
    pane.appendChild(credits);
    pane.appendChild(auroraNote);

    pane.appendChild(createSectionHeader('Help and support'));

    function linkCard(title, desc, label, href, id) {
      var btn = el('button', {
        className: 'btn-dlg', type: 'button', text: label,
        onclick: function () { if (href) window.open(href, '_blank', 'noopener'); }
      });
      if (id) btn.id = id;
      return createCard(title, desc, btn);
    }

    pane.appendChild(linkCard('Documentation',
      'How AuraDE is put together, how to build it, and what each package does.',
      'Open', 'https://github.com/aurade-project/aurade/tree/main/docs'));
    pane.appendChild(createCard('Keyboard shortcuts',
      'Every binding in this window, on one page. Also on question mark.',
      el('button', {
        className: 'btn-dlg', type: 'button', id: 'about-shortcuts', text: 'Show',
        onclick: function () {
          var back = document.getElementById('settings-back');
          if (back) back.click();
          document.dispatchEvent(new KeyboardEvent('keydown',
            { key: '?', shiftKey: true, bubbles: true }));
        }
      })));
    pane.appendChild(createCard('Log location',
      'Where this program writes what it did, for when something goes wrong.',
      el('button', {
        className: 'btn-dlg', type: 'button', id: 'btn-diag', text: 'Copy path',
        onclick: function () {
          if (navigator.clipboard) navigator.clipboard.writeText('~/.local/state/aurade/files.log');
        }
      })));

    pane.appendChild(createExpander('Feedback',
      'Tell us what is wrong or what is missing. Both are welcome.', [
        createNestedCard('Report an issue',
          'Something behaved differently to how it reads. Include what you did and what happened.',
          el('button', {
            className: 'btn-dlg', type: 'button', id: 'btn-link-issues', text: 'Open tracker',
            onclick: function () { window.open('https://github.com/aurade-project/aurade/issues', '_blank', 'noopener'); }
          })),
        createNestedCard('Request a feature',
          'Something is missing. Say what you were trying to do, not only what to add.',
          el('button', {
            className: 'btn-dlg', type: 'button', text: 'Open tracker',
            onclick: function () { window.open('https://github.com/aurade-project/aurade/issues/new', '_blank', 'noopener'); }
          }))
      ], false));

    pane.appendChild(createSectionHeader('Open source'));

    pane.appendChild(linkCard('Source code',
      'AuraDE is BSD 3-Clause. Read it, build it, fork it.',
      'Open', 'https://github.com/aurade-project/aurade'));
    pane.appendChild(createCard('Privacy',
      'This file manager collects nothing. No telemetry, no crash reports, no '
      + 'identifier. Thumbnails and previews are made on this computer and stay on it.',
      el('span', { className: 'about-badge', text: 'Nothing collected' })));
    pane.appendChild(createCard('Design reference',
      'The layout and behaviour follow Files by the Files Community, under MIT '
      + 'and MPL-2.0. None of its code is used here. The artwork is drawn fresh.',
      el('button', {
        className: 'btn-dlg', type: 'button', text: 'Files',
        onclick: function () { window.open('https://github.com/files-community/Files', '_blank', 'noopener'); }
      })));

    var libsGrid = el('div', { className: 'libs-grid' });
    for (var j = 0; j < THIRD_PARTY_LIBS.length; j++) {
      var lib = THIRD_PARTY_LIBS[j];
      libsGrid.appendChild(el('div', { className: 'lib-card' },
        el('div', { className: 'lib-name', text: lib.name }),
        el('div', { className: 'lib-license', text: lib.license }),
        el('div', { className: 'lib-desc', text: lib.desc })
      ));
    }
    pane.appendChild(createExpander('Third party notices',
      THIRD_PARTY_LIBS.length + ' components, and what each one is for.',
      libsGrid, false));

    return pane;
  }

  function selectCategory(catId) {
    if (!rootContainer) return catId;
    activeCategory = catId;

    var navBtns = rootContainer.querySelectorAll('.snav button, .snav-btn');
    for (var i = 0; i < navBtns.length; i++) {
      var btn = navBtns[i];
      var matches = btn.getAttribute('data-snav') === catId;
      btn.classList.toggle('on', matches);
    }

    var panes = rootContainer.querySelectorAll('.spane');
    for (var j = 0; j < panes.length; j++) {
      var pane = panes[j];
      pane.hidden = (pane.id !== 'spane-' + catId);
    }

    return catId;
  }

  function search(query) {
    if (!rootContainer) return 0;
    var q = (query || '').trim().toLowerCase();

    removeHighlights(rootContainer);

    var panes = rootContainer.querySelectorAll('.spane');
    var navBtns = rootContainer.querySelectorAll('.snav button, .snav-btn');
    var totalMatches = 0;
    var matchCounts = {};
    var firstCatWithMatches = null;

    for (var i = 0; i < panes.length; i++) {
      var pane = panes[i];
      var catId = pane.id.replace('spane-', '');
      var catMatches = 0;

      var cards = pane.querySelectorAll('.scard, .settings-expander, .actions-row, .ide-config-card');
      for (var c = 0; c < cards.length; c++) {
        var card = cards[c];
        if (!q) {
          card.hidden = false;
        } else {
          var textContent = (card.textContent || '').toLowerCase();
          var hit = textContent.indexOf(q) !== -1;
          card.hidden = !hit;
          if (hit) {
            catMatches++;
            totalMatches++;

            var titleEl = card.querySelector('.scard-h, .action-desc, .lib-name');
            if (titleEl && titleEl.firstChild && titleEl.firstChild.nodeType === 3) {
              highlightMatchInNode(titleEl.firstChild, query.trim());
            }
            var descEl = card.querySelector('.scard-d, .lib-desc');
            if (descEl && descEl.firstChild && descEl.firstChild.nodeType === 3) {
              highlightMatchInNode(descEl.firstChild, query.trim());
            }
          }
        }
      }

      var secs = pane.querySelectorAll('.ssec');
      for (var s = 0; s < secs.length; s++) {
        var sec = secs[s];
        if (!q) {
          sec.hidden = false;
        } else {
          var sibling = sec.nextElementSibling;
          var hasVisible = false;
          while (sibling && !sibling.classList.contains('ssec')) {
            if (!sibling.hidden) {
              hasVisible = true;
              break;
            }
            sibling = sibling.nextElementSibling;
          }
          sec.hidden = !hasVisible;
        }
      }

      matchCounts[catId] = catMatches;
      if (catMatches > 0 && !firstCatWithMatches) {
        firstCatWithMatches = catId;
      }
    }

    for (var b = 0; b < navBtns.length; b++) {
      var btn = navBtns[b];
      var bCat = btn.getAttribute('data-snav');
      var badge = btn.querySelector('.snav-badge');
      if (!badge) {
        badge = el('span', { className: 'snav-badge' });
        btn.appendChild(badge);
      }

      if (!q) {
        btn.hidden = false;
        badge.textContent = '';
        badge.hidden = true;
      } else {
        var cnt = matchCounts[bCat] || 0;
        badge.textContent = String(cnt);
        badge.hidden = (cnt === 0);
        btn.hidden = (cnt === 0);
      }
    }

    if (q) {
      if (matchCounts[activeCategory] === 0 && firstCatWithMatches) {
        selectCategory(firstCatWithMatches);
      }
    } else {
      selectCategory(activeCategory);
    }

    return totalMatches;
  }

  function openSettings(category) {
    var sp = document.getElementById('settings-page');
    var fa = document.getElementById('filearea');
    if (fa) fa.hidden = true;
    if (sp) {
      sp.hidden = false;
      if (category) {
        selectCategory(category);
      }
    }
    return true;
  }

  function closeSettings() {
    var sp = document.getElementById('settings-page');
    var fa = document.getElementById('filearea');
    if (sp) sp.hidden = true;
    if (fa) fa.hidden = false;
    return true;
  }

  function isOpen() {
    var sp = document.getElementById('settings-page');
    return Boolean(sp && !sp.hidden);
  }

  function exportSettings() {
    var bundle = {
      version: 1,
      exportedAt: new Date().toISOString(),
      prefs: getPrefs(),
      theme: localStorage.getItem(THEME_KEY) || 'dark',
      tags: getTags(),
      shortcuts: getShortcuts(),
      startupPages: getPref('startupPages') || ['/home']
    };
    return JSON.stringify(bundle, null, 2);
  }

  function importSettings(jsonObjOrStr) {
    var data = jsonObjOrStr;
    if (typeof data === 'string') {
      try {
        data = JSON.parse(data);
      } catch (e) {
        return false;
      }
    }
    if (!data || typeof data !== 'object') return false;

    if (data.prefs && typeof data.prefs === 'object') {
      Object.assign(prefs, data.prefs);
      savePrefs();
    } else {
      for (var k in data) {
        if (k in DEFAULT_PREFS) {
          prefs[k] = data[k];
        }
      }
      savePrefs();
    }

    if (data.theme) {
      try { localStorage.setItem(THEME_KEY, data.theme); } catch (e) {}
      applyTheme(data.theme);
    }

    if (Array.isArray(data.tags)) {
      tags = data.tags.slice();
      saveTags();
    }

    if (Array.isArray(data.shortcuts)) {
      shortcuts = data.shortcuts.slice();
      saveShortcuts();
    }

    for (var pk in prefs) {
      applyPref(pk, prefs[pk]);
    }

    if (rootContainer) {
      render(rootContainer);
    }
    return true;
  }

  function refreshTagsDOM() {
    var container = document.getElementById('tags-pills-container');
    if (!container) return;
    clearElem(container);
    var currentTags = getTags();
    for (var j = 0; j < currentTags.length; j++) {
      (function(tItem) {
        var p = el('div', { className: 'tag-pill' });
        p.appendChild(el('span', { className: 'tag-dot', style: 'background-color:' + tItem.color + ';' }));
        p.appendChild(el('span', { className: 'tag-name', text: tItem.name }));

        var editBtn = el('button', {
          className: 'tag-btn-edit',
          title: 'Edit tag',
          text: 'Edit',
          onclick: function() {
            var newName = prompt('Enter new tag name:', tItem.name);
            if (newName && newName.trim()) {
              updateTag(tItem.id, { name: newName.trim() });
            }
          }
        });
        p.appendChild(editBtn);

        var delBtn = el('button', {
          className: 'tag-btn-delete',
          title: 'Delete tag',
          text: 'x',
          onclick: function() {
            removeTag(tItem.id);
          }
        });
        p.appendChild(delBtn);

        container.appendChild(p);
      })(currentTags[j]);
    }
  }

  function refreshShortcutsDOM(filterQuery, targetEl) {
    var tableContainer = targetEl || document.getElementById('shortcuts-table');
    if (!tableContainer && rootContainer) {
      tableContainer = rootContainer.querySelector('#shortcuts-table');
    }
    if (!tableContainer) return;
    clearElem(tableContainer);
    var q = (filterQuery || '').trim().toLowerCase();
    var list = getShortcuts();
    for (var j = 0; j < list.length; j++) {
      (function(sc) {
        if (q && sc.name.toLowerCase().indexOf(q) === -1 && sc.keys.toLowerCase().indexOf(q) === -1) {
          return;
        }
        var row = el('div', { className: 'actions-row sact' });
        row.dataset.keys = sc.keys;
        row.appendChild(el('div', { className: 'action-desc sdo', text: sc.name }));

        var keycapsBox = el('div', { style: 'display:flex; align-items:center; gap:4px;' });
        var keyParts = sc.keys.split('+');
        for (var k = 0; k < keyParts.length; k++) {
          if (k > 0) {
            keycapsBox.appendChild(document.createTextNode('+'));
          }
          keycapsBox.appendChild(el('span', { className: 'keycap skey', text: keyParts[k] }));
        }
        row.appendChild(keycapsBox);

        var editBtn = el('button', {
          className: 'btn-dlg',
          text: 'Edit',
          onclick: function() {
            var cmdSelect = document.querySelector('.cmd-picker');
            var captureInput = document.querySelector('.key-capture-input');
            if (cmdSelect) cmdSelect.value = sc.id;
            if (captureInput) {
              captureInput.value = sc.keys;
              captureInput.focus();
            }
          }
        });

        var delBtn = el('button', {
          className: 'btn-dlg btn-danger',
          text: 'Delete',
          onclick: function() {
            removeShortcut(sc.id);
          }
        });

        var acts = el('div', { style: 'display:flex; gap:6px;' }, editBtn, delBtn);
        row.appendChild(acts);
        tableContainer.appendChild(row);
      })(list[j]);
    }
  }

  function getTags() {
    return JSON.parse(JSON.stringify(tags));
  }

  function addTag(tag) {
    if (!tag || !tag.name) return null;
    var newTag = {
      id: tag.id || ('tag-' + Date.now() + '-' + Math.floor(Math.random() * 1000)),
      name: String(tag.name),
      color: tag.color || '#3584e4'
    };
    tags.push(newTag);
    saveTags();
    refreshTagsDOM();
    return newTag;
  }

  function removeTag(tagId) {
    var idx = -1;
    for (var i = 0; i < tags.length; i++) {
      if (tags[i].id === tagId) {
        idx = i;
        break;
      }
    }
    if (idx !== -1) {
      tags.splice(idx, 1);
      saveTags();
      refreshTagsDOM();
      return true;
    }
    return false;
  }

  function updateTag(tagId, data) {
    for (var i = 0; i < tags.length; i++) {
      if (tags[i].id === tagId) {
        if (data.name) tags[i].name = data.name;
        if (data.color) tags[i].color = data.color;
        saveTags();
        refreshTagsDOM();
        return JSON.parse(JSON.stringify(tags[i]));
      }
    }
    return null;
  }

  function getShortcuts() {
    return JSON.parse(JSON.stringify(shortcuts));
  }

  function setShortcut(cmdId, keys) {
    var res = null;
    for (var i = 0; i < shortcuts.length; i++) {
      if (shortcuts[i].id === cmdId) {
        shortcuts[i].keys = keys;
        saveShortcuts();
        res = JSON.parse(JSON.stringify(shortcuts[i]));
        break;
      }
    }
    if (!res) {
      var name = cmdId;
      for (var j = 0; j < COMMANDS_LIST.length; j++) {
        if (COMMANDS_LIST[j].id === cmdId) {
          name = COMMANDS_LIST[j].name;
          break;
        }
      }
      res = { id: cmdId, name: name, keys: keys };
      shortcuts.push(res);
      saveShortcuts();
    }
    refreshShortcutsDOM();
    return res;
  }

  function removeShortcut(cmdId) {
    for (var i = 0; i < shortcuts.length; i++) {
      if (shortcuts[i].id === cmdId) {
        shortcuts.splice(i, 1);
        saveShortcuts();
        refreshShortcutsDOM();
        return true;
      }
    }
    return false;
  }

  function resetShortcuts() {
    shortcuts = JSON.parse(JSON.stringify(DEFAULT_SHORTCUTS));
    saveShortcuts();
    refreshShortcutsDOM();
    return getShortcuts();
  }

  function render(containerEl) {
    var container = containerEl || document.getElementById('settings-page');
    if (!container) return null;
    rootContainer = container;

    clearElem(container);

    var header = el('div', { className: 'shead' },
      el('button', {
        className: 'nbtn',
        id: 'settings-back',
        title: 'Back',
        onclick: function() { closeSettings(); }
      }, createSvgIcon('close', 14)),
      el('span', { text: 'Settings', style: 'font-weight:600; font-size:16px;' }),
      el('input', {
        id: 'settings-search',
        placeholder: 'Search settings',
        'aria-label': 'Search settings',
        autocomplete: 'off',
        spellcheck: 'false',
        oninput: function(e) { search(e.target.value); }
      })
    );
    container.appendChild(header);

    var sbody = el('div', { className: 'sbody' });
    var snav = el('div', { className: 'snav settings-sidebar' });

    var categories = [
      { id: 'general', name: 'General', icon: 'general' },
      { id: 'appearance', name: 'Appearance', icon: 'appearance' },
      { id: 'icons', name: 'Icons', icon: 'icons' },
      { id: 'toolbar', name: 'Toolbar', icon: 'toolbar' },
      { id: 'layout', name: 'Layout', icon: 'layout' },
      { id: 'folders', name: 'Files & folders', icon: 'folders' },
      { id: 'actions', name: 'Actions', icon: 'actions' },
      { id: 'tags', name: 'Tags', icon: 'tags' },
      { id: 'devtools', name: 'Developer tools', icon: 'devtools' },
      { id: 'advanced', name: 'Advanced', icon: 'advanced' },
      { id: 'about', name: 'About', icon: 'about' }
    ];

    for (var i = 0; i < categories.length; i++) {
      (function(cat) {
        var btn = el('button', {
          className: 'snav snav-btn' + (cat.id === activeCategory ? ' on' : ''),
          dataset: { snav: cat.id },
          onclick: function() { selectCategory(cat.id); }
        },
          el('span', { className: 'snav-ico' }, createSvgIcon(cat.icon, 16)),
          el('span', { className: 'snav-lbl', text: cat.name }),
          el('span', { className: 'snav-badge', hidden: true })
        );
        snav.appendChild(btn);
      })(categories[i]);
    }
    sbody.appendChild(snav);

    var spanes = el('div', { className: 'spanes' });
    spanes.appendChild(renderGeneralPane());
    spanes.appendChild(renderAppearancePane());
    spanes.appendChild(renderIconsPane());
    spanes.appendChild(renderToolbarPane());
    spanes.appendChild(renderLayoutPane());
    spanes.appendChild(renderFoldersPane());
    spanes.appendChild(renderActionsPane());
    spanes.appendChild(renderTagsPane());
    spanes.appendChild(renderDevToolsPane());
    spanes.appendChild(renderAdvancedPane());
    spanes.appendChild(renderAboutPane());

    sbody.appendChild(spanes);
    container.appendChild(sbody);

    refreshShortcutsDOM();
    refreshTagsDOM();

    selectCategory(activeCategory);
    return container;
  }

  loadAllData();

  window.SettingsEngine = {
    openSettings: openSettings,
    closeSettings: closeSettings,
    isOpen: isOpen,
    selectCategory: selectCategory,
    search: search,
    getPref: getPref,
    setPref: setPref,
    getPrefs: getPrefs,
    resetPrefs: resetPrefs,
    exportSettings: exportSettings,
    importSettings: importSettings,
    getTags: getTags,
    addTag: addTag,
    removeTag: removeTag,
    updateTag: updateTag,
    getShortcuts: getShortcuts,
    setShortcut: setShortcut,
    resetShortcuts: resetShortcuts,
    render: render
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      var sp = document.getElementById('settings-page');
      if (sp) render(sp);
    });
  } else {
    var sp = document.getElementById('settings-page');
    if (sp) render(sp);
  }

})();

  })();


