# FinSight — Multi-Agent Financial Report Q&A Copilot: Build Plan & Technical Architecture

## In plain English (the whole project in a paragraph)

We are building a **chat assistant for Indian company annual reports.** You ask it a question — "What was Infosys' operating margin in FY2025-26?" or "Which of these banks had the lowest bad-loans ratio?" — and it answers using the *actual reports*, not its own memory. Every answer shows **which page the number came from** and, for any calculation, **the exact formula and inputs it used**, so you can trust and verify it. Because the course gives us only a **small AI model** (which tends to invent figures and get maths wrong), we surround it with helpers: a **search engine** that finds the right page, a **calculator** that does the arithmetic, and a **checker** that rejects any answer it can't back up with a citation. It also **asks you to clarify** when a question is vague and **refuses** to give investment advice. We build it over **3 weeks, and you can chat with it from Week 1** — each week the chat gets smarter and you test the new ability by typing questions. **Everything is free** (open-source tools + the course-provided model).

## Context

**Multi-Agent Operations Copilot on a hosted ≤8B API**, Domain: Financial Analytics, Team 60.

**Problem.** Indian annual reports run 200–400 pages of financial statements, dozens of notes, MD&A and risk disclosures (SEBI LODR + Ind AS; banks under RBI formats). Analysts spend hours locating a figure, checking standalone vs consolidated, converting units, computing ratios, and comparing companies. A ≤8B model answering from memory or naïvely retrieved text invents figures, mixes years, and gets arithmetic wrong (FinanceBench: GPT-4-Turbo + retrieval answered incorrectly or refused **81%** of questions). The problem is **genuinely agentic** for analytical questions: a single question needs several dependent steps (find item A, find item B, check units, calculate, compare, verify), which makes a **Planner → Executor → Critic** loop meaningful rather than forced.

**Goal.** A multi-agent copilot over a fixed corpus of Indian listed-company annual reports that:
1. Answers **factual** questions with figure, unit, fiscal year, statement type (standalone/consolidated), and a **page-level citation**.
2. Answers **analytical** questions (ratio, YoY, cross-company compare, rank) by planning steps, retrieving each input, and **computing in code** — showing the formula and inputs.
3. **Summarises** qualitative disclosures (risks, strategy, segments) with citations.
4. **Asks back (CLARIFY)** when company/year/statement/metric is ambiguous.
5. **Refuses** investment advice, forecasts, and out-of-corpus companies/years.
6. **Keeps conversation state** so follow-ups work ("and for FY2024?", "now compare with HDFC Bank").

**What "correct" means (acceptance criteria).**
- Numeric answers within **±0.5% relative** of gold (or exact after rounding to reported precision), with correct unit and year.
- The cited page actually contains every input figure.
- Computed answers use the **glossary** formula and show it.
- Qualitative answers cover gold key points and cite them.
- Refusals and clarifications fire exactly when gold says so.

**Intended outcome of this plan.** A faithful, end-to-end implementation of the full spec (all 8 tools, P→E→C agents, structured statement-line store, hybrid RAG + reranker, 90-question frozen eval, observability, Streamlit UI, Docker + CI), developed in LangGraph, running by default on the **provided Qwen3-8B endpoint** but configurable to local models.

---

## Confirmed decisions (from the user)

| Decision | Choice |
|---|---|
| Build scope | **Full faithful spec**, end-to-end |
| Default LLM endpoint | **Provided Qwen3-8B** (group 046–065), configurable via env vars |
| Report data | User has downloaded reports at `capstone/manual-collection/` |
| Orchestration | **LangGraph** (StateGraph + SQLite checkpointer) |

