# FinSight — Multi-Agent Financial Report Q&A Copilot

**Technical report — DRAFT of 22 Nov 2026.** Track B (model of at most 8B parameters).
Team: [TO FILL: team number and member names].

> Draft status. Sections 1 to 7 and 9 to 12 describe what is built and can be reviewed now. The numbers in
> section 8 are from **practice runs** and are marked as such; they are replaced by the official runs after
> the freeze. Every place that still needs input is marked **[TO FILL]**.

## 1. Summary

FinSight answers questions about the annual reports of 15 companies listed on the NSE (five IT services, five
consumer goods, five banks) for FY2024-25 and FY2025-26. It runs on a Qwen3-8B model behind an OpenAI-compatible
endpoint.

The design follows from one observation: a small model is unreliable at arithmetic, at reading figures out of
statement tables and at judging its own answer. So the model is given three small jobs (fill the slots of a
plan, point at a number in a page of text, word the answer) and everything else is code: reading statement
figures from a store built at ingestion, calculating with formulas from a glossary, checking every number in
the answer against its source, and refusing what is out of scope.

On 90 questions with gold answers, a practice run of the agent scored 84 (93.3%) against 37 (41.1%) for the
baseline of one search and one model answer. [TO FILL: official numbers, mean and range of three runs each.]

## 2. Problem and scope

| | |
|---|---|
| Users | A reader of annual reports who wants a figure, a ratio, a comparison or a short summary, with the page it came from |
| Corpus | 30 annual reports: 15 companies × 2 fiscal years (`config/companies.yaml`, `data/report_sources.csv`) |
| Question types | Fact, ratio, year-on-year change, comparison and ranking, multi-step questions from the notes, summary of one topic |
| Also handled | A question back when the question is incomplete; refusal of advice, forecasts and insider information; "not in the reports" for other companies and years; instructions planted in a question or a page |
| Not handled | Investment advice, forecasts, share prices, quarterly results, anything outside the 30 reports |
| Answer format | One sentence with the value and unit, the formula, the input figures with their pages, caveats, and a trace of the steps (`docs/SPEC.md` section 6) |

The rules are in `docs/SPEC.md`: scope, refusal policy, conventions (fiscal year, units in crore, standalone
and consolidated), the glossary of formulas, the answer and citation format, and the human-in-the-loop boundary.

## 3. Data

- **Reports.** 30 PDFs of 300 to 700 pages, downloaded from the companies' and the exchanges' websites. They
  are not in the repository. `data/report_sources.csv` records for each file its address, download date and
  SHA-256 checksum, so the exact file can be fetched and verified (`scripts/hash_reports.py`).
- **Parsing.** `ingest/parse.py` reads the text layer page by page (PyMuPDF). One report used a private font
  that turned digits into other characters; these are mapped back at parsing.
- **Figure store.** `ingest/statements.py` finds the balance sheet, the profit and loss statement and the cash
  flow statement, standalone and consolidated, and writes every line to `store/statement_lines.csv` (about
  14,000 lines: company, year, scope, statement, label, value, unit, page, and the previous-year column).
  A quality gate refuses a report in which the main statements are not found.
- **Text index.** The pages are cut into chunks (about 28,700), each with a header line (company, year, scope,
  section, page), embedded with `BAAI/bge-small-en-v1.5` and stored in Qdrant; a BM25 index is built over the
  same chunks.

## 4. Architecture

```
question
   │
 guard ──────────► refused (advice, forecast, insider information, not in the corpus)
   │
 planner ────────► clarify (company, year, measure or scope cannot be settled)
   │   model fills slots → code validates them and builds the steps
 executor
   │   figure store · glossary formulas · calculate · compare/rank · search (text pages only)
 writer
   │   model words the answer (last attempt: a sentence built by code)
 critic ─────────► up to 3 attempts → "Unverified, please check page …"
   │   code: numbers, formula, citations, wording
 memory            slots of the last verified answer (SQLite)
   │
 answer: value · formula · figures with pages · caveats · trace
```

The loop is a plain Python function (`src/finsight/agent/graph.py`); see section 5.

