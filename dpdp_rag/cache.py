"""Download and restore coordinator-published worker caches."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import requests


def coordinator_base() -> str:
    endpoint = os.environ.get("DPDP_COORDINATOR_URL", "https://dpdp.hari-pi.com/internal/worker/ws")
    return endpoint.replace("wss://", "https://").replace("ws://", "http://").split(
        "/internal/worker/ws", 1
    )[0]


def restore() -> dict[str, int | str]:
    """Fetch and verify the published cache, then restore local index/models."""
    token = os.environ.get("DPDP_WORKER_TOKEN", "")
    if not token:
        return {"status": "skipped", "files": 0, "index": 0}
    root = Path(os.environ.get("DPDP_ARTIFACT_DIR", "data/worker-artifacts"))
    root.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {token}"}
    base = coordinator_base()
    manifest = requests.get(f"{base}/internal/worker/artifact-manifest", headers=headers, timeout=30)
    manifest.raise_for_status()
    items = [item for item in manifest.json().get("files", []) if item.get("path", "").startswith("cache/")]
    downloaded = 0
    for item in items:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe artifact path: {relative}")
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(f"{base}/internal/worker/artifact/{item['path']}", headers=headers, timeout=300)
        response.raise_for_status()
        payload = response.content
        if hashlib.sha256(payload).hexdigest() != item["sha256"]:
            raise RuntimeError(f"cache checksum mismatch: {relative}")
        temporary = destination.with_suffix(destination.suffix + ".partial")
        temporary.write_bytes(payload)
        temporary.replace(destination)
        downloaded += 1

    cache_root = root / "cache"
    index = cache_root / "chroma_db"
    index_restored = 0
    if index.is_dir() and any(index.iterdir()):
        index_restored = 1
        local_index = Path("chroma_db")
        local_index.mkdir(exist_ok=True)
        for source in index.rglob("*"):
            if source.is_file():
                target = local_index / source.relative_to(index)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        (root / "cache-restored.json").write_text(
            json.dumps({"version": manifest.json().get("version", "none"), "files": downloaded}),
            encoding="utf-8",
        )
    model_dir = cache_root / "ollama" / "models"
    if model_dir.is_dir() and any(model_dir.iterdir()):
        os.environ["OLLAMA_MODELS"] = str(model_dir.resolve())
    return {"status": "restored" if downloaded else "empty", "files": downloaded, "index": index_restored}
