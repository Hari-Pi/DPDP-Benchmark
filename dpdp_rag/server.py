"""HTTP API for the DPDP RAG chatbot.

Endpoints:
  GET  /health          -> liveness check (always open)
  GET  /                -> continuous chat web UI (static/index.html)
  POST /ask             -> {"question": "...", "history": [...]} -> answer + sources
  GET  /auth/check      -> {auth_required, authenticated}
  POST /auth/login      -> {username, password} -> session cookie
  POST /auth/logout     -> revokes the session

Access control: when DPDP_USER + DPDP_AUTH_SALT + DPDP_AUTH_HASH are set
(via scripts/hash_auth.py), /ask requires a valid session cookie minted by
/auth/login. Unset = local-only mode.
"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, config, query

app = FastAPI(title="DPDP RAG", version="0.4.0",
              description="Q&A over the DPDP Act 2023 and DPDP Rules 2025")

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

MAX_HISTORY = 6
COOKIE = "dpdp_session"


def client_ip(request: Request) -> str:
    # Behind Cloudflare the real client IP arrives in CF-Connecting-IP.
    return (request.headers.get("CF-Connecting-IP")
            or (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown"))


def session_token(request: Request, dpdp_session: str | None) -> str:
    return request.headers.get("X-DPDP-Session") or dpdp_session or ""


def check_auth(request: Request, dpdp_session: str | None) -> None:
    """Reject /ask calls when auth is enabled and no live session is present."""
    if not auth.AUTH_ENABLED:
        return
    if not auth.session_valid(session_token(request, dpdp_session)):
        raise HTTPException(status_code=401, detail="not authenticated")


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
def auth_check(request: Request, dpdp_session: str | None = Cookie(default=None)) -> dict:
    """Open endpoint so the web UI knows whether to show the login dialog."""
    return {
        "auth_required": auth.AUTH_ENABLED,
        "authenticated": auth.AUTH_ENABLED and auth.session_valid(
            session_token(request, dpdp_session)),
    }


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@app.post("/auth/login")
def login(body: LoginRequest, request: Request, response: Response) -> dict:
    ip = client_ip(request)
    allowed, retry_in = auth.login_allowed(ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"too many failed attempts — try again in {retry_in // 60 + 1} min")
    if not auth.verify_credentials(body.username, body.password):
        auth.login_failed(ip)
        # uniform delay blunts username-enumeration timing probes
        raise HTTPException(status_code=401, detail="invalid username or password")
    auth.login_reset(ip)
    token = auth.create_session()
    secure = (request.url.scheme == "https"
              or request.headers.get("X-Forwarded-Proto") == "https")
    response.set_cookie(
        COOKIE, token, max_age=int(auth.SESSION_TTL.total_seconds()),
        httponly=True, samesite="lax", secure=secure, path="/")
    return {"ok": True}


@app.post("/auth/logout")
def logout(request: Request, response: Response,
           dpdp_session: str | None = Cookie(default=None)) -> dict:
    auth.revoke_session(session_token(request, dpdp_session))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, request: Request,
        dpdp_session: str | None = Cookie(default=None)) -> AskResponse:
    check_auth(request, dpdp_session)
    history = [m.model_dump() for m in req.history[-MAX_HISTORY:]]
    answer_text, hits = query.answer(req.question, k=req.k, model=req.model,
                                     history=history)
    seen: list[Source] = []
    for h in hits:
        src = Source(source=h["meta"]["source"], unit=h["meta"]["unit"])
        if src not in seen:
            seen.append(src)
    return AskResponse(question=req.question, answer=answer_text, sources=seen)
