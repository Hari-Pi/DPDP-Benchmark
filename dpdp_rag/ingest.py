"""Ingest the chunked corpus into a persistent Chroma collection.

Resumable: progress is checkpointed to chroma_db/.ingest_state.json after
every batch. If the process (or Ollama) dies mid-run, rerunning continues
from the last completed batch — as long as the corpus is unchanged (tracked
by a SHA-256 over the chunk texts; a changed corpus restarts from scratch).
Individual Ollama calls are retried with exponential backoff.
"""
import hashlib
import json
import time

import chromadb
from ollama import Client

from . import chunker, config

STATE_FILE = config.DB_DIR / ".ingest_state.json"
BATCH = config.EMBED_BATCH  # small batches keep per-request GPU load low
MAX_ATTEMPTS = 6


def _corpus_hash(docs: list[dict]) -> str:
    h = hashlib.sha256()
    for d in sorted(docs, key=lambda x: x["id"]):
        h.update(d["id"].encode())
        h.update(d["text"].encode())
    return h.hexdigest()


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"corpus_hash": None, "done": []}


def _save_state(state: dict) -> None:
    config.DB_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def _embed(client: Client, texts: list[str]) -> list[list[float]]:
    """Embed with nomic task prefix and exponential-backoff retries."""
    last = None
    for i in range(MAX_ATTEMPTS):
        try:
            resp = client.embed(
                model=config.EMBED_MODEL,
                input=[f"search_document: {t}" for t in texts])
            return resp["embeddings"]
        except Exception as e:  # noqa: BLE001
            last = e
            wait = 5 * (2 ** i)
            print(f"[retry] embed batch failed ({e}); wait {wait:.0f}s "
                  f"({i + 1}/{MAX_ATTEMPTS})")
            time.sleep(wait)
    raise RuntimeError(f"embedding failed after {MAX_ATTEMPTS} attempts") from last


def main(reset: bool = False) -> None:
    docs = chunker.build_documents()
    chash = _corpus_hash(docs)
    state = _load_state()
    if state.get("corpus_hash") != chash:
        if state.get("corpus_hash") is not None:
            print("Corpus changed since last run — restarting from scratch")
        state = {"corpus_hash": chash, "done": []}
    done = set(state["done"])

    client = Client(host="http://localhost:11434")
    chroma = chromadb.PersistentClient(path=str(config.DB_DIR))
    if reset and config.COLLECTION in [c.name for c in chroma.list_collections()]:
        chroma.delete_collection(config.COLLECTION)
        state, done = {"corpus_hash": chash, "done": []}, set()
    col = chroma.get_or_create_collection(
        config.COLLECTION, metadata={"hnsw:space": "cosine"})

    pending = [d for d in docs if d["id"] not in done]
    if not pending and col.count() >= len(docs):
        print("Nothing to do — checkpoint and collection are up to date")
        return
    if not done and col.count() >= len(docs):
        # Collection already holds the full corpus (e.g. from a pre-checkpoint
        # run): seed the checkpoint instead of re-embedding everything.
        done.update(d["id"] for d in docs)
        state["done"] = sorted(done)
        _save_state(state)
        pending = []
        print(f"Seeded checkpoint from existing collection ({len(docs)} vectors)")
    else:
        pending = [d for d in docs if d["id"] not in done]
    print(f"{len(docs)} chunks, {len(done)} already ingested, "
          f"{len(pending)} to do")

    for i in range(0, len(pending), BATCH):
        part = pending[i:i + BATCH]
        col.upsert(
            ids=[d["id"] for d in part],
            documents=[d["text"] for d in part],
            metadatas=[d["metadata"] for d in part],
            embeddings=_embed(client, [d["text"] for d in part]),
        )
        done.update(d["id"] for d in part)
        state["done"] = sorted(done)
        _save_state(state)
        print(f"  embedded {len(done)}/{len(docs)}")
    print(f"Done. Collection '{config.COLLECTION}' at {config.DB_DIR}")


if __name__ == "__main__":
    main()
