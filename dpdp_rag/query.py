"""Retrieval + generation with section-level citations."""
import math
import re
import time
from collections import Counter
from datetime import date

import chromadb
from ollama import Client

from . import config

_STOP = {"the", "and", "for", "must", "how", "what", "which", "does", "did",
         "with", "that", "from", "are", "was", "were", "has", "have", "not",
         "can", "may", "within", "into", "under", "any", "its", "their"}

_BM25_K1, _BM25_B = 1.5, 0.75

# How much weight a source's rank carries, by what it is. The corpus mixes the
# law in force with superseded drafts, a consultation record and a third-party
# explainer; the draft Rules alone are the largest source in it, so without
# this they crowd out the operative text. A graded weight demotes them while
# still letting them win when they are plainly what was asked about — unlike
# the previous hard tier split, which ordered every tier-1 chunk ahead of
# every tier-2 one and in practice only ever demoted the FAQ.
AUTHORITY = {
    "act": 1.0,             # the Act as in force
    "rules": 1.0,           # the Rules as corrected
    "notification": 1.0,    # commencement / establishment notifications
    "corrigendum": 1.0,     # corrections to the Rules
    "parliament_qa": 0.9,   # official, but secondary reporting
    "summary": 0.8,         # consultation record, not law
    "faq": 0.7,             # third-party explainer
    "draft_rules": 0.65,    # superseded by the final Rules
}

# Prompt budgeting. num_ctx has to cover the system prompt, history, retrieved
# context and the generated answer; anything over the limit is dropped by
# Ollama without warning, so we trim deliberately instead.
CTX_SAFETY = 192        # slack for chat-template scaffolding
MSG_OVERHEAD = 8        # per-message role/delimiter tokens
BLOCK_OVERHEAD = 12     # per-passage separator and citation header
HISTORY_SHARE = 0.25    # cap on the share of the budget history may take
_bm25_cache: dict = {"size": None, "docs": None, "df": None, "avgdl": 0.0}


def _retry(fn, *, what: str, attempts: int = 5, base_wait: float = 5.0):
    """Run an Ollama call with exponential backoff.

    Survives transient GPU OOM / server restarts so long pipelines (ingest,
    benchmark) can wait out a recovery instead of dying mid-run.
    """
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            wait = base_wait * (2 ** i)
            print(f"[retry] {what} failed ({e}); backing off {wait:.0f}s "
                  f"({i + 1}/{attempts})")
            time.sleep(wait)
    raise RuntimeError(f"{what} failed after {attempts} attempts") from last


def _client() -> Client:
    return Client(host="http://localhost:11434")


def _tokenize(text: str) -> list[str]:
    return [_stem(t) for t in
            re.findall(r"[a-z][a-z\-]{2,}|\d{2,}", text.lower())
            if t not in _STOP]


def _bm25_search(question: str, n: int) -> list[dict]:
    """In-process BM25 over the whole collection (corpus is small).

    This guarantees keyword-only matches (e.g. the corrigendum or penalty
    schedule) are always candidates, even when dense retrieval misses them.
    """
    client = chromadb.PersistentClient(path=str(config.DB_DIR))
    col = client.get_or_create_collection(
        config.COLLECTION, metadata={"hnsw:space": "cosine"})
    total = col.count()
    if _bm25_cache["size"] != total or _bm25_cache["docs"] is None:
        got = col.get(include=["documents", "metadatas"])
        docs = []
        df: Counter = Counter()
        for doc, meta in zip(got["documents"], got["metadatas"]):
            tokens = _tokenize(doc)
            docs.append({"text": doc, "meta": meta, "tokens": tokens,
                         "len": len(tokens)})
            df.update(set(tokens))
        _bm25_cache.update(size=total, docs=docs, df=df,
                           avgdl=sum(d["len"] for d in docs) / max(len(docs), 1))
    docs, df, avgdl = (_bm25_cache["docs"], _bm25_cache["df"],
                       _bm25_cache["avgdl"])
    n_docs = len(docs)
    q_tokens = _tokenize(question)
    scored = []
    for d in docs:
        tf = Counter(d["tokens"])
        score = 0.0
        for t in q_tokens:
            if t not in tf:
                continue
            idf = math.log(1 + (n_docs - df[t] + 0.5) / (df[t] + 0.5))
            f = tf[t]
            score += idf * f * (_BM25_K1 + 1) / (
                f + _BM25_K1 * (1 - _BM25_B + _BM25_B * d["len"] / avgdl))
        if score > 0:
            scored.append({"text": d["text"], "meta": d["meta"],
                           "bm25": score})
    scored.sort(key=lambda h: -h["bm25"])
    return scored[:n]


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


