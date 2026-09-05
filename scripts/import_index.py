"""Import a prebuilt Chroma index (artifacts/chroma_db.zip) into chroma_db/.

Used on the local serving machine after `git pull` so no embedding is needed
locally. Skipped automatically if the local index is already current
(checkpoint matches the archive's). Use --force to overwrite.

Run:  python scripts/import_index.py [--force]
"""
import argparse
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "artifacts" / "chroma_db.zip"
STATE = ROOT / "chroma_db" / ".ingest_state.json"


def local_state() -> dict | None:
    if not STATE.exists():
        return None
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def archive_state() -> dict | None:
    if not ARCHIVE.exists():
        return None
    try:
        with zipfile.ZipFile(ARCHIVE) as z:
            return json.loads(z.read("chroma_db/.ingest_state.json"))
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true",
                   help="overwrite the local index even if it looks current")
    args = p.parse_args()

    if not ARCHIVE.exists():
        print(f"no archive at {ARCHIVE} — nothing to import")
        return

    a_state, l_state = archive_state(), local_state()
    a_hash = (a_state or {}).get("corpus_hash")
    l_hash = (l_state or {}).get("corpus_hash")
    l_done = len((l_state or {}).get("done", []))
    a_done = len((a_state or {}).get("done", []))
    same = a_hash is not None and a_hash == l_hash
    ahead = a_done > l_done

    if not args.force and same and not ahead:
        print(f"local index already matches archive "
              f"({l_done} chunks, corpus {l_hash[:12]}) — nothing to do")
        return

    with zipfile.ZipFile(ARCHIVE) as z:
        z.extractall(ROOT)
    print(f"imported index: {a_done} chunks, corpus {a_hash[:12] if a_hash else '?'}")
    print("verifying...")
    import chromadb
    from dpdp_rag import config
    col = chromadb.PersistentClient(
        path=str(config.DB_DIR)).get_or_create_collection(config.COLLECTION)
    print(f"collection '{config.COLLECTION}' now holds {col.count()} vectors")


if __name__ == "__main__":
    main()
