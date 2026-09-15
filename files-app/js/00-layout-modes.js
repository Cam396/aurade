window.__DIR_CATALOG = __BUILD("CATALOG_JSON");
(() => {
  const btn = document.getElementById('btn-layout');
  const grid = document.querySelector('.grid');
  const rows = document.querySelector('.rows');
  const list = document.querySelector('.list');
  const cards = document.querySelector('.cards');
  const cols = document.querySelector('.columns');
  if (!btn || !grid || !rows) return;
  // No HTML string is ever assigned to an element here.
  // chrome://file-manager enforces
  // require-trusted-types-for 'script', so any HTML string assignment throws
  // "This document requires 'TrustedHTML' assignment" and the app dies before
  // drawing a pixel. That is what killed the previous redesign. All layout
  // glyphs are parsed at load and we only flip which one is hidden.
  const gridIco = btn.querySelector('.lay-grid');
  const detailsIco = btn.querySelector('.lay-details');
  const listIco = btn.querySelector('.lay-list');
  const cardsIco = btn.querySelector('.lay-cards');
  const colsIco = btn.querySelector('.lay-cols');
  const names = { grid: 'Grid view', details: 'Details view', list: 'List view',
    cards: 'Cards view', columns: 'Columns view', adaptive: 'Adaptive view' };
  const MODES = ['grid', 'details', 'list', 'cards', 'columns', 'adaptive'];
  let mode = 'grid';
  //: Adaptive is a rule, not a view. The reference keeps the chosen mode and a
  //: separate "overridden" flag, and picking any real layout sets it, which is
  //: why this is a variable of its own rather than mode === 'adaptive'.
  let adaptive = false;

  //: What the folder is mostly made of decides. Pictures want a grid, anything
  //: else wants the columns of a details view.
  function adaptiveChoice() {
    const cells = document.querySelectorAll('.grid .cell, .cards .tile');
    let files = 0, pictures = 0;
    cells.forEach(el => {
      if (el.getAttribute('data-k') === 'Folder') return;
      files += 1;
      const n = (el.getAttribute('data-n') || '').toLowerCase();
      if (/\.(png|jpe?g|gif|bmp|webp|tiff?|ico|avif|svg|mp4|mkv|mov|webm)$/
          .test(n)) pictures += 1;
    });
    if (!files) return 'details';
    return (pictures / files) >= 0.4 ? 'grid' : 'details';
  }

  function setLayout(next) {
    const asked = typeof next === 'string' ? next : (next ? 'details' : 'grid');
    adaptive = asked === 'adaptive';
    mode = adaptive ? adaptiveChoice() : asked;
    if (MODES.indexOf(mode) === -1) mode = 'grid';
    const hw = document.getElementById('home-widgets');
    const onHome = hw && !hw.hidden;
    if (onHome) {
      grid.hidden = true;
      rows.hidden = true;
      if (list) list.hidden = true;
      if (cards) cards.hidden = true;
      if (cols) cols.hidden = true;
    } else {
      grid.hidden = mode !== 'grid';
      rows.hidden = mode !== 'details';
      if (list) list.hidden = mode !== 'list';
      if (cards) cards.hidden = mode !== 'cards';
      if (cols) cols.hidden = mode !== 'columns';
    }
    if (gridIco) gridIco.hidden = mode !== 'grid';
    if (detailsIco) detailsIco.hidden = mode !== 'details';
    if (listIco) listIco.hidden = mode !== 'list';
    if (cardsIco) cardsIco.hidden = mode !== 'cards';
    if (colsIco) colsIco.hidden = mode !== 'columns';
    btn.setAttribute('aria-label', names[adaptive ? 'adaptive' : mode]);
    document.documentElement.dataset.adaptive = adaptive ? '1' : '';
    if (window.__syncSelectionOnLayout) window.__syncSelectionOnLayout();
  }
  //: Re-decide after a navigation, but only while adaptive is on. A folder of
  //: photographs and a folder of source should not look the same.
  window.__relayoutAdaptive = function () {
    if (adaptive) setLayout('adaptive');
  };
  window.__isAdaptive = () => adaptive;
  const h = window.location.hash;
  const dl = document.documentElement.dataset.layout;
  if (h === '#details' || h === '#list' || h === '#cards' || h === '#columns'
      || h === '#adaptive')
    setLayout(h.slice(1));
  else if (MODES.indexOf(dl) !== -1) setLayout(dl);
  else setLayout('grid');
  window.__setLayout = setLayout;
  window.__mode = () => mode;
  window.__modes = MODES;
})();
