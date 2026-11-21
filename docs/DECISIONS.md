# RAG Decisions (Week 2 deliverable)

Record each decision with: options tried, evidence (from `results/retrieval_experiment.csv`), and the choice.

## 1. Chunking
- Options: page · section · table-as-chunk · 300-token window.
- Evidence: _recall@1/3/5/10 per option_ (TBD)
- Decision: _TBD_

## 2. Embedding model
- Options: bge-small-en-v1.5 · bge-m3.
- Evidence: _TBD_
- Decision: _TBD_

## 3. Reranker
- Options: bge-reranker-v2-m3 · ms-marco-MiniLM-L-6-v2 · none.
- Evidence: _TBD_
- Decision: _TBD_

---

## Evidence so far (PROVISIONAL, 18 Nov 2026) — no decision taken yet

Run: `python eval/retrieval_experiment.py` on a Windows laptop, Python 3.11, Qdrant in Docker.
Embedding `BAAI/bge-small-en-v1.5`, reranker `cross-encoder/ms-marco-MiniLM-L-6-v2`, 27,862 word-window chunks.
72 test cases: an evaluation question and the page where the figure extractor found its figure.

| Mode | Company + year filter | recall@1 | recall@3 | recall@5 | recall@10 |
|------|-----------------------|----------|----------|----------|-----------|
| bm25 | yes | 0.014 | 0.028 | 0.028 | 0.042 |
| bm25 | no | 0.000 | 0.000 | 0.000 | 0.014 |
| dense | yes | 0.069 | 0.167 | 0.222 | 0.347 |
| dense | no | 0.014 | 0.083 | 0.125 | 0.222 |
| hybrid (RRF) | yes | 0.042 | 0.111 | 0.181 | 0.264 |
| hybrid (RRF) | no | 0.014 | 0.042 | 0.069 | 0.125 |
| hybrid + reranker | yes | 0.042 | 0.083 | 0.153 | 0.292 |
| hybrid + reranker | no | 0.014 | 0.069 | 0.125 | 0.181 |

What these numbers do and do not show:

- The company + year filter helps in every mode (dense recall@10: 0.347 with it, 0.222 without).
- Vector search is far ahead of keyword search on this test; fusing the two is worse than vector search alone,
  and the reranker does not help.
- Even the best mode finds the right page in the first 10 results for only about a third of the questions.
  Text search is a poor way to locate a figure in a statement table, which is why the agent reads figures from
  the figure store and not from search.
- Limits: the target pages are the extractor's, not hand-checked; all 72 targets are statement pages (tables).
  The agent uses search for TEXT pages (CASA or NPA ratios, risk and strategy summaries), and this run does not
  test those. Repeat it with `--source workbook --verified` when the gold workbook has pages for the reported
  ratios and the summary key points, before choosing the embedding model or the reranker.
- Not tested yet: other embedding models (bge-m3), the larger reranker (bge-reranker-v2-m3), chunking variants.

