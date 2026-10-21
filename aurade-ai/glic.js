// AuraDE's Glic page: the browser's Glic panel, answered by Gemma through the
// built-in Prompt API instead of by Gemini.
'use strict';

// The page's own nonce, which the Glic API script Chrome sends us must carry.
const NONCE = document.currentScript.nonce;
// About 3,000 tokens of page text. Reading a page is most of the wait for the
// first answer on a processor, about twice as long for twice the text, and
// the start of an article usually holds what is asked about it.
const TAB_TEXT_LIMIT = 12000;
const SYSTEM_PROMPT =
    'You are Gemma, a helpful assistant built into the AuraDE browser. You ' +
    'run on the user\'s own computer and cannot browse the web. When the ' +
    'user shares a web page, answer from it and say so when the page does ' +
    'not cover the question. Answer briefly unless asked for detail.';

// The answer languages the browser's built-in AI attests to; others fall back
// to English.
const LANGUAGES = ['de', 'en', 'es', 'fr', 'ja'];
const LANGUAGE = LANGUAGES.find((l) => navigator.language.startsWith(l)) || 'en';

const $ = (id) => document.getElementById(id);
let host = null;
let session = null;
// The tab whose text the session has already been given.
let sharedUrl = null;
let busy = null;

function showStatus(text) {
  $('status').hidden = !text;
  $('status').textContent = text || '';
}

// Text with **bold** and `code`, built as nodes so nothing the model writes
// is ever parsed as HTML.
function render(el, text) {
  el.replaceChildren();
  const parts = text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/);
  for (const part of parts) {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      const b = document.createElement('strong');
      b.textContent = part.slice(2, -2);
      el.append(b);
    } else if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      const c = document.createElement('code');
      c.textContent = part.slice(1, -1);
      el.append(c);
    } else {
      el.append(part);
    }
  }
}

function addMessage(kind, text, note) {
  $('welcome').hidden = true;
  const el = document.createElement('div');
  el.className = 'msg ' + kind;
  const body = document.createElement('span');
  render(body, text);
  el.append(body);
  if (note) {
    const n = document.createElement('span');
    n.className = 'context';
    n.textContent = note;
    el.append(n);
  }
  $('chat').append(el);
  el.scrollIntoView({block: 'end'});
  return body;
}

async function newSession() {
  session?.destroy();
  sharedUrl = null;
  session = await LanguageModel.create({
    initialPrompts: [{role: 'system', content: SYSTEM_PROMPT}],
    monitor(m) {
      m.addEventListener('downloadprogress', (e) => {
        showStatus('Loading Gemma... ' + Math.round(e.loaded * 100) + '%');
      });
    },
    expectedOutputs: [{type: 'text', languages: [LANGUAGE]}],
  });
}

async function tabText() {
  if (!host?.getContextFromFocusedTab) {
    return null;
  }
  const ctx = await host.getContextFromFocusedTab(
      {innerText: true, innerTextBytesLimit: TAB_TEXT_LIMIT});
  const doc = ctx.webPageData?.mainDocument;
  if (!doc?.innerText) {
    return null;
  }
  return {
    url: ctx.tabData.url,
    title: ctx.tabData.title || ctx.tabData.url,
    text: doc.innerText,
  };
}

async function buildPrompt(question) {
  if (!$('use-tab').checked) {
    return {prompt: question, note: null};
  }
  let page = null;
  try {
    page = await tabText();
  } catch (e) {
    // A page Chrome will not share, such as a settings page: answer anyway.
  }
  if (!page || page.url === sharedUrl) {
    return {prompt: question, note: null};
  }
  sharedUrl = page.url;
  return {
    prompt: 'The user is looking at this web page.\nTitle: ' + page.title +
        '\nAddress: ' + page.url + '\n<page>\n' + page.text +
        '\n</page>\n\n' + question,
    note: 'Read ' + page.title,
  };
}

async function ask(question) {
  addMessage('mine', question);
  const controller = new AbortController();
  busy = controller;
  $('send').hidden = true;
  $('stop').hidden = false;
  let answer = null;
  try {
    if (!session) {
      showStatus('Starting Gemma...');
      await newSession();
    }
    const {prompt, note} = await buildPrompt(question);
    showStatus(note ? 'Gemma is reading the page...' : 'Gemma is thinking...');
    answer = addMessage('', '', note);
    let text = '';
    const stream = session.promptStreaming(prompt, {signal: controller.signal});
    for await (const chunk of stream) {
      if (!text) {
        showStatus('');
      }
      text += chunk;
      render(answer, text);
      answer.parentElement.scrollIntoView({block: 'end'});
    }
    if (!text) {
      render(answer, 'Gemma had no answer.');
    }
  } catch (e) {
    if (e.name === 'AbortError') {
      if (answer && !answer.textContent) {
        render(answer, 'Stopped.');
      }
    } else if (e.name === 'QuotaExceededError') {
      session?.destroy();
      session = null;
      addMessage('error', 'This chat is longer than Gemma can hold. ' +
          'Ask again to start over with this question.');
    } else {
      addMessage('error', 'Gemma could not answer: ' + e.message);
    }
    answer?.parentElement.querySelector('.context')?.remove();
  } finally {
    busy = null;
    showStatus('');
    $('send').hidden = false;
    $('stop').hidden = true;
  }
}

function showFocusedTab(data) {
  const tab = data?.hasFocus?.tabData;
  $('tab-title').textContent = tab ? (tab.title || tab.url) : '';
}

// Until a page first asks for it with a click or a key, Chrome reports the
// model as downloadable even when its file is already on disk; asking from
// the send gesture is what loads it.
async function checkModel() {
  if (typeof LanguageModel === 'undefined') {
    showStatus('The browser\'s built-in AI is off. It needs the Advanced ' +
        'Plus AI profile and the aurade-ai package.');
    return false;
  }
  if (await LanguageModel.availability() === 'unavailable') {
    showStatus('Gemma is not available on this computer. It is ready after ' +
        'its download finishes and you sign in again.');
    return false;
  }
  showStatus('');
  return true;
}

const client = {
  async initialize(glicBrowserHost) {
    host = glicBrowserHost;
    host.getFocusedTabStateV2?.().subscribe(showFocusedTab);
  },
  async notifyPanelWillOpen() {
    $('question').focus();
    return {};
  },
  async notifyPanelWasClosed() {
    busy?.abort();
  },
  async checkResponsive() {},
};

// Chrome's Glic panel sends the API it implements as script source once the
// page has loaded. Only the panel itself may.
window.addEventListener('message', function onBoot(event) {
  if (event.origin !== 'chrome://glic' || !event.source) {
    return;
  }
  const message = event.data;
  if (message?.type !== 'glic-bootstrap' || !message.glicApiSource) {
    return;
  }
  window.removeEventListener('message', onBoot);
  const script = document.createElement('script');
  script.nonce = NONCE;
  script.text = message.glicApiSource;
  document.head.append(script);
  window.internalAutoGlicBoot(event.source).registerWebClient(client);
});

$('ask').addEventListener('submit', async (event) => {
  event.preventDefault();
  const question = $('question').value.trim();
  if (!question || busy || !(await checkModel())) {
    return;
  }
  $('question').value = '';
  ask(question);
});

$('question').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    $('ask').requestSubmit();
  }
});

$('stop').addEventListener('click', () => busy?.abort());

$('new-chat').addEventListener('click', () => {
  busy?.abort();
  session?.destroy();
  session = null;
  sharedUrl = null;
  for (const el of $('chat').querySelectorAll('.msg')) {
    el.remove();
  }
  $('welcome').hidden = false;
  $('question').focus();
});

checkModel();
