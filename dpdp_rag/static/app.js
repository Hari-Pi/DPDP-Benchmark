/* DPDP RAG — chat client.
   Submits durable jobs to the Droidian coordinator and polls until the
   connected Colab worker returns an answer. */
'use strict';

const DEFAULTS = { k: 8, model: 'qwen2.5:7b-instruct' };
const MAX_HISTORY = 6;          // must match MAX_HISTORY on the server

const $ = (id) => document.getElementById(id);
const chatEl = $('chat');
const scroller = $('scroller');
const qEl = $('q');
const formEl = $('f');
const sendBtn = $('send');
const sendIcon = $('sendIcon');
const sendSpinner = $('sendSpinner');
const toBottomBtn = $('toBottom');

let history = [];               // [{role, content}] — trimmed to the last few turns
let busy = false;

/* ------------------------------------------------------------- sign in/out */

const loginModal = $('loginModal');
const loginError = $('loginError');
const loginRate = $('loginRate');
const loginUser = $('loginUser');
const loginPass = $('loginPass');
const loginBtn = $('loginBtn');

function openLogin(rejected, rateMsg) {
  loginError.classList.toggle('hidden', !rejected);
  loginRate.classList.toggle('hidden', !rateMsg);
  loginRate.textContent = rateMsg || '';
  loginUser.value = '';
  loginPass.value = '';
  loginModal.showModal();
  loginUser.focus();
}

let authRequired = false;

/** /auth/check is open and tells us whether the server is in auth mode and
    whether the current session cookie is still live. */
async function checkAuth() {
  try {
    const res = await fetch('/auth/check', { cache: 'no-store' });
    const d = await res.json();
    authRequired = !!d.auth_required;
    if (authRequired && !d.authenticated) openLogin(false);
  } catch (e) { /* offline — the status pill already shows it */ }
}

$('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const username = loginUser.value.trim();
  const password = loginPass.value;
  if (!username || !password || loginBtn.disabled) return;
  loginBtn.disabled = true;
  loginBtn.textContent = 'Signing in…';
  loginError.classList.add('hidden');
  loginRate.classList.add('hidden');
  try {
    const res = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username, password: password }),
    });
    if (res.ok) {
      loginModal.close();
      toast('Signed in');
      return;
    }
    let detail = 'Invalid username or password.';
    try { const b = await res.json(); if (b && b.detail) detail = b.detail; } catch (err) {}
    if (res.status === 429) openLogin(false, detail);
    else { loginError.textContent = detail; openLogin(true); }
  } catch (err) {
    openLogin(false, 'Network error — is the server reachable?');
  } finally {
    loginBtn.disabled = false;
    loginBtn.textContent = 'Sign in';
  }
});

$('logoutBtn').addEventListener('click', async () => {
  try { await fetch('/auth/logout', { method: 'POST' }); } catch (e) {}
  $('settings').removeAttribute('open');
  if (authRequired) openLogin(false);
  toast('Signed out');
});

/* ------------------------------------------------------------------ theme */

function applyTheme(dark) {
  document.documentElement.setAttribute('data-theme', dark ? 'night' : 'winter');
  $('themeToggle').checked = dark;
  try { localStorage.setItem('dpdp.theme', dark ? 'dark' : 'light'); } catch (e) {}
}

$('themeToggle').addEventListener('change', (e) => applyTheme(e.target.checked));
$('themeToggle').checked =
  document.documentElement.getAttribute('data-theme') === 'night';

/* --------------------------------------------------------------- settings */

const settings = { ...DEFAULTS };

function loadSettings() {
  try {
    const raw = localStorage.getItem('dpdp.settings');
    if (raw) Object.assign(settings, JSON.parse(raw));
  } catch (e) {}
  settings.k = Math.min(20, Math.max(1, Number(settings.k) || DEFAULTS.k));
  if (!settings.model) settings.model = DEFAULTS.model;
  $('kRange').value = settings.k;
  $('kVal').textContent = settings.k;
  $('modelInput').value = settings.model;
}

function saveSettings() {
  try { localStorage.setItem('dpdp.settings', JSON.stringify(settings)); } catch (e) {}
}

