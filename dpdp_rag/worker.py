"""Outbound Colab worker for the persistent DPDP coordinator."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import uuid
from pathlib import Path

import requests
import websockets

COORDINATOR = os.environ.get(
    "DPDP_COORDINATOR_URL", "wss://dpdp.hari-pi.com/internal/worker/ws")
TOKEN = os.environ.get("DPDP_WORKER_TOKEN", "")
WORKER_KIND = os.environ.get(
    "DPDP_WORKER_KIND",
    "colab" if os.environ.get("COLAB_RELEASE_TAG") else "pc",
).lower()
WORKER_ID = os.environ.get(
    "DPDP_WORKER_ID",
    f"{WORKER_KIND}-{socket.gethostname()}-{uuid.uuid4().hex[:8]}",
)
CONCURRENCY = max(1, min(8, int(os.environ.get("DPDP_WORKER_CONCURRENCY", "1"))))


def _health_url() -> str:
    base = COORDINATOR.replace("wss://", "https://").replace("ws://", "http://")
    return base.split("/internal/worker/ws", 1)[0] + "/health"


def sync_artifacts() -> int:
    """Download any published coordinator artifacts, verifying each digest."""
    manifest_url = COORDINATOR.replace("wss://", "https://").replace(
        "/internal/worker/ws", "/internal/worker/artifact-manifest")
    if not TOKEN:
        return 0
    response = requests.get(manifest_url, headers={"Authorization": f"Bearer {TOKEN}"},
                            timeout=30)
    response.raise_for_status()
    manifest = response.json()
    files = manifest.get("files", [])
    target_root = Path(os.environ.get("DPDP_ARTIFACT_DIR", "data/worker-artifacts"))
    for item in files:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("unsafe artifact path")
        destination = target_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        url = manifest_url.rsplit("/artifact-manifest", 1)[0] + "/artifact/" + item["path"]
        data = requests.get(url, headers={"Authorization": f"Bearer {TOKEN}"},
                            timeout=120).content
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise RuntimeError(f"artifact checksum mismatch: {relative}")
        destination.write_bytes(data)
    return len(files)


async def process_job(socket, job: dict, query) -> dict:
    """Run one answer in a thread while forwarding stage updates."""
    updates: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def report(stage: str, progress: int) -> None:
        loop.call_soon_threadsafe(updates.put_nowait, (stage, progress))

    task = asyncio.create_task(asyncio.to_thread(
        query.answer, job["question"], k=job["k"], model=job["model"],
        history=job["history"], progress=report,
    ))
    while not task.done():
        try:
            stage, progress = await asyncio.wait_for(updates.get(), timeout=1)
            print(f"[job:{job['id']}] {progress:3d}% {stage}", flush=True)
            await socket.send(json.dumps({
                "type": "progress", "job_id": job["id"],
                "stage": stage, "progress": progress,
            }))
        except asyncio.TimeoutError:
            continue
    answer, hits = await task
    while not updates.empty():
        stage, progress = updates.get_nowait()
        await socket.send(json.dumps({
            "type": "progress", "job_id": job["id"],
            "stage": stage, "progress": progress,
        }))
    sources = []
    for hit in hits:
        source = {"source": hit["meta"]["source"],
                  "unit": hit["meta"]["unit"]}
        if source not in sources:
            sources.append(source)
    return {"type": "result", "job_id": job["id"],
            "answer": answer, "sources": sources}


async def monitor_coordinator() -> None:
    """Print the load balancer's view so a worker is easy to monitor."""
    url = _health_url()
    while True:
        try:
            response = await asyncio.to_thread(requests.get, url, timeout=10)
            response.raise_for_status()
            status = response.json()
            jobs = status.get("jobs", {})
            kinds = status.get("worker_types", {})
            print(
                "[monitor] coordinator=online "
                f"pc={kinds.get('pc', 0)} colab={kinds.get('colab', 0)} "
                f"queued={jobs.get('queued', 0)} running={jobs.get('running', 0)}",
                flush=True,
            )
        except Exception as error:  # noqa: BLE001
            print(f"[monitor] coordinator check failed: {error}", flush=True)
        await asyncio.sleep(10)


async def run_slot(slot: int, query) -> None:
    slot_id = f"{WORKER_ID}-slot-{slot + 1}"
    while True:
        try:
            async with websockets.connect(
                    COORDINATOR, additional_headers={"Authorization": f"Bearer {TOKEN}"},
                    ping_interval=20, ping_timeout=30,
                    max_size=16 * 1024 * 1024) as socket:
                await socket.send(json.dumps({
                    "type": "hello", "worker_id": slot_id,
                    "worker_kind": WORKER_KIND,
                }))
                async for raw in socket:
                    message = json.loads(raw)
                    kind = message.get("type")
                    if kind == "ready":
                        print(
                            f"[worker:{slot + 1}] CONNECTED to {COORDINATOR} "
                            f"as {WORKER_KIND}", flush=True,
                        )
                    elif kind == "job":
                        job = message["job"]
                        print(
                            f"[worker:{slot + 1}] received job {job['id']}",
                            flush=True,
                        )
                        try:
                            result = await process_job(socket, job, query)
                        except Exception as error:  # noqa: BLE001
                            print(
                                f"[worker:{slot + 1}] job {job['id']} failed: {error}",
                                flush=True,
                            )
                            result = {"type": "result", "job_id": job["id"],
                                      "error": str(error)}
                        else:
                            print(
                                f"[worker:{slot + 1}] completed job {job['id']}",
                                flush=True,
                            )
                        await socket.send(json.dumps(result))
                    elif kind == "wait":
                        await socket.send('{"type":"heartbeat"}')
                    elif kind == "heartbeat_ack":
                        continue
        except Exception as error:  # noqa: BLE001
            print(f"[worker:{slot + 1}] disconnected: {error}; retrying in 5s",
                  flush=True)
            await asyncio.sleep(5)


async def run() -> None:
    if not TOKEN:
        raise RuntimeError("DPDP_WORKER_TOKEN is required")
    print("[startup] Loading the local RAG engine...", flush=True)
    from . import query

    print("[startup] Opening and validating the local vector index...", flush=True)
    vectors = await asyncio.to_thread(query.warmup)
    print(f"[worker] index ready: {vectors} vectors", flush=True)
    print(f"[worker] kind={WORKER_KIND} concurrency={CONCURRENCY}", flush=True)
    print("[startup] Connecting worker slots to the coordinator...", flush=True)
    await asyncio.gather(
        monitor_coordinator(),
        *(run_slot(slot, query) for slot in range(CONCURRENCY)),
    )


if __name__ == "__main__":
    print(f"[startup] worker_id={WORKER_ID} endpoint={COORDINATOR}", flush=True)
    print("[startup] Synchronizing coordinator artifacts...", flush=True)
    artifact_count = sync_artifacts()
    print(f"[startup] Artifact sync complete ({artifact_count} files)", flush=True)
    asyncio.run(run())
