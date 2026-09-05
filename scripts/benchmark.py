"""DPDP RAG benchmark: question -> expected source units and key facts.

Scored dimensions:
  retrieval_hit   at least one retrieved chunk is from an expected unit
  retrieval_rank  1-based rank of the first such chunk (drives MRR), so a
                  correct source buried at rank 9 no longer scores like one
                  at rank 1
  answer_ok       the answer states every expected fact, matched on word
                  boundaries rather than as a bare substring
  abstained       the answer declines to answer. Required for the negative
                  cases; on a positive case it is a *false* abstention, the
                  failure mode where the fact is in the corpus and the model
                  says it is not
  cites_expected  the answer cites at least one expected unit
  ungrounded      references cited by the answer that appear in nothing that
                  was retrieved — invented citations
  noise           share of retrieved passages from non-operative sources
                  (draft rules, consultation summary, third-party FAQ)

Run:  $env:PYTHONPATH='<repo root>'; python scripts/benchmark.py [--k 8]
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dpdp_rag import config, query  # noqa: E402

CASES = [
    {
        "id": "penalty-security-failure",
        "q": "What is the maximum monetary penalty for a Data Fiduciary's failure to take reasonable security safeguards?",
        "expect_units": ["THE SCHEDULE"],
        "expect_facts": ["two hundred and fifty crore||250 crore"],
    },
    {
        "id": "penalty-breach-notice",
        "q": "What is the penalty for failing to notify a personal data breach to the Board?",
        "expect_units": ["THE SCHEDULE"],
        "expect_facts": ["two hundred crore"],
    },
    {
        "id": "breach-72h",
        "q": "How quickly must a Data Fiduciary give detailed information of a breach to the Board?",
        "expect_units": ["r. 7"],
        "expect_facts": ["seventy-two hours"],
    },
    {
        "id": "consent-manager-networth",
        "q": "What is the minimum net worth required for Consent Manager registration?",
        "expect_units": ["FIRST SCHEDULE", "FIRST SCHEDULE PART A", "r. 4"],
        "expect_facts": ["two crore||2 crore"],
    },
    {
        "id": "commencement-phase-3",
        "q": "Which rules of the DPDP Rules 2025 come into force eighteen months after publication?",
        "expect_units": ["r. 1", "GSR 843(E)"],
        "expect_facts": ["Rules 3", "eighteen months||18 months"],
    },
    {
        "id": "commencement-in-force-now",
        "q": "Which provisions of the DPDP Act are currently in force as of 2026?",
        "expect_units": ["GSR 843(E)", "r. 1"],
        "expect_facts": ["13 November 2025||13 Nov 2025||November 2025", "May 2027"],
    },
    {
        "id": "corrigendum",
        "q": "What did corrigendum G.S.R. 892(E) change in the DPDP Rules?",
        "expect_units": ["GSR 892(E)"],
        "expect_facts": ["Official Gazette", "Departments"],
    },
    {
        "id": "board-status",
        "q": "Have the Chairperson and Members of the Data Protection Board been appointed?",
        "expect_units": ["QA AU3960"],
        "expect_facts": ["6 June 2026"],
    },
    {
        "id": "consultation-submissions",
        "q": "How many responses were received on the draft DPDP Rules consultation?",
        "expect_units": ["QA AU3960", "summary"],
        "expect_facts": ["6,915||6915||6,951||6951"],
    },
    {
        "id": "child-consent",
        "q": "How can a Data Fiduciary verify the identity of a parent before processing a child's data?",
        "expect_units": ["r. 10"],
        "expect_facts": ["virtual token"],
    },
    {
        "id": "retention-logs",
        "q": "For how long must a Data Fiduciary retain processing logs and traffic data?",
        "expect_units": ["r. 8"],
        "expect_facts": ["one year"],
    },
    {
        "id": "erasure-notice-48h",
        "q": "How long before erasure must a Data Fiduciary inform the Data Principal under Rule 8?",
        "expect_units": ["r. 8"],
        "expect_facts": ["forty-eight hours"],
    },
    {
        "id": "grievance-window",
        "q": "Within how many days must a grievance redressal system respond to Data Principal grievances?",
        "expect_units": ["r. 14", "FAQ", "summary"],
        "expect_facts": ["ninety days"],
    },
    {
        "id": "sdf-dpia",
        "q": "How often must a Significant Data Fiduciary undertake a Data Protection Impact Assessment?",
        "expect_units": ["r. 13"],
        "expect_facts": ["twelve months"],
    },
    {
        "id": "localization-sdf",
        "q": "What restriction applies to a Significant Data Fiduciary on transferring specified personal data outside India?",
        "expect_units": ["r. 13"],
        "expect_facts": ["not transferred outside the territory of India"],
    },
    {
        "id": "def-personal-data",
        "q": "How does the DPDP Act define personal data?",
        "expect_units": ["s. 2"],
        "expect_facts": ["identifiable"],
    },
    {
        "id": "board-inquiry-timeline",
        "q": "Within what period must an inquiry by the Board be completed?",
        "expect_units": ["r. 19", "FAQ"],
        "expect_facts": ["six months"],
    },
    {
        "id": "appeal-tribunal",
        "q": "Within how many days must an appeal against a Board order be filed with the Appellate Tribunal?",
        "expect_units": ["s. 29", "r. 22"],
        "expect_facts": ["sixty days"],
    },
    # Negative cases: the corpus genuinely cannot answer these, so the only
    # correct behaviour is to decline. Without them the benchmark rewards a
    # system that answers everything confidently.
    {
        "id": "neg-gdpr-out-of-scope",
        "q": "What does the GDPR require for cross-border transfers of personal data?",
        "expect_abstain": True,   # the corpus contains no GDPR material at all
    },
    {
        "id": "neg-nonexistent-section",
        "q": "What does section 55 of the DPDP Act 2023 provide?",
        "expect_abstain": True,   # the Act ends at section 44
    },
    {
        "id": "neg-no-enforcement-data",
        "q": "How many penalties has the Data Protection Board imposed to date, "
             "and what is the total amount collected?",
        "expect_abstain": True,   # no enforcement record in the corpus
    },
]

# Phrasings the model uses when it declines. Checked against the opening of
# the answer as well as the whole, so a leading refusal still counts even if
# the model then rambles.
REFUSALS = [
    "does not specify", "does not contain", "does not provide",
    "does not mention", "not explicitly stated", "not provided in",
    "not mentioned in", "not available in", "not included in",
    "is not present in", "no information", "cannot be determined",
    "cannot answer", "is not covered", "does not appear in",
    "outside the scope", "not found in the provided",
]

# Non-operative sources: useful context, but not the law in force.
NOISE_DOC_TYPES = {"draft_rules", "summary", "faq"}

_SECTION_RE = re.compile(r"\b(?:s\.|section)\s*(\d{1,2})\b", re.I)
_RULE_RE = re.compile(r"\b(?:r\.|rule)\s*(\d{1,2})\b", re.I)
_SCHEDULE_RE = re.compile(
    r"\b((?:THE|FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH)\s+SCHEDULE)\b",
    re.I)
_GSR_RE = re.compile(r"\bG\.?\s?S\.?\s?R\.?\s*(\d{1,4})\s*\(?E\)?", re.I)


def _norm(s: str) -> str:
    return s.lower().replace(",", "").replace("₹", "").replace("  ", " ")


def _fact_match(alt: str, answer: str) -> bool:
    """Match an expected fact on word boundaries.

    A bare substring test let "250" match inside "1250" or an unrelated
    figure, which quietly inflated the score.
    """
    words = [re.escape(w) for w in _norm(alt).split()]
    if not words:
        return False
    pattern = r"\s+".join(words)
    if _norm(alt)[0].isalnum():
        pattern = r"\b" + pattern
    if _norm(alt)[-1].isalnum():
        pattern = pattern + r"\b"
    return re.search(pattern, _norm(answer)) is not None


def _is_abstention(answer: str) -> bool:
    head = answer[:400].lower()
    return any(p in head for p in REFUSALS)


def _referenced_units(text: str) -> set[str]:
    """Canonical unit ids referenced anywhere in a piece of text."""
    units = {f"s. {n}" for n in _SECTION_RE.findall(text)}
    units |= {f"r. {n}" for n in _RULE_RE.findall(text)}
    units |= {s.upper().replace("  ", " ") for s in _SCHEDULE_RE.findall(text)}
    units |= {f"GSR {n}(E)" for n in _GSR_RE.findall(text)}
    return units


def _canon(unit: str) -> str:
    """Drop the draft marker so a citation checker is not fooled by it."""
    return unit[len("draft "):] if unit.startswith("draft ") else unit


def score_retrieval(case: dict, hits: list[dict]) -> dict:
    """Rank-sensitive retrieval scoring for one case."""
    units = [h["meta"]["unit"] for h in hits]
    expected = set(case.get("expect_units", []))
    rank = next((i for i, u in enumerate(units, 1) if u in expected), None)
    noise = sum(1 for h in hits
                if h["meta"].get("doc_type") in NOISE_DOC_TYPES)
    return {
        "retrieval_hit": rank is not None,
        "retrieval_rank": rank,
        "noise_ratio": round(noise / len(hits), 3) if hits else 0.0,
        "retrieved": [f"{h['meta']['source']} | {h['meta']['unit']}"
                      for h in hits],
    }


def score_answer(case: dict, answer: str, hits: list[dict]) -> dict:
    """Fact coverage, abstention and citation grounding for one case."""
    abstained = _is_abstention(answer)
    row = {"abstained": abstained, "answer": answer,
           "answer_excerpt": answer[:400]}

    if case.get("expect_abstain"):
        row["answer_ok"] = abstained
        return row

    matched = []
    for fact in case["expect_facts"]:
        alts = fact.split("||")
        matched.append(next((a for a in alts if _fact_match(a, answer)), None))
    row["answer_contains"] = matched
    row["answer_ok"] = all(m is not None for m in matched)
    row["false_abstention"] = abstained

    cited = _referenced_units(answer)
    retrieved_units = {_canon(h["meta"]["unit"]) for h in hits}
    retrieved_text = "\n".join(h["text"] for h in hits)
    seen_in_text = _referenced_units(retrieved_text)
    row["cites_expected"] = bool(
        cited & {_canon(u) for u in case.get("expect_units", [])})
    row["ungrounded_citations"] = sorted(
        cited - retrieved_units - seen_in_text)
    return row


def _load_existing() -> dict:
    """Resume support: previously completed cases (with both retrieval and
    answer results) are kept and skipped on rerun."""
    out = Path(__file__).resolve().parent.parent / "benchmark_results.json"
    if out.exists():
        try:
            rows = json.loads(out.read_text(encoding="utf-8"))
            return {r["id"]: r for r in rows if "answer_ok" in r}
        except Exception:  # noqa: BLE001
            pass
    return {}


def run(k: int, skip_llm: bool, resume: bool) -> None:
    out = Path(__file__).resolve().parent.parent / "benchmark_results.json"
    results = []
    if not skip_llm and resume:
        prev = _load_existing()
        if prev:
            print(f"resuming: {len(prev)} case(s) already complete, "
                  "will be skipped")
        results = list(prev.values())
    for case in CASES:
        if not skip_llm and any(r["id"] == case["id"] for r in results):
            print("SKIP", case["id"])
            continue
        negative = bool(case.get("expect_abstain"))
        hits = query.retrieve(case["q"], k=k)
        row = {"id": case["id"], "negative": negative}
        # Retrieval is only meaningful where an expected unit exists.
        row.update(score_retrieval(case, hits) if not negative
                   else {"retrieved": [f"{h['meta']['source']} | "
                                       f"{h['meta']['unit']}" for h in hits]})
        if not skip_llm:
            answer, used = query.answer(case["q"], k=k)
            row.update(score_answer(case, answer, used))
        results = [r for r in results if r["id"] != case["id"]] + [row]
        out.write_text(json.dumps(results, indent=2), encoding="utf-8")

        marks = []
        if not negative:
            marks.append(f"ret@{row['retrieval_rank']}"
                         if row["retrieval_hit"] else "ret MISS")
        if not skip_llm:
            marks.append("ans PASS" if row["answer_ok"] else "ans FAIL")
            if row.get("false_abstention"):
                marks.append("FALSE-ABSTAIN")
            if row.get("ungrounded_citations"):
                marks.append("ungrounded: "
                             + ",".join(row["ungrounded_citations"]))
        print(f"{case['id']:<28} " + "  ".join(marks), flush=True)
        time.sleep(2)  # keep GPU/CPU load low between cases

    rows = {r["id"]: r for r in results}
    ordered = [rows[c["id"]] for c in CASES if c["id"] in rows]
    out.write_text(json.dumps(ordered, indent=2), encoding="utf-8")
    report(ordered, k, skip_llm)
    print(f"\ndetails -> {out}")


def _pct(n: int, d: int) -> str:
    return f"{n / d:.0%} ({n}/{d})" if d else "n/a"


def report(rows: list[dict], k: int, skip_llm: bool) -> None:
    pos = [r for r in rows if not r.get("negative")]
    neg = [r for r in rows if r.get("negative")]

    print(f"\n{'=' * 52}\nRetrieval  ({len(pos)} answerable cases, k={k})")
    if pos:
        hit = [r for r in pos if r["retrieval_hit"]]
        mrr = sum(1 / r["retrieval_rank"] for r in hit) / len(pos)
        print(f"  hit-rate@{k}        {_pct(len(hit), len(pos))}")
        print(f"  MRR               {mrr:.2f}")
        if hit:
            ranks = sorted(r["retrieval_rank"] for r in hit)
            print(f"  median rank       {ranks[len(ranks) // 2]}")
            print(f"  worst rank        {ranks[-1]}")
        noise = sum(r["noise_ratio"] for r in pos) / len(pos)
        print(f"  non-operative     {noise:.0%} of retrieved passages")

    if skip_llm:
        return

    print(f"\nAnswers    ({len(pos)} answerable cases)")
    ok = sum(1 for r in pos if r["answer_ok"])
    print(f"  fact coverage     {_pct(ok, len(pos))}")
    false_abs = [r["id"] for r in pos if r.get("false_abstention")]
    print(f"  false abstention  {len(false_abs)}"
          + (f"  {false_abs}" if false_abs else ""))
    cites = sum(1 for r in pos if r.get("cites_expected"))
    print(f"  cites expected    {_pct(cites, len(pos))}")
    bad = {r["id"]: r["ungrounded_citations"] for r in pos
           if r.get("ungrounded_citations")}
    print(f"  ungrounded cites  {sum(len(v) for v in bad.values())}"
          + (f"  {bad}" if bad else ""))

    print(f"\nAbstention ({len(neg)} unanswerable cases)")
    declined = sum(1 for r in neg if r["answer_ok"])
    print(f"  correctly declined {_pct(declined, len(neg))}")
    wrong = [r["id"] for r in neg if not r["answer_ok"]]
    if wrong:
        print(f"  answered anyway    {wrong}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--retrieval-only", action="store_true")
    p.add_argument("--resume", action="store_true",
                   help="keep completed cases from a previous run instead of "
                        "re-running them (off by default, so a code change is "
                        "never measured against stale results)")
    args = p.parse_args()
    run(args.k, skip_llm=args.retrieval_only, resume=args.resume)
