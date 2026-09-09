"""Persistent Droidian coordinator for the DPDP RAG service.

The coordinator owns the public UI, authentication boundary, and durable job
queue. A later Colab worker will claim queued jobs over the internal worker
protocol and write answers back; no public Colab URL is required.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
from pathlib import Path
from typing import Literal

from fastapi import Cookie, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi import WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, config
from .job_store import JobStore

STATIC_DIR = Path(__file__).resolve().parent / "static"
DB_PATH = Path(os.environ.get("DPDP_COORDINATOR_DB", "/data/dpdp-coordinator.sqlite3"))
ARTIFACT_DIR = Path(os.environ.get("DPDP_ARTIFACT_DIR", "/data/artifacts/current"))
WORKER_TOKEN = os.environ.get("DPDP_WORKER_TOKEN", "")
MAX_HISTORY = 6
COOKIE = "dpdp_session"

app = FastAPI(
    title="DPDP RAG Coordinator",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
store = JobStore(DB_PATH)
connected_workers: dict[str, str] = {}


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class JobRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[Message] = Field(default_factory=list, max_length=12)
    k: int = Field(default=config.TOP_K, ge=1, le=20)
    model: str = Field(default=config.CHAT_MODEL)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def _token(request: Request, cookie: str | None) -> str:
    return request.headers.get("X-DPDP-Session") or cookie or ""


def _client_ip(request: Request) -> str:
    return (request.headers.get("CF-Connecting-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown"))


def _check_auth(request: Request, cookie: str | None) -> None:
    if auth.AUTH_ENABLED and not auth.session_valid(_token(request, cookie)):
        raise HTTPException(status_code=401, detail="not authenticated")


def _worker_token(request: Request) -> str:
    value = request.headers.get("Authorization", "")
    if value.lower().startswith("bearer "):
        return value[7:]
    return request.headers.get("X-DPDP-Worker-Token", "")


def _worker_allowed(token: str) -> bool:
    return bool(WORKER_TOKEN) and secrets.compare_digest(token, WORKER_TOKEN)


def _job_response(job: dict) -> dict:
    return {
        "job_id": job["id"],
        "status": job["status"],
        "question": job["question"],
        "answer": job.get("answer"),
        "sources": job.get("sources", []),
        "error": job.get("error"),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    counts = store.counts()
    worker_types = {
        kind: sum(1 for value in connected_workers.values() if value == kind)
        for kind in ("pc", "colab")
    }
    return {"status": "ok", "coordinator": "ready", "jobs": counts,
            "workers": len(connected_workers), "worker_types": worker_types}


@app.get("/auth/check")
def auth_check(request: Request,
               dpdp_session: str | None = Cookie(default=None)) -> dict:
    return {
        "auth_required": auth.AUTH_ENABLED,
        "authenticated": auth.AUTH_ENABLED and auth.session_valid(
            _token(request, dpdp_session)),
    }


@app.post("/auth/login")
def login(body: LoginRequest, request: Request, response: Response) -> dict:
    ip = _client_ip(request)
    allowed, retry_in = auth.login_allowed(ip)
    if not allowed:
        raise HTTPException(status_code=429,
                            detail=f"too many failed attempts; retry in {retry_in}s")
    if not auth.verify_credentials(body.username, body.password):
        auth.login_failed(ip)
        raise HTTPException(status_code=401, detail="invalid username or password")
    auth.login_reset(ip)
    token = auth.create_session()
    secure = request.url.scheme == "https" or request.headers.get(
        "X-Forwarded-Proto") == "https"
    response.set_cookie(COOKIE, token,
                        max_age=int(auth.SESSION_TTL.total_seconds()),
                        httponly=True, samesite="lax", secure=secure, path="/")
    return {"ok": True}


@app.post("/auth/logout")
def logout(request: Request, response: Response,
           dpdp_session: str | None = Cookie(default=None)) -> dict:
    auth.revoke_session(_token(request, dpdp_session))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.post("/api/jobs", status_code=202)
def submit_job(body: JobRequest, request: Request,
               dpdp_session: str | None = Cookie(default=None)) -> dict:
    _check_auth(request, dpdp_session)
    job = store.create(
        question=body.question,
        history=[message.model_dump() for message in body.history[-MAX_HISTORY:]],
        k=body.k,
        model=body.model,
    )
    return _job_response(job)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, request: Request,
            dpdp_session: str | None = Cookie(default=None)) -> dict:
    _check_auth(request, dpdp_session)
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_response(job)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request,
               dpdp_session: str | None = Cookie(default=None)) -> dict:
    _check_auth(request, dpdp_session)
    job = store.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_response(job)


@app.post("/ask")
def compatibility_ask(body: JobRequest, request: Request,
                      dpdp_session: str | None = Cookie(default=None)) -> JSONResponse:
    """Queue legacy requests until the frontend is switched to job polling."""
    job = submit_job(body, request, dpdp_session)
    return JSONResponse(status_code=202, content={
        "detail": "queued; a Colab worker must connect to process this job",
        **job,
    })


@app.websocket("/internal/worker/ws")
async def worker_socket(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token", "")
    token = token or websocket.headers.get("authorization", "")
    if token.lower().startswith("bearer "):
        token = token[7:]
    token = token or websocket.headers.get("x-dpdp-worker-token", "")
    if not _worker_allowed(token):
        await websocket.close(code=4401, reason="worker authentication failed")
        return
    await websocket.accept()
    worker_id = ""
    worker_kind = "colab"
    try:
        hello = await asyncio.wait_for(websocket.receive_json(), timeout=15)
        if hello.get("type") != "hello" or not hello.get("worker_id"):
            await websocket.close(code=4400, reason="hello required")
            return
        worker_id = str(hello["worker_id"])[:128]
        worker_kind = str(hello.get("worker_kind", "colab")).lower()
        if worker_kind not in {"pc", "colab"}:
            await websocket.close(code=4400, reason="invalid worker kind")
            return
        connected_workers[worker_id] = worker_kind
        await websocket.send_json({
            "type": "ready", "worker_id": worker_id,
            "worker_kind": worker_kind,
        })
        while True:
            pc_available = any(
                kind == "pc" for wid, kind in connected_workers.items()
                if wid != worker_id
            )
            job = store.claim_next(
                worker_id, worker_kind=worker_kind,
                pc_available=pc_available,
            )
            if job is not None:
                await websocket.send_json({
                    "type": "job",
                    "job": {
                        "id": job["id"], "question": job["question"],
                        "history": job["history"], "k": job["k"],
                        "model": job["model"],
                    },
                })
                while True:
                    message = await asyncio.wait_for(
                        websocket.receive_json(), timeout=3600)
                    if message.get("type") == "heartbeat":
                        await websocket.send_json({"type": "heartbeat_ack"})
                        continue
                    if message.get("type") != "result" or message.get("job_id") != job["id"]:
                        continue
                    if message.get("error"):
                        if worker_kind == "pc":
                            store.retry_on_colab(job["id"], str(message["error"]))
                        else:
                            store.fail(job["id"], str(message["error"]))
                    else:
                        store.complete(
                            job["id"], answer=str(message.get("answer", "")),
                            sources=message.get("sources", []),
                        )
                    break
            else:
                await websocket.send_json({"type": "wait", "seconds": 20})
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(), timeout=30)
                    if message.get("type") == "heartbeat":
                        await websocket.send_json({"type": "heartbeat_ack"})
                except asyncio.TimeoutError:
                    continue
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    finally:
        if worker_id:
            connected_workers.pop(worker_id, None)
            store.requeue_worker(
                worker_id, pc_attempted=(worker_kind == "pc"))


@app.get("/internal/worker/artifact-manifest")
def artifact_manifest(request: Request) -> dict:
    if not _worker_allowed(_worker_token(request)):
        raise HTTPException(status_code=401, detail="worker authentication failed")
    files = []
    if ARTIFACT_DIR.is_dir():
        for path in sorted(p for p in ARTIFACT_DIR.rglob("*") if p.is_file()):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files.append({"path": str(path.relative_to(ARTIFACT_DIR)),
                          "sha256": digest, "bytes": path.stat().st_size})
    return {"version": os.environ.get("DPDP_ARTIFACT_VERSION", "none"),
            "files": files}


@app.get("/internal/worker/artifact/{relative_path:path}")
def artifact(relative_path: str, request: Request) -> FileResponse:
    if not _worker_allowed(_worker_token(request)):
        raise HTTPException(status_code=401, detail="worker authentication failed")
    candidate = (ARTIFACT_DIR / relative_path).resolve()
    if ARTIFACT_DIR.resolve() not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(candidate)