| Stage | Who does it | What it does |
|---|---|---|
| Guard | Code | Refuses advice, forecasts, insider information; companies and years outside the corpus |
| Planner | Model, then code | The model proposes intent, companies, years, measure and scope in a small schema. Code accepts a measure only if the question names it, takes companies from a name list, reads years by pattern, applies the default scope, and asks back if something is missing |
| Executor | Code (model for one sub-step) | Runs the steps: reads figures, applies the formula, compares. For a ratio printed in the report the model points at the number and code verifies it. Limits: 10 steps, 12,000 tokens |
| Writer | Model, then code | Words the answer from the result. The third attempt is a fixed sentence template |
| Critic | Code | Every number in the answer must be a figure used or the computed value; the formula must be the glossary's; citations must be pages that were read; no advice wording |
| Memory | Code | Saves the slots of an answer that passed the check; keeps an unfinished question for one reply |

**Tools** (`src/finsight/tools/`): `get_company_profile`, `get_financial_item` (figure store),
`calculate` (glossary formulas), `compare_rank`, `normalise_units`, `search_report` (BM25 + vectors, fused,
reranked, with a company and year filter), `read_table`, `create_note_draft`.

**Glossary** (`config/glossary.yaml`): 11 measures for non-banks (operating margin, EBITDA margin, net profit
margin, year-on-year change, debt-to-equity, current ratio, return on equity, return on capital employed,
earnings per share, effective tax rate, share of short-term borrowings) and 9 for banks (gross and net NPA
ratio, net interest margin, CASA ratio, cost-to-income, return on assets, capital adequacy, effective tax rate,
provision coverage). Eight of them are printed by the reports themselves and are read from the text.

**Statuses.** Every answer has one of four: *answered*, *clarify*, *refused*, *escalated* (the agent could not
complete or verify the answer and says so).

## 5. Design decisions

Each decision, its alternatives and the evidence are in `docs/DECISIONS.md`. In short:

| Decision | Choice | Main reason |
|---|---|---|
| Agent loop | Plain Python, not a LangGraph graph | The stages run in a fixed order; a function is simpler to test and to explain |
| Statement figures | Figure store built at ingestion | Search finds the right statement page in the top 10 for about a third of questions |
| Arithmetic | Code, with glossary formulas | The baseline answered 3 of 12 year-on-year questions |
| Checking the answer | Code, not a second model call | Exact, repeatable, costs no tokens |
| Scope not stated | A default per company | Follows the statements each company leads with |
| Ratios printed in the report | Read from the text and verified | Banks define them with data that is not in the statements |
| Summaries | One topic, a page for every point | A point without a page cannot be checked |
| Memory | Slots of the last verified answer only | A wrong answer must not shape the next one |
| Notes | DRAFT until a person approves | SPEC section 8 |

Open: chunking, embedding model and reranker were not chosen by experiment (one configuration was built).
[TO FILL: either the results of the retrieval study or a sentence stating this as a limitation.]

## 6. What was done to compensate for a small model

The full log, with before and after, is `docs/SMALL_MODEL_FIXES.md`. The pattern in every row is the same:
take the task away from the model, or keep the model's output and verify it in code.

| Weakness | Compensation |
|---|---|
| Arithmetic | The model never calculates |
| Reading tables | Figures come from the figure store |
| Wrong or invented slots | Code validates each slot against the words of the question |
| Answering a vague question | Code asks back |
| Unsafe requests, planted instructions | A guard in code, before the model |
| Pointing at the wrong number in text | Must be on the cited page; a percentage must be 0 to 100; three pages tried |
| Changing a number while wording | Critic in code; template on the last attempt |
| Labels in place of sentences in summaries | Prompt asks for full sentences; critic rejects short points; reason fed back |
| Following whatever passages it is given | Passages chosen by section; an instruction line per kind of topic |
| Small context | Memory keeps slots, not text; limits on steps, tokens and passages |

## 7. Evaluation method

- **Questions.** 90, written before the agent was built (`eval/eval_set.jsonl`): fact 18, ratio 16,
  year-on-year 12, comparison 14, multi-step 6, summary 8, clarify 6, refuse 6, not in the corpus 2, planted
  instruction 2.
- **Gold answers.** For numeric questions the team typed the input figures and pages from the reports into
  `eval/gold_workbook.xlsx`; a second member re-read every figure; `eval/compute_gold.py` computes the gold
  value from the inputs with the glossary formula. For a ratio the report prints, the printed value and its page
  were typed. No gold value was taken from the agent.
  Summaries have five gold key points each, with pages.
