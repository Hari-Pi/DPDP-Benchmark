"""Train-on-Colab / serve-locally bundle, no git needed.

Two modes:

  Create a bundle (run where training finished, e.g. Colab):
      python scripts/bundle.py
    -> dpdp_bundle.zip  (trained Chroma index + benchmark results)

  Import a bundle (run on the local serving machine):
      python scripts/bundle.py --import [path/to/dpdp_bundle.zip]
    -> installs the index into chroma_db/, then prints the progress dashboard.

--import accepts a zip path or a directory containing dpdp_bundle.zip; with
no argument it searches the repo root, current dir, and ~/Downloads.
"""
import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BUNDLE_NAME = "dpdp_bundle.zip"
INDEX_DIR = ROOT / "chroma_db"
RESULTS = ROOT / "benchmark_results.json"


# ---------------------------------------------------------------- create ----
def create() -> Path:
    if not INDEX_DIR.exists() or not (INDEX_DIR / ".ingest_state.json").exists():
        sys.exit(f"no trained index at {INDEX_DIR} — run the ingest first")
    out = ROOT / BUNDLE_NAME
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(INDEX_DIR.rglob("*")):
            if f.is_file():
                z.write(f, f"chroma_db/{f.relative_to(INDEX_DIR)}")
        if RESULTS.exists():
            z.write(RESULTS, "benchmark_results.json")
    print(f"bundle -> {out}")
    print(f"  size: {out.stat().st_size / 1e6:.1f} MB")
    print("download this file (Colab: files.download) and put it anywhere on "
          "the local machine, then run:")
    print(f"  python scripts/bundle.py --import {out.name}")
    return out


# ---------------------------------------------------------------- import ----
def locate_bundle(arg: str | None) -> Path | None:
    candidates: list[Path] = []
    if arg:
        p = Path(arg).expanduser()
        candidates.append(p if p.is_file() else p / BUNDLE_NAME)
    else:
        candidates += [ROOT / BUNDLE_NAME, Path.cwd() / BUNDLE_NAME,
                       Path.home() / "Downloads" / BUNDLE_NAME]
    for c in candidates:
        if c.is_file():
            return c
    return None


def do_import(path: Path) -> None:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if not any(n.startswith("chroma_db/") for n in names):
            sys.exit(f"{path} does not look like a dpdp bundle (missing chroma_db/)")
        a_state = None
        try:
            a_state = json.loads(z.read("chroma_db/.ingest_state.json"))
        except Exception:  # noqa: BLE001
            pass
        a_done = len((a_state or {}).get("done", []))

        l_state = None
        if (INDEX_DIR / ".ingest_state.json").exists():
            try:
                l_state = json.loads(
                    (INDEX_DIR / ".ingest_state.json").read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
        l_done = len((l_state or {}).get("done", []))
        same = (a_state or {}).get("corpus_hash") == \
            (l_state or {}).get("corpus_hash")

        if same and a_done <= l_done:
            print(f"local index already current ({l_done} chunks) — no import "
                  "needed")
        else:
            if INDEX_DIR.exists():
                shutil.rmtree(INDEX_DIR)
            for n in names:
                if n.startswith("chroma_db/"):
                    target = INDEX_DIR / n[len("chroma_db/"):]
                    if not n.endswith("/"):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(z.read(n))
            print(f"imported index: {a_done} chunks from {path.name}")
        if "benchmark_results.json" in names:
            z.extract("benchmark_results.json", ROOT)
            print("imported benchmark_results.json")
    print()
    import subprocess
    subprocess.run([sys.executable, str(ROOT / "scripts" / "progress.py")],
                   check=False)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--import", dest="imp", nargs="?", const="default",
                   metavar="PATH", help="import a bundle zip and show progress")
    args = p.parse_args()

    if args.imp is None:
        create()
    else:
        arg = None if args.imp == "default" else args.imp
        path = locate_bundle(arg)
        if not path:
            searched = [str(ROOT / BUNDLE_NAME), str(Path.cwd() / BUNDLE_NAME),
                        str(Path.home() / "Downloads" / BUNDLE_NAME)]
            sys.exit("bundle not found. Searched:\n  " + "\n  ".join(searched))
        do_import(path)


if __name__ == "__main__":
    main()
