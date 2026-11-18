# FinSight (team repo) — Agent Layer: Changes, New Files and Task Status

Date: 13 Nov 2026\. Covers Item IV (agent layer) added to `FinInsight-AIAgent-master`.

Rules followed:

- No existing code was deleted. Replaced code is kept as comments marked `# OLD:` or `# ORIGINAL PLACEHOLDER (kept):`, with a WHY note beside the new code.  
- Everything was written for and tested on **Python 3.11**.

## 1\. What was tested

Last updated: 15 Nov 2026\.

| Check | Result |
| :---- | :---- |
| Unit tests on Python 3.11.17 | **114 passed** (before any change: 22 passed, 3 skipped placeholders) |
| Figure store coverage | 793 of 940 standard figures found with a confirmed unit (was 469). See section 10 |
| Agent with the real Qwen3-8B endpoint, in this repo | Verified : fact, follow-up, ratio (14 Nov) and a reported ratio, HDFC Bank CASA 34.80%, p210 (15 Nov) |
| Agent on the real figure store with a scripted (fake) model | Fact, follow-up, ratio, year-on-year, comparison, bank ratio, refusal and clarify all correct |
| Summary and reported-ratio questions | Work with keyword search after `python -m ingest.run_ingest --no-index` (27,696 chunks). The vector index is not built yet |
| Chat screen (Streamlit) with the agent | Tested without a browser (Streamlit AppTest, scripted model). Not yet opened in a browser with the real endpoint |

Sample answers from the real figure store:

| Question | Answer | Citation |
| :---- | :---- | :---- |
| Infosys consolidated revenue FY2025-26 | ₹178,650 crore | INFY-FY2526-p287 |
| TCS consolidated net profit FY2024-25 | ₹48,797 crore | TCS-FY2425-p181 |
| Infosys operating margin FY2025-26 | 20.92% | INFY-FY2526-p287 |
| TCS revenue change FY2024-25 → FY2025-26 | \+4.58% (₹255,324 → ₹267,021 crore) | TCS-FY2526-p168 |
| Infosys vs Tech Mahindra revenue FY2025-26 | Infosys ₹178,650 crore; Tech Mahindra ₹56,815.40 crore (converted from million) | p287, p555 |
| SBI standalone cost-to-income FY2025-26 | 50.11% | SBIN-FY2526-p209 |

These figures come from the extractor and still need a human check against the PDF pages before they are used as gold answers.

## 2\. How a question flows

```
question
  → guard     (code)   refuse advice, forecasts, insider info, tax/legal, prompt injection, years outside the corpus
  → planner   (model fills slots; code validates, fills gaps from keywords and memory, builds the steps)
  → executor  (code)   calls the tools; blocks repeated calls; stops at 10 steps or 12,000 tokens
  → writer    (model words the answer; code template is the fallback)
  → critic    (code)   every number must trace to a tool result; citation, year, scope, formula, no advice
  → memory    (SQLite) saves company/year/metric for follow-up questions
```

Result status is one of `answered`, `clarify`, `refused`, `escalated`.

The loop is plain Python, not a LangGraph graph. Reason: with an 8B model, code-controlled flow is easier to cap, test and debug. `agent/graph.py` keeps the file name so imports do not change.

## 3\. The 8 tools

| \# | Tool | File | State |
| :---- | :---- | :---- | :---- |
| 1 | get\_company\_profile | `tools/get_company_profile.py` | Existing, unchanged |
| 2 | get\_financial\_item | `tools/get_financial_item.py` | Rewritten (old code kept as comment) |
| 3 | search\_report | `tools/search_report.py` | Existing \+ keyword-only fallback |
| 4 | read\_table | `tools/read_table.py` | Existing, unchanged |
| 5 | normalise\_units | `tools/normalise_units.py` | Existing, unchanged |
| 6 | calculate | `tools/calculate.py` | Existing, unchanged |
| 7 | compare\_rank | `tools/compare_rank.py` | Placeholder → implemented |
| 8 | create\_note\_draft | `tools/create_note_draft.py` | Placeholder → implemented |

## 4\. Existing files that were changed

