  // =========================================================================
  // Wave 4: Status Center (P10)
  // =========================================================================
  (function() {
/**
 * Wave 4: Status Center (P10) for AuraDE Files
 * WinUI 3 Fluent Status Center controller and SpeedGraph implementation.
 *
 * Requirements:
 * 1. ZERO em dashes and ZERO en dashes.
 * 2. Strict Trusted Types: ZERO assignments to HTML injection sinks.
 * 3. String escaping safety: DO NOT use literal newlines in strings or regex.
 */

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.StatusCenter = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';

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

  function createSvgRect(x, y, width, height, rx, fill) {
    var r = document.createElementNS(SVG_NS, 'rect');
    r.setAttribute('x', String(x));
    r.setAttribute('y', String(y));
    r.setAttribute('width', String(width));
    r.setAttribute('height', String(height));
    if (rx) r.setAttribute('rx', String(rx));
    if (fill) r.setAttribute('fill', fill);
    return r;
  }

  function createSvgCircle(cx, cy, r, fill, stroke, strokeWidth, className) {
    var c = document.createElementNS(SVG_NS, 'circle');
    c.setAttribute('cx', String(cx));
    c.setAttribute('cy', String(cy));
    c.setAttribute('r', String(r));
    if (fill) c.setAttribute('fill', fill);
    else c.setAttribute('fill', 'none');
    if (stroke) c.setAttribute('stroke', stroke);
    if (strokeWidth) c.setAttribute('stroke-width', String(strokeWidth));
    if (className) c.setAttribute('class', className);
    return c;
  }

  function createStatusCenterIcon() {
    var svg = createSvg(16, 16, '0 0 16 16');
    var p1 = createSvgPath('M5 2h6v2H5zM4 3a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V4a1 1 0 0 0-1-1h-1V2a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v1H3zm2 4h4v1.2H6V7zm0 3h4v1.2H6V10zm0 3h3v1.2H6V13z', 'currentColor');
    svg.appendChild(p1);
    return svg;
  }

  function createProgressRingSvg() {
    var svg = createSvg(16, 16, '0 0 16 16');
    svg.setAttribute('class', 'status-center-ring-svg');
    var track = createSvgCircle(8, 8, 6, 'none', 'currentColor', 2, 'status-ring-track');
    var fill = createSvgCircle(8, 8, 6, 'none', 'currentColor', 2, 'status-ring-fill');
    svg.appendChild(track);
    svg.appendChild(fill);
    return svg;
  }

  function createPauseIcon() {
    var svg = createSvg(12, 12, '0 0 12 12');
    svg.appendChild(createSvgRect(2.5, 2, 2.2, 8, 0.8, 'currentColor'));
    svg.appendChild(createSvgRect(7.3, 2, 2.2, 8, 0.8, 'currentColor'));
    return svg;
  }

  function createResumeIcon() {
    var svg = createSvg(12, 12, '0 0 12 12');
    svg.appendChild(createSvgPath('M3 2.5L10 6L3 9.5z', 'currentColor'));
    return svg;
  }

  function createCancelIcon() {
    var svg = createSvg(12, 12, '0 0 12 12');
    svg.appendChild(createSvgPath('M2.5 2.5L9.5 9.5M9.5 2.5L2.5 9.5', 'none', 'currentColor', 1.5, 'round'));
    return svg;
  }

  function createChevronIcon() {
    var svg = createSvg(12, 12, '0 0 12 12');
    svg.appendChild(createSvgPath('M2.5 4.5L6 8L9.5 4.5', 'none', 'currentColor', 1.5, 'round', 'round'));
    return svg;
  }

  function createBadgeIcon(state, iconKind) {
    var svg = createSvg(16, 16, '0 0 16 16');
    if (state === 'Successful') {
      svg.appendChild(createSvgPath('M3 8.5L6.5 12L13 4', 'none', 'currentColor', 2, 'round', 'round'));
    } else if (state === 'Paused') {
      svg.appendChild(createSvgRect(4.2, 3.5, 2.6, 9, 1, 'currentColor'));
      svg.appendChild(createSvgRect(9.2, 3.5, 2.6, 9, 1, 'currentColor'));
    } else if (state === 'Error') {
      svg.appendChild(createSvgCircle(8, 8, 6.5, 'none', 'currentColor', 1.5));
      svg.appendChild(createSvgPath('M8 4.5v4M8 11v.5', 'none', 'currentColor', 1.8, 'round'));
    } else if (state === 'Canceled') {
      svg.appendChild(createSvgCircle(8, 8, 6.5, 'none', 'currentColor', 1.5));
      svg.appendChild(createSvgPath('M4 4l8 8', 'none', 'currentColor', 1.5, 'round'));
    } else {
      // InProgress
      var p1 = createSvgPath('M2 4.5A1.5 1.5 0 0 1 3.5 3h6A1.5 1.5 0 0 1 11 4.5V11a1.5 1.5 0 0 1-1.5 1.5h-6A1.5 1.5 0 0 1 2 11V4.5z', 'none', 'currentColor', 1.2);
      var p2 = createSvgPath('M5 2V1.5A1.5 1.5 0 0 1 6.5 0h6A1.5 1.5 0 0 1 14 1.5V8a1.5 1.5 0 0 1-1.5 1.5H12', 'none', 'currentColor', 1.2);
      svg.appendChild(p1);
      svg.appendChild(p2);
    }
    return svg;
  }

  function parseSpeedNumber(val) {
    if (typeof val === 'number') return isNaN(val) ? 0 : val;
    if (typeof val === 'string') {
      var num = parseFloat(val);
      if (!isNaN(num)) {
        var lower = val.toLowerCase();
        if (lower.indexOf('kb') !== -1) return num / 1024;
        if (lower.indexOf('gb') !== -1) return num * 1024;
        return num;
      }
    }
    return 0;
  }

  function renderSpeedGraph(canvas, speedHistory) {
    if (!canvas) return;
    var container = canvas.parentElement;
    if (!container) return;
    var rect = container.getBoundingClientRect();
    var width = rect.width || container.clientWidth || 374;
    var height = rect.height || container.clientHeight || 88;
    if (width <= 0 || height <= 0) return;

    var dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';

    var ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.save();
    ctx.scale(dpr, dpr);

    var isLight = document.body.classList.contains('light-theme') ||
                  document.documentElement.getAttribute('data-theme') === 'light' ||
                  document.body.getAttribute('data-theme') === 'light';

    var accentColor = isLight ? '#0067c0' : '#60cdff';
    var gridColor = isLight ? 'rgba(0, 0, 0, 0.08)' : 'rgba(255, 255, 255, 0.08)';
    var textColor = isLight ? 'rgba(0, 0, 0, 0.45)' : 'rgba(255, 255, 255, 0.45)';

    ctx.clearRect(0, 0, width, height);

    var points = Array.isArray(speedHistory) ? speedHistory.slice() : [0];
    if (points.length === 0) points = [0];
    if (points.length === 1) points = [points[0], points[0]];

    var highestValue = 1;
    for (var i = 0; i < points.length; i++) {
      if (points[i] > highestValue) highestValue = points[i];
    }

    // Formula matching Files.App SpeedGraph.cs:
    // YValue(y) = height - (y / highestValue) * (height - 24) - 4
    function getY(y) {
      var scaled = (y / highestValue) * (height - 24);
      return height - scaled - 4;
    }

    // Grid lines
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);

    var topY = getY(highestValue);
    var bottomY = getY(0);
    var midY = (topY + bottomY) / 2;

    ctx.beginPath();
    ctx.moveTo(0, topY);
    ctx.lineTo(width, topY);
    ctx.moveTo(0, midY);
    ctx.lineTo(width, midY);
    ctx.moveTo(0, bottomY);
    ctx.lineTo(width, bottomY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Labels
    ctx.fillStyle = textColor;
    ctx.font = '10px Segoe UI, system-ui, sans-serif';
    ctx.fillText(highestValue.toFixed(1) + ' MB/s', 8, 14);
    ctx.fillText('0 MB/s', 8, height - 8);

    // Area under curve with vertical gradient
    var grad = ctx.createLinearGradient(0, 20, 0, height);
    if (isLight) {
      grad.addColorStop(0, 'rgba(0, 103, 192, 0.28)');
      grad.addColorStop(1, 'rgba(0, 103, 192, 0.02)');
    } else {
      grad.addColorStop(0, 'rgba(96, 205, 255, 0.35)');
      grad.addColorStop(1, 'rgba(96, 205, 255, 0.02)');
    }

    ctx.beginPath();
    ctx.moveTo(0, height);
    for (var j = 0; j < points.length; j++) {
      var px = (j / (points.length - 1)) * width;
      var py = getY(points[j]);
      if (j === 0) ctx.lineTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.lineTo(width, height);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Curve stroke
    ctx.beginPath();
    for (var k = 0; k < points.length; k++) {
      var sx = (k / (points.length - 1)) * width;
      var sy = getY(points[k]);
      if (k === 0) ctx.moveTo(sx, sy);
      else ctx.lineTo(sx, sy);
    }
    ctx.strokeStyle = accentColor;
    ctx.lineWidth = 1.75;
    ctx.stroke();

    // Current speed indicator line at latest speed
    var lastVal = points[points.length - 1];
    var lastY = getY(lastVal);
    ctx.beginPath();
    ctx.setLineDash([2, 2]);
    ctx.strokeStyle = isLight ? 'rgba(0, 103, 192, 0.5)' : 'rgba(96, 205, 255, 0.5)';
    ctx.moveTo(0, lastY);
    ctx.lineTo(width, lastY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Point marker at latest speed
    ctx.beginPath();
    ctx.arc(width - 4, lastY, 3, 0, Math.PI * 2);
    ctx.fillStyle = accentColor;
    ctx.fill();
    ctx.strokeStyle = isLight ? '#ffffff' : '#1f1f1f';
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.restore();
  }

  // Controller State
  var tasks = [];
  var cardMap = new Map();
  var idSequence = 0;

  var toolbarBtn = null;
  var ringContainer = null;
  var badgeEl = null;
  var flyoutEl = null;
  var listEl = null;
  var emptyStateEl = null;

  function updateToolbarState() {
    var activeTasks = tasks.filter(function (t) {
      return t.state === 'InProgress' || t.state === 'Paused';
    });
    var activeCount = activeTasks.length;

    if (badgeEl) {
      if (activeCount > 0) {
        badgeEl.textContent = String(activeCount);
        badgeEl.hidden = false;
        badgeEl.style.display = 'inline-flex';
      } else {
        badgeEl.hidden = true;
        badgeEl.style.display = 'none';
      }
    }

    if (ringContainer) {
      ringContainer.replaceChildren();
      if (activeCount === 0) {
        ringContainer.appendChild(createStatusCenterIcon());
      } else {
        var hasIndeterminate = activeTasks.some(function (t) { return t.isIndeterminate; });
        var ringSvg = createProgressRingSvg();
        var fillCircle = ringSvg.querySelector('.status-ring-fill');
        if (hasIndeterminate) {
          if (fillCircle) {
            fillCircle.classList.add('indeterminate');
            fillCircle.setAttribute('stroke-dasharray', '12 26');
          }
        } else {
          var sum = 0;
          for (var i = 0; i < activeTasks.length; i++) {
            sum += (typeof activeTasks[i].progress === 'number' ? activeTasks[i].progress : 0);
          }
          var avg = sum / activeTasks.length;
          var C = 2 * Math.PI * 6;
          var dash = Math.max(0, Math.min(C, (avg / 100) * C));
          if (fillCircle) {
            fillCircle.setAttribute('stroke-dasharray', dash.toFixed(1) + ' ' + (C - dash).toFixed(1));
            fillCircle.setAttribute('stroke-dashoffset', '0');
          }
        }
        ringContainer.appendChild(ringSvg);
      }
    }
  }

  function updateFlyoutVisibility() {
    if (!emptyStateEl || !listEl) return;
    if (tasks.length === 0) {
      emptyStateEl.hidden = false;
      listEl.hidden = true;
    } else {
      emptyStateEl.hidden = true;
      listEl.hidden = false;
    }
  }

  function positionFlyout() {
    if (!flyoutEl) return;
    var anchor = toolbarBtn || document.getElementById('btn-sc');
    if (!anchor) return;
    var rect = anchor.getBoundingClientRect();
    var flyWidth = 400;
    var top = rect.bottom + 6;
    var right = Math.max(10, window.innerWidth - rect.right);
    if (right + flyWidth > window.innerWidth) {
      right = Math.max(10, window.innerWidth - flyWidth - 10);
    }
    flyoutEl.style.top = top + 'px';
    flyoutEl.style.right = right + 'px';
  }

  function openFlyout() {
    if (!flyoutEl) return;
    flyoutEl.hidden = false;
    flyoutEl.classList.remove('hidden');
    flyoutEl.classList.add('visible');
    if (toolbarBtn) toolbarBtn.setAttribute('aria-expanded', 'true');
    positionFlyout();
    redrawAllSpeedGraphs();
  }

  function closeFlyout() {
    if (!flyoutEl) return;
    flyoutEl.hidden = true;
    flyoutEl.classList.add('hidden');
    flyoutEl.classList.remove('visible');
    if (toolbarBtn) toolbarBtn.setAttribute('aria-expanded', 'false');
  }

  function toggleFlyout() {
    if (!flyoutEl) return;
    if (flyoutEl.hidden || flyoutEl.classList.contains('hidden')) {
      openFlyout();
    } else {
      closeFlyout();
    }
  }

  function redrawAllSpeedGraphs() {
    for (var i = 0; i < tasks.length; i++) {
      var t = tasks[i];
      if (t.isExpanded) {
        var card = cardMap.get(t.id);
        if (card && card.canvas) {
          renderSpeedGraph(card.canvas, t.speedHistory);
        }
      }
    }
  }

  function createTaskCard(handle) {
    var card = document.createElement('div');
    card.className = 'status-card state-in-progress';
    card.setAttribute('data-task-id', handle.id);

    // Main row
    var mainRow = document.createElement('div');
    mainRow.className = 'status-card-main-row';

    var badge = document.createElement('div');
    badge.className = 'status-card-icon-badge';
    badge.appendChild(createBadgeIcon(handle.state, handle.iconKind));

    var textCol = document.createElement('div');
    textCol.className = 'status-card-text-col';

    var titleEl = document.createElement('div');
    titleEl.className = 'status-card-title';
    titleEl.textContent = handle.title;
    titleEl.setAttribute('title', handle.title);

    var subtitleEl = document.createElement('div');
    subtitleEl.className = 'status-card-subtitle';
    subtitleEl.textContent = handle.subtitle || '';
    subtitleEl.setAttribute('title', handle.subtitle || '');

    textCol.appendChild(titleEl);
    textCol.appendChild(subtitleEl);

    var actions = document.createElement('div');
    actions.className = 'status-card-actions';

    var pauseBtn = document.createElement('button');
    pauseBtn.className = 'status-card-btn-pause';
    pauseBtn.type = 'button';
    pauseBtn.setAttribute('title', 'Pause');
    pauseBtn.setAttribute('aria-label', 'Pause');
    pauseBtn.appendChild(createPauseIcon());

    var cancelBtn = document.createElement('button');
    cancelBtn.className = 'status-card-btn-cancel';
    cancelBtn.type = 'button';
    cancelBtn.setAttribute('title', 'Cancel');
    cancelBtn.setAttribute('aria-label', 'Cancel');
    cancelBtn.appendChild(createCancelIcon());

    var chevronBtn = document.createElement('button');
    chevronBtn.className = 'status-card-btn-chevron';
    chevronBtn.type = 'button';
    chevronBtn.setAttribute('title', 'Toggle details');
    chevronBtn.setAttribute('aria-label', 'Toggle details');
    chevronBtn.setAttribute('aria-expanded', 'false');
    chevronBtn.appendChild(createChevronIcon());

    actions.appendChild(pauseBtn);
    actions.appendChild(cancelBtn);
    actions.appendChild(chevronBtn);

    mainRow.appendChild(badge);
    mainRow.appendChild(textCol);
    mainRow.appendChild(actions);

    // Progress bar
    var trackEl = document.createElement('div');
    trackEl.className = 'status-card-progress-track';
    trackEl.setAttribute('role', 'progressbar');
    trackEl.setAttribute('aria-valuenow', String(Math.round(handle.progress)));
    trackEl.setAttribute('aria-valuemin', '0');
    trackEl.setAttribute('aria-valuemax', '100');

    var fillEl = document.createElement('div');
    fillEl.className = 'status-card-progress-fill';
    fillEl.style.width = handle.progress + '%';
    trackEl.appendChild(fillEl);

    // Details panel
    var detailsEl = document.createElement('div');
    detailsEl.className = 'status-card-details';
    detailsEl.hidden = true;

    var graphContainer = document.createElement('div');
    graphContainer.className = 'status-card-speedgraph';

    var canvas = document.createElement('canvas');
    canvas.className = 'status-speedgraph-canvas';
    graphContainer.appendChild(canvas);

    var infoRows = document.createElement('div');
    infoRows.className = 'status-card-info-rows';

    var speedRow = document.createElement('div');
    speedRow.className = 'status-card-info-row status-card-speed-row';
    var speedLabel = document.createElement('span');
    speedLabel.className = 'status-card-label';
    speedLabel.textContent = 'Speed:';
    var speedVal = document.createElement('span');
    speedVal.className = 'status-card-val status-card-speed-val';
    speedVal.textContent = typeof handle.speed === 'number' ? (handle.speed.toFixed(1) + ' MB/s') : String(handle.speed || '0 MB/s');
    speedRow.appendChild(speedLabel);
    speedRow.appendChild(speedVal);

    var itemRow = document.createElement('div');
    itemRow.className = 'status-card-info-row status-card-item-row';
    var itemLabel = document.createElement('span');
    itemLabel.className = 'status-card-label';
    itemLabel.textContent = 'Name:';
    var itemName = document.createElement('span');
    itemName.className = 'status-card-val status-card-item-name';
    itemName.textContent = handle.currentItem || '-';
    itemRow.appendChild(itemLabel);
    itemRow.appendChild(itemName);

    var bytesRow = document.createElement('div');
    bytesRow.className = 'status-card-info-row status-card-bytes-row';
    var bytesLabel = document.createElement('span');
    bytesLabel.className = 'status-card-label';
    bytesLabel.textContent = 'Processed:';
    var bytesVal = document.createElement('span');
    bytesVal.className = 'status-card-val status-card-bytes-val';
    bytesVal.textContent = handle.processedBytes || '-';
    bytesRow.appendChild(bytesLabel);
    bytesRow.appendChild(bytesVal);

    infoRows.appendChild(speedRow);
    infoRows.appendChild(itemRow);
    infoRows.appendChild(bytesRow);

    detailsEl.appendChild(graphContainer);
    detailsEl.appendChild(infoRows);

    card.appendChild(mainRow);
    card.appendChild(trackEl);
    card.appendChild(detailsEl);

    // Event handlers
    pauseBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (handle.state === 'InProgress') handle.pause();
      else if (handle.state === 'Paused') handle.resume();
    });

    cancelBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      handle.cancel();
    });

    chevronBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      handle.isExpanded = !handle.isExpanded;
      card.classList.toggle('expanded', handle.isExpanded);
      detailsEl.hidden = !handle.isExpanded;
      chevronBtn.setAttribute('aria-expanded', handle.isExpanded ? 'true' : 'false');
      if (handle.isExpanded) {
        requestAnimationFrame(function () {
          renderSpeedGraph(canvas, handle.speedHistory);
        });
      }
    });

    var cardRecord = {
      cardEl: card,
      titleEl: titleEl,
      subtitleEl: subtitleEl,
      badgeEl: badge,
      trackEl: trackEl,
      fillEl: fillEl,
      pauseBtn: pauseBtn,
      cancelBtn: cancelBtn,
      chevronBtn: chevronBtn,
      detailsEl: detailsEl,
      canvas: canvas,
      speedVal: speedVal,
      itemName: itemName,
      bytesVal: bytesVal,
      update: function () {
        card.classList.remove('state-in-progress', 'state-paused', 'state-successful', 'state-error', 'state-canceled');
        if (handle.state === 'InProgress') card.classList.add('state-in-progress');
        else if (handle.state === 'Paused') card.classList.add('state-paused');
        else if (handle.state === 'Successful') card.classList.add('state-successful');
        else if (handle.state === 'Error') card.classList.add('state-error');
        else if (handle.state === 'Canceled') card.classList.add('state-canceled');

        titleEl.textContent = handle.title;
        titleEl.setAttribute('title', handle.title);

        var sub = handle.subtitle;
        if (!sub) {
          if (handle.state === 'Successful') sub = 'Completed';
          else if (handle.state === 'Canceled') sub = 'Canceled';
          else if (handle.state === 'Error') sub = handle.error || 'Failed';
          else if (handle.speed) sub = String(handle.speed);
          else sub = '';
        }
        subtitleEl.textContent = sub;
        subtitleEl.setAttribute('title', sub);

        badge.replaceChildren(createBadgeIcon(handle.state, handle.iconKind));

        trackEl.setAttribute('aria-valuenow', String(Math.round(handle.progress)));
        trackEl.classList.toggle('indeterminate', !!handle.isIndeterminate && handle.state === 'InProgress');
        fillEl.style.width = handle.progress + '%';

        if (handle.state === 'InProgress') {
          pauseBtn.hidden = !handle.isPausable;
          pauseBtn.setAttribute('title', 'Pause');
          pauseBtn.setAttribute('aria-label', 'Pause');
          pauseBtn.replaceChildren(createPauseIcon());
          cancelBtn.hidden = !handle.isCancelable;
        } else if (handle.state === 'Paused') {
          pauseBtn.hidden = !handle.isPausable;
          pauseBtn.setAttribute('title', 'Resume');
          pauseBtn.setAttribute('aria-label', 'Resume');
          pauseBtn.replaceChildren(createResumeIcon());
          cancelBtn.hidden = !handle.isCancelable;
        } else {
          pauseBtn.hidden = true;
          cancelBtn.hidden = true;
        }

        speedVal.textContent = typeof handle.speed === 'number' ? (handle.speed.toFixed(1) + ' MB/s') : String(handle.speed || '0 MB/s');
        itemName.textContent = handle.currentItem || '-';
        bytesVal.textContent = handle.processedBytes || '-';

        if (handle.isExpanded) {
          requestAnimationFrame(function () {
            renderSpeedGraph(canvas, handle.speedHistory);
          });
        }
      }
    };

    cardRecord.update();
    return cardRecord;
  }

  function TaskHandle(options) {
    var self = this;
    this.id = options.id || ('task_' + (++idSequence) + '_' + Date.now());
    this.title = options.title || 'Task';
    this.subtitle = options.subtitle || '';
    this.kind = options.kind || 'file';
    this.iconKind = options.iconKind || 'copy';
    this.progress = typeof options.progress === 'number' ? Math.min(100, Math.max(0, options.progress)) : 0;
    this.speed = options.speed !== undefined ? options.speed : '0 MB/s';
    this.speedHistory = Array.isArray(options.speedHistory) ? options.speedHistory.slice() : [];
    if (this.speedHistory.length === 0) {
      this.speedHistory.push(parseSpeedNumber(this.speed));
    }
    this.currentItem = options.currentItem || '';
    this.processedBytes = options.processedBytes || '';
    this.isIndeterminate = !!options.isIndeterminate;
    this.isCancelable = options.isCancelable !== false;
    this.isPausable = options.isPausable !== false;
    this.state = options.state || 'InProgress';
    this.error = null;
    this.isExpanded = !!options.isExpanded;

    this.update = function (opts) {
      if (!opts) return;
      if (typeof opts.progress === 'number') {
        self.progress = Math.min(100, Math.max(0, opts.progress));
      }
      if (typeof opts.title === 'string') self.title = opts.title;
      if (typeof opts.subtitle === 'string') self.subtitle = opts.subtitle;
      if (typeof opts.currentItem === 'string') self.currentItem = opts.currentItem;
      if (typeof opts.processedBytes === 'string') self.processedBytes = opts.processedBytes;
      if (typeof opts.isIndeterminate === 'boolean') self.isIndeterminate = opts.isIndeterminate;
      if (opts.speed !== undefined) {
        self.speed = opts.speed;
        var num = parseSpeedNumber(opts.speed);
        self.speedHistory.push(num);
        if (self.speedHistory.length > 60) self.speedHistory.shift();
      }
      if (Array.isArray(opts.speedHistory)) {
        self.speedHistory = opts.speedHistory.slice();
      }

      var card = cardMap.get(self.id);
      if (card) card.update();
      updateToolbarState();
    };

    this.pause = function () {
      if (self.state === 'InProgress') {
        self.state = 'Paused';
        var card = cardMap.get(self.id);
        if (card) card.update();
        updateToolbarState();
      }
    };

    this.resume = function () {
      if (self.state === 'Paused') {
        self.state = 'InProgress';
        var card = cardMap.get(self.id);
        if (card) card.update();
        updateToolbarState();
      }
    };

    this.cancel = function () {
      if (self.state !== 'Successful' && self.state !== 'Canceled') {
        self.state = 'Canceled';
        var card = cardMap.get(self.id);
        if (card) card.update();
        updateToolbarState();
      }
    };

    this.complete = function () {
      self.state = 'Successful';
      self.progress = 100;
      var card = cardMap.get(self.id);
      if (card) card.update();
      updateToolbarState();
    };

    this.fail = function (err) {
      self.state = 'Error';
      self.error = err || 'Operation failed';
      var card = cardMap.get(self.id);
      if (card) card.update();
      updateToolbarState();
    };

    this.getState = function () {
      return {
        id: self.id,
        title: self.title,
        subtitle: self.subtitle,
        kind: self.kind,
        iconKind: self.iconKind,
        progress: self.progress,
        speed: self.speed,
        speedHistory: self.speedHistory.slice(),
        currentItem: self.currentItem,
        processedBytes: self.processedBytes,
        isIndeterminate: self.isIndeterminate,
        isCancelable: self.isCancelable,
        isPausable: self.isPausable,
        state: self.state,
        error: self.error,
        isExpanded: self.isExpanded
      };
    };
  }

  function initStatusCenterDOM() {
    if (flyoutEl) return;

    // 1. Toolbar Button
    toolbarBtn = document.createElement('button');
    toolbarBtn.id = 'show-status-center-btn';
    toolbarBtn.className = 'status-center-toolbar-btn tbtn';
    toolbarBtn.type = 'button';
    toolbarBtn.setAttribute('title', 'Status Center');
    toolbarBtn.setAttribute('aria-label', 'Status Center');
    toolbarBtn.setAttribute('aria-expanded', 'false');

    ringContainer = document.createElement('span');
    ringContainer.className = 'status-center-ring-container';
    ringContainer.appendChild(createStatusCenterIcon());

    badgeEl = document.createElement('span');
    badgeEl.className = 'status-center-badge hidden';
    badgeEl.hidden = true;
    badgeEl.style.display = 'none';

    toolbarBtn.appendChild(ringContainer);
    toolbarBtn.appendChild(badgeEl);

    // Auto-mount toolbar button
    var tbTarget = document.querySelector('.toolbar .tbgroup.right') ||
                    document.querySelector('.toolbar') ||
                    document.body;

    var btnPane = document.getElementById('btn-pane');
    if (btnPane && btnPane.parentElement === tbTarget) {
      tbTarget.insertBefore(toolbarBtn, btnPane);
    } else {
      tbTarget.appendChild(toolbarBtn);
    }

    // Connect existing #btn-sc if present
    var btnSc = document.getElementById('btn-sc');
    if (btnSc) {
      btnSc.addEventListener('click', function (e) {
        e.stopPropagation();
        toggleFlyout();
      });
      var dummyFly = document.getElementById('sc-fly');
      if (dummyFly) dummyFly.hidden = true;
    }

    toolbarBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      toggleFlyout();
    });

    // 2. Flyout Overlay
    flyoutEl = document.createElement('div');
    flyoutEl.id = 'status-center-flyout';
    flyoutEl.className = 'status-center-flyout hidden';
    flyoutEl.hidden = true;

    // Header
    var header = document.createElement('div');
    header.className = 'status-center-header';

    var headerTitle = document.createElement('span');
    headerTitle.className = 'status-center-title';
    headerTitle.textContent = 'Status Center';

    var clearBtn = document.createElement('button');
    clearBtn.className = 'status-center-clear-btn';
    clearBtn.type = 'button';
    clearBtn.textContent = 'Clear completed';
    clearBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      clearCompleted();
    });

    header.appendChild(headerTitle);
    header.appendChild(clearBtn);

    // Empty state
    emptyStateEl = document.createElement('div');
    emptyStateEl.className = 'status-center-empty';

    var emptyIconWrap = document.createElement('div');
    emptyIconWrap.className = 'status-center-empty-icon';
    emptyIconWrap.appendChild(createStatusCenterIcon());

    var emptyText = document.createElement('span');
    emptyText.textContent = 'No background tasks';

    emptyStateEl.appendChild(emptyIconWrap);
    emptyStateEl.appendChild(emptyText);

    // List container
    listEl = document.createElement('div');
    listEl.className = 'status-center-list';
    listEl.hidden = true;

    flyoutEl.appendChild(header);
    flyoutEl.appendChild(emptyStateEl);
    flyoutEl.appendChild(listEl);

    document.body.appendChild(flyoutEl);

    // Outside click & keyboard listener
    document.addEventListener('pointerdown', function (e) {
      if (flyoutEl.hidden) return;
      if (flyoutEl.contains(e.target)) return;
      if (toolbarBtn && toolbarBtn.contains(e.target)) return;
      var bsc = document.getElementById('btn-sc');
      if (bsc && bsc.contains(e.target)) return;
      closeFlyout();
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !flyoutEl.hidden) {
        closeFlyout();
      }
    });

    window.addEventListener('resize', function () {
      if (!flyoutEl.hidden) {
        positionFlyout();
        redrawAllSpeedGraphs();
      }
    });
  }

  function addTask(options) {
    initStatusCenterDOM();
    var handle = new TaskHandle(options || {});
    tasks.push(handle);

    var cardRecord = createTaskCard(handle);
    cardMap.set(handle.id, cardRecord);
    listEl.appendChild(cardRecord.cardEl);

    updateFlyoutVisibility();
    updateToolbarState();

    return handle;
  }

  function clearCompleted() {
    initStatusCenterDOM();
    var remaining = [];
    for (var i = 0; i < tasks.length; i++) {
      var t = tasks[i];
      if (t.state === 'Successful' || t.state === 'Canceled' || t.state === 'Error') {
        var card = cardMap.get(t.id);
        if (card && card.cardEl && card.cardEl.parentElement) {
          card.cardEl.parentElement.removeChild(card.cardEl);
        }
        cardMap.delete(t.id);
      } else {
        remaining.push(t);
      }
    }
    tasks = remaining;
    updateFlyoutVisibility();
    updateToolbarState();
  }

  function getTasks() {
    return tasks.slice();
  }

  // Initialize immediately if body is ready, or on DOMContentLoaded
  if (document.body) {
    initStatusCenterDOM();
  } else {
    document.addEventListener('DOMContentLoaded', initStatusCenterDOM);
  }

  return {
    addTask: addTask,
    clearCompleted: clearCompleted,
    openFlyout: openFlyout,
    closeFlyout: closeFlyout,
    toggleFlyout: toggleFlyout,
    getTasks: getTasks,
    get toolbarButton() { return toolbarBtn; },
    get flyout() { return flyoutEl; },
    __initialized: true
  };
});

  })();