$('kRange').addEventListener('input', (e) => {
  settings.k = Number(e.target.value);
  $('kVal').textContent = settings.k;
  saveSettings();
});
$('modelInput').addEventListener('change', (e) => {
  settings.model = e.target.value.trim() || DEFAULTS.model;
  e.target.value = settings.model;
  saveSettings();
});
$('resetSettings').addEventListener('click', () => {
  Object.assign(settings, DEFAULTS);
  saveSettings();
  loadSettings();
  toast('Settings reset');
});

/* ----------------------------------------------------------------- toasts */

function toast(message, kind) {
  const el = document.createElement('div');
  el.className = 'alert alert-' + (kind || 'success') + ' rise py-2 text-sm shadow-lg';
  el.setAttribute('role', 'status');
  el.textContent = message;
  $('toasts').appendChild(el);
  setTimeout(() => el.remove(), 2600);
}

/* ------------------------------------------------------------- rendering */

const CITE_RE =
  /\((?:Draft\s+)?(?:DPDP|G\.?S\.?R\.?)[^()]*(?:\([^()]*\)[^()]*)*\)/g;

/** Wrap statutory citations found in answer prose in a chip, leaving code alone. */
function decorateCitations(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (node.parentElement.closest('code, pre, a, .cite')) {
        return NodeFilter.FILTER_REJECT;
      }
      CITE_RE.lastIndex = 0;
      return CITE_RE.test(node.nodeValue)
        ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    },
  });
  const targets = [];
  while (walker.nextNode()) targets.push(walker.currentNode);

  for (const node of targets) {
    const frag = document.createDocumentFragment();
    let last = 0;
    node.nodeValue.replace(CITE_RE, (match, offset) => {
      if (offset > last) {
        frag.appendChild(document.createTextNode(node.nodeValue.slice(last, offset)));
      }
      const chip = document.createElement('span');
      chip.className = 'cite';
      chip.textContent = match;
      frag.appendChild(chip);
      last = offset + match.length;
      return match;
    });
    frag.appendChild(document.createTextNode(node.nodeValue.slice(last)));
    node.parentNode.replaceChild(frag, node);
  }
}

function renderMarkdown(text) {
  const el = document.createElement('div');
  el.className = 'answer';
  el.innerHTML = DOMPurify.sanitize(marked.parse(text, { breaks: true }));
  el.querySelectorAll('a').forEach((a) => {
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
  });
  decorateCitations(el);
  return el;
}

function icon(paths, cls) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.8');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('class', cls || 'size-4');
  for (const d of paths) {
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', d);
    svg.appendChild(p);
  }
  return svg;
}

const ICON_SHIELD = ['M12 3l7 3v5.5c0 4.3-2.9 8.2-7 9.5-4.1-1.3-7-5.2-7-9.5V6l7-3z',
                     'M9 12.2l2.1 2.1L15.2 10'];
const ICON_COPY = ['M9 9h9a1.5 1.5 0 011.5 1.5v9A1.5 1.5 0 0118 21H9a1.5 1.5 0 01-1.5-1.5v-9A1.5 1.5 0 019 9z',
                   'M5.5 15A1.5 1.5 0 014 13.5v-9A1.5 1.5 0 015.5 3h9A1.5 1.5 0 0116 4.5V6'];
const ICON_REFRESH = ['M20 12a8 8 0 10-2.6 5.9', 'M20 6v5h-5'];
const ICON_DOC = ['M14 3H7a1.8 1.8 0 00-1.8 1.8v14.4A1.8 1.8 0 007 21h10a1.8 1.8 0 001.8-1.8V8L14 3z',
                  'M14 3v5h4.8'];

/** Assistant avatar bubble. */
function botAvatar() {
  const a = document.createElement('div');
  a.className = 'grid size-8 shrink-0 place-items-center rounded-lg bg-primary/12 ' +
                'text-primary border border-primary/25';
  a.appendChild(icon(ICON_SHIELD, 'size-[1.05rem]'));
  return a;
}