SYSTEM_PROMPT_TEMPLATE = """You are a legal research assistant specialised in
India's Digital Personal Data Protection Act, 2023 (DPDP Act) and the Digital
Personal Data Protection Rules, 2025 (DPDP Rules).

Rules:
- Answer ONLY from the provided context. If the context does not contain the
  answer, say so explicitly instead of guessing.
- Cite every claim with its source, e.g. (DPDP Act 2023, s. 8(5)) or
  (DPDP Rules 2025, r. 7(2)(b)). Use the exact source labels shown in the
  context. When citing the draft rules, always say "Draft DPDP Rules 2025".
- Quote key phrases verbatim where useful.
- Do not provide legal advice; note that this is general legal information.

Working out what is in force:
- Today's date is {today}.
- The commencement notification G.S.R. 843(E) sets the trigger dates as
  offsets from its own publication, and Rule 1 does the same for the Rules.
  Where a passage gives an offset ("one year", "eighteen months"), work the
  calendar date out from the publication date in that passage and show it.
- The draft Rules are superseded. Prefer the DPDP Rules 2025 for the law as
  made, and say so when a passage is from the draft.
- Answer from the context even where it conflicts with anything you recall
  from training; the retrieved gazette text is authoritative here.
"""


def system_prompt() -> str:
    """The prompt carries behaviour and today's date only.

    It used to also state which provisions were in force on which dates, the
    Board's appointment status and so on. That was ungrounded (the model
    could not cite it), it went stale the moment it was written, and it let
    the commencement benchmark cases pass on memorisation rather than on
    retrieval. All of it is in the corpus as primary source — the schedule in
    G.S.R. 843(E) and Rule 1, the Board's status in the Lok Sabha answers.
    """
    return SYSTEM_PROMPT_TEMPLATE.format(today=date.today().strftime("%d %B %Y"))



def _hybrid_rerank(question: str, dense: list[dict], bm25: list[dict],
                   k: int) -> list[dict]:
    """Fuse dense and BM25 rankings, then weight each hit by how
    authoritative its source is (see AUTHORITY)."""
    by_id = {}
    for rank, h in enumerate(dense):
        h = dict(h)
        h["dense_rank"] = rank
        by_id[h["meta"]["unit"] + f"#{h['meta']['part']}:" + h["text"][:40]] = h
    for rank, h in enumerate(bm25):
        key = h["meta"]["unit"] + f"#{h['meta']['part']}:" + h["text"][:40]
        h = by_id.setdefault(key, dict(h))
        h.setdefault("dense_rank", len(dense) + rank)
        h["bm25_rank"] = rank

    hits = list(by_id.values())
    nd, nb = max(len(dense), 1), max(len(bm25), 1)
    for h in hits:
        dense_score = 1 - h.get("dense_rank", nd) / nd
        bm25_score = 1 - h.get("bm25_rank", nb) / nb
        h["authority"] = AUTHORITY.get(h["meta"].get("doc_type"), 0.8)
        h["score"] = (0.55 * dense_score + 0.45 * bm25_score) * h["authority"]
    ranked = sorted(hits, key=lambda h: -h["score"])
    return ranked[:k]