| File | What changed | Why |
| :---- | :---- | :---- |
| `ingest/run_ingest.py` | Calls the new `extract_statement_rows`; new `--figures-only` flag | The old table extractor gave wrong or missing figures (see `ingest/statements.py`). The flag rebuilds only the figure store in minutes, without parsing and embedding everything |
| `config/companies.yaml` | Added an `aliases:` list per company | Users type "SBI", "HUL", "Kotak", "TechM". Matching needs these names. Nothing removed |
| `config/glossary.yaml` | Added three sections at the end: `line_items`, `derived_inputs`, `reported` | `line_items` maps one fixed id (e.g. `net_profit`) to the different labels companies print. `derived_inputs` defines values no statement prints directly (EBIT, EBITDA, total debt, capital employed, net interest income). `reported` lists bank ratios that are read from the text, not calculated (GNPA, NNPA, CASA, NIM, CRAR, ROA, EPS). Existing formulas untouched |
| `src/finsight/tools/glossary.py` | Added `line_items()`, `derived_inputs()`, `reported_metrics()`, `not_for_banks()` | Readers for the new glossary sections |
| `src/finsight/tools/get_financial_item.py` | New lookup: fixed ids, tolerant label match, scope, choice of report, "first page" rule, nth occurrence, free-text fallback | The old version matched a label by plain substring and could return the wrong row, wrong scope, or a row from a note page. Returns the same keys as before plus a few extra, so old callers still work |
| `src/finsight/tools/search_report.py` | Dense search wrapped in try/except; falls back to keyword search | Without Qdrant running the tool crashed. Now the agent still works |
| `src/finsight/llm.py` | Counts tokens (`TOKENS_USED`); `structured()` uses `create_with_completion` | The 12,000-token budget per question needs the real usage numbers from each call |
| `src/finsight/schemas.py` | Added AgentPlan, AgentStep, Figure, Draft, KeyPoint, SummaryDraft, Extracted, AgentAnswer, Verdict | Shapes for the plan, tool results and final answer. Original schemas untouched |
| `src/finsight/safety/guard_rules.py` | Placeholder → refusal rules | Refuses in code, before any model call (0 tokens) |
| `src/finsight/safety/sanitiser.py` | Placeholder → `sanitise`, `clean_question` | Removes planted instructions ("ignore previous instructions…") from report text before the model sees it |
| `src/finsight/safety/pii.py` | Placeholder → `mask_pii` | Masks email and phone numbers in traces |
| `src/finsight/tools/compare_rank.py` | Placeholder → implemented | Ranks companies highest/lowest, reports ties, rejects missing values |
| `src/finsight/tools/create_note_draft.py` | Placeholder → implemented | Writes a DRAFT note file only from a verified answer; always needs human approval |
| `src/finsight/agent/guard.py` | Placeholder → implemented | Agent node that applies the guard rules |
| `src/finsight/agent/planner.py` | Placeholder → implemented | Model fills intent/company/year/metric; code checks every slot, uses keyword backstops, asks a clarifying question when something is missing |
| `src/finsight/agent/executor.py` | Placeholder → implemented | Runs the steps, converts units, computes derived inputs, enforces caps |
| `src/finsight/agent/writer.py` | Placeholder → implemented | Model wording with a safe code template as fallback |
| `src/finsight/agent/critic.py` | Placeholder → implemented | Code checks; up to 2 rewrites, then the template answer |
| `src/finsight/agent/graph.py` | Placeholder → `run(question, session_id, llm, memory)` | The main entry point |
| `src/finsight/agent/state.py` | Placeholder → typed dictionaries | Documents the data passed between nodes |
| `src/finsight/agent/prompts/planner.md`, `writer.md`, `critic.md` | Placeholder → real prompts | Short prompts sized for the 8,192-token limit |
| `tests/test_get_financial_item.py`, `test_critic.py`, `test_caps.py` | Skipped placeholders → real tests | The 3 skipped tests are now 20 real tests |

## 5\. New files

