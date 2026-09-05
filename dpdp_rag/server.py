"""HTTP API for the DPDP RAG chatbot.

Endpoints:
  GET  /health          -> liveness check
  POST /ask             -> {"question": "..."}  -> answer + sources
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import config, query

app = FastAPI(title="DPDP RAG", version="0.1.0",
              description="Q&A over the DPDP Act 2023 and DPDP Rules 2025")

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>DPDP RAG</title>
<style>
 body { font-family: -apple-system, Segoe UI, sans-serif; max-width: 860px;
        margin: 2rem auto; padding: 0 1rem; color: #222; }
 h1 { font-size: 1.4rem; }
 form { display: flex; gap: .5rem; }
 input[type=text] { flex: 1; padding: .6rem .8rem; font-size: 1rem;
        border: 1px solid #999; border-radius: 6px; }
 button { padding: .6rem 1.2rem; font-size: 1rem; border: 0;
        border-radius: 6px; background: #1a56db; color: #fff; cursor: pointer; }
 #answer { margin-top: 1.5rem; white-space: pre-wrap; line-height: 1.5; }
 #sources { margin-top: 1rem; color: #555; font-size: .9rem; }
 .tag { display: inline-block; background: #eef; border-radius: 4px;
        padding: 2px 8px; margin: 2px 4px 2px 0; }
 #status { color: #777; }
</style>
</head>
<body>
<h1>DPDP RAG — DPDP Act 2023 &amp; Rules 2025</h1>
<form onsubmit="ask(event)">
 <input id="q" type="text" placeholder="Ask a question, e.g. What is the penalty for failing to report a breach?" autofocus>
 <button>Ask</button>
</form>
<div id="status"></div>
<div id="answer"></div>
<div id="sources"></div>
<script>
async function ask(e) {
  e.preventDefault();
  const q = document.getElementById('q').value.trim();
  if (!q) return;
  document.getElementById('status').textContent = 'Thinking...';
  document.getElementById('answer').textContent = '';
  document.getElementById('sources').innerHTML = '';
  try {
    const r = await fetch('/ask', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: q})});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    document.getElementById('status').textContent = '';
    document.getElementById('answer').textContent = d.answer;
    document.getElementById('sources').innerHTML =
      'Sources: ' + d.sources.map(s => `<span class="tag">${s.source}, ${s.unit}</span>`).join('');
  } catch (err) {
    document.getElementById('status').textContent = 'Error: ' + err.message;
  }
}
</script>
</body>
</html>"""


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
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
    answer_text, hits = query.answer(req.question, k=req.k, model=req.model)
    seen: list[Source] = []
    for h in hits:
        src = Source(source=h["meta"]["source"], unit=h["meta"]["unit"])
        if src not in seen:
            seen.append(src)
    return AskResponse(question=req.question, answer=answer_text, sources=seen)
