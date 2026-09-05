"""Extract clean English text from the official DPDP source PDFs.

Outputs go to data/text/official/<same-stem>.txt. Bilingual gazettes are
filtered to drop Devanagari lines (same approach as the Rules text).
"""
import re
import sys
from pathlib import Path

from pypdf import PdfReader

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "official"
OUT = Path(__file__).resolve().parent.parent / "data" / "text" / "official"

DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def extract(pdf: Path) -> str:
    reader = PdfReader(str(pdf))
    pages = [p.extract_text() or "" for p in reader.pages]
    text = "\n\n".join(pages)
    if DEVANAGARI.search(text):
        # bilingual gazette: keep only lines without Devanagari characters
        text = "\n".join(l for l in text.splitlines() if not DEVANAGARI.search(l))
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for pdf in sorted(RAW.glob("*.pdf")):
        text = extract(pdf)
        out = OUT / (pdf.stem + ".txt")
        out.write_text(text, encoding="utf-8")
        print(f"{out.name}: {len(text)} chars")
    sys.exit(0)


if __name__ == "__main__":
    main()
