# FinSight — Multi-Agent Financial Report Q&A Copilot

A chat assistant for Indian company annual reports. Ask a question and get an answer
drawn from the **actual reports** — every answer shows the **page it came from**, and every
calculation shows **the formula and inputs it used**. Built on the course-provided ≤8B model
(Qwen3-8B) and surrounded by a search engine, a calculator, and a self-checking critic so a
small model stays trustworthy.

See **[BUILD_PLAN.md](BUILD_PLAN.md)** for the full plan and technical architecture — it is the
single reference this project is built from.

---

## Quick start (Docker)

> Prerequisites: **Docker** and **Docker Compose**.

1. **Clone & configure:**
   ```bash
   cp .env.example .env        # edit .env → set OPENAI_API_KEY
   ```
2. **Place required files** in the project root:
   - `vm04-ca.crt` (CA certificate)
   - PDFs in `data/manual-collection/`
3. **Start all services** (app + Qdrant + Langfuse):
   ```bash
   docker compose --env-file .env up --build --wait
   ```
4. **Run ingestion** (one-off):
   ```bash
   docker compose exec app python -m ingest.run_ingest          # all companies
   docker compose exec app python -m ingest.run_ingest --only INFY  # single company
   ```
5. **Open the chat UI:** [http://localhost:8501](http://localhost:8501)
6. **Stop:**
   ```bash
   docker compose --env-file .env down
   ```

> Langfuse tracing UI is at [http://localhost:3000](http://localhost:3000). Qdrant dashboard at [http://localhost:6333/dashboard](http://localhost:6333/dashboard).

---

## Quick start (Windows)

> Prerequisites: **Python 3.11** (step 1 below) and, on Windows, PowerShell. Docker is optional.
> Commands below use PowerShell.
>
> **Use Python 3.11.** It is the newest version where the whole stack (torch, onnxruntime, Docling,
> Camelot, pdfplumber) has compatible wheels and installs together. Newer versions (3.12+) lack wheels
> for these libraries.

### Before you begin — get these 3 things from your team (they are NOT in the repo)

For security and size reasons these are deliberately excluded from git (`.gitignore`), so after
cloning you must obtain them from your coordinator / team drive:

1. **Group API key** — the key for your group's inference endpoint. Goes in `.env` (step 4).
2. **CA certificate `vm04-ca.crt`** — the HTTPS certificate for the endpoint. **Save it in the project
   root** (the `Project\` folder, next to `README.md`). If the file has a different name or location,
   point `OPENAI_CA_CERT` in `.env` at it.
3. **The 30 annual-report PDFs** — put them in `data\manual-collection\` (step 4).

> Your base URL and certificate are **group-specific**. The defaults in `.env.example` are for group
> 046–065 (`https://103.42.50.41:1034/v1`, `vm04-ca.crt`); if you are in another group, use your
> group's URL and certificate instead.

### 1. Install Python 3.11 (Py Manager)

Windows ships the **Py Manager** (`py`). Install 3.11 with it, then confirm:

```powershell
py install 3.11
py --list                    # 3.11 should now appear in the list
```

### 2. Create and activate the virtual environment

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python --version             # confirm the active interpreter is Python 3.11.x
```

*(If activation is blocked by execution policy, run `Set-ExecutionPolicy -Scope Process -Bypass` once,
then re-run the activate line. After activation your prompt shows `(.venv)` and `python`/`pip` refer to
the 3.11 environment.)*

### 3. Install the project (everything, one command)

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[all]"
```

### 4. Configure and run

1. **Create your `.env`** from the template, then fill in your key and the certificate path:
   ```powershell
   copy .env.example .env             # creates .env; now open it in an editor
   ```
   In `.env`, set these (everything else already has a working default):
   - `OPENAI_API_KEY` — your **group API key**.
   - `OPENAI_CA_CERT` — path to the certificate. Leave as `./vm04-ca.crt` if you saved the cert in the
     project root (recommended); otherwise point it at the cert's full path.
   - *(optional)* `QDRANT_URL=./store/qdrant` — run the search database locally, no Docker (see step 3).

   Then run the Day-0 endpoint check (confirms the key + certificate work):
   ```powershell
   python scripts\endpoint_check.py
   ```
2. **Add the PDFs** — put the 30 annual-report PDFs (obtained from your team) into
   `data\manual-collection\`.
3. **Pick a vector store** — either run Qdrant in Docker:
   ```powershell
   docker compose up -d qdrant
   ```
   **or** set `QDRANT_URL=./store/qdrant` in `.env` to run Qdrant locally (embedded) with no Docker.
   *(Embedded mode locks the folder to one process — ingest first, then run the app; don't run both at once.)*
4. **Run ingestion** (one-off; full run is slow on CPU — run overnight, try `--only INFY` first):
   ```powershell
   python -m ingest.run_ingest --only INFY  # omit --only INFY for all companies
   python scripts\validate_ingest.py     # confirm it produced all artifacts (PASS on all 3)
   ```
5. **Chat:**
   ```powershell
   python -m streamlit run app\streamlit_app.py
   ```

> Keep the `(.venv)` environment activated for every command above. In a new terminal, re-activate
> with `.venv\Scripts\Activate.ps1` first.
> Run ingestion from the project root using `python -m ingest.run_ingest`, not
> `python ingest\run_ingest.py`, so Python can resolve the `ingest` package.

## Makefile shortcuts

| Command | What it does |
|---|---|
| `make setup` | First-time setup: start services → install deps → run ingestion |
| `make dev` | Daily start: start services → launch the app |
| `make install` | Install the package (editable) + dev deps |
| `make check` | Verify the LLM endpoint + capabilities (Day-0 check) |
| `make services` | Start Qdrant + Langfuse in the background |
| `make ingest` | Run the one-off PDF ingestion pipeline |
| `make validate` | Check that ingestion produced all expected artifacts |
| `make app` | Launch the Streamlit chat UI |
| `make eval` | Run evaluation over the frozen 90-question set |
| `make test` | Run unit tests |
| `make lint` | Lint the codebase with Ruff |
| `make down` | Stop all Docker services |

## What gets built, week by week

| Week | The chat can… | Track B items |
|---|---|---|
| 1 | Answer from the PDFs, with a page citation | I (spec + eval), III (RAG) |
| 2 | Calculate and check itself (agents + tools + memory) | IV (agents), V (evaluation) |
| 3 | Polished, safe, and shipped (UI, guard rails, Docker/CI) | VI (ship it) |

## Repository layout

See the **Repository skeleton** section of `BUILD_PLAN.md` for a file-by-file explanation. In short:

- `src/finsight/` — the core package (LLM client, retrieval, the 8 tools, the agent loop, safety)
- `ingest/` — the one-off pipeline that turns PDFs into the figure store + search index
- `eval/` — the frozen 90-question test set and the grading harness
- `app/` — the Streamlit chat UI
- `config/` — editable data files (companies, metric glossary, sections to ingest)
- `docs/` — SPEC, RAG decisions, and the small-model-fixes log

## Data

The 30 source annual-report PDFs (15 companies × FY2024-25 and FY2025-26) go in
`data/manual-collection/`. Record each file's source and checksum in `data/report_sources.csv`
(`python scripts/hash_reports.py`). An automated data-quality gate rejects any report missing a
balance sheet, P&L, notes, or auditor's report.

## Not investment advice

FinSight answers factual and analytical questions about the reports in its corpus. It refuses
buy/sell/hold advice, price targets, and forecasts, and marks any answer it cannot verify.