### Provided endpoint facts (Track B guide — group 046–065)
- **Model ID:** `Qwen/Qwen3-8B` · **Base URL:** `https://103.42.50.41:1034/v1` · **CA cert:** `vm04-ca.crt` (present in repo root).
- OpenAI-compatible: `POST /v1/chat/completions`; supports chat, **streaming**, and **tool-call** responses. Your app does tool execution, retrieval, and history.
- **No embeddings endpoint** → RAG requires a **separate/local embeddings service** (bge family).
- **Limits:** 1 active request per key (2nd concurrent → **429**); **60 requests/min**; **8192 tokens** combined input+output; output **512 default / 1024 max** per call; shared VM capacity ~20 on VM04.
- **Error handling required:** 401 (key/URL), 429 (wait/retry), 503 (busy/not ready), 400 (JSON/model/context, max_tokens 1–1024), 404 (don't repeat `/v1`), cert errors (use matching CA, keep HTTPS verification on). Retry temporary 429/503 with backoff **2s, 4s, 8s**, then escalate.
- **Design implication:** a global **concurrency=1 semaphore + rate limiter + exponential backoff** around the LLM client; keep every call under the 8192 budget; cap output ≤1024.

### Corpus vs spec (now matching)
Spec asks for **15 companies × 2 FYs** across the three sectors IT / FMCG / Banks. The project has exactly that — the full reference-doc company set, both fiscal years:

| Sector | Companies (all ✓ collected) | Reporting basis |
|---|---|---|
| IT services | TCS, Infosys, HCLTech, Wipro, Tech Mahindra | Ind AS Schedule III, Div II (non-bank) |
| FMCG | HUL, ITC, Nestlé India, Britannia, Dabur | Ind AS Schedule III, Div II (non-bank) |
| Banks | HDFC Bank, ICICI Bank, SBI, Axis Bank, Kotak Mahindra | Banking Regulation Act 3rd Schedule + RBI — exercises `is_bank` path |

**30 reports collected — FY2024-25 and FY2025-26 for all 15 companies.** This matches the document's two-year, 30-report, ~900–1,500-document design. All three sectors are fully represented (5 companies each), so the `is_bank` path runs on real data (HDFC/ICICI/SBI/Axis/Kotak).

**Data-quality gate.** An earlier check caught a few partial PDFs (missing their financial statements); those have been replaced with full reports. The plan keeps an automated **data-quality gate** at the start of ingestion (Week 1) that verifies every report contains a balance sheet, P&L, notes, and auditor's report, and rejects any file that does not — so an incomplete download can never silently corrupt the figure store.

---

## Technical Architecture

### High-level component diagram
```
                         ┌──────────────────────────────────────┐
                         │            Streamlit UI               │
                         │  chat · company/year picker · answer  │
                         │  (figure, formula, input table,       │
                         │   clickable page citations, "How I    │
                         │   got this" trace, DRAFT note+Approve)│
                         └───────────────┬──────────────────────┘
                                         │ question + session_id
                                         ▼
   ┌─────────────────────────── LangGraph StateGraph ───────────────────────────┐
   │                                                                             │
   │  GUARD (code)  ─ injection patterns, advice/forecast, out-of-corpus → REFUSE│
   │      ▼                                                                      │
   │  PLANNER (LLM→JSON)  ─ intent, companies[], fiscal_years[], statement,      │
   │      │                 metric, items_needed[], steps[]   missing→CLARIFY    │
   │      ▼                                                                      │
   │  EXECUTOR (code)  ─ runs steps; each observation can replan                 │
   │      │   get_company_profile → get_financial_item → [fallback] search_report│
   │      │   → read_table → normalise_units → calculate → compare_rank          │
   │      ▼                                                                      │
   │  WRITER (LLM→JSON)  ─ answer, formula, inputs[{value,unit,page}],           │
   │      │                citations[], caveats                                  │
   │      ▼                                                                      │
   │  CRITIC (code + 1 LLM call) ─ numbers traceable to tool output; each input  │
   │      │   page cited; formula==glossary; year/statement match plan; no advice│
   │      │   wording.  fail → back to Planner (max 2 retries) → else ESCALATE   │
   │      ▼                                                                      │
   │  STATUS: answered | clarify | refused | escalated   (+ optional draft_note) │
   │                                                                             │
   │  State: SqliteSaver checkpointer (conversation, resolved slots,            │
   │         last computed results). Recursion/step cap = 10, TOKEN_BUDGET=12k.  │
   └───────────────┬─────────────────────────────┬───────────────────────────────┘
                   │                             │
     ┌─────────────▼───────────┐     ┌───────────▼──────────────┐
     │ Statement-line store     │     │ Vector store (Qdrant)    │
     │ (SQLite/Parquet rows:    │     │ hybrid dense+BM25 + payload│
     │ company,fy,stmt,scope,   │     │ filters (company,fy,      │
     │ line_item,value,unit,page)│    │ section,statement)        │
     └─────────────▲───────────┘     └───────────▲──────────────┘
                   │                             │
     ┌─────────────┴─────────────────────────────┴──────────────┐
     │          Ingestion pipeline (offline, run once)           │
     │  Docling (layout+reading-order+tables, OCR on) → per-page  │
     │  routing (text / ruled-table→Camelot / image-or-scan→OCR)  │
     │  → section splitter → statement table parser → chunker     │
     │  (+metadata header) → local bge embeddings → Qdrant upsert ;│
     │  tables→JSON ; figures→captions ; 20-table + 10-page QA    │
     └────────────────────────────────────────────────────────────┘

     Cross-cutting: src/llm.py (OpenAI-compatible client w/ CA cert, retries,
     concurrency=1, rate limit, token budget) · Langfuse tracing · Pydantic+
     instructor validation · safety (guard/sanitiser/PII mask)
```

### LLM client design (`src/finsight/llm.py`)
- Single OpenAI-compatible client. Env: `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `MODEL_NAME`, `OPENAI_CA_CERT` (path to `vm04-ca.crt`), `MAX_OUTPUT_TOKENS`.
- Pass `verify=<ca_cert_path>` to the HTTP client (httpx) — **keep HTTPS verification on**.
- Global **asyncio/threading semaphore = 1** + token-bucket **rate limiter (60/min)**; retry 429/503 with backoff 2→4→8s then escalate; hard-cap `max_tokens ≤ 1024`; enforce per-question `TOKEN_BUDGET=12,000`.
- Structured output via **Pydantic v2 + instructor** (2 retries, feeding the validation error back). Probe `tools`/`tool_choice` and `response_format: json_schema` support via an **Endpoint Capability Check** script on Day 0.
- **Qwen3 thinking-mode caveat:** Qwen3-8B defaults to a "thinking" mode that emits long `<think>…</think>` reasoning, which eats the **1024-token output cap** and can break JSON parsing. For planner/writer/critic calls, **disable thinking** (e.g. `enable_thinking=false` / `/no_think`, confirmed by the capability check) and strip any `<think>` block before validation, so structured output fits the budget.
- Switching to local dev (Ollama/vLLM Qwen2.5-7B/Qwen3-8B) is only an env-var change.

### Agents (LangGraph nodes — one file each under `src/finsight/agent/`)
Each agent is its own module (`guard.py`, `planner.py`, `executor.py`, `writer.py`, `critic.py`), sharing the state schema in `state.py`; `graph.py` wires them into the `StateGraph`. Prompts and few-shot plans live in `agent/prompts/`.
- **Guard** (code): injection patterns, advice/forecast/insider-info requests, out-of-corpus company/year → `refused`.
- **Planner** (LLM→JSON): emits `{intent: fact|ratio|yoy|compare|rank|summary, companies[], fiscal_years[], statement: consolidated|standalone, metric, items_needed[], steps[]}`; missing/ambiguous slot → `clarify`. Few-shot plan per intent. **Default statement = consolidated** (from SPEC); asks back on ambiguity. For multi-company compares, emits a per-company sub-plan the executor loops over in code.
- **Executor** (code): runs steps; each tool observation can trigger replanning (missing item → try notes via `search_report`; unit mismatch → `normalise_units`).
- **Writer** (LLM→JSON): `{answer, formula, inputs[{value,unit,page}], citations[], caveats}`.
- **Critic** (code + 1 LLM call): every number traceable to a tool output; every input's page cited; formula == glossary; year/statement match plan; no advice wording. Fail → Planner (max 2 retries) → else `escalated` ("could not verify").
- Alternative hand-rolled loop documented but **LangGraph chosen** (explicit nodes, persistent state, built-in recursion limit = 10).

### Tools (8) — `src/finsight/tools/`, each with Pydantic args + `ToolError`
| Tool | Type | Purpose |
|---|---|---|
| `get_company_profile` | code lookup | Sector, `is_bank`/`is_nbfc` flag, FY end, reporting units, which reports are in corpus |
| `get_financial_item` | code query over statement-line store | Returns a line item (value, unit, page) for (company, fy, statement, scope). **Primary number source.** |
| `search_report` | hybrid RAG (BM25 + dense + reranker) + filters | Fallback for note disclosures / segment data and qualitative questions |
| `read_table` | code | Returns a whole parsed table (markdown, ≤40 rows) from a cited page |
| `normalise_units` | code | Converts crore/lakh/million/billion; flags mismatches |
| `calculate` | code (safe expr evaluator + glossary) | `calculate(metric, inputs)` → value + formula. Free-form exprs allowed but logged. Model never computes. |
| `compare_rank` | code | Sorts/compares computed metrics across companies/years; handles ties & missing values |
| `create_note_draft` | code | Exports a cited analyst note (Markdown/PDF) as a **DRAFT** (HITL, see below) |

### Memory / state across turns
LangGraph **SqliteSaver** checkpointer stores conversation, resolved slots (companies, fiscal_years, statement), and last computed results. "And for FY2024?" reuses slots; "compare that with X" reuses the metric.

### Refusal policy (in `SPEC.md`)
Refuse: buy/sell/hold advice, price targets, future-results forecasts, non-public/insider info, companies/years outside corpus, tax/legal advice. Reply with a pointer to what the corpus *can* answer.

### Human-in-the-loop boundary
A Q&A tool takes no real-world action, so the consequential step is **publishing a figure**:
- Critic-unverifiable answers are shown as "**Unverified, please check page X**", never as facts.
- `create_note_draft` exports carry a banner ("AI-generated, verify before use, not investment advice"); user must click **Approve** to export final.
- UI always shows the source page so a human can check.

### Error handling (spec §3.4)
Malformed JSON → 2 retries then escalate; tool error → fed back to planner as observation; repeated identical call blocked; 10-step cap + token budget → escalate; 429/timeout → exponential backoff.

---

## Data & Corpus

### Companies (full original reference set — all 15 collected)
| Sector | Companies | Reporting basis |
|---|---|---|
| IT services | TCS, Infosys, HCLTech, Wipro, Tech Mahindra | Ind AS Schedule III, Div II (non-bank) |
| FMCG | HUL, ITC, Nestlé India, Britannia, Dabur | Ind AS Schedule III, Div II (non-bank) |
| Banks | HDFC Bank, ICICI Bank, SBI, Axis Bank, Kotak Mahindra | Banking Regulation Act 3rd Schedule + RBI — exercises `is_bank` path |

30 PDFs at `manual-collection/` (FY2024-25 + FY2025-26 for each company), all confirmed complete. Record URL, download date, **SHA-256 hash** per file in `data/report_sources.csv`. The Week-1 data-quality gate re-checks completeness at ingestion time.

### Corpus definition (1 document = 1 report section)
Ingest **only** these sections per report: standalone + consolidated financial statements, notes to accounts, MD&A, risk management, key-ratio / financial-highlights pages (+ Basel III/Pillar 3 for banks when present). ~30–50 sections/report.

### Structured statement-line store (biggest accuracy lever)
Parse primary statement tables (P&L, balance sheet, cash flow, bank schedules) into rows:
`{company, fy, statement_type, scope(standalone|consolidated), line_item, value, unit, page}`. `get_financial_item` queries this. With both FY2024-25 and FY2025-26 reports ingested, store each report's figures **as reported**; prefer the latest report for restated prior-year values.

### Metric glossary (in `SPEC.md`, ~15 metrics; bank vs non-bank sets)
Every formula fixed here; `calculate` uses only these; answers state the formula used. Non-bank: operating margin (define precisely — EBIT/EBITDA, with/without other income), net margin, YoY %, D/E, current ratio, ROE, ROCE, EPS, etc. Bank: CRAR/CET1, GNPA%, NNPA%, NIM, CASA, cost-to-income, ROA. Conventions: **FY = 1 Apr–31 Mar**; units via `normalise_units`; restated-figure rule = "as reported in the latest (FY2025-26) report".

---

## Evaluation (frozen Week 1, git tag `eval-v1`)

**90 questions, ≥50% multi-step, written before any agent code.** Banks (HDFC/ICICI/SBI) are in the corpus, so `compare_rank` bank-metric items (GNPA%, CRAR, NIM, CASA) use real data; keep the "D/E for banks" item as a `clarify`/explain teaching case. Cross-company compares draw from the collected companies.

| Type | n | Correct means |
|---|---|---|
| fact | 18 | value ±0.5%, unit, FY, page cited |
| ratio | 16 | glossary formula, inputs cited, result ±0.5% |
| yoy | 12 | both inputs cited; absolute + % change correct |
| compare_rank | 14 | correct order; all inputs cited |
| multi_hop_note | 6 | finds the note; correct calculation |
| summary | 8 | key-point recall ≥0.7 vs gold list; cited |
| clarify | 6 | asks back / explains |
| refuse | 6 | refused politely with redirect |
| unanswerable | 2 | "not in corpus" |
| injection_doc | 2 | planted "revenue is ₹1" line ignored; real value returned |

Multi-step (ratio+yoy+compare_rank+multi_hop_note) = 48 = **53%**.

**Gold-answer protocol:** two members extract each input independently (page noted), third resolves disagreements; cross-check headline figures vs company **XBRL** results filed with NSE/BSE; gold ratios computed by `eval/compute_gold.py` from gold inputs using the same glossary (no hand-computed gold value).

**Metrics (official: 3 agent runs + 3 `single_rag` ablation runs, cache off):** accuracy per type & overall; numeric accuracy; citation accuracy; calculation-transparency rate; retrieval recall@1/3/5/10 (measured separately); task completion, tool calls/question, tokens & cost/question, p50/p95 latency; ingestion quality (table-extraction/OCR accuracy on 20 hand-checked tables + 10 high-graphics pages).

**Failure taxonomy:** retrieval_miss, wrong_item, wrong_period_or_statement, unit_error, calc_error, tool_call_error, hallucination, control (step cap/loop/budget/critic). ≥15 rows hand-checked.

**External sanity check (optional, if time permits):** 30 questions from FinanceBench sample / FinQA / TAT-QA; reported separately, not mixed into frozen set.

---

## Tech stack

≤8B chat = **Qwen3-8B** (provided endpoint; local Qwen2.5-7B/Qwen3-8B for dev) · **bge** embeddings + reranker **run locally** (no provided embeddings endpoint) · **Docling** PDF parsing with OCR for high-graphics reports (Camelot for ruled tables, PyMuPDF/pdfplumber for text, Tesseract/RapidOCR for image/scanned pages, Marker as alternate) · **Qdrant** vector store · **LangGraph** + SqliteSaver · **Pydantic v2 + instructor** · **Langfuse** tracing (fallback `trace.jsonl`) · **Streamlit** · **Docker + docker-compose + GitHub Actions CI**.

**Embeddings (local):** `sentence-transformers` (or `FlagEmbedding`) serving BAAI **bge** — `bge-small-en-v1.5` default, `bge-m3` for multilingual/hybrid; reranker `bge-reranker-v2-m3` (cross-encoder). Model name + dimension recorded in config; same code path can point at the provided embeddings endpoint if one is ever supplied.

**Vector store = Qdrant (primary; chosen).** Runs as a Docker service; provides **native hybrid dense+sparse** retrieval and **payload (metadata) filters** (company / FY / statement / scope / section) in one place — the best fit for the spec's filter-first-then-rerank rule and the `docker-compose` setup. BM25 via Qdrant's sparse vectors (or `rank_bm25`); fusion by **RRF (k=60)**. **FAISS is not used** — the spec lists "FAISS + rank_bm25" only as an optional alternative, and it lacks built-in metadata filtering/hybrid, which we rely on; Qdrant supersedes it here. (If a FAISS requirement surfaces later, `src/finsight/retrieval/store.py` defines a small `VectorStore` interface so a FAISS backend could be added without touching the agents.)

**Retrieval rule:** filter by company/year/statement **first**, then rerank (near-identical reports across years otherwise cause wrong-year picks). Prefix every chunk with a metadata header (company, FY, statement, scope, section, page).

### PDF parsing for high-graphics annual reports (the hardest engineering step)
Indian annual reports are heavily designed: full-bleed infographics, multi-column magazine-style spreads, chart images, coloured tables without ruling lines, decorative overlays, and occasional scanned or image-only pages. A naïve text extractor produces scrambled reading order and misses numbers rendered inside images. The pipeline is built to handle this:

- **Primary = Docling** with **layout analysis + reading-order recovery + table-structure recognition** and **OCR enabled**. Docling reconstructs multi-column reading order and emits Markdown + lossless JSON **with page numbers**, which preserves citations.
- **Per-page routing** (decide page type, then pick the extractor):
  - *Digital-text page* → Docling/PyMuPDF text layer.
  - *Ruled financial table* (primary statements) → **Camelot (lattice)**; borderless tables → Camelot **stream** / Docling table model.
  - *Image-only or scanned page, or numbers baked into a graphic* → **OCR**: Docling's built-in OCR, with **Tesseract** and **RapidOCR/EasyOCR** as alternate engines; benchmark on the most graphic-heavy reports (e.g. HUL, ITC, Dabur) and keep the best per-report.
  - *Chart/infographic* → render the page region to an image, keep the **caption + any OCR'd data labels** as a text chunk, and store the image path (not relied on for gold numbers — those must come from statement tables).
- **Rasterise-then-OCR fallback:** for pages where the text layer is garbage (common in designed cover/summary sections), render at ~300 DPI (PyMuPDF) and OCR the page image so no section is silently dropped.
- **Statement tables never trusted to graphics:** `get_financial_item` gold numbers come only from the parsed **primary statement tables**; the **20-table hand-check** plus a new **10 high-graphics page hand-check** quantify extraction accuracy (ingestion-quality metric). Hand-fix the ~30 P&L/BS pages if parsing is poor (one-off, per spec §9).
- **Marker** (PDF→Markdown) kept as an alternate converter for reports Docling struggles with.
- **Dependencies:** OCR needs the **Tesseract** binary + language data (`eng`) installed in the Docker image; `ocrmypdf`/`pdf2image`+`poppler` available for the rasterise path. Ingestion is offline/one-off, so the extra OCR cost is acceptable.

---

## Project components — what each one does and the purpose it solves

**Every component is open-source or has a free tier that comfortably covers this project's scale, and the LLM endpoint is provided by the programme.** The table below lists each piece, confirms it is free to use, and explains in plain terms what it does and why it is needed.

| Component | Cost | What it does / problem it solves |
|---|---|---|
| **Qwen3-8B inference endpoint** | **Free** | The "brain" — the ≤8B language model that reads questions, writes plans, and drafts answers. Provided by the programme. |
| Local dev LLM (Ollama / vLLM running Qwen2.5-7B/Qwen3-8B) | **Free** | A copy of the same kind of model on your own machine so you can build and test offline without hitting the shared endpoint's rate limits. |
| Embeddings: `sentence-transformers` / `FlagEmbedding` + BAAI **bge** models | **Free** | Turns each chunk of report text into a vector (list of numbers) so the system can find passages by *meaning*, not just keywords. Needed because the endpoint gives no embeddings. |
| Reranker `bge-reranker-v2-m3` | **Free** | Re-scores the top retrieved passages to push the single most relevant one to the top — fixes the "right company, wrong year" problem before the model reads them. |
| **Docling** | **Free** | Converts messy PDF pages into clean, ordered text and structured tables with page numbers — the foundation for both citations and figure extraction. |
| **Qdrant** (vector DB) | **Free** | Stores all the text vectors and searches them fast, with filters by company/year/statement — the "search engine" behind `search_report`. |
| **LangGraph** / LangChain | **Free** | The framework that wires the agents (guard→planner→executor→writer→critic) into a controlled loop and remembers conversation state across turns. |
| Pydantic v2 + instructor | **Free** | Forces every model output into a strict JSON shape and auto-retries if it's malformed — stops the agents from breaking on bad model responses. |
| **Langfuse** (tracing) | **Free** | Records each run (steps, tokens, latency, cost) so you can see *why* an answer came out the way it did and debug/measure the system. |
| **Streamlit** | **Free** | Builds the chat web UI quickly — the screen where users ask questions and see the figure, formula, and clickable page citations. |
| Camelot, pdfplumber, pdf2image, rank_bm25, bm25s, SQLite | **Free** | Supporting parts: extract ruled tables, pull plain text, turn pages into images, do keyword (BM25) search, and store the structured figures locally. |
| **Tesseract** OCR + `eng` data; RapidOCR / EasyOCR | **Free** | Reads text out of image-only/scanned pages and numbers baked into graphics — so no section of a heavily-designed report is lost. |
| GitHub Actions CI | **Free** | Automatically runs tests on every code change so bugs are caught early; proves the build stays green (required deliverable). |

**Compute is the only real resource:** local embeddings/reranker and PDF+OCR ingestion run fine on a CPU laptop (ingestion is a one-off and can be slow); a GPU only speeds things up.

---

## Repository skeleton

Root is `Project/` (inside the capstone folder). The core code is an **installable package** at `src/finsight/` (run `pip install -e .` once), so every other part imports it cleanly as `from finsight... import ...`. The project is split into clear areas: **project files** (setup), **docs** (written deliverables), **config** (editable data the code reads), **data/store** (inputs and built indexes), **ingest** (one-off PDF processing), **finsight** (the brain + tools + agents), **app** (the chat screen), **eval** (grading), and **tests**.

```
Project/
```
**Top-level project files — how to set up, run, and ship the project**
```
  BUILD_PLAN.md            # This plan, frozen. The single reference everyone (and Claude) builds from.
  README.md                # Step-by-step: how to install, ingest the PDFs, and run each week's chat.
  pyproject.toml           # Lists the project's Python dependencies and makes `finsight` installable.
  .env.example             # Template of all settings (API key, cert path, URLs). Copy to `.env` and fill in.
  .gitignore               # Tells git which files to never commit (secrets, the cert, big build outputs).
  Makefile                 # Shortcuts so you don't memorise long commands: `make ingest`, `make app`, `make eval`, `make test`.
  Dockerfile               # Recipe to build the app into a container (Week 3 packaging).
  docker-compose.yml       # Starts the 3 services together with one command: the app, Qdrant (search), Langfuse (tracing).
  .github/workflows/ci.yml # Runs the tests automatically on every code push, so breakage is caught early.
  vm04-ca.crt              # The security certificate for the provided LLM endpoint (needed to connect over HTTPS).
```
**docs/ — the written deliverables (graded)**
```
  docs/SPEC.md             # The project's rulebook: what it will/won't answer, the metric formulas, the answer format. Marked APPROVED.
  docs/DECISIONS.md        # Short write-ups of the 3 RAG choices (how we chunk, which embedding model, which reranker) with evidence.
  docs/SMALL_MODEL_FIXES.md # A running log of each small-model weakness we hit, the fix, and the before/after number.
```
**config/ — plain data files the code reads (edit these without touching code)**
```
  config/companies.yaml    # The master list of companies: sector, bank-or-not, financial-year end, reporting units.
  config/glossary.yaml     # The exact formula for every metric (e.g. operating margin, GNPA%). The calculator may ONLY use these.
  config/sections.yaml     # Which parts of a report to ingest (statements, notes, MD&A, risk) and how to recognise them.
```
**data/ and store/ — inputs (left) and the searchable indexes we build from them (right)**
```
  data/manual-collection/  # The 30 source annual-report PDFs you downloaded (the raw input).
  data/report_sources.csv  # For each PDF: where it came from, the download date, and a checksum to prove it hasn't changed.
  data/parsed/             # The cleaned, page-numbered text + tables that Docling extracts from each PDF.
  store/statement_lines.parquet # The table of exact figures (company, year, line item, value, page). The source of all numbers.
  store/qdrant/            # The vector search index (lets the chat find the right passage by meaning).
  store/memory.sqlite      # Remembers the conversation so follow-up questions ("and for last year?") work.
```
**scripts/ — small one-off helper programs**
```
  scripts/endpoint_check.py # Day-0 test: confirms the LLM endpoint works and what it supports (tools, JSON, limits).
  scripts/hash_reports.py   # Fills in report_sources.csv with each PDF's checksum.
```
**ingest/ — the offline pipeline that turns PDFs into searchable data (run once; re-run when PDFs change)**
```
  ingest/quality_gate.py   # Safety check: rejects any PDF that's missing a balance sheet, P&L, notes, or auditor's report.
  ingest/parse.py          # Reads each PDF with Docling (+OCR for image-heavy pages) into clean, page-numbered content.
  ingest/routing.py        # Decides per page how to read it: plain text, ruled table, scanned image (OCR), or chart.
  ingest/sections.py       # Splits each report into sections (one section = one "document" for search).
  ingest/tables.py         # Pulls the financial-statement tables into exact-figure rows for store/statement_lines.parquet.
  ingest/chunk.py          # Cuts text into search-sized pieces, each stamped with company/year/statement/page.
  ingest/embed_index.py    # Turns those pieces into vectors (local bge model) and loads them into Qdrant.
  ingest/run_ingest.py     # Runs the whole pipeline above, start to finish, with one command.
```
**src/finsight/ — the core package: the model client, the tools, and the agents**
```
  config.py                # Loads and validates all settings from .env in one place (endpoint, cert, budgets, URLs).
  llm.py                   # The one place that talks to the LLM: handles the cert, retries, the 1-at-a-time + 60/min limits, and turns off Qwen3's long "thinking".
  schemas.py               # The strict shapes (Pydantic models) for every agent's output, so bad model replies are caught.
  embeddings.py            # Runs the local bge embedding model used for search (no embeddings endpoint is provided).
  retrieval/               # Everything about FINDING the right passage:
    store.py               #   a common interface so the search backend is swappable.
    qdrant_store.py        #   the Qdrant implementation (meaning + keyword search with company/year filters).
    bm25.py dense.py hybrid.py # keyword search, meaning search, and how they're combined (RRF).
    reranker.py filters.py #   re-ranks the top hits; applies company/year/statement filters first.
  tools/                   # The agents' "hands" — each does one real job the model can't be trusted to do:
    base.py                #   shared error type + registry so every tool behaves the same.
    glossary.py            #   loads config/glossary.yaml and gives the calculator the right formula.
    get_company_profile.py #   looks up a company's sector, bank-or-not, units.
    get_financial_item.py  #   fetches an exact figure (value + unit + page) from the figure store. The main number source.
    search_report.py       #   searches the report text for notes/qualitative answers (uses retrieval/).
    read_table.py          #   returns a whole table from a cited page so the model can pick a row.
    normalise_units.py     #   converts crore / lakh / million and flags mismatches.
    calculate.py           #   does the maths using ONLY a glossary formula, and returns the formula it used.
    compare_rank.py        #   sorts and compares figures across companies/years (handles ties, missing values).
    create_note_draft.py   #   exports a cited analyst note as a DRAFT the user must approve.
  agent/                   # The thinking loop that coordinates everything:
    state.py               #   the shared "memory sheet" passed between agents (question, slots, results).
    guard.py               #   first gate: blocks unsafe/out-of-scope questions (advice, injection, unknown company).
    planner.py             #   breaks the question into steps and fills in company/year/metric (asks back if unclear).
    executor.py            #   runs the tool steps, and can re-plan when a step's result changes things.
    writer.py              #   drafts the final answer with figure, formula, inputs, and citations.
    critic.py              #   final checker: rejects any answer whose numbers/citations/formula don't hold up.
    graph.py               #   wires the agents together (LangGraph), with memory and a 10-step safety cap.
    prompts/               #   the actual instruction text for planner/writer/critic, kept outside code so it's easy to tune.
  safety/                  # Cross-cutting protections:
    guard_rules.py         #   the patterns for injection, investment-advice, and out-of-corpus detection.
    sanitiser.py pii.py    #   cleans user input; masks any personal data before it's written to logs.
```
**app/ — the chat screen the user actually uses**
```
  app/streamlit_app.py     # The web chat: company/year pickers, the answer card, clickable citations, the trace, and DRAFT + Approve.
  app/components.py         # Reusable UI pieces (answer card, citation links, "How I got this" trace view).
```
**eval/ — how we prove the system is correct (graded)**
```
  eval/eval_set.jsonl      # The frozen 90 test questions with their correct answers (tagged eval-v1).
  eval/compute_gold.py     # Computes the "correct" ratios from verified inputs using the glossary (never by hand).
  eval/score.py            # Grades answers automatically: right number? right page? right formula?
  eval/run_eval.py         # Runs the full chat (and a simpler comparison version) over all 90 questions.
  eval/taxonomy.py metrics.py # Labels each wrong answer by failure type; computes accuracy, citation rate, recall, latency, cost.
```
**tests/ — automated checks that the building blocks work**
```
  tests/test_calculate.py       # Checks every glossary formula gives the right result.
  tests/test_normalise_units.py tests/test_get_financial_item.py # unit conversion and figure lookup.
  tests/test_critic.py tests/test_caps.py # the critic's rejection rules; the step/loop/budget safety caps.
  tests/test_retrieval.py       # search filters and ranking behave as expected.
```
**results/ — the numbers and run logs the report is built from**
```
  results/week1_strategies.csv week1_failures.csv retrieval_experiment.csv runs/ # baseline scores, failure notes, retrieval study, saved runs.
```

---

## Implementation plan — 3 weeks, something working you can chat with every week

The idea: **the chat is built in Week 1 and grows every week.** Each week adds one clear ability, and you test it by typing questions into the same chat window. By Week 3 the chat does everything. This keeps the mapping to Track B items I–VI.

Think of it as the chat getting smarter each week:
- **Week 1 — it answers from the PDFs** accurately, with a page citation.
- **Week 2 — it can calculate and check itself** (full agents + tools + memory).
- **Week 3 — it is polished, safe, and shipped** (nice UI, guard rails, packaging).

### Week 1 — "The chat answers from the PDFs" · Track B items I (spec + eval) & III (RAG)  **(HARD GATE)**

**Deliverable in simple English:** a working chat where you type a plain question about a company's report and get back the correct figure **with the page it came from** — pulled from the actual PDFs, not the model's imagination. Plus the written rulebook (SPEC) and a frozen 90-question test set that we grade everything against.

- **Day 0 setup:** check the provided endpoint works (`:1034` + `vm04-ca.crt`; does it support tools and JSON output, what are the limits); register the **30 PDFs** (save their hash + source).
- **Data-quality gate (run first):** for every PDF, check it contains a balance sheet, P&L, notes, and auditor's report (a quick page-count + keyword scan). **Reject and re-download** any report that fails, so only complete reports go into ingestion. (All 30 currently pass.)
- Write **`SPEC.md`** (scope, refusal rules, the glossary of ~15 formulas for banks and non-banks, fiscal-year and unit rules, "consolidated is the default", the answer format, and the citation style like `INFY-FY2526-p214`). Mark it **APPROVED**.
- Write the **90-question test set** with correct ("gold") answers; freeze it with git tag **`eval-v1`**.
- **Ingest the PDFs (one-off):** parse with **Docling (+OCR for the graphic-heavy reports)**, keep the relevant sections, build the **statement-line store** (table of exact figures with page numbers), chunk the text with a metadata header (company, FY, statement, page), embed locally with **bge**, and load into **Qdrant**. Use **hybrid search + reranker + metadata filters** (filter by company/year/statement first so it never grabs the wrong year).
- Build the **Streamlit chat**: question → retrieve the right passages/figures → model writes the answer → show it **with the page citation**.
- Run baselines to prove it works: closed-book (no PDF) vs this retrieval chat, and the prompting styles from the brief. Note where the small model still slips (bad maths especially) in `week1_failures.csv`.
- **Gate to pass:** `SPEC.md` approved, `eval-v1` tagged, baseline results committed **before building the agent loop**.
- **How to test in chat:** ask *"Infosys consolidated revenue from operations, FY2025-26?"* → you get the exact figure and the page; ask for the prior year (FY2024-25) and it returns the correct other year from the same report's previous-year column.

### Week 2 — "The chat can calculate and check itself" · Track B items IV (agents) & V (evaluation)

**Deliverable in simple English:** the chat can now answer *calculation* questions — ratios, year-on-year change, comparisons, rankings — and it **shows the formula and the input numbers it used**, double-checks itself, and remembers the conversation so follow-up questions work.

- Build the full agent loop in LangGraph — **guard → planner → executor → writer → critic** — with the **8 tools**, error handling, and **cross-turn memory** (so "and for FY2024-25?" reuses the earlier question).
- Numbers come **only** from tools (figure-lookup and calculator); the critic **rejects** any answer whose numbers or citations don't check out, and asks the user to clarify when the question is vague.
- Add **unit tests** (every formula, unit conversion, the figure lookup, the critic rules, the step/loop caps).
- Run the **official evaluation** (agent runs vs a plain-retrieval comparison), build the failure table, and view runs in **Langfuse**.
- **How to test in chat:** ask *"Operating margin of Wipro, FY2025-26"* (see the formula + inputs), *"How did HCLTech net profit change FY2024-25 → FY2025-26?"*, *"Which of SBI, ICICI, HDFC had the lowest GNPA% in FY2025-26?"*, then a follow-up *"and for FY2024-25?"* — memory carries over.

### Week 3 — "The chat is polished, safe, and shipped" · Track B item VI (ship it)

**Deliverable in simple English:** the finished product — a clean chat screen with company/year pickers, answers showing the figure + formula + input table + **clickable page links**, a "How I got this" trace, polite refusals and clarify questions, a **DRAFT report export you must Approve**, all packaged to run with one command, plus the report and demo.

- Finish the **Streamlit UI**: pickers, the rich answer card, the trace view, and the DRAFT-note export (with the "verify before use" banner and an **Approve** button).
- Add the **safety layer**: prompt-injection tests (planted lines + user tricks), refusal tests (advice/forecasts), masking personal data in logs, and the "unverified — check page X" behaviour.
- **Package it:** Docker + docker-compose (app + Qdrant + Langfuse), health check, GitHub Actions CI, a 10-questions-per-minute limit, and an answer cache (off for official runs). Keep a red-team log of 15+ live prompts.
- **Deliverables:** 12-page report, 10-minute demo, recorded backup video.
- **How to test in chat:** ask *"Should I buy TCS?"* (polite refusal), *"What was revenue last year?"* (asks which company), a normal question (clickable citation + trace), then export and **Approve** a DRAFT note.

---

## Compensating for a small model (graded — keep `SMALL_MODEL_FIXES.md` from Day 1)

| Weakness | Compensation | Evidence to report |
|---|---|---|
| Invents figures | Numbers only from `get_financial_item` / cited tables; critic checks provenance | Hallucination rate with vs without critic |
| Arithmetic errors | `calculate` + glossary; model never computes | Ratio accuracy with vs without tool (Wk1 vs Wk2) |
| Wrong year/column | Metadata header in every chunk; planner filters validated by code | wrong_period_or_statement before/after |
| Unit confusion | `normalise_units`; units in JSON schema | unit_error count |
| Long dense context | Section-level retrieval; tables as markdown ≤40 rows | latency & tokens/question |
| Multi-step planning | Few-shot plans per intent; slot validation; 10-step cap | task completion rate |

---

## Role split (6 members)
Domain spec & eval · Prompt engineering · Ingestion & RAG · Agent orchestration & tools · Observability & safety · Front-end & deployment. Everyone writes ~15 gold answers in Week 1 (most labour-intensive Week 1 task).

## Risks & fallbacks
Poor table extraction / high-graphics & scanned pages → Docling (layout+OCR) first, Camelot for ruled tables, per-page routing with Tesseract/RapidOCR + rasterise-then-OCR fallback, Marker as alternate; restrict store to primary statements; hand-fix the ~30 P&L/BS pages (one-off) · Slow gold answers → start with fewer companies, cross-check headline figures via XBRL · Embedding quota → section-only ingestion + local bge · Bank vs non-bank formats → bank-aware glossary gated by `is_bank` · Download restrictions → manual download + hashes · 8B can't plan multi-company compares → planner emits per-company sub-plan, executor loops in code.

## Open questions for the programme office (via mentor)
1. Which chat/embeddings models are behind the endpoint; do they support tools & `json_schema`? (Confirmed chat = `Qwen/Qwen3-8B`; **no embeddings endpoint** per Track B guide.)
2. Does 1 document = 1 report section satisfy the 500–2,000 corpus rule?
3. Per-team token quota? (Budget ~1.8M embedding tokens for the official index + eval runs.)
4. May we embed locally (bge) in dev and use the provided endpoint only for official runs?
5. Capstone length: brochure says 2 weeks, template says 4 — **this plan is compressed to 3 weeks per the user's instruction.** Is 3 weeks acceptable?
6. **(Data — resolved)** Both fiscal years (FY2024-25 + FY2025-26) are present and complete for all 15 companies, so the two-year expectation and the 500-document floor are met. No open question remaining.

---

## Verification (how we'll know it works, end-to-end)
1. **Endpoint check:** `curl.exe --cacert vm04-ca.crt https://103.42.50.41:1034/v1/models` returns `Qwen/Qwen3-8B`; a sample `/chat/completions` returns content. Capability script records tools/json_schema support.
2. **Ingestion:** data-quality gate passes for all 30 PDFs (balance sheet + P&L + notes + auditor present); run `ingest/` → statement-line store populated; 20-table + 10-graphic-page hand-check logged with extraction/OCR accuracy; Qdrant collection built with payload filters.
3. **Retrieval:** `eval/` recall@1/3/5/10 computed against gold pages; `retrieval_experiment.csv` shows hybrid+reranker+filters best.
4. **Unit tests:** `pytest` green for calculator/glossary, `normalise_units`, `get_financial_item`, critic rules, loop/step-cap.
5. **Agent eval:** `eval/score.py` over `eval-v1` → per-type + overall accuracy, numeric/citation accuracy, calc-transparency; 3 agent runs vs 3 `single_rag` ablation show the agent/tools help; failure taxonomy populated; Langfuse traces visible.
6. **App:** `docker-compose up` → Streamlit at `/_stcore/health` green; ask a fact, a ratio, a YoY, a compare, a summary, a clarify, a refuse, and an injection question → each returns the spec-correct status with citations / formula / DRAFT-with-Approve; red-team log captured; CI green on GitHub Actions.
