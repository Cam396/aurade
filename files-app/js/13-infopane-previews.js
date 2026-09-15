  // =========================================================================
  // Wave 3: Rich InfoPane Previews (P09)
  // =========================================================================
  var SVG_NS = 'http://www.w3.org/2000/svg';

  function createSvgElement(tag, attrs) {
    var el = document.createElementNS(SVG_NS, tag);
    if (attrs) {
      for (var key in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, key)) {
          el.setAttribute(key, attrs[key]);
        }
      }
    }
    return el;
  }

  function createFolderIcon() {
    var svg = createSvgElement('svg', {
      viewBox: '0 0 48 40',
      width: '56',
      height: '56',
      'aria-hidden': 'true'
    });
    var path1 = createSvgElement('path', {
      d: 'M1 6a4 4 0 0 1 4-4h12.3a4 4 0 0 1 2.9 1.2L24 7h19a4 4 0 0 1 4 4v3H1z',
      fill: 'var(--folder-back, #b9860f)'
    });
    var path2 = createSvgElement('path', {
      d: 'M1 12h46a0 0 0 0 1 0 0v22a4 4 0 0 1-4 4H5a4 4 0 0 1-4-4z',
      fill: 'var(--folder-a, #ffd15c)'
    });
    svg.appendChild(path1);
    svg.appendChild(path2);
    return svg;
  }

  function createFileIcon() {
    var svg = createSvgElement('svg', {
      viewBox: '0 0 40 48',
      width: '48',
      height: '48',
      'aria-hidden': 'true'
    });
    var path1 = createSvgElement('path', {
      d: 'M2 6a4 4 0 0 1 4-4h18l14 14v26a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4z',
      fill: 'rgba(255, 255, 255, 0.1)'
    });
    var path2 = createSvgElement('path', {
      d: 'M24 2v14h14z',
      fill: 'rgba(255, 255, 255, 0.2)'
    });
    svg.appendChild(path1);
    svg.appendChild(path2);
    return svg;
  }

  function getFileExtension(filename) {
    if (!filename || typeof filename !== 'string') return '';
    var lastDot = filename.lastIndexOf('.');
    if (lastDot === -1 || lastDot === 0 || lastDot === filename.length - 1) return '';
    return filename.slice(lastDot + 1).toLowerCase();
  }

  //: HTML preview. The page enforces Trusted Types, so the document is parsed
  //: and then rebuilt node by node against an allowlist rather than injected.
  //: DOMParser does not run scripts, and nothing here copies an element the
  //: allowlist does not name, so a preview cannot become an execution.
  var HTML_OK_TAGS = {
    'P': 1, 'DIV': 1, 'SPAN': 1, 'BR': 1, 'HR': 1, 'STRONG': 1, 'B': 1,
    'EM': 1, 'I': 1, 'U': 1, 'S': 1, 'CODE': 1, 'PRE': 1, 'BLOCKQUOTE': 1,
    'UL': 1, 'OL': 1, 'LI': 1, 'DL': 1, 'DT': 1, 'DD': 1,
    'H1': 1, 'H2': 1, 'H3': 1, 'H4': 1, 'H5': 1, 'H6': 1,
    'TABLE': 1, 'THEAD': 1, 'TBODY': 1, 'TFOOT': 1, 'TR': 1, 'TD': 1,
    'TH': 1, 'CAPTION': 1, 'A': 1, 'IMG': 1, 'FIGURE': 1, 'FIGCAPTION': 1,
    'SMALL': 1, 'SUB': 1, 'SUP': 1, 'ABBR': 1, 'MARK': 1, 'TIME': 1
  };
  var HTML_MAX_NODES = 4000;

  //: el() belongs to the settings scope. This one is local on purpose.
  function pvEl(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  //: chrome://file-manager enforces Trusted Types, and DOMParser is a sink
  //: there: a plain string throws. The policy carries the name of the one
  //: Chromium's own parseHtmlSubset makes, because this does the same job
  //: the same way, the string goes in unchanged and the walk below is the
  //: sanitizer. That name is on the SWA's allow list; an invented one is not.
  var previewHtmlPolicy = null;
  function previewHtml(source) {
    if (!window.trustedTypes) return source;
    if (!previewHtmlPolicy) {
      previewHtmlPolicy = window.trustedTypes.createPolicy('parse-html-subset', {
        createHTML: function (s) { return s; }
      });
    }
    return previewHtmlPolicy.createHTML(source);
  }

  function sanitizeHtmlInto(box, source, baseName) {
    var doc = new DOMParser().parseFromString(previewHtml(source), 'text/html');
    var budget = { left: HTML_MAX_NODES, cut: false };

    function copy(node, into) {
      if (budget.left <= 0) { budget.cut = true; return; }
      budget.left = budget.left - 1;
      if (node.nodeType === 3) {
        into.appendChild(document.createTextNode(node.nodeValue));
        return;
      }
      if (node.nodeType !== 1) return;
      var tag = node.tagName;
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'LINK' ||
          tag === 'IFRAME' || tag === 'OBJECT' || tag === 'EMBED' ||
          tag === 'FORM' || tag === 'INPUT' || tag === 'BUTTON') return;
      if (!HTML_OK_TAGS[tag]) {
        //: An unknown wrapper is not content, but what is inside it might be,
        //: so the element is dropped and its children are kept.
        var kids = node.childNodes;
        for (var k = 0; k < kids.length; k++) copy(kids[k], into);
        return;
      }
      var out = document.createElement(tag.toLowerCase());
      //: Two attributes survive, and only when their value is a link that
      //: cannot execute. Everything else, style and event handlers included,
      //: is dropped.
      if (tag === 'A') {
        var href = node.getAttribute('href') || '';
        if (/^(https?:|mailto:|#)/i.test(href)) {
          out.setAttribute('href', href);
          out.setAttribute('rel', 'noopener noreferrer');
          out.setAttribute('target', '_blank');
        }
      }
      if (tag === 'IMG') {
        var src = node.getAttribute('src') || '';
        //: A src the allowlist rejects leaves an empty broken frame, so the
        //: image goes with it rather than the attribute alone.
        if (!/^(https?:|data:image\/)/i.test(src)) return;
        out.setAttribute('src', src);
        var alt = node.getAttribute('alt');
        if (alt) out.setAttribute('alt', alt);
      }
      var ch = node.childNodes;
      for (var j = 0; j < ch.length; j++) copy(ch[j], out);
      into.appendChild(out);
    }

    var body = doc.body || doc.documentElement;
    var kids = body ? body.childNodes : [];
    for (var i = 0; i < kids.length; i++) copy(kids[i], box);
    if (budget.cut) {
      var cut = pvEl('div', 'pv-cut');
      cut.textContent = 'Preview shortened. The rest of the document is not shown.';
      box.appendChild(cut);
    }
    var title = (doc.title || '').trim();
    return title || baseName;
  }

  //: Rich text. Enough of RTF to read a document with: paragraphs, line
  //: breaks, bold, italic, underline, the hex and unicode escapes, and the
  //: destination groups whose contents are machinery rather than text. Not a
  //: renderer, a reader, which is what a preview pane is for.
  var RTF_SKIP = {
    fonttbl: 1, colortbl: 1, stylesheet: 1, info: 1, pict: 1, header: 1,
    footer: 1, footnote: 1, listtable: 1, listoverridetable: 1,
    generator: 1, filetbl: 1, revtbl: 1, themedata: 1, datastore: 1
  };

  function renderRtfInto(box, source) {
    var para = pvEl('div', 'pv-p');
    box.appendChild(para);
    var style = { b: false, i: false, u: false };
    var stack = [];
    var skipDepth = -1;
    var uc = 1;
    var depth = 0;
    var i = 0;
    var buf = '';

    function flush() {
      if (!buf) return;
      var node = document.createTextNode(buf);
      var wrap = node;
      if (style.u) { var u = pvEl('u'); u.appendChild(wrap); wrap = u; }
      if (style.i) { var em = pvEl('em'); em.appendChild(wrap); wrap = em; }
      if (style.b) { var st = pvEl('strong'); st.appendChild(wrap); wrap = st; }
      para.appendChild(wrap);
      buf = '';
    }
    function newPara() {
      flush();
      para = pvEl('div', 'pv-p');
      box.appendChild(para);
    }

    while (i < source.length) {
      var c = source.charAt(i);
      if (c === '{') {
        depth = depth + 1;
        stack.push({ b: style.b, i: style.i, u: style.u });
        i = i + 1;
        continue;
      }
      if (c === '}') {
        if (skipDepth !== -1 && depth <= skipDepth) skipDepth = -1;
        depth = depth - 1;
        var prev = stack.pop();
        if (prev) { flush(); style = prev; }
        i = i + 1;
        continue;
      }
      if (c === '\\') {
        var m = /^\\([a-zA-Z]+)(-?[0-9]*) ?/.exec(source.slice(i));
        if (m) {
          var word = m[1];
          var arg = m[2];
          i = i + m[0].length;
          if (skipDepth !== -1) continue;
          if (RTF_SKIP[word.toLowerCase()]) { skipDepth = depth; continue; }
          if (word === 'par' || word === 'pard') { newPara(); continue; }
          if (word === 'line') { flush(); para.appendChild(pvEl('br')); continue; }
          if (word === 'tab') { buf = buf + '\t'; continue; }
          if (word === 'b') { flush(); style.b = arg !== '0'; continue; }
          if (word === 'i') { flush(); style.i = arg !== '0'; continue; }
          if (word === 'ul') { flush(); style.u = true; continue; }
          if (word === 'ulnone') { flush(); style.u = false; continue; }
          if (word === 'uc') {
            var n = parseInt(arg, 10);
            if (!isNaN(n) && n >= 0) uc = n;
            continue;
          }
          if (word === 'u') {
            var code = parseInt(arg, 10);
            if (!isNaN(code)) {
              buf = buf + String.fromCharCode(code < 0 ? code + 65536 : code);
            }
            //: The characters after a \uN are the same character written
            //: for a reader that cannot do unicode. Showing both doubles it.
            i = i + uc;
            continue;
          }
          continue;
        }
        var hex = /^\\'([0-9a-fA-F]{2})/.exec(source.slice(i));
        if (hex) {
          if (skipDepth === -1) {
            buf = buf + String.fromCharCode(parseInt(hex[1], 16));
          }
          i = i + hex[0].length;
          continue;
        }
        //: An escaped brace or backslash is literal text.
        if (skipDepth === -1) buf = buf + source.charAt(i + 1);
        i = i + 2;
        continue;
      }
      if (c === '\n' || c === '\r') { i = i + 1; continue; }
      if (skipDepth === -1) buf = buf + c;
      i = i + 1;
    }
    flush();
    //: A trailing \par leaves an empty last paragraph.
    if (para && !para.childNodes.length && para.parentNode) para.remove();
    return box.querySelectorAll('.pv-p').length;
  }

  window.__previewRich = {
    html: sanitizeHtmlInto,
    rtf: renderRtfInto
  };

  function detectFileType(name, kind) {
    var k = (kind || '').toLowerCase();
    var ext = getFileExtension(name);

    if (k === 'folder' || k === 'directory') return 'folder';

    var imageExtensions = ['png', 'jpg', 'jpeg', 'svg', 'webp', 'gif', 'bmp', 'ico', 'avif'];
    if (imageExtensions.indexOf(ext) !== -1 || k.indexOf('image') !== -1) {
      return 'image';
    }

    var videoExtensions = ['mp4', 'webm', 'ogg', 'ogv', 'mov', 'mkv', 'avi'];
    if (videoExtensions.indexOf(ext) !== -1 || k.indexOf('video') !== -1) {
      return 'video';
    }

    var audioExtensions = ['mp3', 'wav', 'ogg', 'm4a', 'aac', 'flac', 'opus', 'wma'];
    if (audioExtensions.indexOf(ext) !== -1 || k.indexOf('audio') !== -1) {
      return 'audio';
    }

    if (ext === 'pdf') return 'pdf';
    if (ext === 'html' || ext === 'htm' || ext === 'xhtml') return 'html';
    if (ext === 'rtf') return 'richtext';

    var markdownExtensions = ['md', 'markdown', 'mdown', 'mkd'];
    if (markdownExtensions.indexOf(ext) !== -1 || k.indexOf('markdown') !== -1) {
      return 'markdown';
    }

    var codeExtensions = [
      'py', 'js', 'json', 'html', 'css', 'txt', 'sh', 'bash', 'zsh',
      'c', 'cpp', 'h', 'hpp', 'rs', 'go', 'java', 'ts', 'tsx', 'jsx',
      'xml', 'yaml', 'yml', 'toml', 'ini', 'conf', 'cfg', 'log', 'bat',
      'sql', 'diff', 'patch'
    ];
    if (codeExtensions.indexOf(ext) !== -1 ||
        k.indexOf('text') !== -1 ||
        k.indexOf('script') !== -1 ||
        k.indexOf('code') !== -1 ||
        k.indexOf('log') !== -1 ||
        k.indexOf('file') !== -1) {
      return 'text';
    }

    return 'text';
  }

  function parseInlineMarkdown(text, parentElement) {
    var bs = String.fromCharCode(92);
    var inlinePattern = new RegExp('(`[^`]+`|' +
      bs + '*' + bs + '*[^*]+' + bs + '*' + bs + '*|' +
      '__[^_]+__|' +
      bs + '*[^*]+' + bs + '*|' +
      '_[^_]+_|' +
      bs + '[' + '[^' + bs + ']' + ']+' + bs + ']' +
      bs + '(' + '[^)]+' + bs + '))', 'g');
    var lastIndex = 0;
    var match;

    while ((match = inlinePattern.exec(text)) !== null) {
      if (match.index > lastIndex) {
        parentElement.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
      }
      var token = match[0];
      if (token.charAt(0) === '`' && token.charAt(token.length - 1) === '`') {
        var codeEl = document.createElement('code');
        codeEl.textContent = token.slice(1, -1);
        parentElement.appendChild(codeEl);
      } else if ((token.slice(0, 2) === '**' && token.slice(-2) === '**') ||
                 (token.slice(0, 2) === '__' && token.slice(-2) === '__')) {
        var strongEl = document.createElement('strong');
        strongEl.textContent = token.slice(2, -2);
        parentElement.appendChild(strongEl);
      } else if ((token.charAt(0) === '*' && token.charAt(token.length - 1) === '*') ||
                 (token.charAt(0) === '_' && token.charAt(token.length - 1) === '_')) {
        var emEl = document.createElement('em');
        emEl.textContent = token.slice(1, -1);
        parentElement.appendChild(emEl);
      } else if (token.charAt(0) === '[' && token.indexOf('](') !== -1 && token.charAt(token.length - 1) === ')') {
        var linkEnd = token.indexOf('](');
        var linkText = token.slice(1, linkEnd);
        var linkHref = token.slice(linkEnd + 2, -1).trim();
        var aEl = document.createElement('a');
        aEl.textContent = linkText;
        var isSafeLink = linkHref.startsWith('https:') || linkHref.startsWith('http:') ||
                         linkHref.startsWith('#') || linkHref.startsWith('/');
        if (isSafeLink) {
          aEl.setAttribute('href', linkHref);
          aEl.setAttribute('target', '_blank');
          aEl.setAttribute('rel', 'noopener noreferrer');
        } else {
          aEl.setAttribute('href', '#');
        }
        parentElement.appendChild(aEl);
      }
      lastIndex = inlinePattern.lastIndex;
    }

    if (lastIndex < text.length) {
      parentElement.appendChild(document.createTextNode(text.slice(lastIndex)));
    }
  }

  function renderMarkdownToDom(text, targetContainer) {
    if (typeof targetContainer.replaceChildren === 'function') {
      targetContainer.replaceChildren();
    } else {
      while (targetContainer.firstChild) {
        targetContainer.removeChild(targetContainer.firstChild);
      }
    }

    if (!text || typeof text !== 'string') {
      var emptyNotice = document.createElement('p');
      emptyNotice.textContent = 'Empty file.';
      targetContainer.appendChild(emptyNotice);
      return;
    }

    var newlineChar = String.fromCharCode(10);
    var crChar = String.fromCharCode(13);
    var rawLines = text.split(newlineChar);
    var lines = [];
    for (var r = 0; r < rawLines.length; r++) {
      var rl = rawLines[r];
      if (rl.length > 0 && rl.charAt(rl.length - 1) === crChar) {
        rl = rl.slice(0, -1);
      }
      lines.push(rl);
    }
    var inCodeBlock = false;
    var codeBlockLines = [];
    var currentList = null;
    var currentListType = '';

    function closeList() {
      if (currentList) {
        targetContainer.appendChild(currentList);
        currentList = null;
        currentListType = '';
      }
    }

    for (var i = 0; i < lines.length; i++) {
      var rawLine = lines[i];
      var trimmed = rawLine.trim();

      if (trimmed.slice(0, 3) === '```') {
        closeList();
        if (inCodeBlock) {
          var preEl = document.createElement('pre');
          var codeEl = document.createElement('code');
          codeEl.textContent = codeBlockLines.join(newlineChar);
          preEl.appendChild(codeEl);
          targetContainer.appendChild(preEl);
          codeBlockLines = [];
          inCodeBlock = false;
        } else {
          inCodeBlock = true;
          codeBlockLines = [];
        }
        continue;
      }

      if (inCodeBlock) {
        codeBlockLines.push(rawLine);
        continue;
      }

      if (!trimmed) {
        closeList();
        continue;
      }

      if (trimmed === '---' || trimmed === '***' || trimmed === '___') {
        closeList();
        targetContainer.appendChild(document.createElement('hr'));
        continue;
      }

      if (trimmed.charAt(0) === '#') {
        closeList();
        var headingLevel = 0;
        while (headingLevel < trimmed.length && trimmed.charAt(headingLevel) === '#') {
          headingLevel++;
        }
        if (headingLevel > 6) headingLevel = 6;
        var headingText = trimmed.slice(headingLevel).trim();
        var headingTag = 'h' + (headingLevel <= 4 ? headingLevel : 4);
        var headingEl = document.createElement(headingTag);
        parseInlineMarkdown(headingText, headingEl);
        targetContainer.appendChild(headingEl);
        continue;
      }

      if (trimmed.charAt(0) === '>') {
        closeList();
        var quoteText = trimmed.slice(1).trim();
        var blockquoteEl = document.createElement('blockquote');
        var bqParagraph = document.createElement('p');
        parseInlineMarkdown(quoteText, bqParagraph);
        blockquoteEl.appendChild(bqParagraph);
        targetContainer.appendChild(blockquoteEl);
        continue;
      }

      var isUnordered = (trimmed.charAt(0) === '-' || trimmed.charAt(0) === '*') &&
                        (trimmed.charAt(1) === ' ' || trimmed.charCodeAt(1) === 9);
      if (isUnordered) {
        if (!currentList || currentListType !== 'ul') {
          closeList();
          currentList = document.createElement('ul');
          currentListType = 'ul';
        }
        var liUnordered = document.createElement('li');
        parseInlineMarkdown(trimmed.slice(2).trim(), liUnordered);
        currentList.appendChild(liUnordered);
        continue;
      }

      var dotSpaceIdx = trimmed.indexOf('. ');
      var isOrdered = false;
      var orderedText = '';
      if (dotSpaceIdx > 0) {
        var numPart = trimmed.slice(0, dotSpaceIdx);
        if (/^[0-9]+$/.test(numPart)) {
          isOrdered = true;
          orderedText = trimmed.slice(dotSpaceIdx + 2).trim();
        }
      }
      if (isOrdered) {
        if (!currentList || currentListType !== 'ol') {
          closeList();
          currentList = document.createElement('ol');
          currentListType = 'ol';
        }
        var liOrdered = document.createElement('li');
        parseInlineMarkdown(orderedText, liOrdered);
        currentList.appendChild(liOrdered);
        continue;
      }

      closeList();
      var paragraphEl = document.createElement('p');
      parseInlineMarkdown(trimmed, paragraphEl);
      targetContainer.appendChild(paragraphEl);
    }

    closeList();

    if (inCodeBlock && codeBlockLines.length > 0) {
      var hangingPre = document.createElement('pre');
      var hangingCode = document.createElement('code');
      hangingCode.textContent = codeBlockLines.join(newlineChar);
      hangingPre.appendChild(hangingCode);
      targetContainer.appendChild(hangingPre);
    }
  }

  function getSelectedItems(scope) {
    var root = scope || document;
    var selectors = [
      '.cell.sel', '.row.sel', '.lrow.sel', '.tile.sel', '.crow.sel',
      '.grid .sel', '.dbody .sel', '.list .sel', '.cards .sel', '.columns .sel',
      '#filearea .sel', '.filearea .sel', '[aria-selected="true"]'
    ];
    var seen = [];
    for (var s = 0; s < selectors.length; s++) {
      var elements = root.querySelectorAll(selectors[s]);
      for (var i = 0; i < elements.length; i++) {
        var el = elements[i];
        if (seen.indexOf(el) === -1) {
          seen.push(el);
        }
      }
    }
    return seen;
  }

  function clearElement(el) {
    if (!el) return;
    if (typeof el.replaceChildren === 'function') {
      el.replaceChildren();
    } else {
      while (el.firstChild) {
        el.removeChild(el.firstChild);
      }
    }
  }

  function setupInfoPanePreviews(options) {
    options = options || {};

    var pane = options.pane;
    if (!pane) {
      pane = document.getElementById('pane') ||
             document.getElementById('infopane') ||
             document.querySelector('.pane') ||
             document.querySelector('.infopane');
    }
    if (!pane) return null;

    var fileArea = options.fileArea ||
                   document.getElementById('filearea') ||
                   document.querySelector('.filearea') ||
                   document.body;

    var customFetchPreview = options.fetchPreview || null;
    var onTabChange = typeof options.onTabChange === 'function' ? options.onTabChange : null;

    var tabsContainer = pane.querySelector('.infopane-tabs');
    var detailsTab = null;
    var previewTab = null;

    if (!tabsContainer) {
      var existingTabs = pane.querySelector('.itabs');
      if (existingTabs) {
        tabsContainer = existingTabs;
        tabsContainer.classList.add('infopane-tabs');
        detailsTab = tabsContainer.querySelector('[data-itab="details"]');
        previewTab = tabsContainer.querySelector('[data-itab="preview"]');
        if (detailsTab) detailsTab.classList.add('infopane-tab');
        if (previewTab) previewTab.classList.add('infopane-tab');
      } else {
        tabsContainer = document.createElement('div');
        tabsContainer.className = 'infopane-tabs';
        tabsContainer.setAttribute('role', 'tablist');

        detailsTab = document.createElement('button');
        detailsTab.type = 'button';
        detailsTab.className = 'infopane-tab active';
        detailsTab.setAttribute('role', 'tab');
        detailsTab.setAttribute('aria-selected', 'true');
        detailsTab.setAttribute('data-itab', 'details');
        detailsTab.textContent = 'Details';

        previewTab = document.createElement('button');
        previewTab.type = 'button';
        previewTab.className = 'infopane-tab';
        previewTab.setAttribute('role', 'tab');
        previewTab.setAttribute('aria-selected', 'false');
        previewTab.setAttribute('data-itab', 'preview');
        previewTab.textContent = 'Preview';

        tabsContainer.appendChild(detailsTab);
        tabsContainer.appendChild(previewTab);

        if (pane.firstChild) {
          pane.insertBefore(tabsContainer, pane.firstChild);
        } else {
          pane.appendChild(tabsContainer);
        }
      }
    } else {
      detailsTab = tabsContainer.querySelector('[data-itab="details"]');
      previewTab = tabsContainer.querySelector('[data-itab="preview"]');
    }

    if (!detailsTab) {
      detailsTab = tabsContainer.querySelector('.infopane-tab:nth-child(1)') ||
                   tabsContainer.querySelector('button:nth-child(1)');
    }
    if (!previewTab) {
      previewTab = tabsContainer.querySelector('.infopane-tab:nth-child(2)') ||
                   tabsContainer.querySelector('button:nth-child(2)');
    }

    var detailsView = options.detailsView ||
                      pane.querySelector('#ipane-details') ||
                      pane.querySelector('.infopane-details-view') ||
                      pane.querySelector('.ipane:not(#ipane-preview):not(.infopane-preview-view)') ||
                      pane.querySelector('.psec');

    var previewView = options.previewView ||
                      pane.querySelector('.infopane-preview-view') ||
                      pane.querySelector('#ipane-preview');

    if (!previewView) {
      previewView = document.createElement('div');
      previewView.className = 'infopane-preview-view';
      previewView.id = 'ipane-preview';
      previewView.hidden = true;
      pane.appendChild(previewView);
    } else {
      previewView.classList.add('infopane-preview-view');
    }

    /* Locate or create #ipart and #ipreview-text inside #ipane-preview without wiping container */
    var ipart = previewView.querySelector('#ipart') || document.getElementById('ipart');
    if (!ipart) {
      ipart = document.createElement('div');
      ipart.id = 'ipart';
      ipart.className = 'ipreview-art';
      if (previewView.firstChild) {
        previewView.insertBefore(ipart, previewView.firstChild);
      } else {
        previewView.appendChild(ipart);
      }
    }

    var ipreviewText = previewView.querySelector('#ipreview-text') || document.getElementById('ipreview-text');
    if (!ipreviewText) {
      ipreviewText = document.createElement('div');
      ipreviewText.id = 'ipreview-text';
      ipreviewText.className = 'ipreview-text';
      ipreviewText.hidden = true;
      if (ipart && ipart.nextSibling) {
        previewView.insertBefore(ipreviewText, ipart.nextSibling);
      } else {
        previewView.appendChild(ipreviewText);
      }
    }

    var activeTab = 'details';
    var currentPreviewToken = 0;

    function renderEmptyState(message, subtitle) {
      clearElement(ipart);

      var box = document.createElement('div');
      box.className = 'preview-empty-box';

      var iconWrap = document.createElement('div');
      iconWrap.className = 'preview-empty-icon';
      iconWrap.appendChild(createFileIcon());
      box.appendChild(iconWrap);

      var msg = document.createElement('div');
      msg.className = 'preview-empty-message';
      msg.textContent = message || 'Select a file to preview';
      box.appendChild(msg);

      if (subtitle) {
        var sub = document.createElement('div');
        sub.className = 'preview-empty-sub';
        sub.textContent = subtitle;
        box.appendChild(sub);
      }

      ipart.appendChild(box);

      if (ipreviewText) {
        clearElement(ipreviewText);
        ipreviewText.textContent = '';
        ipreviewText.hidden = true;
      }
    }

    function renderImagePreview(item, name, path) {
      clearElement(ipart);

      var box = document.createElement('div');
      box.className = 'preview-image-box';

      var img = document.createElement('img');
      img.setAttribute('alt', name || 'Image preview');

      var src = item ? (item.getAttribute('data-src') || item.getAttribute('data-url') || '') : '';
      if (!src && item && item.querySelector('img')) {
        src = item.querySelector('img').getAttribute('src') || '';
      }
      if (!src) {
        src = path;
      }

      if (src) {
        img.setAttribute('src', src);
      }

      img.addEventListener('error', function () {
        img.style.display = 'none';
        if (!box.querySelector('.preview-fallback-icon')) {
          var thumbSvg = item ? item.querySelector('svg') : null;
          if (thumbSvg) {
            var clone = thumbSvg.cloneNode(true);
            clone.classList.add('preview-fallback-icon');
            box.appendChild(clone);
          } else {
            var fileIcon = createFileIcon();
            fileIcon.classList.add('preview-fallback-icon');
            box.appendChild(fileIcon);
          }
        }
      });

      box.appendChild(img);
      ipart.appendChild(box);

      if (ipreviewText) {
        clearElement(ipreviewText);
        ipreviewText.textContent = '';
        ipreviewText.hidden = true;
      }
    }

    //: A PDF's first page, rendered by the backend and handed over as one
    //: image. The reference has a PDFPreview control with a page strip; this is
    //: the first page of it, and it says so rather than pretending otherwise.
    function renderPagePreview(item, name, path, token) {
      clearElement(ipart);
      var box = document.createElement('div');
      box.className = 'preview-image-box';
      var img = document.createElement('img');
      img.setAttribute('alt', name || 'Page preview');
      box.appendChild(img);
      var note = document.createElement('div');
      note.className = 'preview-media-title';
      note.textContent = name;
      box.appendChild(note);
      ipart.appendChild(box);

      var baked = item ? (item.getAttribute('data-th') || '') : '';
      if (baked) { img.setAttribute('src', baked); return; }
      if (!window.__fetchThumb) {
        note.textContent = name + ' (the first page needs the backend)';
        return;
      }
      window.__fetchThumb(path).then(function (uri) {
        if (token !== currentPreviewToken) return;
        if (uri) img.setAttribute('src', uri);
        else note.textContent = name + ' (no page preview available)';
      }).catch(function () {});
    }

    function renderMediaPreview(item, name, path, isVideo) {
      clearElement(ipart);

      var box = document.createElement('div');
      box.className = 'preview-media-box';

      var mediaEl;
      if (isVideo) {
        mediaEl = document.createElement('video');
      } else {
        mediaEl = document.createElement('audio');
      }

      mediaEl.setAttribute('controls', 'true');
      mediaEl.setAttribute('preload', 'metadata');
      if (path) {
        mediaEl.setAttribute('src', path);
      }
      // A frame from a second in, so the box shows the video rather than the
      // black rectangle that most first frames are. Playing it still needs the
      // file itself, which this backend does not serve.
      if (isVideo) {
        var poster = item ? (item.getAttribute('data-th') || '') : '';
        if (poster) mediaEl.setAttribute('poster', poster);
        else if (window.__fetchThumb) {
          window.__fetchThumb(path).then(function (uri) {
            if (uri) mediaEl.setAttribute('poster', uri);
          }).catch(function () {});
        }
      }

      box.appendChild(mediaEl);

      var titleEl = document.createElement('div');
      titleEl.className = 'preview-media-title';
      titleEl.textContent = name;
      box.appendChild(titleEl);

      ipart.appendChild(box);

      if (ipreviewText) {
        clearElement(ipreviewText);
        ipreviewText.textContent = '';
        ipreviewText.hidden = true;
      }
    }

    function renderFolderPreview(item, name) {
      clearElement(ipart);

      var box = document.createElement('div');
      box.className = 'preview-folder-box';

      var iconWrap = document.createElement('div');
      iconWrap.className = 'preview-folder-icon';
      var srcSvg = item ? item.querySelector('.thumb svg, .rico svg, .ricobox svg, svg') : null;
      if (srcSvg) {
        iconWrap.appendChild(srcSvg.cloneNode(true));
      } else {
        iconWrap.appendChild(createFolderIcon());
      }
      box.appendChild(iconWrap);

      var nameEl = document.createElement('div');
      nameEl.className = 'preview-folder-name';
      nameEl.textContent = name;
      box.appendChild(nameEl);

      var countText = item ? (item.getAttribute('data-contents') ||
                              item.getAttribute('data-items') ||
                              item.getAttribute('data-s') ||
                              'Folder') : 'Folder';
      var countEl = document.createElement('div');
      countEl.className = 'preview-folder-count';
      countEl.textContent = countText;
      box.appendChild(countEl);

      ipart.appendChild(box);

      if (ipreviewText) {
        clearElement(ipreviewText);
        ipreviewText.textContent = '';
        ipreviewText.hidden = true;
      }
    }

    function renderTextPreview(item, name, path, previewData, token) {
      clearElement(ipart);
      var srcSvg = item ? item.querySelector('.thumb svg, .rico svg, .ricobox svg, svg') : null;
      if (srcSvg) {
        ipart.appendChild(srcSvg.cloneNode(true));
      } else {
        ipart.appendChild(createFileIcon());
      }

      if (ipreviewText) {
        clearElement(ipreviewText);
        ipreviewText.hidden = false;

        var pre = document.createElement('pre');
        pre.className = 'preview-text-box';
        var code = document.createElement('code');
        pre.appendChild(code);
        ipreviewText.appendChild(pre);

        // Source gets coloured, prose does not. The reference has a separate
        // CodePreview control for exactly this split, and a wall of one colour
        // is the thing that made this pane read as a text dump.
        var paint = function (text) {
          if (window.__isCodeName && window.__isCodeName(name)
              && window.__highlightCode) {
            while (code.firstChild) code.removeChild(code.firstChild);
            window.__highlightCode(code, text, name);
          } else {
            code.textContent = text;
          }
        };

        if (previewData) {
          paint(previewData);
          return;
        }

        code.textContent = 'Loading preview...';

        fetchPreviewContent(path, item).then(function (content) {
          if (token !== currentPreviewToken) return;
          if (content) paint(content);
          else code.textContent = 'No preview available.';
        }).catch(function () {
          if (token !== currentPreviewToken) return;
          code.textContent = 'Failed to load preview.';
        });
      }
    }

    //: HTML and rich text follow the markdown renderer's shape exactly: the
    //: item's own icon, then the document, with the fetch guarded by the
    //: preview token so a slow file cannot paint over a later selection.
    function renderRichPreview(item, name, path, previewData, token, paint) {
      clearElement(ipart);
      var srcSvg = item ? item.querySelector('.thumb svg, .rico svg, .ricobox svg, svg') : null;
      if (srcSvg) ipart.appendChild(srcSvg.cloneNode(true));
      else ipart.appendChild(createFileIcon());
      if (!ipreviewText) return;
      clearElement(ipreviewText);
      ipreviewText.hidden = false;
      var box = document.createElement('div');
      box.className = 'preview-rich-box';
      ipreviewText.appendChild(box);
      if (previewData) { paint(box, previewData); return; }
      var notice = document.createElement('p');
      notice.textContent = 'Loading preview...';
      box.appendChild(notice);
      fetchPreviewContent(path, item).then(function (content) {
        if (token !== currentPreviewToken) return;
        clearElement(box);
        if (!content) {
          var e0 = pvEl('p');
          e0.textContent = 'This file is empty.';
          box.appendChild(e0);
          return;
        }
        paint(box, content);
      }).catch(function () {
        if (token !== currentPreviewToken) return;
        clearElement(box);
        var e1 = pvEl('p');
        e1.textContent = 'Preview is not available.';
        box.appendChild(e1);
      });
    }

    function renderHtmlPreview(item, name, path, previewData, token) {
      renderRichPreview(item, name, path, previewData, token,
        function (box, text) {
          box.classList.add('pv-html');
          window.__previewRich.html(box, text, name);
        });
    }

    function renderRichTextPreview(item, name, path, previewData, token) {
      renderRichPreview(item, name, path, previewData, token,
        function (box, text) {
          box.classList.add('pv-rtf');
          window.__previewRich.rtf(box, text);
        });
    }

    function renderMarkdownPreview(item, name, path, previewData, token) {
      clearElement(ipart);
      var srcSvg = item ? item.querySelector('.thumb svg, .rico svg, .ricobox svg, svg') : null;
      if (srcSvg) {
        ipart.appendChild(srcSvg.cloneNode(true));
      } else {
        ipart.appendChild(createFileIcon());
      }

      if (ipreviewText) {
        clearElement(ipreviewText);
        ipreviewText.hidden = false;

        var mdBox = document.createElement('div');
        mdBox.className = 'preview-markdown-box';
        ipreviewText.appendChild(mdBox);

        if (previewData) {
          renderMarkdownToDom(previewData, mdBox);
          return;
        }

        var loadingNotice = document.createElement('p');
        loadingNotice.textContent = 'Loading markdown preview...';
        mdBox.appendChild(loadingNotice);

        fetchPreviewContent(path, item).then(function (content) {
          if (token !== currentPreviewToken) return;
          renderMarkdownToDom(content || 'Empty markdown file.', mdBox);
        }).catch(function () {
          if (token !== currentPreviewToken) return;
          renderMarkdownToDom('Failed to load markdown preview.', mdBox);
        });
      }
    }

    function fetchPreviewContent(path, item) {
      if (typeof customFetchPreview === 'function') {
        return customFetchPreview(path, item);
      }
      if (typeof window !== 'undefined' && typeof window.__fetchPreview === 'function') {
        return window.__fetchPreview(path);
      }
      if (typeof fetch === 'function' && path) {
        return fetch('/api/preview?path=' + encodeURIComponent(path))
          .then(function (res) {
            if (!res.ok) throw new Error('Preview fetch status ' + res.status);
            return res.json();
          })
          .then(function (data) {
            if (data && !data.binary && typeof data.text === 'string') {
              return data.text;
            }
            return '';
          });
      }
      return Promise.resolve('');
    }

    function renderPreview(explicitItem) {
      currentPreviewToken++;
      var token = currentPreviewToken;

      var selected = [];
      if (explicitItem) {
        selected = [explicitItem];
      } else {
        selected = getSelectedItems(fileArea);
      }

      if (selected.length === 0) {
        renderEmptyState('Select a file to preview');
        return;
      }

      if (selected.length > 1) {
        renderEmptyState('Select a file to preview', selected.length + ' items selected');
        return;
      }

      var item = selected[0];
      var name = item.getAttribute('data-n') ||
                 item.getAttribute('data-name') ||
                 (item.querySelector('.rname, .name, .cname, .gname, .title') ?
                  item.querySelector('.rname, .name, .cname, .gname, .title').textContent.trim() :
                  '');

      var kind = item.getAttribute('data-k') ||
                 item.getAttribute('data-kind') ||
                 item.getAttribute('data-type') ||
                 '';

      var path = item.getAttribute('data-p') ||
                 item.getAttribute('data-path') ||
                 name;

      var previewData = item.getAttribute('data-pv') ||
                        item.getAttribute('data-preview') ||
                        '';

      var fileType = detectFileType(name, kind);

      //: A rendered document sets its own typography per block, so the
      //: monospace and the pre-wrap that plain text needs come off for it and
      //: go back on for everything else.
      if (ipreviewText) {
        ipreviewText.classList.toggle(
          'pv-rich', fileType === 'html' || fileType === 'richtext');
      }

      if (fileType === 'folder') {
        renderFolderPreview(item, name);
      } else if (fileType === 'image') {
        renderImagePreview(item, name, path);
      } else if (fileType === 'video') {
        renderMediaPreview(item, name, path, true);
      } else if (fileType === 'audio') {
        renderMediaPreview(item, name, path, false);
      } else if (fileType === 'pdf') {
        renderPagePreview(item, name, path, token);
      } else if (fileType === 'html') {
        renderHtmlPreview(item, name, path, previewData, token);
      } else if (fileType === 'richtext') {
        renderRichTextPreview(item, name, path, previewData, token);
      } else if (fileType === 'markdown') {
        renderMarkdownPreview(item, name, path, previewData, token);
      } else {
        renderTextPreview(item, name, path, previewData, token);
      }
    }

    function switchTab(tabName) {
      if (tabName !== 'details' && tabName !== 'preview') return;
      activeTab = tabName;

      if (tabName === 'details') {
        if (detailsTab) {
          detailsTab.classList.add('active', 'on');
          detailsTab.setAttribute('aria-selected', 'true');
        }
        if (previewTab) {
          previewTab.classList.remove('active', 'on');
          previewTab.setAttribute('aria-selected', 'false');
        }
        if (detailsView) {
          detailsView.hidden = false;
          detailsView.style.display = '';
        }
        if (previewView) {
          previewView.hidden = true;
          previewView.style.display = 'none';
        }
      } else {
        if (previewTab) {
          previewTab.classList.add('active', 'on');
          previewTab.setAttribute('aria-selected', 'true');
        }
        if (detailsTab) {
          detailsTab.classList.remove('active', 'on');
          detailsTab.setAttribute('aria-selected', 'false');
        }
        if (detailsView) {
          detailsView.hidden = true;
          detailsView.style.display = 'none';
        }
        if (previewView) {
          previewView.hidden = false;
          previewView.style.display = '';
        }
        renderPreview();
      }

      if (onTabChange) {
        onTabChange(tabName);
      }
    }

    function onDetailsTabClick(e) {
      if (e) e.preventDefault();
      switchTab('details');
    }

    function onPreviewTabClick(e) {
      if (e) e.preventDefault();
      switchTab('preview');
    }

    if (detailsTab) {
      detailsTab.addEventListener('click', onDetailsTabClick);
    }
    if (previewTab) {
      previewTab.addEventListener('click', onPreviewTabClick);
    }

    var selectionDebounceTimer = null;
    function schedulePreviewUpdate() {
      if (activeTab !== 'preview') return;
      if (selectionDebounceTimer) clearTimeout(selectionDebounceTimer);
      selectionDebounceTimer = setTimeout(function () {
        renderPreview();
      }, 30);
    }

    function onFileAreaClick(e) {
      schedulePreviewUpdate();
    }

    function onFileAreaKeyup(e) {
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown' ||
          e.key === 'ArrowLeft' || e.key === 'ArrowRight' ||
          e.key === 'Home' || e.key === 'End' ||
          e.key === 'PageUp' || e.key === 'PageDown' ||
          (e.ctrlKey && (e.key === 'a' || e.key === 'A'))) {
        schedulePreviewUpdate();
      }
    }

    fileArea.addEventListener('click', onFileAreaClick);
    fileArea.addEventListener('keyup', onFileAreaKeyup);

    var observer = null;
    if (typeof MutationObserver !== 'undefined') {
      observer = new MutationObserver(function (mutations) {
        for (var i = 0; i < mutations.length; i++) {
          var m = mutations[i];
          if (m.type === 'attributes' && (m.attributeName === 'class' || m.attributeName === 'aria-selected')) {
            schedulePreviewUpdate();
            break;
          }
        }
      });

      observer.observe(fileArea, {
        attributes: true,
        attributeFilter: ['class', 'aria-selected'],
        subtree: true
      });
    }

    var initialTab = options.defaultTab === 'preview' ? 'preview' : 'details';
    switchTab(initialTab);

    return {
      switchTab: switchTab,
      renderPreview: renderPreview,
      getActiveTab: function () { return activeTab; },
      getPane: function () { return pane; },
      getDetailsView: function () { return detailsView; },
      getPreviewView: function () { return previewView; },
      getIpart: function () { return ipart; },
      getIpreviewText: function () { return ipreviewText; },
      destroy: function () {
        if (detailsTab) detailsTab.removeEventListener('click', onDetailsTabClick);
        if (previewTab) previewTab.removeEventListener('click', onPreviewTabClick);
        fileArea.removeEventListener('click', onFileAreaClick);
        fileArea.removeEventListener('keyup', onFileAreaKeyup);
        if (observer) observer.disconnect();
        if (selectionDebounceTimer) clearTimeout(selectionDebounceTimer);
      }
    };
  }



