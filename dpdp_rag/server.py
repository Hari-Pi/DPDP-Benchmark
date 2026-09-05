"""HTTP API for the DPDP RAG chatbot.

Endpoints:
  GET  /health          -> liveness check (always open)
  GET  /                -> continuous chat web UI (static/index.html)
  POST /ask             -> {"question": "...", "history": [...]} -> answer + sources

Access control: if the DPDP_TOKEN environment variable is set, /ask requires
that token (X-DPDP-Token header or ?token= query). Unset = local-only mode.
"""
import os
import secrets
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, query

app = FastAPI(title="DPDP RAG", version="0.3.1",
              description="Q&A over the DPDP Act 2023 and DPDP Rules 2025")

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

MAX_HISTORY = 6
TOKEN = os.environ.get("DPDP_TOKEN", "").strip()


def check_token(request: Request) -> None:
    """Reject /ask calls when a public token is configured and not presented."""
    if not TOKEN:
        return
    given = (request.headers.get("X-DPDP-Token")
             or request.query_params.get("token") or "")
    if not secrets.compare_digest(given, TOKEN):
        raise HTTPException(status_code=401, detail="invalid or missing token")


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


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/auth/check")
def auth_check() -> dict:
    """Open endpoint so the web UI knows whether to ask for a token."""
    return {"token_required": bool(TOKEN)}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, request: Request) -> AskResponse:
    check_token(request)
    history = [m.model_dump() for m in req.history[-MAX_HISTORY:]]
    answer_text, hits = query.answer(req.question, k=req.k, model=req.model,
                                     history=history)
    seen: list[Source] = []
    for h in hits:
        src = Source(source=h["meta"]["source"], unit=h["meta"]["unit"])
        if src not in seen:
            seen.append(src)
    return AskResponse(question=req.question, answer=answer_text, sources=seen)
