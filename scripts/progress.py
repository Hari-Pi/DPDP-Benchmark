"""Progress dashboard for the DPDP RAG pipeline — safe to run any time.

  python scripts/progress.py

Shows:
  - Ollama server status and loaded models
  - GPU memory per device (nvidia-smi if available)
  - Ingest checkpoint progress (chunks done / total)
  - Chroma collection size
  - Benchmark progress (cases complete, hit-rate, next case)
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dpdp_rag import chunker, config  # noqa: E402

STATE = config.DB_DIR / ".ingest_state.json"
RESULTS = Path(__file__).resolve().parent.parent / "benchmark_results.json"
CASES = [
    "penalty-security-failure", "penalty-breach-notice", "breach-72h",
    "consent-manager-networth", "commencement-phase-3",
    "commencement-in-force-now", "corrigendum", "board-status",
    "consultation-submissions", "child-consent", "retention-logs",
    "erasure-notice-48h", "grievance-window", "sdf-dpia",
    "localization-sdf", "def-personal-data", "board-inquiry-timeline",
    "appeal-tribunal",
]


def bar(done: int, total: int, width: int = 28) -> str:
    pct = done / total if total else 0
    filled = int(width * pct)
    return f"[{'#' * filled}{'.' * (width - filled)}] {pct:5.1%} ({done}/{total})"


def ollama_status() -> None:
    print("== Ollama ==")
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/version",
                                    timeout=3) as r:
            print("   server:", json.loads(r.read())["version"], "- UP")
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",
                                    timeout=5) as r:
            models = json.loads(r.read())["models"]
        for m in models:
            print(f"   model : {m['name']} ({m['size'] / 1e9:.1f} GB)")
    except Exception as e:  # noqa: BLE001
        print("   server: DOWN —", e)
        print("   fix   : powershell -File scripts\\start_ollama.ps1")


def gpu_status() -> None:
    print("== GPUs ==")
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total",
             "--format=csv,noheader"], capture_output=True, text=True,
            timeout=10).stdout.strip()
        for line in out.splitlines():
            print("   ", line)
    except Exception as e:  # noqa: BLE001
        print("   nvidia-smi unavailable:", e)


def ingest_status() -> None:
    print("== Ingest ==")
    docs = chunker.build_documents()
    total = len(docs)
    done_ids = set()
    chash_ok = None
    if STATE.exists():
        try:
            st = json.loads(STATE.read_text(encoding="utf-8"))
            done_ids = set(st.get("done", []))
            h = hashlib.sha256()
            for d in sorted(docs, key=lambda x: x["id"]):
                h.update(d["id"].encode())
                h.update(d["text"].encode())
            chash_ok = st.get("corpus_hash") == h.hexdigest()
        except Exception as e:  # noqa: BLE001
            print("   checkpoint unreadable:", e)
    if chash_ok is False:
        print("   NOTE: corpus changed since checkpoint — next ingest "
              "restarts from scratch")
    elif chash_ok is None:
        print("   no checkpoint yet — next ingest starts fresh")
    print("   chunks:", bar(len(done_ids), total))
    # collection size
    try:
        import chromadb
        col = chromadb.PersistentClient(
            path=str(config.DB_DIR)).get_or_create_collection(config.COLLECTION)
        print("   chroma:", col.count(), "vectors in", f"'{config.COLLECTION}'")
    except Exception as e:  # noqa: BLE001
        print("   chroma: unavailable —", e)


def benchmark_status() -> None:
    print("== Benchmark ==")
    if not RESULTS.exists():
        print("   not started yet")
        return
    try:
        rows = {r["id"]: r for r in json.loads(
            RESULTS.read_text(encoding="utf-8"))}
    except Exception as e:  # noqa: BLE001
        print("   results unreadable:", e)
        return
    complete = [c for c in CASES if c in rows and "answer_ok" in rows[c]]
    passed = [c for c in complete if rows[c]["retrieval_hit"]]
    answered = [c for c in complete if rows[c]["answer_ok"]]
    print("   cases  :", bar(len(complete), len(CASES)))
    print("   retrieval:", bar(len(passed), len(complete) or 1))
    print("   answers :", bar(len(answered), len(complete) or 1))
    nxt = next((c for c in CASES if c not in complete), None)
    print("   next   :", nxt or "ALL DONE")
    for c in complete:
        mark = "PASS" if rows[c]["retrieval_hit"] else "FAIL"
        amark = "PASS" if rows[c]["answer_ok"] else "FAIL"
        print(f"   {mark:4} {amark:4} {c}")


def main() -> None:
    ollama_status()
    print()
    gpu_status()
    print()
    ingest_status()
    print()
    benchmark_status()


if __name__ == "__main__":
    main()