function addUserMessage(text) {
  const row = document.createElement('div');
  row.className = 'rise flex justify-end';
  const bubble = document.createElement('div');
  bubble.className = 'max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md ' +
                     'bg-primary px-4 py-2.5 text-[0.95rem] leading-relaxed text-primary-content shadow-sm';
  bubble.textContent = text;
  row.appendChild(bubble);
  chatEl.appendChild(row);
  return row;
}

/** Group sources by document so a long citation list stays readable. */
function sourcesBlock(sources) {
  const groups = new Map();
  for (const s of sources) {
    if (!groups.has(s.source)) groups.set(s.source, []);
    const units = groups.get(s.source);
    if (!units.includes(s.unit)) units.push(s.unit);
  }

  const wrap = document.createElement('details');
  wrap.className = 'group mt-4 rounded-xl border border-base-300 bg-base-200/60';

  const summary = document.createElement('summary');
  summary.className = 'flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs ' +
                      'font-medium text-base-content/70 transition hover:text-base-content';
  summary.appendChild(icon(ICON_DOC, 'size-3.5'));
  const label = document.createElement('span');
  label.textContent = 'Sources — ' + sources.length + ' passage' +
                      (sources.length === 1 ? '' : 's') + ' from ' +
                      groups.size + ' document' + (groups.size === 1 ? '' : 's');
  summary.appendChild(label);
  const caret = icon(['M6 9l6 6 6-6'], 'ml-auto size-3.5 transition group-open:rotate-180');
  summary.appendChild(caret);
  wrap.appendChild(summary);

  const body = document.createElement('div');
  body.className = 'space-y-2.5 border-t border-base-300 px-3 py-3';
  for (const [doc, units] of groups) {
    const line = document.createElement('div');
    const title = document.createElement('p');
    title.className = 'text-xs font-semibold text-base-content/80';
    title.textContent = doc;
    line.appendChild(title);
    const chips = document.createElement('div');
    chips.className = 'mt-1 flex flex-wrap gap-1.5';
    for (const u of units) {
      const chip = document.createElement('span');
      chip.className = 'badge badge-sm border-primary/25 bg-primary/10 font-mono ' +
                       'text-[0.7rem] text-primary';
      chip.textContent = u;
      chips.appendChild(chip);
    }
    line.appendChild(chips);
    body.appendChild(line);
  }
  wrap.appendChild(body);
  return wrap;
}

function actionButton(label, paths, onClick, extraClass) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'btn btn-ghost btn-xs gap-1 text-base-content/55 hover:text-base-content' +
                (extraClass ? ' ' + extraClass : '');
  b.appendChild(icon(paths, 'size-3.5'));
  b.appendChild(document.createTextNode(label));
  b.addEventListener('click', onClick);
  return b;
}

/** Retry rewrites the last turn, so it may only ever sit on the newest one. */
function dropStaleRetryButtons() {
  chatEl.querySelectorAll('.js-retry').forEach((b) => b.remove());
}

/** Assistant card: avatar, markdown answer, sources, footer actions. */
function addAssistantMessage(text, sources, meta) {
  dropStaleRetryButtons();
  const row = document.createElement('div');
  row.className = 'rise flex gap-3';
  row.appendChild(botAvatar());

  const card = document.createElement('div');
  card.className = 'min-w-0 flex-1 rounded-2xl rounded-tl-md border border-base-300 ' +
                   'bg-base-100 px-4 py-3.5 shadow-sm';
  card.appendChild(renderMarkdown(text));

  if (sources && sources.length) card.appendChild(sourcesBlock(sources));

  const footer = document.createElement('div');
  footer.className = 'mt-3 flex items-center gap-1 border-t border-base-300/70 pt-2';
  footer.appendChild(actionButton('Copy', ICON_COPY, async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast('Answer copied');
    } catch (e) {
      toast('Could not copy', 'error');
    }
  }));
  if (meta && meta.question) {
    footer.appendChild(actionButton('Retry', ICON_REFRESH, () => {
      if (!busy) submitQuestion(meta.question, { replaceLast: true, dropTurn: true });
    }, 'js-retry'));
  }
  if (meta && meta.seconds) {
    const t = document.createElement('span');
    t.className = 'ml-auto text-[0.7rem] text-base-content/40';
    t.textContent = meta.seconds.toFixed(1) + 's';
    footer.appendChild(t);
  }
  card.appendChild(footer);

  row.appendChild(card);
  chatEl.appendChild(row);
  return row;
}

