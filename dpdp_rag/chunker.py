"""Section-aware chunking of the DPDP Act 2023 and DPDP Rules 2025.

The gazette extracts are noisy (page headers, Hindi transliteration, marginal
notes), so we clean them first and then split the text on legal unit
boundaries: sections for the Act, rules and schedules for the Rules.
Each unit keeps structured metadata so the chatbot can cite precisely.
"""
import re
from collections import defaultdict
from dataclasses import dataclass

from . import config

GAZETTE_NOISE = [
    re.compile(r"THE GAZETTE OF INDIA", re.I),
    re.compile(r"^SEC\. 1\]", re.I),
    re.compile(r"GI/\d{4}"),
    re.compile(r"REGD\. No\."),
    re.compile(r"PUBLISHED BY AUTHORITY", re.I),
    re.compile(r"NEW DELHI, ", re.I),
    re.compile(r"CG-DL-E-"),
    re.compile(r"^[0-9 ]+$"),
    re.compile(r"PART II"),
    re.compile(r"^xxx"),
    re.compile(r"MGIPMRND|Uploaded by|Controller of Publications|GOVERNMENT OF INDIA PRESS", re.I),
]


# Corrigendum G.S.R. 892(E) (10 Dec 2025) corrects the Rules as notified.
# Its corrections are anchored to gazette page and line numbers, which the
# text extraction does not preserve, so each is applied only where its search
# string occurs exactly the expected number of times — otherwise the wrong
# occurrence would be rewritten. Three corrections cannot be applied this way
# and are left to the corrigendum document itself:
#   page 29 line 44  "Department" -> "Departments"   ("Department" occurs 4x)
#   page 38 line 2   "." -> ";"                      (no usable anchor)
#   page 38          "(a) to (f)" -> "(a) to (g)"    (phrase not in the extract)
CORRIGENDA = [
    ("of this Gazette", "in the Official Gazette", 2),
    ("given in such", "given in such order", 1),
    ("everybody", "every body", 1),
    ("(18 or 2013)", "(18 of 2013)", 1),
]


def apply_corrigenda(text: str) -> tuple[str, list[str]]:
    """Return the Rules text as corrected, plus the corrections applied."""
    applied = []
    for old, new, expected in CORRIGENDA:
        if text.count(old) == expected:
            text = text.replace(old, new)
            applied.append(f"{old!r} -> {new!r}")
    return text, applied


