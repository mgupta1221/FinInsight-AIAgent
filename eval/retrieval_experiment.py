"""Compare the search modes: how often does each one find the page that holds the answer?

NEW FILE (18 Nov 2026). This is the retrieval experiment behind docs/DECISIONS.md.

For every test case (a question and the report page where its figure is printed) the script searches in four
modes, each with and without the company + year filter, and checks whether the right page is among the first
1, 3, 5 and 10 passages returned:

    bm25            keyword search only
    dense           vector (embedding) search only
    hybrid          both, fused with reciprocal rank fusion (RRF)
    hybrid+rerank   the fused list re-ordered by the reranker model

Where the test cases come from (chosen automatically, or with --source):
    workbook   eval/gold_workbook.xlsx: every input row with a page typed in by the author. Use --verified to
               keep only rows where the verifier agrees. This is the real experiment.
    store      the page where the figure extractor found each figure. Available at once, but PROVISIONAL:
               those pages are not hand-checked.

Run from the project root (needs the built index: python -m ingest.run_ingest):
    python eval/retrieval_experiment.py
    python eval/retrieval_experiment.py --source workbook --verified
It prints the table and writes results/retrieval_experiment.csv. No model endpoint is called.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "eval")]

from finsight import embeddings  # noqa: E402
from finsight.config import settings  # noqa: E402
from finsight.retrieval.bm25 import bm25_search  # noqa: E402
from finsight.retrieval.dense import dense_search  # noqa: E402
from finsight.retrieval.hybrid import rrf_fuse  # noqa: E402
from finsight.retrieval.reranker import rerank  # noqa: E402

OUT = ROOT / "results" / "retrieval_experiment.csv"
KS = (1, 3, 5, 10)
MODES = ("bm25", "dense", "hybrid", "hybrid+rerank")
POOL = 30                                   # candidates taken from each search before fusing / reranking


def cases_from_workbook(path: Path, verified: bool = False) -> list[dict]:
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    questions = {r[0]: r[2] for r in wb["Questions"].iter_rows(min_row=2, values_only=True) if r[0]}
    ws = wb["Inputs"]
    col = {c.value: i for i, c in enumerate(ws[1])}
    out, seen = [], set()
    for r in ws.iter_rows(min_row=2, values_only=True):
        page = r[col["page_author"]]
        if page in (None, "") or r[col["question_id"]] not in questions:
            continue
        if verified and (r[col["page_verifier"]] in (None, "") or int(r[col["page_verifier"]]) != int(page)):
            continue
        key = (r[col["question_id"]], r[col["company"]], str(r[col["read_from_report"]]), int(page))
        if key not in seen:
            seen.add(key)
            out.append({"id": key[0], "query": questions[key[0]], "ticker": key[1], "fiscal_year": key[2], "page": key[3]})
    # The summary questions: each key point's page is a target too. These are TEXT pages (risks, strategy), the
    # kind of page the agent really uses search for; the figure rows above are mostly statement tables.
    meta = {r[0]: r for r in wb["Questions"].iter_rows(min_row=2, values_only=True) if r[0]}
    for r in wb["KeyPoints"].iter_rows(min_row=2, values_only=True):
        qid, page, verified_by = r[0], r[3], r[5]
        if qid not in meta or page in (None, "") or not r[2] or (verified and not verified_by):
            continue
        key = (qid, str(meta[qid][3]).split(",")[0].strip(), str(meta[qid][4]), int(page))
        if key not in seen:
            seen.add(key)
            out.append({"id": qid, "query": questions[qid], "ticker": key[1], "fiscal_year": key[2], "page": key[3]})
    return out


def cases_from_store() -> list[dict]:
    import make_gold_workbook as mg
    out, seen = [], set()
    for q in mg.load_questions():
        d = mg.describe(q)
        for inp in d["inputs"]:
            page = mg.page_hint(inp, d["scope"])
            key = (q["id"], inp["company"], inp["read_from_report"], page)
            if page and key not in seen:
                seen.add(key)
                out.append({"id": q["id"], "query": q["question"], "ticker": inp["company"], "fiscal_year": inp["read_from_report"], "page": int(page)})
    return out


def search(mode: str, query: str, flt: dict | None, store) -> list[dict]:
    """The first 10 passages for `query` in one mode. `store` is a QdrantStore, or None for bm25."""
    if mode == "bm25":
        return bm25_search(query, top_k=10, flt=flt)
    if mode == "dense":
        return dense_search(store, query, top_k=10, flt=flt)
    fused = rrf_fuse([dense_search(store, query, top_k=POOL, flt=flt), bm25_search(query, top_k=POOL, flt=flt)], key="id")
    return fused[:10] if mode == "hybrid" else rerank(query, fused[:POOL], top_k=10)


def found_at(hits: list[dict], case: dict) -> int | None:
    """1-based rank of the first passage from the right company, year and page; None if not in the list."""
    for rank, h in enumerate(hits, 1):
        if h.get("ticker") == case["ticker"] and str(h.get("fiscal_year")) == case["fiscal_year"] and int(h.get("page", -1)) == case["page"]:
            return rank
    return None


def run(cases: list[dict], store=None, modes=MODES, searcher=search) -> list[dict]:
    rows = []
    for mode in modes:
        for filtered in (True, False):
            ranks = []
            for c in cases:
                flt = {"ticker": c["ticker"], "fiscal_year": c["fiscal_year"]} if filtered else None
                ranks.append(found_at(searcher(mode, c["query"], flt, store), c))
            row = {"mode": mode, "company_year_filter": "yes" if filtered else "no", "cases": len(cases)}
            for k in KS:
                row[f"recall@{k}"] = round(sum(1 for r in ranks if r is not None and r <= k) / len(cases), 3) if cases else 0.0
            rows.append(row)
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["auto", "workbook", "store"], default="auto")
    ap.add_argument("--verified", action="store_true", help="workbook rows only where the verifier's page agrees")
    ap.add_argument("--limit", type=int, help="use only the first N test cases (quick try)")
    ap.add_argument("--modes", default=",".join(MODES), help="comma-separated subset, e.g. bm25 (needs no vector index)")
    args = ap.parse_args()

    workbook = ROOT / "eval" / "gold_workbook.xlsx"
    cases, source = [], args.source
    if source in ("auto", "workbook") and workbook.exists():
        cases = cases_from_workbook(workbook, verified=args.verified)
        source = "workbook" + (" (verified pages)" if args.verified else " (author pages)")
    if not cases:
        if args.source == "workbook":
            sys.exit("No pages are filled in eval/gold_workbook.xlsx yet. Run without --source to use the figure-store pages.")
        cases, source = cases_from_store(), "figure store (PROVISIONAL: pages not hand-checked)"
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        sys.exit("No test cases. Build the figure store first: python -m ingest.run_ingest --figures-only")

    modes = tuple(m.strip() for m in args.modes.split(",") if m.strip() in MODES)
    store, embed = None, "not used"
    if modes != ("bm25",):
        from finsight.retrieval.qdrant_store import QdrantStore
        store = QdrantStore()
        embeddings.encode(["warm up"])                               # loads the model, so the label below is right
        embed = "FALLBACK hashing embedding (sentence-transformers not installed)" if embeddings._use_fallback else settings.embedding_model
    print(f"Test cases: {len(cases)} from {source}\nEmbedding: {embed}\nReranker: {settings.reranker_model}\n")
    rows = run(cases, store, modes=modes)
    header = ["mode", "company_year_filter", "cases"] + [f"recall@{k}" for k in KS]
    print("  ".join(f"{h:>19}" for h in header))
    for r in rows:
        print("  ".join(f"{str(r[h]):>19}" for h in header))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["source", "embedding", "reranker"] + header)
        w.writeheader()
        for r in rows:
            w.writerow({"source": source, "embedding": embed, "reranker": settings.reranker_model, **r})
    print(f"\nWritten to {OUT.relative_to(ROOT)}. Copy the numbers into docs/DECISIONS.md with the choice they support.")