function addErrorMessage(message, question) {
  dropStaleRetryButtons();
  const row = document.createElement('div');
  row.className = 'rise flex gap-3';
  row.appendChild(botAvatar());
  const box = document.createElement('div');
  box.className = 'min-w-0 flex-1 rounded-2xl rounded-tl-md border border-error/40 ' +
                  'bg-error/12 px-4 py-3.5';
  const head = document.createElement('p');
  head.className = 'text-sm font-semibold text-error';
  head.textContent = 'Request failed';
  const detail = document.createElement('p');
  detail.className = 'mt-1 text-sm text-base-content/75';
  detail.textContent = message;
  const hint = document.createElement('p');
  hint.className = 'mt-2 text-xs text-base-content/55';
  hint.textContent = 'Check that the API server and Ollama are both running, then retry.';
  box.append(head, detail, hint);
  if (question) {
    const bar = document.createElement('div');
    bar.className = 'mt-2';
    bar.appendChild(actionButton('Retry', ICON_REFRESH, () => {
      if (!busy) submitQuestion(question, { replaceLast: true });
    }, 'js-retry'));
    box.appendChild(bar);
  }
  row.appendChild(box);
  chatEl.appendChild(row);
  return row;
}

/** Skeleton shown while the model retrieves and generates. */
function addPending() {
  const row = document.createElement('div');
  row.className = 'rise flex gap-3';
  row.appendChild(botAvatar());
  const card = document.createElement('div');
  card.className = 'min-w-0 flex-1 rounded-2xl rounded-tl-md border border-base-300 ' +
                   'bg-base-100 px-4 py-3.5 shadow-sm';
  const label = document.createElement('p');
  label.className = 'shimmer text-sm font-medium';
  label.textContent = 'Searching the gazette texts…';
  const bars = document.createElement('div');
  bars.className = 'mt-3 space-y-2';
  ['w-full', 'w-11/12', 'w-8/12'].forEach((w) => {
    const s = document.createElement('div');
    s.className = 'skeleton h-3 ' + w;
    bars.appendChild(s);
  });
  card.append(label, bars);
  row.appendChild(card);
  chatEl.appendChild(row);
  return row;
}

function pendingStatus(row, text) {
  const label = row && row.querySelector('p');
  if (label) label.textContent = text;
}