def retrieve(question: str, k: int = config.TOP_K) -> list[dict]:
    chroma = chromadb.PersistentClient(path=str(config.DB_DIR))
    col = chroma.get_or_create_collection(
        config.COLLECTION, metadata={"hnsw:space": "cosine"})
    emb = _retry(
        lambda: _client().embed(
            model=config.EMBED_MODEL,
            input=[f"search_query: {question}"])["embeddings"][0],
        what="embed query")
    res = col.query(query_embeddings=[emb],
                    n_results=min(max(16, k * 2), col.count() or 16),
                    include=["documents", "metadatas", "distances"])
    dense = [{"text": doc, "meta": meta, "distance": dist}
             for doc, meta, dist in zip(res["documents"][0],
                                        res["metadatas"][0],
                                        res["distances"][0])]
    bm25 = _bm25_search(question, n=max(16, k * 2))
    return _hybrid_rerank(question, dense, bm25, k)


def _block(hit: dict, n: int = 0) -> str:
    """Render one context passage. Shared with the budget so what we measure
    is exactly what we send.

    Chunks embed their own source label so the embedding carries that context,
    but the block header states it too. Repeating it made several passages
    open with identical lines — with the penalty Schedule split per entry,
    three blocks began the same way and the model answered from the wrong one.
    """
    m = hit["meta"]
    text = hit["text"]
    embedded = f"{m['source'].split(' (')[0]}, {m['unit']}."
    first, sep, rest = text.partition("\n")
    if sep and first.strip() == embedded:
        text = rest
    return f"[{n}] {m['source']}, {m['unit']}\n{text}"


def build_context(hits: list[dict]) -> str:
    return "\n\n---\n\n".join(_block(h, i) for i, h in enumerate(hits, 1))


def _tokens(text: str) -> int:
    """Rough token count. Gazette text packs numbers, brackets and section
    references, so it tokenises denser than prose — estimate conservatively."""
    return int(len(text) / 3.4) + 1


def _fit_history(history: list[dict], budget: int) -> list[dict]:
    """Keep the most recent whole turns that fit the budget."""
    kept, used = [], 0
    for msg in reversed(history):
        cost = _tokens(msg["content"]) + MSG_OVERHEAD
        if used + cost > budget:
            break
        kept.append(msg)
        used += cost
    kept.reverse()
    if kept and kept[0]["role"] == "assistant":
        kept = kept[1:]     # never open on a reply whose question was trimmed
    return kept


def _fit_context(hits: list[dict], budget: int) -> list[dict]:
    """Keep the highest-ranked hits that fit, always keeping at least one."""
    kept, used = [], 0
    for h in hits:
        cost = _tokens(_block(h)) + BLOCK_OVERHEAD
        if kept and used + cost > budget:
            break
        kept.append(h)
        used += cost
    return kept


def answer(question: str, k: int = config.TOP_K, model: str = config.CHAT_MODEL,
           history: list[dict] | None = None) -> tuple[str, list[dict]]:
    """Return the generated answer and the hits actually used, so callers cite
    only what the model saw.

    The prompt is fitted to num_ctx before sending: Ollama truncates silently,
    so an over-long prompt would quietly drop the system instructions or the
    earliest context instead of failing.
    """
    hits = retrieve(question, k)
    history = history or []

    prompt = system_prompt()
    budget = (config.NUM_CTX - config.MAX_OUTPUT_TOKENS - CTX_SAFETY
              - _tokens(prompt) - _tokens(question))
    kept_history = _fit_history(history, int(max(budget, 0) * HISTORY_SHARE))
    budget -= sum(_tokens(m["content"]) + MSG_OVERHEAD for m in kept_history)
    kept = _fit_context(hits, budget)

    if len(kept) < len(hits) or len(kept_history) < len(history):
        print(f"[budget] num_ctx={config.NUM_CTX}: kept {len(kept)}/{len(hits)} "
              f"passages, {len(kept_history)}/{len(history)} history messages")

    context = build_context(kept)
    messages = [{"role": "system", "content": prompt}]
    messages.extend(kept_history)
    messages.append({
        "role": "user",
        "content": f"Context:\n\n{context}\n\nQuestion: {question}",
    })
    resp = _retry(
        lambda: _client().chat(
            model=model, messages=messages,
            options={"temperature": 0.1, "num_ctx": config.NUM_CTX,
                     "num_predict": config.MAX_OUTPUT_TOKENS}),
        what="chat completion")
    return resp["message"]["content"], kept
