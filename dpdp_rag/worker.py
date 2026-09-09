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


def sync_artifacts() -> None:
    """Download any published coordinator artifacts, verifying each digest."""
    manifest_url = COORDINATOR.replace("wss://", "https://").replace(
        "/internal/worker/ws", "/internal/worker/artifact-manifest")
    if not TOKEN:
        return
    response = requests.get(manifest_url, headers={"Authorization": f"Bearer {TOKEN}"},
                            timeout=30)
    response.raise_for_status()
    manifest = response.json()
    target_root = Path(os.environ.get("DPDP_ARTIFACT_DIR", "data/worker-artifacts"))
    for item in manifest.get("files", []):
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


async def run() -> None:
    if not TOKEN:
        raise RuntimeError("DPDP_WORKER_TOKEN is required")
    from . import query

    while True:
        try:
            async with websockets.connect(
                    COORDINATOR, additional_headers={"Authorization": f"Bearer {TOKEN}"},
                    ping_interval=20, ping_timeout=30,
                    max_size=16 * 1024 * 1024) as socket:
                await socket.send(json.dumps({
                    "type": "hello", "worker_id": WORKER_ID,
                    "worker_kind": WORKER_KIND,
                }))
                async for raw in socket:
                    message = json.loads(raw)
                    kind = message.get("type")
                    if kind == "job":
                        job = message["job"]
                        try:
                            answer, hits = await asyncio.to_thread(
                                query.answer, job["question"], k=job["k"],
                                model=job["model"], history=job["history"])
                            sources = []
                            for hit in hits:
                                source = {"source": hit["meta"]["source"],
                                          "unit": hit["meta"]["unit"]}
                                if source not in sources:
                                    sources.append(source)
                            result = {"type": "result", "job_id": job["id"],
                                      "answer": answer, "sources": sources}
                        except Exception as error:  # noqa: BLE001
                            result = {"type": "result", "job_id": job["id"],
                                      "error": str(error)}
                        await socket.send(json.dumps(result))
                    elif kind == "wait":
                        await socket.send('{"type":"heartbeat"}')
                    elif kind == "heartbeat_ack":
                        continue
        except Exception as error:  # noqa: BLE001
            print(f"[worker] disconnected: {error}; retrying in 5s", flush=True)
            await asyncio.sleep(5)


if __name__ == "__main__":
    sync_artifacts()
    asyncio.run(run())