async function waitForJob(jobId, pending) {
  const deadline = Date.now() + 60 * 60 * 1000;
  while (Date.now() < deadline) {
    const res = await fetch('/api/jobs/' + encodeURIComponent(jobId), {
      cache: 'no-store',
    });
    if (res.status === 401) {
      openLogin(false);
      throw new Error('Please sign in to continue.');
    }
    if (!res.ok) throw new Error('Could not read job status (HTTP ' + res.status + ')');
    const job = await res.json();
    if (job.status === 'completed') return job;
    if (job.status === 'failed' || job.status === 'cancelled') {
      throw new Error(job.error || 'The request was ' + job.status + '.');
    }
    pendingStatus(pending, job.status === 'running'
      ? 'Colab worker is answering…'
      : 'Waiting for a Colab worker…');
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
  throw new Error('The request timed out while waiting for the worker.');
}

/* ------------------------------------------------------------ empty state */

const SUGGESTIONS = [
  { title: 'Notice requirements',
    q: 'What must a Data Fiduciary include in the notice given to a Data Principal?' },
  { title: 'Breach reporting',
    q: 'What are the timelines and contents for reporting a personal data breach to the Board?' },
  { title: 'Penalties',
    q: 'What is the maximum monetary penalty for failing to take reasonable security safeguards?' },
  { title: "Children's data",
    q: "What obligations apply to processing children's personal data, and are there exemptions?" },
];

const EXTRA_PROMPTS = [
  'Which provisions of the DPDP Act are in force today?',
  'Who is a Consent Manager and how do they register?',
  'What rights does a Data Principal have?',
  'What changed in the corrigendum G.S.R. 892(E)?',
];

function renderEmptyState() {
  const wrap = document.createElement('div');
  wrap.className = 'js-empty-state rise py-6 sm:py-10';

  const badge = document.createElement('div');
  badge.className = 'mb-4 inline-flex items-center gap-2 rounded-full border border-primary/25 ' +
                    'bg-primary/10 px-3 py-1 text-xs font-medium text-primary';
  badge.appendChild(icon(ICON_SHIELD, 'size-3.5'));
  badge.appendChild(document.createTextNode('Grounded in the official gazette texts'));

  const h = document.createElement('h2');
  h.className = 'font-serif-brand text-3xl font-semibold leading-tight tracking-tight sm:text-4xl';
  h.textContent = 'Ask anything about the DPDP Act and Rules.';

  const p = document.createElement('p');
  p.className = 'mt-3 max-w-xl text-[0.95rem] leading-relaxed text-base-content/60';
  p.textContent = 'Notices, consent, breach reporting, penalties, the Data Protection Board, ' +
                  "children's data, commencement timelines. Every claim is answered from the " +
                  'retrieved passages and cited down to the section or rule.';

  const grid = document.createElement('div');
  grid.className = 'mt-7 grid gap-3 sm:grid-cols-2';
  for (const s of SUGGESTIONS) {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'group rounded-xl border border-base-300 bg-base-100/80 p-4 text-left ' +
                     'focus-ring shadow-sm transition hover:-translate-y-0.5 ' +
                     'hover:border-primary/40 hover:shadow-md';
    const t = document.createElement('p');
    t.className = 'flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-primary';
    t.textContent = s.title;
    const d = document.createElement('p');
    d.className = 'mt-1.5 text-sm leading-snug text-base-content/75';
    d.textContent = s.q;
    card.append(t, d);
    card.addEventListener('click', () => submitQuestion(s.q));
    grid.appendChild(card);
  }

  const more = document.createElement('div');
  more.className = 'mt-4 flex flex-wrap gap-2';
  for (const q of EXTRA_PROMPTS) {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'btn btn-sm h-auto max-w-full whitespace-normal rounded-full px-3 py-1.5 ' +
                     'text-left font-normal border-base-content/12 bg-base-100/70 ' +
                     'text-base-content/70 hover:border-primary/45 hover:text-base-content';
    chip.textContent = q;
    chip.addEventListener('click', () => submitQuestion(q));
    more.appendChild(chip);
  }

  wrap.append(badge, h, p, grid, more);
  chatEl.appendChild(wrap);
}

/* --------------------------------------------------------------- scrolling */

function atBottom(slack) {
  return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < (slack || 80);
}

function scrollToBottom(smooth) {
  scroller.scrollTo({ top: scroller.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
}

scroller.addEventListener('scroll', () => {
  toBottomBtn.classList.toggle('hidden', atBottom(160));
});
toBottomBtn.addEventListener('click', () => scrollToBottom(true));

/* ------------------------------------------------------------------- asking */

function setBusy(state) {
  busy = state;
  sendBtn.disabled = state;
  sendIcon.classList.toggle('hidden', state);
  sendSpinner.classList.toggle('hidden', !state);
}

async function submitQuestion(question, opts) {
  question = (question || '').trim();
  if (!question || busy) return;
  opts = opts || {};

  if (opts.replaceLast) {
    // Drop the answer being replaced and the question that produced it. Only
    // the newest turn carries a Retry button, so this always lines up.
    if (chatEl.lastElementChild) chatEl.lastElementChild.remove();
    if (chatEl.lastElementChild) chatEl.lastElementChild.remove();
    // A failed turn was never recorded, so only a real answer is un-recorded
    // here — otherwise the retry would eat the preceding successful turn.
    if (opts.dropTurn) history = history.slice(0, -2);
  }
  const empty = chatEl.querySelector('.js-empty-state');
  if (empty) empty.remove();

  addUserMessage(question);

  const pending = addPending();
  scrollToBottom(true);
  setBusy(true);
  const started = performance.now();

  try {
    const res = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: question,
        history: history,
        k: settings.k,
        model: settings.model,
      }),
    });
    if (res.status === 401) {
      openLogin(false);
      throw new Error('Please sign in to continue.');
    }
    if (!res.ok) {
      let detail = 'HTTP ' + res.status + ' ' + res.statusText;
      try {
        const body = await res.json();
        if (body && body.detail) detail = typeof body.detail === 'string'
          ? body.detail : JSON.stringify(body.detail);
      } catch (e) {}
      throw new Error(detail);
    }
    const accepted = await res.json();
    if (!accepted.job_id) throw new Error('The coordinator did not return a job id.');
    pendingStatus(pending, 'Waiting for a Colab worker…');
    const data = await waitForJob(accepted.job_id, pending);
    pending.remove();
    addAssistantMessage(data.answer, data.sources, {
      question: question,
      seconds: (performance.now() - started) / 1000,
    });
    history.push({ role: 'user', content: question },
                 { role: 'assistant', content: data.answer });
    history = history.slice(-MAX_HISTORY);
  } catch (err) {
    pending.remove();
    addErrorMessage(err.message || String(err), question);
  } finally {
    setBusy(false);
    if (atBottom(400)) scrollToBottom(true);
    qEl.focus();
  }
}

