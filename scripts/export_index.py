"""Package the built Chroma index into artifacts/chroma_db.zip.

Run this on the machine where ingest completed (e.g. Colab) so the index can
be committed/pushed to git; local machines then import it with
scripts/import_index.py instead of re-embedding everything.
"""
import hashlib
import sys
import zipfile
from pathlib import Path

from dpdp_rag import config

OUT = Path(__file__).resolve().parent.parent / "artifacts" / "chroma_db.zip"


def main() -> None:
    if not config.DB_DIR.exists():
        sys.exit(f"no index at {config.DB_DIR} — run ingest first")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(config.DB_DIR.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(config.DB_DIR.parent))
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"packed {OUT}")
    print(f"  size: {OUT.stat().st_size / 1e6:.1f} MB")
    print(f"  sha256: {digest}")


if __name__ == "__main__":
    main()
