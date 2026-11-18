# FinSight — Installation on Windows (Python 3.11)

This guide takes a new laptop from nothing to a working agent. Use **Python 3.11** only. Run every command in **Command Prompt** (not PowerShell) from the project folder.

## Quick view: what to run and when

| Step | Command | How often | Needed before asking questions? |
| :---- | :---- | :---- | :---- |
| 2 | create and activate `.venv` | Create once; activate in every new window | Yes |
| 3 | `python -m pip install -e ".[dev]"` | Once | Yes |
| 4 | create `.env` | Once | Yes |
| 5 | copy the 30 PDFs | Once | Yes |
| 6 | `python scripts\endpoint_check.py` | Optional | No |
| 7 | `python -m pytest -q` | Optional; after code changes | No |
| 8 | `python -m ingest.run_ingest --figures-only` | Once; again if PDFs or the extractor change | Yes, for number questions |
| 9 | `python -m ingest.run_ingest` | Once; again if PDFs change | Yes, for summary and reported-ratio questions |
| 10 | `python scripts\ask.py "..."` | Every question |  |

Steps 8 and 9 save their results in `store\` and `data\parsed\`. You do not run them again before each question.

## 1\. What you need

| Item | Where from |
| :---- | :---- |
| Python 3.11 (64-bit) | python.org → Downloads → Windows → 3.11.x. Tick **"Add python.exe to PATH"** in the installer |
| The project folder |  |
| Team API key |  |
| Certificate `vm04-ca.crt` |  |
| 30 annual report PDFs | Team shared drive (about 500 MB) |

Check Python:

```
py -3.11 --version
```

It must print `Python 3.11.x`.

## 2\. Create the virtual environment

```
cd C:\path\to\FinInsight-AIAgent-master
py -3.11 -m venv .venv
.venv\Scripts\activate
python --version
python -m pip install --upgrade pip
```

The prompt now starts with `(.venv)`. Activate it again each time you open a new window.

## 3\. Install the packages

Pick one.

**Option A — core only (small, enough for the agent layer, tests and figure store):**

```
python -m pip install -e ".[dev]"
```

**Option B — everything (adds real embeddings, reranker and Docling; about 3 GB, needs good internet):**

```
python -m pip install -e ".[all,dev]"
```

Always type `python -m pip`, not `pip`.

## 4\. Create the `.env` file

```
copy .env.example .env
notepad .env
```

Change these lines and save:

```
OPENAI_API_KEY=<the team key>
OPENAI_CA_CERT=./vm04-ca.crt
QDRANT_URL=./store/qdrant
```

Copy `vm04-ca.crt` into the project folder (next to `pyproject.toml`).

`QDRANT_URL=./store/qdrant` stores the search index in a local folder, so Docker is not needed. If you use Docker instead, keep `QDRANT_URL=http://localhost:6333` and run `docker compose --env-file .env up -d qdrant`.

`.env` and `*.crt` are in `.gitignore`. Do not remove them from there.

## 5\. Put the PDFs in place

Copy the 30 PDFs into `data\manual-collection\`. Names must follow this pattern:

```
Infosys-Annual-Report-2025-26.pdf
Infosys-Annual-Report-2024-25.pdf
```

The first part is the `pdf_prefix` in `config\companies.yaml`.

Record where the files came from (once, and again if a PDF is replaced):

```
python scripts\hash_reports.py
```

It lists every PDF with its SHA-256 checksum in `data\report_sources.csv`. Type the download URL and date into that file by hand; they are kept when the script runs again. A line marked `CHANGED` means a PDF is not the same file as before.

## 6\. Check the endpoint (once per day is enough)

```
python scripts\endpoint_check.py
```

## 7\. Run the tests (no key, PDFs or internet needed)

```
python -m pytest -q
```

Expected: **128 passed**.

## 8\. Build the figure store (needed for number questions)

```
python -m ingest.run_ingest --figures-only
```

Takes about 2 minutes for 30 reports. It writes `store\statement_lines.csv` and `store\statement_lines.parquet`. Run it again whenever `ingest\statements.py` or the PDFs change (last extractor change: 15 Nov 2026). One company only: `python -m ingest.run_ingest --figures-only --only INFY`.

## 9\. Build the search index (needed for summary and reported-ratio questions)

```
python -m ingest.run_ingest
```

This parses, chunks, embeds and indexes all reports. It is slow on a laptop; start it and leave it running. Quicker version (text chunks for keyword search only, no vector index):

```
python -m ingest.run_ingest --no-index
```

Until it is run, questions such as "CASA ratio" or "summarise the risks" return *escalated*. Use Option B in step 3 first for real embedding quality; with Option A the code uses a weaker fallback embedding.

## 10\. Ask questions

```
python scripts\ask.py "What was Infosys' consolidated revenue from operations in FY2025-26?"
python scripts\ask.py "And for FY2024-25?"
python scripts\ask.py "What was Infosys' operating margin in FY2025-26?" --trace
python scripts\ask.py --reset
```

`--trace` prints every step. `--reset` clears the conversation memory. `--session NAME` keeps separate conversations.

Chat screen in the browser. It uses the agent by default and shows the answer, the formula, the figures used with their pages, and a "How I got this" trace. The sidebar has a switch back to the older "Simple search (Week 1)" mode and a "New conversation" button that clears the memory:

```
streamlit run app\streamlit_app.py
```

## 11\. Common problems

| Message | Fix |
| :---- | :---- |
| `py is not recognized` | Reinstall Python 3.11 with "Add to PATH" ticked, or use the full path to `python.exe` |
| `Unable to create process` when using `pip` | Use `python -m pip ...` |
| `CERTIFICATE_VERIFY_FAILED` | `OPENAI_CA_CERT` in `.env` does not point to `vm04-ca.crt` |
| `401` | Wrong or missing `OPENAI_API_KEY` |
| `429` | Only one request at a time is allowed per key. Wait and retry; do not run two terminals together |
| `figure store not found` | Run step 8 |
| `dense search unavailable ... actively refused` / `Connection refused` | `QDRANT_URL` in `.env` points to a Qdrant server that is not running. Set `QDRANT_URL=./store/qdrant` (no Docker needed). Until the index is built the agent uses keyword search, which still works |
| `sentence-transformers unavailable` | Only a notice. Install Option B in step 3 for better search quality |
| `nothing found for ...` (escalated) | Search index not built. Run step 9 |
| `ModuleNotFoundError: finsight` | The venv is not active, or step 3 was skipped |

&nbsp;