/* -------------------------------------------------------------- composer */

/** The composer stays one row tall when empty, so the placeholder must fit on
    a single line at every width. */
function syncPlaceholder() {
  const w = window.innerWidth;
  qEl.placeholder = w < 420 ? 'Ask a question…'
    : w < 700 ? 'Ask about the DPDP Act…'
    : 'Ask about notices, consent, breach reporting, penalties, the Board…';
}

function autoGrow() {
  qEl.style.height = 'auto';
  // An empty textarea keeps its one-row height: scrollHeight would otherwise
  // count the wrapped placeholder and leave the composer permanently tall.
  qEl.style.height = qEl.value ? Math.min(qEl.scrollHeight, 176) + 'px' : '';
}

window.addEventListener('resize', () => { syncPlaceholder(); autoGrow(); });

qEl.addEventListener('input', autoGrow);
qEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    formEl.requestSubmit();
  }
});

formEl.addEventListener('submit', (e) => {
  e.preventDefault();
  const q = qEl.value;
  qEl.value = '';
  autoGrow();
  submitQuestion(q);
});

document.addEventListener('keydown', (e) => {
  const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
  if (e.key === '/' && !typing) {
    e.preventDefault();
    qEl.focus();
  } else if (e.key === 'Escape') {
    $('settings').removeAttribute('open');
  }
});

// Close the settings dropdown on an outside click.
document.addEventListener('click', (e) => {
  const s = $('settings');
  if (s.hasAttribute('open') && !s.contains(e.target)) s.removeAttribute('open');
});

$('clearBtn').addEventListener('click', () => {
  history = [];
  chatEl.innerHTML = '';
  renderEmptyState();
  scroller.scrollTop = 0;
  qEl.focus();
});

/* --------------------------------------------------------------- health */

async function pingHealth() {
  const dot = $('statusDot');
  const text = $('statusText');
  const pill = $('statusPill');
  try {
    const res = await fetch('/health', { cache: 'no-store' });
    if (!res.ok) throw new Error();
    dot.className = 'inline-block size-1.5 rounded-full bg-success';
    text.textContent = 'connected';
    pill.setAttribute('data-tip', 'API reachable');
  } catch (e) {
    dot.className = 'inline-block size-1.5 rounded-full bg-error';
    text.textContent = 'offline';
    pill.setAttribute('data-tip', 'API unreachable — is uvicorn running?');
  }
}

/* ----------------------------------------------------------------- start */

loadSettings();
renderEmptyState();
syncPlaceholder();
autoGrow();
qEl.focus();
pingHealth();
setInterval(pingHealth, 30000);
checkAuth();
