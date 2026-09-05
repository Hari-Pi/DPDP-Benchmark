"""HTTP API for the DPDP RAG chatbot.

Endpoints:
  GET  /health          -> liveness check
  GET  /                -> continuous chat web UI
  POST /ask             -> {"question": "...", "history": [...]} -> answer + sources
"""
import html
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import config, query

app = FastAPI(title="DPDP RAG", version="0.2.0",
              description="Q&A over the DPDP Act 2023 and DPDP Rules 2025")

MAX_HISTORY = 6


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[Message] = Field(default_factory=list, max_length=12)
    k: int = Field(default=config.TOP_K, ge=1, le=20)
    model: str = Field(default=config.CHAT_MODEL)


class Source(BaseModel):
    source: str
    unit: str


class AskResponse(BaseModel):
    question: str
    answer: str
    sources: list[Source]


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    history = [m.model_dump() for m in req.history[-MAX_HISTORY:]]
    answer_text, hits = query.answer(req.question, k=req.k, model=req.model,
                                     history=history)
    seen: list[Source] = []
    for h in hits:
        src = Source(source=h["meta"]["source"], unit=h["meta"]["unit"])
        if src not in seen:
            seen.append(src)
    return AskResponse(question=req.question, answer=answer_text, sources=seen)


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DPDP RAG Chat</title>
<style>
 body { font-family: -apple-system, "Segoe UI", sans-serif; margin: 0;
        background: #f5f6fa; color: #222; height: 100vh;
        display: flex; flex-direction: column; }
 header { background: #1a2a4a; color: #fff; padding: .7rem 1rem;
          display: flex; align-items: center; gap: .8rem; }
 header h1 { font-size: 1.05rem; margin: 0; flex: 1; }
 header button { background: transparent; border: 1px solid #5a6f9e;
                 color: #cdd8f0; border-radius: 6px; padding: .3rem .7rem;
                 cursor: pointer; font-size: .8rem; }
 header button:hover { background: #2a3f6e; }
 #chat { flex: 1; overflow-y: auto; padding: 1rem 0; }
 .msg { max-width: 780px; margin: 0 auto; padding: 0 1rem; display: flex; }
 .msg.user { justify-content: flex-end; }
 .bubble { border-radius: 12px; padding: .7rem 1rem; margin: .3rem 0;
           line-height: 1.55; white-space: pre-wrap; word-wrap: break-word; }
 .msg.user .bubble { background: #1a56db; color: #fff;
                     border-bottom-right-radius: 3px; max-width: 78%; }
 .msg.bot .bubble { background: #fff; border: 1px solid #e2e4ea;
                    border-bottom-left-radius: 3px; max-width: 90%; }
 .msg.bot .bubble p { margin: .4em 0; }
 .msg.bot .bubble ul, .msg.bot .bubble ol { margin: .4em 0; padding-left: 1.3em; }
 .msg.bot .bubble code { background: #eef1f6; border-radius: 3px; padding: 0 4px; }
 .srcs { margin-top: .55rem; font-size: .78rem; }
 .srcs span { display: inline-block; background: #eef2ff; color: #334;
              border-radius: 4px; padding: 2px 8px; margin: 2px 4px 2px 0; }
 form { display: flex; gap: .5rem; padding: .8rem 1rem;
        background: #fff; border-top: 1px solid #e2e4ea; }
 #q { flex: 1; padding: .65rem .8rem; font-size: 1rem;
      border: 1px solid #b9bfca; border-radius: 8px; }
 #q:focus { outline: 2px solid #1a56db33; border-color: #1a56db; }
 button.send { padding: .65rem 1.3rem; font-size: 1rem; border: 0;
               border-radius: 8px; background: #1a56db; color: #fff;
               cursor: pointer; }
 button.send:disabled { background: #9db6e8; cursor: wait; }
 footer { text-align: center; font-size: .72rem; color: #8a8f9a;
          padding: .3rem 0 .5rem; background: #fff; }
 #status { max-width: 780px; margin: 0 auto; padding: 0 1.2rem;
           color: #777; font-size: .85rem; height: 1.2em; }
</style>
</head>
<body>
<header>
 <h1>DPDP RAG &mdash; DPDP Act 2023 &amp; Rules 2025</h1>
 <button id="clear" onclick="clearChat()">Clear chat</button>
</header>
<div id="chat"></div>
<div id="status"></div>
<form id="f">
 <input id="q" type="text" autocomplete="off" autofocus
        placeholder="Ask about the DPDP Act or Rules&hellip;">
 <button class="send" id="send">Send</button>
</form>
<footer>Research prototype &mdash; general legal information, not legal advice.</footer>
<script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
<script>
const chatEl = document.getElementById('chat');
const qEl = document.getElementById('q');
const sendBtn = document.getElementById('send');
const statusEl = document.getElementById('status');
let history = [];   // [{role, content}] — plain text, last few turns sent up

function addMsg(role, text, sources) {
  const wrap = document.createElement('div');
  wrap.className = 'msg ' + (role === 'user' ? 'user' : 'bot');
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  if (role === 'user') {
    bubble.textContent = text;
  } else {
    bubble.innerHTML = DOMPurify.sanitize(marked.parse(text));
    if (sources && sources.length) {
      const s = document.createElement('div');
      s.className = 'srcs';
      sources.forEach(x => {
        const t = document.createElement('span');
        t.textContent = x.source + ', ' + x.unit;
        s.appendChild(t);
      });
      bubble.appendChild(s);
    }
  }
  wrap.appendChild(bubble);
  chatEl.appendChild(wrap);
  chatEl.scrollTop = chatEl.scrollHeight;
  return bubble;
}

async function ask(e) {
  e.preventDefault();
  const q = qEl.value.trim();
  if (!q || sendBtn.disabled) return;
  qEl.value = '';
  addMsg('user', q);
  sendBtn.disabled = true;
  statusEl.textContent = 'Thinking\u2026';
  try {
    const r = await fetch('/ask', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: q, history: history})});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    addMsg('assistant', d.answer, d.sources);
    history.push({role: 'user', content: q},
                 {role: 'assistant', content: d.answer});
    history = history.slice(-6);
  } catch (err) {
    addMsg('assistant', '**Error:** ' + err.message +
      ' — is the server running?');
  } finally {
    statusEl.textContent = '';
    sendBtn.disabled = false;
    qEl.focus();
  }
}

function clearChat() {
  history = [];
  chatEl.innerHTML = '';
  addMsg('assistant',
    "Namaste! Ask me anything about India's DPDP Act 2023 or the DPDP " +
    "Rules 2025 — notices, consent, breach reporting, penalties, the Data " +
    "Protection Board, children's data, commencement timelines\u2026 " +
    "I answer only from the official gazette texts and cite every claim.");
}

document.getElementById('f').addEventListener('submit', ask);
clearChat();
qEl.focus();
</script>
</body>
</html>
"""
