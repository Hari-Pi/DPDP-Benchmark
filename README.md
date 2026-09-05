# Project 1 — DPDPA-Bench

**First open benchmark & test bench for faithful RAG over Indian data-protection law — with a compliance-checker app: describe your business model, get flagged DPDPA violations with clause citations**

- **Domain:** Gen AI / NLP / Legal Tech / Data Governance
- **Team:** 4–5 B.E. final year students
- **Compute:** Google Colab / Kaggle free tier sufficient
- **Status:** Idea approved for detailing (2026-08-25)

---

## 1. Problem

India's Digital Personal Data Protection Act (DPDPA 2023) is now the operative privacy law, and startups/SMEs must comply with it. Generic LLMs hallucinate on legal text — they invent section numbers, misstate obligations, and mix up GDPR with DPDPA. Any compliance assistant must answer with **verifiable, clause-level grounding** and must **abstain when it doesn't know**.

The practical gap founders actually face: they don't ask "what does Section 6 say?" — they ask **"I'm building X, am I breaking any DPDPA rules?"** (e.g., *"We scrape public profiles and sell the data to recruiters"*). There is no tool that maps a plain-English business description onto specific DPDPA obligations/violations with citations. Legal consultation is expensive; generic chatbots guess. This project builds both the benchmark that makes such a system measurable and a working compliance-checker demo on top of it.

## 2. Research gap

- RAG evaluation is a hot 2025/26 research area (RAGAS, hallucination-detection benchmarks), **but no public benchmark exists for Indian privacy law**.
- Existing legal-QA benchmarks focus on US/EU law (EU AI Act, GDPR, case law). DPDPA is untouched.
- Existing RAG eval metrics emphasize answer relevance; legal QA additionally needs **citation accuracy** and **abstention quality** — no standard harness measures these together.
- Whoever publishes the first benchmark + harness becomes the reference point future papers cite.

## 3. The contribution (the real deliverable)

The paper is the vehicle; the **artifacts** are the contribution:

1. **Clause-tagged DPDPA 2023 corpus** — the act split into sections/clauses with metadata (obligation type, actor: data fiduciary/processor, data-principal rights, penalties); optionally a DPDPA↔GDPR concept mapping table.
2. **Gold QA benchmark (~150–300 questions)** — each with answer + verified clause-level citations. LLM-assisted generation, then human verification by the team (split across 4–5 members). Question types:
   - **Factual** ("What is verifiable consent under Section 6?")
   - **Obligation** ("Must a fiduciary appoint a DPO?")
   - **Comparative** (DPDPA vs GDPR obligations)
   - **Unanswerable/adversarial** (to test abstention)
   - **Scenario/compliance** (new): a business-model description ("EdTech app tracking children without parental consent") → gold set of applicable clauses / violations / or "no violation / not determinable from the act"
3. **Compliance-checker application (the flagship demo)** — user describes their business model or idea in plain English; the RAG pipeline:
   - Extracts data-flow facts (what personal data, whose, purpose, consent, sharing, retention, cross-border)
   - Retrieves and maps relevant DPDPA clauses to each fact
   - Reports **compliant / potential violation / not covered by the act** per issue, each with the exact clause citation
   - **Abstains** when the description lacks enough detail or the issue falls outside DPDPA's scope (e.g., labor law, GDPR-only obligations)
   - Ships with a prominent **"research prototype, not legal advice"** disclaimer
4. **Open-source evaluation harness** measuring:
   - Faithfulness (answer supported by retrieved context)
   - Citation accuracy (does the cited clause actually support the claim?)
   - Hallucination rate
   - Abstention quality (correct refusal on unanswerable questions)
   - **Violation-detection metrics (for the compliance checker):** precision/recall on flagged clauses, false-positive rate (flagging compliant practices as violations), false-negative rate (missing real violations), and correct-abstention rate on out-of-scope scenarios
   - Standard RAGAS metrics (context precision/recall, answer relevancy)
5. **Baseline results table** — BM25 vs dense vs hybrid retrieval × several LLMs (open + API), on both the QA set and the scenario-compliance set. Future work compares against these numbers.

## 4. Data sources (all public)

- DPDPA 2023 full text — India Code / MeitY / official gazette
- DPDPA Rules draft (2025) — MeitY public consultation documents
- GDPR text (for cross-law transfer experiments) — EUR-Lex
- Synthetic QA generation via LLM, team-verified

## 5. Paper shape

**Working title:** *"DPDPA-Bench: A Benchmark and Evaluation Harness for Faithful Legal Question Answering and Compliance Checking on India's Digital Personal Data Protection Act"*

Benchmark/harness papers are citation magnets and are accepted from undergrad teams at:
- FIRE (Forum for Information Retrieval Evaluation) — India-based, undergrad-friendly
- IEEE conferences: CONECCT, ICCCNT, Pune Section conferences
- Springer LNCS conference proceedings
- MDPI / Frontiers AI journals (for an extended version)

## 6. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Annotation quality of gold QA pairs | LLM-draft → 2-person independent verify → adjudication; track inter-annotator agreement |
| Legal accuracy of answers & violation verdicts | Restrict claims to what's in the corpus; require exact clause citation for every flagged violation; disclaimer that it's a research benchmark/prototype, not legal advice |
| False positives in compliance checker eroding trust | Report precision/recall per clause in baselines; "potential violation" phrasing instead of definitive verdicts; abstain on vague scenarios |
| Liability perception of a "violation checker" | Frame as educational gap-analysis demo; never output fines/penalty amounts as advice; terms of use |
| Scope creep (whole Indian legal system) | Strictly DPDPA 2023 + draft rules only; anything outside → abstain |
| API costs for LLM baselines | Prefer open models (Llama 3.1 8B via Ollama, Gemma) + free tiers |

## 7. Rough roadmap (idea level)

1. Corpus build + clause tagging (with obligation/actor metadata for compliance mapping)
2. QA benchmark authoring + verification (incl. scenario/compliance gold set)
3. Harness implementation (faithfulness/citation/abstention + violation-detection metrics)
4. Compliance-checker pipeline (fact extraction → clause mapping → verdict + citation)
5. Baseline runs (retrievers × LLMs, on QA set and scenario set)
6. Analysis, failure taxonomy, paper writing

## 8. Averra alignment

Maps onto Averra's **Data Governance** (DPDPA 2023 module) and **Data Science & AI with Gen AI** (LLMs, RAG) courses — reusable as an academy showcase project and demo.

## 9. Validating references (collected 2026-08-25)

- RAGAS: Automated Evaluation of RAG — arXiv:2309.15217
- Real-Time Evaluation Models for RAG (hallucination detection benchmark) — arXiv:2503.21157
- MEGA-RAG (public-health RAG w/ hallucination mitigation) — Frontiers in Public Health, 2025
- Evaluating RAG Variants for Clinical QA — MDPI Electronics 14(21):4227, 2025
- Hallucination Mitigation for RAG-based LLMs: A Review — MDPI Mathematics 13(5):856, 2025