- **Scoring** (`eval/score.py`). A number is correct within 0.5% (or 0.006 absolute for small ratios), in the
  expected scope. Clarify, refuse and not-in-corpus questions are correct if the status is the expected one.
  A summary is correct if it covers at least 70% of the gold key points; coverage is first estimated by word
  overlap and then decided by a person in `summary_review.csv`.
- **Other measures** (`eval/metrics.py`). Share of answers that cite a page, share where a cited page is a gold
  page, share of computed answers that show a formula, share within the step and token limits, steps, tokens
  and seconds per question.
- **Causes of error** (`eval/taxonomy.py`). Each wrong answer is labelled: control (wrong status), tool call
  error, retrieval miss, unit error, wrong period or statement, wrong item, calculation error, hallucination.
- **Baseline.** One search of the reports and one model answer over the same 90 questions
  (`python eval/run_eval.py --mode simple`).
- **Practice and official runs.** While fixing, runs were practice runs (`results/runs/`, not committed). After
  the freeze of code and gold answers, three official runs of each mode are made (`results/official/`); each
  records the code version.
- **Unit tests.** 193 tests with a scripted model; they need no key, reports or network and run on every push.

## 8. Results

> **Practice runs, not final.** Agent: `2026-11-21_183017_agent`. Baseline: `2026-11-21_163005_simple`.
> [TO FILL after the official runs: replace this table by mean and range of three runs per mode.]