def clean(text: str) -> str:
    """Drop gazette page furniture, fix extraction artifacts, collapse blanks."""
    lines = []
    for line in text.splitlines():
        if any(p.search(line) for p in GAZETTE_NOISE):
            continue
        lines.append(line)
    out = "\n".join(lines)
    # Gazette PDFs extract hyphenated words with a stray space ("forty -eight").
    out = re.sub(r"(\w) -(\w)", r"\1-\2", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


@dataclass
class Unit:
    """A legal unit: one section/rule/schedule of a source document."""
    source: str        # "DPDP Act 2023" | "DPDP Rules 2025"
    doc_type: str      # "act" | "rules"
    unit_id: str       # e.g. "s. 8", "r. 7", "THIRD SCHEDULE"
    text: str


SCHEDULE_NAMES = [
    "THE SCHEDULE",
    "FIRST SCHEDULE",
    "SECOND SCHEDULE",
    "THIRD SCHEDULE",
    "FOURTH SCHEDULE",
    "FIFTH SCHEDULE",
    "SIXTH SCHEDULE",
    "SEVENTH SCHEDULE",
]


def _split_units(text: str, source: str, doc_type: str) -> list[Unit]:
    """Split on section/rule starts, plus schedule headers."""
    sched_starts = []
    for sched in SCHEDULE_NAMES:
        for m in re.finditer(rf"^\s*{re.escape(sched).replace(r'\ ', r'\s+')}\b.*$",
                             text, re.M):
            sched_starts.append((m.start(), sched))
    sched_starts.sort()

    def in_schedule(pos: int) -> bool:
        # All numbered rule items that follow the first schedule header are
        # schedule contents, not rules of their own.
        return bool(sched_starts) and pos >= sched_starts[0][0]

    if doc_type == "act":
        # Sections start as "N. (1) ..." or "N. Text ..." (leading whitespace
        # tolerated); the second form covers sections with no sub-sections.
        starts = [(m.start(), m.group(1)) for m in
                  re.finditer(r"^\s*(\d{1,2})\. +(?:\(|[A-Z])", text, re.M)
                  if not in_schedule(m.start())]
        prefix = "s."
    else:
        starts = [(m.start(), m.group(1)) for m in
                  re.finditer(r"^\s*(\d{1,2})\. [A-Z]", text, re.M)
                  if not in_schedule(m.start())]
        prefix = "r."

    starts.extend(sched_starts)
    starts.sort()

    units = []
    if not starts:
        units.append(Unit(source, doc_type, "full", text))
        return units
    if starts[0][0] > 0:
        units.append(Unit(source, doc_type, "preamble", text[: starts[0][0]]))
    for i, (pos, uid) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        units.append(Unit(source, doc_type, f"{prefix} {uid}" if not uid.isupper()
                          else uid, text[pos:end]))
    units = [u for u in units if len(u.text.strip()) > 40]

    # In the Act's gazette PDF, the penalty table rows are extracted before
    # the "THE SCHEDULE" header, so they land inside the last section. Split
    # them back out into their own unit.
    if doc_type == "act":
        marker = "Breach of provisions of"
        fixed = []
        for u in units:
            idx = u.text.find(marker)
            if idx > 0 and not any(x.unit_id == "THE SCHEDULE" for x in fixed):
                fixed.append(Unit(u.source, u.doc_type, u.unit_id, u.text[:idx]))
                fixed.append(Unit(u.source, u.doc_type, "THE SCHEDULE",
                                  u.text[idx:]))
            else:
                fixed.append(u)
        units = fixed
        sched = [u for u in units if u.unit_id == "THE SCHEDULE"]
        if len(sched) > 1:
            merged = Unit(sched[0].source, sched[0].doc_type, "THE SCHEDULE",
                          "\n\n".join(u.text for u in sched))
            units = [u for u in units if u.unit_id != "THE SCHEDULE"]
            units.append(merged)
            sched = [merged]

        # Rebuild the penalty table as one unit per entry, so each breach
        # travels with its own penalty amount.
        if sched:
            rows = _penalty_schedule_rows(sched[0].text)
            if rows:
                units = [u for u in units if u.unit_id != "THE SCHEDULE"]
                units.extend(Unit(sched[0].source, sched[0].doc_type,
                                  "THE SCHEDULE", r) for r in rows)

    # Split large schedules at PART A / PART B boundaries so retrieval can
    # target individual parts precisely.
    part_units = []
    for u in units:
        m = re.search(r"^PART [AB]\b.*$", u.text, re.M)
        if m and u.unit_id.upper().endswith("SCHEDULE"):
            head = Unit(u.source, u.doc_type, u.unit_id, u.text[: m.start()])
            part_units.append(head)
            parts = list(re.finditer(r"^PART [AB]\b.*$", u.text, re.M))
            for i, pm in enumerate(parts):
                end = parts[i + 1].start() if i + 1 < len(parts) else len(u.text)
                part_units.append(Unit(u.source, u.doc_type,
                                       f"{u.unit_id} {pm.group(0).strip()}",
                                       u.text[pm.start():end]))
        else:
            part_units.append(u)
    units = part_units
    return units


def _sentences(block: str) -> list[str]:
    """Flatten wrapped lines, then split on sentence ends."""
    flat = re.sub(r"\s+", " ", block).strip()
    return [s.strip() for s in re.split(r"(?<=\.)\s+", flat) if s.strip()]


def _penalty_schedule_rows(text: str) -> list[str] | None:
    """Re-join the Act's penalty Schedule, which extracts column-by-column.

    The gazette PDF yields every breach description first, then the serial
    numbers, then every penalty amount — so a breach and its penalty land in
    different chunks and no retrieval can associate them. Return one string
    per entry, or None if the layout is not the one we know how to repair.
    """
    sl = re.search(r"^\s*Sl\.\s*No\.\s*$", text, re.M)
    pen = re.search(r"^\s*Penalty\s*$", text, re.M)
    if not sl or not pen or not (sl.start() < pen.start()):
        return None

    caption = ""
    cap = re.search(r"^\s*\[See section[^\]]*\]", text[pen.end():], re.M)
    if cap:
        caption = re.sub(r"\s+", " ", cap.group(0)).strip()

    def strip_headers(block: str, drop_first: bool) -> str:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if drop_first and lines:
            lines = lines[1:]                       # the column caption
        lines = [ln for ln in lines if not re.fullmatch(r"\s*\(\d\)\s*", ln)]
        return "\n".join(lines)

    breaches = _sentences(strip_headers(text[:sl.start()], True))
    numbers = re.findall(r"^\s*(\d{1,2})\.\s*$", text[sl.start():pen.start()], re.M)

    tail = text[pen.end():]
    end = re.search(r"^\s*THE\s+SCHEDULE\s*$", tail, re.M)
    penalties = _sentences(strip_headers(tail[: end.start()] if end else tail, False))

    if not numbers or not (len(breaches) == len(penalties) == len(numbers)):
        return None

    head = f"THE SCHEDULE {caption}".strip()
    return [f"{head}\nEntry {n}. Breach: {b}\nPenalty: {p}"
            for n, b, p in zip(numbers, breaches, penalties)]


def _schedule_rows(text: str) -> list[str] | None:
    """Split a numbered schedule table into its caption plus one item per row."""
    starts = [m.start() for m in re.finditer(r"^\s*\d{1,2}\.\s", text, re.M)]
    if len(starts) < 2:
        return None
    bounds = starts + [len(text)]
    rows = [text[a:b].strip() for a, b in zip(starts, bounds[1:])]
    return [text[: starts[0]].strip()] + [r for r in rows if r]


def chunk_schedule(text: str, size: int = config.CHUNK_SIZE) -> list[str]:
    """Chunk a schedule without ever cutting a row in half.

    Rows are packed up to `size`, and the schedule caption (its title, the
    "[See rule N]" reference and the column names) rides along with every
    chunk so a row is never stranded without its column headings.
    """
    rows = _schedule_rows(text)
    if not rows:
        return chunk(text)
    caption, rows = rows[0][:300], rows[1:]
    budget = max(size - len(caption), size // 2)   # the caption rides along
    chunks, cur = [], ""
    for row in rows:
        for piece in _split_long(row, budget):
            if cur and len(cur) + len(piece) > budget:
                chunks.append(cur.strip())
                cur = ""
            cur = (cur + "\n" + piece) if cur else piece
    if cur.strip():
        chunks.append(cur.strip())
    return [f"{caption}\n{c}" if caption else c for c in chunks]


def _split_long(p: str, size: int) -> list[str]:
    """Split an oversized paragraph on sentence boundaries."""
    if len(p) <= size:
        return [p]
    sentences = re.split(r"(?<=[.;:]) ", p)
    out, cur = [], ""
    for s in sentences:
        if len(cur) + len(s) > size and cur:
            out.append(cur.strip())
            cur = ""
        cur = (cur + " " + s) if cur else s
    if cur.strip():
        out.append(cur.strip())
    return out


def chunk(text: str, size: int = config.CHUNK_SIZE,
          overlap: int = config.CHUNK_OVERLAP) -> list[str]:
    """Split a long unit into overlapping windows on paragraph boundaries."""
    paragraphs = []
    for p in text.split("\n\n"):
        paragraphs.extend(_split_long(p, size))
    chunks, cur = [], ""
    for p in paragraphs:
        if len(cur) + len(p) > size and cur:
            chunks.append(cur.strip())
            cur = cur[-overlap:] if overlap < len(cur) else ""
        cur = (cur + "\n\n" + p) if cur else p
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def _doc(source: str, doc_type: str, unit: str, tier: int, part: int,
         text: str) -> dict:
    """Wrap a chunk with a short citation header so embeddings carry context."""
    short = source.split(" (")[0]  # e.g. "Draft DPDP Rules 2025"
    header = f"{short}, {unit}.\n"
    return {
        "id": f"{doc_type}:{unit}:{part}",
        "text": header + text,
        "metadata": {
            "source": source,
            "doc_type": doc_type,
            "unit": unit,
            "part": part,
            "tier": tier,
        },
    }


def _is_schedule(unit_id: str) -> bool:
    return "SCHEDULE" in unit_id.upper()


def _emit(docs: list[dict], parts: dict, source: str, doc_type: str,
          unit_id: str, tier: int, text: str) -> None:
    """Chunk one unit and append it, numbering parts per (doc_type, unit)."""
    pieces = chunk_schedule(text) if _is_schedule(unit_id) else chunk(text)
    for piece in pieces:
        key = (doc_type, unit_id)
        docs.append(_doc(source, doc_type, unit_id, tier, parts[key], piece))
        parts[key] += 1


def build_documents() -> list[dict]:
    """Return all chunks with metadata, ready for embedding."""
    docs: list[dict] = []
    parts: dict = defaultdict(int)
    sources = [
        ("DPDP_Act_2023.txt", "DPDP Act 2023", "act"),
        ("DPDP_Rules_2025_clean.txt",
         "DPDP Rules 2025 (G.S.R. 846(E), 13 Nov 2025)", "rules"),
    ]
    for filename, source, doc_type in sources:
        raw = clean((config.TEXT_DIR / filename).read_text(encoding="utf-8"))
        if doc_type == "rules":
            # Index the Rules as corrected, so retrieval returns the operative
            # wording rather than the wording plus a separate patch note.
            raw, applied = apply_corrigenda(raw)
            print(f"[corrigenda] applied {len(applied)}/{len(CORRIGENDA)} "
                  f"corrections to {source}")
        for unit in _split_units(raw, source, doc_type):
            _emit(docs, parts, source, doc_type, unit.unit_id, 1, unit.text)

    # Draft rules: same structure as the final rules, labelled as a draft.
    draft_path = config.OFFICIAL_TEXT_DIR / "Draft_Rules_Gazette_GSR_02E.txt"
    raw = clean(draft_path.read_text(encoding="utf-8"))
    draft_source = "Draft DPDP Rules 2025 (G.S.R. 02(E), 3 Jan 2025)"
    for unit in _split_units(raw, draft_source, "draft_rules"):
        uid = (f"draft {unit.unit_id}" if unit.unit_id.startswith("r.")
               else unit.unit_id)
        _emit(docs, parts, draft_source, "draft_rules", uid, 1, unit.text)

    # Smaller official documents: single or paragraph chunks.
    simple_docs = [
        ("Commencement_Notification_GSR_843E.txt",
         "Commencement Notification G.S.R. 843(E) (13 Nov 2025)",
         "notification", "GSR 843(E)", 1),
        ("Board_Establishment_GSR_844E.txt",
         "Board Establishment Notification G.S.R. 844(E) (13 Nov 2025)",
         "notification", "GSR 844(E)", 1),
        ("Board_Members_GSR_845E.txt",
         "Board Composition Notification G.S.R. 845(E) (13 Nov 2025)",
         "notification", "GSR 845(E)", 1),
        ("Corrigendum_GSR_892E.txt",
         "Corrigendum G.S.R. 892(E) (10 Dec 2025)",
         "corrigendum", "GSR 892(E)", 1),
        ("Summary_Submissions_Draft_Rules.txt",
         "MeitY Summary of Submissions on Draft Rules (14 Jan 2026)",
         "summary", "summary", 1),
        ("LokSabha_QA_AU3960.txt",
         "Lok Sabha Q&A AU3960 (12 Aug 2026): Board appointments",
         "parliament_qa", "QA AU3960", 1),
        ("LokSabha_QA_AU4091.txt",
         "Lok Sabha Q&A AU4091 (12 Aug 2026): implementation status",
         "parliament_qa", "QA AU4091", 1),
        ("DSCI_FAQ_DPDP_Framework.txt",
         "DSCI FAQ: DPDP Framework — Data Protection Board (2026)",
         "faq", "FAQ", 2),
    ]
    for filename, source, doc_type, unit, tier in simple_docs:
        raw = clean((config.OFFICIAL_TEXT_DIR / filename).read_text(encoding="utf-8"))
        _emit(docs, parts, source, doc_type, unit, tier, raw)
    return docs