| File | What it is | Why it is needed |
| :---- | :---- | :---- |
| `ingest/statements.py` | Position-based extractor for balance sheet, P\&L and cash flow | Reads words with their x/y positions, so amounts stay in the right column. Finds statement pages by title, takes scope (standalone/consolidated) from the title, reads the unit from the page, keeps the prior-year column. The header comment explains what failed in `ingest/tables.py` |
| `src/finsight/textfix.py` | Repairs broken PDF text | The TCS FY2024-25 PDF stores digits as Greek letters and drops letters ("PROFIT FOR THE EAR"). Without this fix TCS numbers cannot be read |
| `src/finsight/corpus.py` | Fiscal-year helpers and citation format | One place for "2025-26" handling: `normalise_fy("FY26")`, `previous_year`, `years_in(text)`, `citation("INFY","2025-26",214)` → `INFY-FY2526-p214` |
| `src/finsight/tools/company_match.py` | Finds company names in a question | Uses name, ticker, pdf prefix and aliases from `companies.yaml`. Returns nothing for companies outside the 15, so the agent can refuse |
| `src/finsight/agent/memory.py` | Conversation memory in SQLite | Lets "And for FY2024-25?" reuse the company and metric from the previous question |
| `src/finsight/agent/llm_adapter.py` | `RealLLM` and `FakeLLM` | `RealLLM` calls the endpoint through `finsight.llm.structured`. `FakeLLM` is a scripted model so tests run with no network |
| `scripts/ask.py` | Command-line entry | `python scripts/ask.py "question" --trace` |
| `tests/conftest.py` | Test fixtures | A small made-up figure store, fixed search passages and a scripted model. The numbers in it are invented for testing only |
| `tests/test_agent_loop.py` | 16 end-to-end test functions | Refuse, clarify, fact, ratio, year-on-year, comparison with unit conversion, bank metrics, escalation, critic rewrite, follow-up, reported ratio, summary |
| `tests/test_agent_tools.py` | 6 test functions | compare\_rank, note draft, company matching, year helpers, glossary consistency |
| `tests/test_guard.py` | 4 test functions (13 cases) | Refusal rules, sanitiser, PII masking |
| `docs/INSTALL_WINDOWS.md`, `docs/INSTALL_MAC.md` | Installation guides | Python 3.11, step by step |
| `docs/CHANGES_AND_STATUS.md` | This file |  |

Data placed locally (ignored by Git, so teammates must do the same on their laptops): 30 PDFs in `data/manual-collection/` and the built `store/statement_lines.parquet`.

## 6\. Running on Python 3.11 (\<your-environment\> )

The team standard is Python 3.11. `pyproject.toml` says the **core** packages install on 3.11, and the agent layer uses only core packages.

In Miniforge Prompt:

```
conda activate <your-environment> 
cd <Folder Path>
python -m pip install -e ".[dev]"
copy .env.example .env
notepad .env
python -m pytest -q
python scripts\ask.py "What was Infosys' consolidated revenue from operations in FY2025-26?" --trace
```

In `.env` set `OPENAI_API_KEY`, `OPENAI_CA_CERT` (full path to `vm04-ca.crt`) and `QDRANT_URL=./store/qdrant`.

If `pip install -e` fails on one package, install only what the agent needs and point Python at the source folder:

```
python -m pip install openai httpx instructor pydantic pydantic-settings tenacity pyyaml pymupdf pandas pyarrow rank-bm25 qdrant-client pytest
set PYTHONPATH=src;.
python -m pytest -q
```

The figure store is already built in this folder (rebuilt on 15 Nov 2026), so step 8 of the install guide can be skipped on this laptop.

figure store after taking this code: `python -m ingest.run_ingest --figures-only`.

.
## 7. Update 15 Nov 2026 — advice question answered from memory (bug fix)

Found on the real model. After "What is the net profit of TCS for FY2024-25?", the question
"What is best price to buy TCS?" was answered with TCS's net profit. It should have been refused.