| Question type | n | Baseline | Agent |
|---|---|---|---|
| Fact | 18 | 12 (66.7%) | 18 (100%) |
| Ratio | 16 | 9 (56.2%) | 15 (93.8%) |
| Year-on-year | 12 | 3 (25.0%) | 12 (100%) |
| Comparison | 14 | 5 (35.7%) | 14 (100%) |
| Multi-step | 6 | 2 (33.3%) | 5 (83.3%) |
| Summary (word count, before the person's review) | 8 | 0 (0%) | 4 (50.0%) |
| Clarify | 6 | 0 (0%) | 6 (100%) |
| Refuse | 6 | 4 (66.7%) | 6 (100%) |
| Not in the corpus | 2 | 0 (0%) | 2 (100%) |
| Planted instruction | 2 | 2 (100%) | 2 (100%) |
| **All** | **90** | **37 (41.1%)** | **84 (93.3%)** |

| Measure | Baseline | Agent |
|---|---|---|
| Answers that cite a page | 100% | 100% |
| A cited page is a gold page | 22.4% | 91.9% |
| Computed answers that show a formula | 2.9% | 97.0% |
| Within the step and token limits | 100% | 100% |
| Average per question | 5.2 s | 1.3 steps, 1,991 tokens, 4.8 s |

### Without the reports

The same 90 questions were also put to the model with no report text, in four prompting styles (practice runs of
22 Nov 2026; `results/week1_strategies.csv`).

| | Closed-book | Few-shot | Step by step ×5 | Decomposition | Simple search | Agent |
|---|---|---|---|---|---|---|
| Correct of 90 | 13 | 12 | 8 | 7 | 37 | 84 |
| Figures correct of 52 (fact, ratio, year-on-year, multi-step) | 0 | 0 | 0 | 0 | 26 | 50 |
| Invented figures | 1 | 2 | 3 | 24 | 19 | 0 |

Without the reports the model gets no figure right; the reports are newer than its training. More elaborate
prompting does not help and decomposition makes it invent figures. What the model can do alone is refuse advice
and ask back; that is what simple search loses and the agent keeps.

How the agent's score moved over the practice runs: 79, 79, 81, 84, 84 of 90. The changes between runs are
listed in `docs/CHANGES_AND_STATUS.md` (sections 35 to 42); each was a general rule, not a rule for one question,
and no gold answer was changed to match the agent.

## 9. Error analysis

**Agent — the six wrong answers of the practice run.**

| Question | What happened | Kind |
|---|---|---|
| ratio-012, ICICI Bank net NPA | Agent 0.35%, gold 0.33%: the report gives two definitions | A definition to decide, not a fault of reading |
| multihop-006, SBI | Needs numbers from two different text pages; the agent says it cannot verify the share and declines | Known limit; no wrong number given |
| summary-003 HDFC Bank, summary-005 Wipro | 3 of 5 gold points covered | One point short |
| summary-004 Hindustan Unilever | Reads the right pages; wording differs from the gold points | For the person's review |
| summary-008 Nestlé | The report discusses risks in two places; the agent reads the other one | Gold wording or question to decide |

**Baseline — where it loses.** Control 11 (never asks back, answers a year that is not in the corpus), retrieval
miss 11 (one search cannot cover several companies), calculation error 12 (two figures and no percentage, or
the report's own ratio in place of the glossary's), hallucination 19 (a number that is not on the cited page).

[TO FILL: table of at least 15 hand-checked wrong answers with confirmed labels.]

## 10. Safety

| Risk | What is done |
|---|---|
| Investment advice, forecasts, price targets, insider information, tax advice | Refused by rules in code before the model is called |
| Instructions planted in a question or in report text | Report text is treated as data; figures come from the figure store, so a sentence on a page cannot change them |
| A wrong number presented as fact | The critic; an answer that fails is shown as "Unverified, please check page …" |
| Personal details typed into a question | Emails, phone numbers and PAN are masked in the agent's log, the evaluation files and the stored conversations |
| A document leaving the app unchecked | Notes are DRAFTs with a warning until a person ticks "checked" and approves; only verified answers can be exported |
| Secrets | The API key is only in `.env`, which is not committed; reports and stores are not committed |

Red-team log: `docs/RED_TEAM_LOG.md`, 28 prompts in five groups. [TO FILL: pass and fail counts after the run.]

## 11. The application

A Streamlit chat screen (`app/streamlit_app.py`):

- the answer with its formula, the figures used, and a link from each figure and each key point to the page of
  the report on the company's website;
- the stage the agent is in while it works; the full trace under "How I got this";
- Quick lookup: sector, companies, figure or ratio, year, scope, for a question without typing;
- follow-up questions, and past conversations that survive a restart;
- export of a verified answer as a DRAFT note, with Approve;
- "Basic search", the baseline, for comparison.

## 12. Limitations

- **Corpus.** 15 companies and two years. A new report is added by configuration (file name, an entry in
  `config/companies.yaml`, the ingest), not detected automatically; a company with different line names may
  need glossary entries. This was not tested end to end.
- **Summaries.** The weakest type. The agent reads at most nine passages of one section; a topic the report
  treats in two places, or a long section, is covered in part.
- **Figures in text.** A figure that needs two different pages of text is declined.
- **Retrieval choices.** Chunking, embedding model and reranker were not compared by experiment.
- **Page numbers.** A citation is the page of the PDF file. If a company replaces the file on its website, the
  link may open a shifted page; the checksum shows which file was ingested.
- **Parsing.** Text layer only; a scanned report would need OCR, which was not needed for these 30.
- **Evaluation.** 90 questions written by the team; summaries are judged by a person; results vary slightly
  between runs because the model's wording varies.

## 13. How to reproduce

1. Install on Python 3.11: `docs/INSTALL_WINDOWS.md` or `docs/INSTALL_MAC.md`.
2. Put the 30 reports in `data/manual-collection/` (addresses and checksums in `data/report_sources.csv`),
   run `python scripts/hash_reports.py` (every line "unchanged"), then `python -m ingest.run_ingest`.
3. Tests: `python -m pytest -q` (193 passed).
4. App: `streamlit run app/streamlit_app.py`.
5. Evaluation: `python eval/run_eval.py` (agent), `python eval/run_eval.py --mode simple` (baseline),
   add `--official` for the runs that are reported; `python eval/metrics.py results/official` for the table.

## 14. Still to fill before submission

| Item | Where |
|---|---|
| Official results: three runs per mode | Section 8 |
| Summary review by a person, then `--rescore` | Section 8 |
| Decisions: net NPA definition, Nestlé risk pages, default scope | Sections 5 and 9, `docs/DECISIONS.md` |
| Hand-checked failure table (15 or more) | Section 9 |
| Red-team results | Section 10 |
| Retrieval study, or the limitation stated | Section 5 |
| Mentor's reply on the plain Python loop | `docs/DECISIONS.md` section 4 |
| Team number, names, and who did what | Top of this report |
