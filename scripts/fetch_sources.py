"""Reproducible download of the official DPDP corpus.

Run:  python scripts/fetch_sources.py
Downloads each source into data/raw/official/ and (re)builds
data/sources_manifest.json with SHA-256 checksums.

As-of note (2026-09-05): MeitY's Explanatory Note to the DPDP Rules 2025
(formerly at writereaddata/files/Explanatory-Note-DPDP-Rules-2025.pdf) now
returns 404; it is recorded in the manifest as unavailable.
"""
import hashlib
import json
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "official"

SOURCES = [
    # (filename, url, tier, gazette_ref, published, note)
    ("DPDP_Act_2023.pdf",
     "https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf",
     1, "Act 22 of 2023", "2023-08-11", "in data/raw/"),
    ("DPDP_Rules_2025_English.pdf",
     "https://egazette.gov.in/WriteReadData/2025/267650.pdf",
     1, "G.S.R. 846(E), CG-DL-E-14112025-267650", "2025-11-13", "in data/raw/"),
    ("official/Commencement_Notification_GSR_843E.pdf",
     "https://egazette.gov.in/WriteReadData/2025/267647.pdf",
     1, "G.S.R. 843(E)", "2025-11-13", "3-phase commencement of the Act"),
    ("official/Board_Establishment_GSR_844E.pdf",
     "https://egazette.gov.in/WriteReadData/2025/267648.pdf",
     1, "G.S.R. 844(E)", "2025-11-13", "establishes the Board under s. 18"),
    ("official/Board_Members_GSR_845E.pdf",
     "https://egazette.gov.in/WriteReadData/2025/267649.pdf",
     1, "G.S.R. 845(E)", "2025-11-13", "Board composition under s. 19(1)"),
    ("official/Corrigendum_GSR_892E.pdf",
     "https://egazette.gov.in/WriteReadData/2025/268455.pdf",
     1, "G.S.R. 892(E)", "2025-12-10", "7 textual corrections to the Rules"),
    ("official/Draft_Rules_Gazette_GSR_02E.pdf",
     "https://egazette.gov.in/WriteReadData/2025/259889.pdf",
     1, "G.S.R. 02(E), CG-DL-E-03012025-259889", "2025-01-03",
     "draft rules for public consultation"),
    ("official/Draft_Rules_PIB_Overview.pdf",
     "https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/jan/doc202515481101.pdf",
     1, "PIB doc202515481101", "2025-01-05", "PIB overview of draft rules"),
    ("official/Summary_Submissions_Draft_Rules.pdf",
     "https://www.meity.gov.in/static/uploads/2026/01/a49c50414777afc2af0b8d59dafacd60.pdf",
     1, "MeitY summary", "2026-01-14",
     "summary of 6,951 submissions on the draft rules"),
    ("official/LokSabha_QA_AU3960.pdf",
     "https://sansad.in/getFile/lsapps/loksabhaquestions/annex/188/AU3960_GyWSTk.pdf",
     1, "LS US Q. 3960", "2026-08-12", "Board appointment status"),
    ("official/LokSabha_QA_AU4091.pdf",
     "https://sansad.in/getFile/lsapps/loksabhaquestions/annex/188/AU4091_ajtbM6.pdf",
     1, "LS US Q. 4091", "2026-08-12", "implementation status, CSC/VLEs"),
    ("official/DSCI_FAQ_DPDP_Framework.pdf",
     "https://www.dsci.in/files/content/documents/2026/faq-on-data-protection-board.pdf",
     2, "DSCI FAQ", "2026", "industry-body FAQ on the Board"),
    # Unavailable as of 2026-09-05 (404 on MeitY):
    # ("official/Explanatory_Note_DPDP_Rules_2025.pdf",
    #  "https://www.meity.gov.in/writereaddata/files/Explanatory-Note-DPDP-Rules-2025.pdf",
    #  1, "MeitY explanatory note", "2025-11-14", "NOT FOUND (404)"),
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    manifest = []
    for filename, url, tier, ref, published, note in SOURCES:
        dest = ROOT / "data" / "raw" / filename
        status = "ok"
        if not dest.exists():
            try:
                r = requests.get(url, headers=HEADERS, timeout=90)
                r.raise_for_status()
                dest.write_bytes(r.content)
            except Exception as e:  # noqa: BLE001
                status = f"failed: {e}"
        entry = {
            "file": filename, "url": url, "tier": tier, "gazette_ref": ref,
            "published": published, "note": note, "status": status,
            "fetched": date.today().isoformat(),
        }
        if dest.exists():
            entry["sha256"] = sha256(dest)
        manifest.append(entry)
        print(f"{filename}: {status}")
    out = ROOT / "data" / "sources_manifest.json"
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"manifest -> {out}")


if __name__ == "__main__":
    main()
