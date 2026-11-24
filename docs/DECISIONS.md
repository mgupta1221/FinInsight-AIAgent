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


---

## Decisions taken in the build (added 22 Nov 2026)

Written from `docs/CHANGES_AND_STATUS.md`. Sections 1 to 3 above (chunking, embedding, reranker) are still open:
see "Status of sections 1 to 3" at the end. Numbers are from practice runs and are replaced by the official runs.

### 4. The agent loop is plain Python, not a LangGraph graph

- Options: a LangGraph graph with the SQLite checkpointer; a plain Python function (`agent/graph.py`).
- What the loop is: guard → planner → executor → writer → critic → memory, in a fixed order, with one loop
  (writer and critic, up to three attempts). There is no branching that the model decides.
- Choice: plain Python.
- Why: the order of the stages is fixed, so a graph library adds nothing the code needs. A plain function is
  easier to read, to test with a scripted model (193 tests, no network) and to explain. Every stage still writes
  to a trace, and the limits (10 steps, 12,000 tokens) are checked in the loop. Memory is one small SQLite
  table, the role the checkpointer would play.
- What would change the choice: stages running in parallel, or the model choosing the next stage. Neither is
  needed for the question types in the SPEC.
- To do: record the mentor's reply here.

### 5. Statement figures come from a figure store, not from search

- Options: find the statement page by search and let the model read the figure; extract every statement line
  once at ingestion and read it by name.
- Evidence: the table in "Evidence so far" above: the best search mode finds the right statement page in the
  first 10 results for about a third of questions. Baseline (search + model): fact 12 of 18. Agent: 18 of 18.
- Choice: figure store (`store/statement_lines.csv`, about 14,000 lines), with the page kept for the citation.

### 6. The model never calculates

- Options: let the model work out ratios and changes; calculate in code from a glossary of formulas.
- Evidence: baseline year-on-year 3 of 12 (two figures, no percentage, or a wrong one); agent 12 of 12.
- Choice: formulas in `config/glossary.yaml` (separate ones for banks), arithmetic in the `calculate` tool,
  formula and inputs shown with the answer.

### 7. The check of the answer is code, not a second model call

- Options: ask the model to review its own answer; check in code.
- Choice: code (`agent/critic.py`): every number in the answer must be one of the figures used or the computed
  value, the formula must be the glossary formula, citations must be pages that were read, wording must not be
  advice. Up to three attempts; the last is a sentence template.
- Why: a small model reviewing itself agrees with itself. A code check is exact, costs no tokens and gives the
  same result every time.

### 8. Which statements a question means when it does not say

- Options: always consolidated (SPEC first draft); a default per company.
- Choice: per company (`default_scope` in `config/companies.yaml`): standalone for the banks and for Hindustan
  Unilever, ITC, Nestlé India and Britannia; consolidated for the IT companies and Dabur. Several companies:
  the majority. A question naming both scopes gets a question back.
- Why: these are the statements each company leads with, and the ones the gold answers were read from.
- To do: team to confirm the list.

### 9. Ratios the report prints (CASA, net interest margin, NPA) are read, not recomputed

- Options: compute from statement lines; read the printed ratio from the report text.
- Choice: read. NPA ratios by a text pattern; the others by letting the model point at the number, which code
  then verifies (printed on the cited page, a percentage between 0 and 100, up to three pages tried).
- Why: banks define these ratios with daily averages and regulatory adjustments that are not in the statements.
- Open: ICICI Bank net NPA, 0.35% (agent) against 0.33% (gold): two definitions in the report. Team to decide.

### 10. A summary is about one part of the report, with a page for every point

- Options: summarise the whole report; summarise one topic from a small set of passages.
- Choice: one topic (performance, risks, strategy, commentary, segments). Without a topic the agent asks which
  part. At most 9 passages from the section the search ranks best; each key point cites its page.
- Why: a report has 300 to 700 pages; a point without a page cannot be checked.
- Open: Nestlé discusses risks in two places (pages 41-42 and 199-201). Team to decide which the question means.

### 11. Memory keeps slots, and only after a verified answer

- Choice: company, year, scope, measure and intent of the last answer that passed the check; an unfinished
  question is kept for one reply. A self-contained new question does not inherit the old scope.
- Why: a wrong or refused answer must not shape the next one, and the model's context is small.

### 12. A person signs off anything that leaves the app

- Choice: an exported note is a DRAFT with a warning until a person ticks "checked" and clicks Approve; only
  verified answers can be exported (SPEC section 8).
- Changed 24 Nov 2026: the mentor asked for a direct export. The app now has one button, "Export to PDF", under
  the newest reply, and it exports the complete conversation; the Draft and Approve steps are commented out in the code. A reply that is not a verified answer is labelled as such in the PDF. What is kept from this
  decision: only a verified answer can be exported, and the PDF carries its citations and the line "Not
  investment advice". SPEC section 8 still describes Draft and Approve and needs a change note agreed by the team.

### 13. Tracing: a trace with every answer, kept in files; Langfuse is not used (added 22 Nov 2026)

- Options: send every run to Langfuse (a separate tracing service with its own database and web screen);
  keep the trace with the answer and write it to files.
- What is built:
  - Every answer carries its own trace: what the guard decided, the slots the model proposed, the plan, each
    step with its arguments and result, and each check of the critic with its reasons (`AgentAnswer.trace`).
  - The app shows it under "How I got this" and stores it with the conversation in `store/memory.sqlite`.
  - Every evaluation run writes `traces.jsonl` beside its results, one line per question, with personal
    details masked.
- Langfuse: the settings exist in `config.py` and `.env.example`, and `docker-compose.yml` can start the
  service, but no code sends anything to it. With the keys left empty nothing changes.
- Choice: files. Why: the trace is needed in two places, beside the answer on the screen and beside the score in
  an evaluation run, and both are covered without another service to install, start and keep running on every
  member's laptop. A file is also easy to hand in with the results.
- What Langfuse would add: a web screen to browse and search runs, and timing per model call. Useful for a
  system in production; not needed to answer "how was this answer produced" for 90 questions.
- To do: confirm with the mentor that file traces meet the tracing requirement.

### Status of sections 1 to 3

| Decision | In use now | Evidence | Status |
|---|---|---|---|
| Chunking | Word-window chunks with a header line (company, year, scope, section, page); about 28,700 chunks | None: only one variant was built | Open. Either run the study with three variants or record that one variant was used and why |
| Embedding | `BAAI/bge-small-en-v1.5` | Provisional table above (statement pages only) | Open. Not compared with another model |
| Reranker | As set in `.env` (`RERANKER_MODEL`); the provisional run used `cross-encoder/ms-marco-MiniLM-L-6-v2` | Provisional table above: no gain on statement pages | Open. Not tested on text pages, where the agent uses search |

The gold workbook now has pages for the reported ratios and the summary key points, so
`python eval/retrieval_experiment.py --source workbook --verified` can be run for text pages.