| File | Change | Why |
|---|---|---|
| `src/finsight/safety/guard_rules.py` | Advice rule extended: `buy` / `sell` / `invest in` as words, "best / right price or time", "entry / exit price". Old patterns unchanged | The old rule needed wording like "should I buy" or "price target"; a plain "to buy" passed the guard |
| `src/finsight/agent/planner.py` | A follow-up may reuse the remembered figure (or the model's copy of it) only when every content word of the question is understood. Otherwise the agent asks which figure is wanted | The model marked the new question as a follow-up and repeated the old item, so the old answer came back for a question that never asked for it |
| `src/finsight/agent/planner.py` | In a follow-up, a word in the question ("revenue") beats an item the model copied from memory | "and its revenue?" after a net-profit question must switch to revenue |
| `src/finsight/corpus.py` | `years_in` also reads "24-25", "FY24-25", "2024-2025", "2024/25" (old version kept as a comment) | "and for 25-26" was not read as a year; the agent silently kept the remembered year. It looked right only because the remembered year happened to be the same |
| `tests/test_guard.py`, `tests/test_agent_loop.py`, `tests/test_agent_tools.py` | 10 test cases added | The exact questions above, plus checks that "share buyback", "selling expenses", "investing activities" and "purchases of stock-in-trade" are still answered |

Unit tests: 113 passed on Python 3.11 at that point.

## 8. Update 15 Nov 2026 — "and 24-25" treated as a year-on-year question (bug fix)

Found on the real model: after "What was Wipro's operating margin in FY2025-26?", the follow-up "and 24-25"
was answered with "Year-on-year change of which figure?".

| File | Change | Why |
|---|---|---|
| `src/finsight/agent/planner.py` | A question is year-on-year only when its own words say so (two years, or a change word; "compared with the previous year" added). The model's "yoy" label alone is ignored | The model labelled a plain year follow-up as "yoy" |
| `tests/test_agent_loop.py` | 1 test added | The exact case above, and a "compare with the previous year" question |

Unit tests: 114 passed on Python 3.11.

## 9. Update 15 Nov 2026 — follow-ups that name no figure keep the remembered one (bug fix)

Found on the real model after section 16: "and 24-25" now answered "'None' is not a statement line". The model
had sent intent "yoy" **and** metric "yoy_change"; section 16 corrected the intent but the metric stayed and
blocked the remembered metric (operating margin). "and for 24-25" worked only because the model guessed
differently for that wording.

| File | Change | Why |
|---|---|---|
| `src/finsight/agent/planner.py` | The model's metric "yoy_change" is accepted only when the question itself is year-on-year (`YOY_WORDS`, two years) | Removes the bogus metric so memory can fill it in |
| `src/finsight/agent/planner.py` | A follow-up that names no figure at all ("and 24-25", "and for Infosys") always keeps the remembered metric / item; the model's guess is ignored | With nothing to go on, the 8B model guesses. Memory is exact, so the result no longer depends on the wording |
| `src/finsight/agent/planner.py` | A bare fragment ("24-25?", "Infosys?", "standalone?") counts as a follow-up even if the model does not flag it | Same reason |
| `tests/test_agent_loop.py` | Cases added to the test from section 16 | The exact failing case and the fragments above |

Unit tests: 114 passed on Python 3.11.

## 18. Update 17 Nov 2026 — wrong consolidated deposits for HDFC Bank FY2024-25 (bug fix)

Found on the real model: "compare the total deposits of HDFC and SBI in FY2024-25" gave HDFC Bank
Rs 24,105.32 crore (marked verified). The real consolidated figure is Rs 27,10,898.23 crore (p441).

Cause: the consolidated balance sheet page (p441) was never read. Its title is letter-spaced and the page has no
other occurrence of the words the quick page filter looks for. The lookup then took the schedule row
"Deposits of branches outside India" (p447) as "deposits". The critic passed it because it checks that a number
comes from a cited figure, not that the figure is the right row.

| File | Change | Why |
|---|---|---|
| `ingest/statements.py` | The quick page filter also looks at the text with spaces removed | The letter-spaced page is no longer skipped |
| `ingest/statements.py` | A page whose heading line begins with "Schedule ..." is not a statement page | Schedule pages repeat the statement's row names with partial amounts |
| `ingest/statements.py` | Scope of a bare title falls back to the last statement page when no auditor's report has been seen | SBI FY2024-25: P&L title has no scope word and follows nine schedule pages |
| `src/finsight/tools/get_financial_item.py` | A row that continues with "of ..." or "before ..." is a different row; the longest matching label decides | "Deposits of branches outside India", "Tax expense of discontinued operations" (ITC), "Net profit ... before deducting minority interest" (ICICI) were being returned |
| `src/finsight/tools/get_financial_item.py` | Primary statement pages may be up to 10 pages apart (was 3) | Banks print schedules between the balance sheet and the P&L |
| `tests/test_get_financial_item.py`, `tests/test_statements.py` | 3 tests added | The cases above |

Result: HDFC Bank FY2024-25 consolidated total assets (was Rs 765 crore, now Rs 43,92,417 crore), deposits and
advances are corrected. ITC tax expense and ICICI consolidated net profit are now "not found" instead of a
neighbouring row. Standard figures found: 788 of 940. The store has 14,119 rows (schedule pages removed).
Unit tests: 117 passed on Python 3.11.

Rebuild the figure store after taking this code: `python -m ingest.run_ingest --figures-only`.

Lesson for the report: "verified" means every number traces to a cited figure. It does not prove the figure is the
right one. Only the hand-check of figures against the PDFs can do that.

## 19. Update 17 Nov 2026 — chat screen keeps the full answer cards (first run in a browser)

The chat screen was opened in a browser with the real endpoint for the first time and answered correctly.
One display problem was found: after a sidebar filter was changed, earlier answers were redrawn as plain text
and lost their formula, figures table and "How I got this" steps.

| File | Change | Why |
|---|---|---|
| `app/streamlit_app.py` | Each agent answer is kept in the chat history and redrawn as a full card | Streamlit reruns the whole script on every click; only the answer text had been kept |
| `app/streamlit_app.py` | A sidebar note says what the filters do in Agent mode | A filter applies only to a new question that names no company or year; answers on screen do not change |
| `tests/test_app.py` | The screen test now changes a filter and checks the cards are still there | The case above |

Unit tests: 117 passed on Python 3.11 (no new test function; one was extended).

## 20. Update 17 Nov 2026 — a whole-report summary now asks for a topic

Found in the chat screen: "can you summarize annual report for HUL in hundred words" returned six points about
dividend dates and how to obtain the report. Every point was cited correctly, but none described the business.

Cause: a summary is written from a handful of passages found by searching for the words of the question. The
words "annual report" match administrative pages. A 300-page report cannot be summarised from five passages.

| File | Change | Why |
|---|---|---|
| `src/finsight/agent/planner.py` | A summary request that names no topic gets a clarifying question: business performance, key risks, strategy and outlook, or management commentary | Asking is better than a summary of the wrong pages |
| `app/components.py` | Under a summary the note now reads "each point cites a page that was retrieved" | "Every number traces to a cited page" overstated what is checked for a text summary |
| `tests/test_agent_loop.py` | 1 test added | The exact question above; a summary with a topic still works |

Unit tests: 118 passed on Python 3.11.

Known limit: summary quality depends on search. The index currently uses the fallback (word-matching) embedding;
with the real bge model and reranker the passages found for a topic should be more relevant.

## 21. Update 17 Nov 2026 — replies to a clarifying question are understood

Found in the chat screen: "summarize annual report for HUL" → "key risks" → "HUL" → "net profit": the agent asked
for the company on every turn. Memory was saved only after a successful answer, so nothing was kept when the
agent asked a question back, and each reply arrived as a new question.

| File | Change | Why |
|---|---|---|
| `src/finsight/agent/memory.py` | `set_pending` / `pop_pending`: the unfinished question is kept for exactly one turn | So the reply can complete it |
| `src/finsight/agent/planner.py` | `is_reply` decides whether a message is a reply or a new question; `merge_reply` joins the unfinished question and the reply. A company or year in the reply replaces the earlier one | "key risks" becomes "summarize ... for HUL. key risks" and is planned as one question |
| `src/finsight/agent/graph.py` | Reads the unfinished question at the start of a turn, plans the completed text, and stores it again if another clarifying question is needed | Several clarifying questions in a row now add up |
| `src/finsight/agent/planner.py` | A question that names a figure but no company uses the company just discussed, when every word is understood | "What was the net profit?" after an answer about Wipro. The answer carries a note saying so |
| `tests/test_agent_loop.py` | 4 tests added | The conversation above, replacing a company or year, choosing an offered option, and dropping the unfinished question on a new question or a refusal |

Safety: the unfinished question is forgotten after one turn, a refusal clears it, and a message that is a full
question of its own (company + figure + year, or a longer question) is not merged.

This was done in the plain Python loop. LangGraph's "interrupt" offers the same pause-and-resume pattern; the
logic that decides what to keep and when to drop it would be the same.

Unit tests: 122 passed on Python 3.11. Verified with a scripted model only.

## 22. Update 17 Nov 2026 — no invented year; summary search widened

Found in the chat screen: "summarize annual report for HUL" → "Business Performance" was answered for FY2025-26
although no year was given, and the summary was about employee performance management and share plans.

| File | Change | Why |
|---|---|---|
| `src/finsight/agent/planner.py` | A year is taken from the question, from "latest / current year" (newest report), from "last / previous year", or from memory in a follow-up. A year supplied only by the model is no longer accepted; the agent asks | The model had filled in a year the user never gave |
| `src/finsight/agent/executor.py` | `SUMMARY_TOPICS`: the topic is widened with the words that section really uses before searching; at most one passage per page, up to 4 pages | The search matches words. "Business performance" matched "performance management" and "performance share plan" pages. With the wider query the same report returns the CEO's statement, the letter to shareholders and the MD&A |
| `tests/test_agent_loop.py` | 2 tests added | Both cases |

Unit tests: 124 passed on Python 3.11.

Still weak: summaries depend on word-matching search (fallback embedding). A check on three topics gave good pages
for HUL business performance, acceptable pages for HUL key risks and poor pages for ITC strategy. Two things would
help: rebuilding the index with the real bge model and reranker, and fixing the section labels in the chunks
(`ingest/sections.py`): in HUL FY2025-26 the CEO's statement is labelled "risk" and part of the MD&A "pnl", so
the labels cannot be used to narrow the search yet.

## 23. Update 17 Nov 2026 — gold-answer workbook and converter

| File | Change | Why |
|---|---|---|
| `eval/make_gold_workbook.py` (new) | Builds `eval/gold_workbook.xlsx` from the 90 questions: one row per figure to read from a PDF (177 rows), 5 key-point rows per summary question | `eval_set.jsonl` is one long JSON line per question; typing gold answers into it by hand is error-prone and leaves no room for inputs, pages, author and verifier |
| `eval/gold_workbook.xlsx` (new) | The sheet the team fills in. Yellow cells only; an OK / CHECK column compares author and verifier | The capstone asks for every gold figure to be read twice, by two people |
| `eval/compute_gold.py` | Placeholder → converter: reads the filled workbook, converts amounts to crore, calculates ratios with `config/glossary.yaml`, writes `gold` and `gold_status` into `eval_set.jsonl` (backup `.bak` first). Incomplete questions are left untouched and listed | Ratios are never calculated by hand; the script can be run while the sheet is still being filled |
| `eval/gold_vs_store.csv` (written by the converter) | Every verified figure that differs from the figure store | This is the hand-check of the extractor |
| `pyproject.toml` | `openpyxl` added to the `dev` extras | Needed to read and write the workbook |
| `.gitignore` | `eval/*.bak` and Excel lock files | Not for Git |
| `tests/test_gold_workbook.py` (new) | 4 tests | Build, fill and convert a small set; pending and disputed rows; same author and verifier is rejected; dry run changes nothing |

How to use:
1. Share `eval/gold_workbook.xlsx` (for example as a Google Sheet) and fill the yellow cells.
2. Save it back as `eval/gold_workbook.xlsx`.
3. `python eval/compute_gold.py --dry-run` to see what is ready, then `python eval/compute_gold.py` to write the gold answers.

The workbook uses the questions' own figures: the planner's code rules decide which statement lines each question
needs, so gold answers and the agent use the same inputs and formulas. The six multi-hop questions have free
"numerator" and "denominator" rows, because their inputs are not in the glossary.

Unit tests: 128 passed on Python 3.11.
