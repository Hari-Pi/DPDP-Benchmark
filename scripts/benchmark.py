"""DPDP RAG benchmark: question -> expected source units and key facts.

Scored dimensions:
  retrieval_hit : at least one retrieved chunk is from an expected source unit
  answer_contains : the generated answer contains the expected fact strings

Run:  $env:PYTHONPATH='<repo root>'; python scripts/benchmark.py [--k 6]
"""
import argparse
import json
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
        "expect_facts": ["two hundred and fifty crore||250 crore||250"],
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
]


def _norm(s: str) -> str:
    return s.lower().replace(",", "").replace("₹", "").replace("  ", " ")


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
        hits = query.retrieve(case["q"], k=k)
        units = [h["meta"]["unit"] for h in hits]
        hit = any(u in units for u in case["expect_units"])
        row = {
            "id": case["id"],
            "retrieval_hit": hit,
            "retrieved": [f"{h['meta']['source']} | {h['meta']['unit']}"
                          for h in hits],
        }
        if not skip_llm:
            answer, _ = query.answer(case["q"], k=k)
            # each fact entry may carry alternatives separated by "||"
            matched = []
            for fact in case["expect_facts"]:
                alts = fact.split("||")
                m = next((a for a in alts if _norm(a) in _norm(answer)), None)
                matched.append(m)
            row["answer_contains"] = matched
            row["answer_ok"] = all(m is not None for m in matched)
            row["answer"] = answer  # full text for fact matching
            row["answer_excerpt"] = answer[:400]
        results = [r for r in results if r["id"] != case["id"]] + [row]
        out.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(("PASS" if hit else "FAIL"), case["id"],
              "" if skip_llm else ("PASS" if row.get("answer_ok") else "FAIL"),
              flush=True)
        time.sleep(2)  # keep GPU/CPU load low between cases

    rows = {r["id"]: r for r in results}
    ordered = [rows[c["id"]] for c in CASES if c["id"] in rows]
    n = len(ordered)
    n_ret = sum(1 for r in ordered if r["retrieval_hit"])
    print(f"\nRetrieval hit-rate: {n_ret / n:.0%} ({n_ret}/{n})")
    if not skip_llm:
        n_ans = sum(1 for r in ordered if r["answer_ok"])
        print(f"Answer fact coverage: {n_ans / n:.0%} ({n_ans}/{n})")
    out.write_text(json.dumps(ordered, indent=2), encoding="utf-8")
    print(f"details -> {out}")


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
