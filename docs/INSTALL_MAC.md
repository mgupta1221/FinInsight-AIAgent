# FinSight — Installation on MacBook (Python 3.11)

This guide takes a new MacBook from nothing to a working agent. Use **Python 3.11** only. Run every command in **Terminal** from the project folder. Works on Apple Silicon (M1–M4) and Intel.

## Quick view: what to run and when

| Step | Command | How often | Needed before asking questions? |
| :---- | :---- | :---- | :---- |
| 2 | create and activate `.venv` | Create once; activate in every new window | Yes |
| 3 | `python -m pip install -e ".[dev]"` | Once | Yes |
| 4 | create `.env` | Once | Yes |
| 5 | copy the 30 PDFs | Once | Yes |
| 6 | `python scripts/endpoint_check.py` | Optional | No |
| 7 | `python -m pytest -q` | Optional; after code changes | No |
| 8 | `python -m ingest.run_ingest --figures-only` | Once; again if PDFs or the extractor change | Yes, for number questions |
| 9 | `python -m ingest.run_ingest` | Once; again if PDFs change | Yes, for summary and reported-ratio questions |
| 10 | `python scripts/ask.py "..."` | Every question |  |

Steps 8 and 9 save their results in `store/` and `data/parsed/`. You do not run them again before each question.

## 1\. What you need

| Item | Where from |
| :---- | :---- |
| Python 3.11 | Homebrew: `brew install python@3.11` (or the 3.11 installer from python.org) |
| The project folder |  |
| Team API key |  |
| Certificate `vm04-ca.crt` |  |
| 30 annual report PDFs | Team shared drive (about 500 MB) |

Check Python:

```
python3.11 --version
```

It must print `Python 3.11.x`.

## 2\. Create the virtual environment

```
cd ~/path/to/FinInsight-AIAgent-master
python3.11 -m venv .venv
source .venv/bin/activate
python --version
python -m pip install --upgrade pip
```

The prompt now starts with `(.venv)`. Run `source .venv/bin/activate` again in each new Terminal window.

## 3\. Install the packages

Pick one.

**Option A — core only (small, enough for the agent layer, tests and figure store):**

```
python -m pip install -e ".[dev]"
```

**Option B — everything (adds real embeddings, reranker and Docling; about 3 GB):**

```
python -m pip install -e ".[all,dev]"
```

Keep the quotes; zsh needs them around the square brackets. If Camelot or pdf2image complain in Option B, run `brew install ghostscript poppler` and repeat.

## 4\. Create the `.env` file

```
cp .env.example .env
open -e .env
```

Change these lines and save:

```
OPENAI_API_KEY=<the team key>
OPENAI_CA_CERT=./vm04-ca.crt
QDRANT_URL=./store/qdrant
```

Copy `vm04-ca.crt` into the project folder (next to `pyproject.toml`).

`QDRANT_URL=./store/qdrant` stores the search index in a local folder, so Docker is not needed. If you use Docker Desktop instead, keep `QDRANT_URL=http://localhost:6333` and run `make services`.

`.env` and `*.crt` are in `.gitignore`. Do not remove them from there.

## 5\. Put the PDFs in place

Since 27 Nov 2026 the 30 PDFs are in the repository, in `data/manual-collection/`; a fresh clone already has them. For a new report, copy it there. Names must follow this pattern:

```
Infosys-Annual-Report-2025-26.pdf
Infosys-Annual-Report-2024-25.pdf
```

The first part is the `pdf_prefix` in `config/companies.yaml`.

Record where the files came from (once, and again if a PDF is replaced):

```
python scripts/hash_reports.py
```

It lists every PDF with its SHA-256 checksum in `data/report_sources.csv`. Type the download URL and date into that file by hand; they are kept when the script runs again. A line marked `CHANGED` means a PDF is not the same file as before.

## 6\. Check the endpoint (once per day is enough)

```
python scripts/endpoint_check.py
```

## 7\. Run the tests (no key, PDFs or internet needed)

```
python -m pytest -q
```

<!-- 24 Nov 2026: was 206 passed before the tests for the new chat screen and the loss question -->
Expected: **211 passed**.

## 8\. Build the figure store (needed for number questions)

```
python -m ingest.run_ingest --figures-only
```

Takes about 2 minutes for 30 reports. It writes `store/statement_lines.csv` and `store/statement_lines.parquet`. Run it again whenever `ingest/statements.py` or the PDFs change (last extractor change: 15 Nov 2026). One company only: `python -m ingest.run_ingest --figures-only --only INFY`.

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
python scripts/ask.py "What was Infosys' consolidated revenue from operations in FY2025-26?"
python scripts/ask.py "And for FY2024-25?"
python scripts/ask.py "What was Infosys' operating margin in FY2025-26?" --trace
python scripts/ask.py --reset
```

`--trace` prints every step. `--reset` clears the conversation memory. `--session NAME` keeps separate conversations.

<!-- Changed 24 Nov 2026: the sidebar no longer has the "Basic search" switch (removed after the mentor's review). Old text:
Chat screen in the browser. It uses the agent by default and shows the answer, the formula, the figures used with their pages, and a "How I got this" trace. The sidebar has a switch to "Basic search (baseline, no checks)", which is one search and one model answer without the agent, and a "New conversation" button that starts a fresh conversation:
-->
Chat screen in the browser. It always uses the agent and shows the answer, the formula and, under "Citation", the figures used with a link to the page of each. The sidebar has a "New conversation" button and the list of past conversations: click one to open it, or click the bin beside it to delete it (it asks first). Under the newest reply, "Export to PDF" saves the complete conversation as a PDF in the Downloads folder:

```
streamlit run app/streamlit_app.py
```

The `Makefile` shortcuts also work on Mac: `make install`, `make check`, `make test`, `make ingest`, `make app`.

## 11\. Common problems

| Message | Fix |
| :---- | :---- |
| `command not found: python3.11` | `brew install python@3.11`, then open a new Terminal |
| `zsh: no matches found: .[dev]` | Put the quotes: `".[dev]"` |
| `CERTIFICATE_VERIFY_FAILED` | `OPENAI_CA_CERT` in `.env` does not point to `vm04-ca.crt` |
| `401` | Wrong or missing `OPENAI_API_KEY` |
| `429` | Only one request at a time is allowed per key. Wait and retry; do not run two terminals together |
| `figure store not found` | Run step 8 |
| `dense search unavailable ... actively refused` / `Connection refused` | `QDRANT_URL` in `.env` points to a Qdrant server that is not running. Set `QDRANT_URL=./store/qdrant` (no Docker needed). Until the index is built the agent uses keyword search, which still works |
| `sentence-transformers unavailable` | Only a notice. Install Option B in step 3 for better search quality |
| `nothing found for ...` (escalated) | Search index not built. Run step 9 |
| `ModuleNotFoundError: finsight` | The venv is not active, or step 3 was skipped |

&nbsp;
<!-- Changed 24 Nov 2026: Quick lookup was removed from the chat screen after the mentor's review; every question is typed in the chat box. Old section:
## Quick lookup in the chat screen (added 19 Nov 2026)

Nothing new to install. Start the chat screen as before (`streamlit run app/streamlit_app.py`). In the sidebar,
under "Quick lookup": pick a sector, one or more companies, a figure or ratio, a year and the scope, then press
"Get answer". Pick two or more companies to compare them. The list of figures changes with the sector (bank
figures for banks). You can still type any question in the chat box.
-->
## The chat screen after the mentor's review (changed 24 Nov 2026)

Nothing new to install. Quick lookup, the Basic search switch and the Deploy button are removed. The sidebar
holds "New conversation" and the past conversations. "Export to PDF" under a verified answer replaces the
Draft and Approve buttons. If the Deploy button or the old sidebar still shows, stop the app and start it
again; with Docker, rebuild the image.

## Run the evaluation (added 21 Nov 2026)

Nothing new to install. Qdrant must be running and `.env` must hold the endpoint key, as for the chat screen.

```
python eval/run_eval.py --limit 5            a quick try with the first 5 questions
python eval/run_eval.py                      practice run, all 90 questions, the agent
python eval/run_eval.py --mode simple        practice run, simple search (for the comparison)
python eval/run_eval.py --resume results/runs/<folder>      continue a run that stopped
python eval/run_eval.py --official           OFFICIAL run: only on frozen code
python eval/metrics.py results/official      average over the official runs
```

Practice runs are saved in `results/runs/` (not pushed to GitHub; delete them when you like). Official runs are
saved in `results/official/` and are committed. In each run folder open `scored.csv` in Excel to see every
question, and `errors.csv` for the wrong ones with a likely cause.

### Reviewing the summaries of a run (added 21 Nov 2026)

Each run folder has `summary_review.csv`: the gold key points beside the agent's summary. Open it in Excel, type Y
or N in the column `human_covered` for every row, save it as CSV, then:

```
python eval/run_eval.py --rescore results/runs/<folder>
```

## Baselines without the reports (added 22 Nov 2026)

Four more evaluation modes ask the model the 90 questions **without any report text**, each in a different
prompting style. They show what the reports and the agent add. Run them one at a time; the last one asks every
question five times and takes several times longer.

```
python eval/run_eval.py --mode closed_book
python eval/run_eval.py --mode few_shot
python eval/run_eval.py --mode decompose
python eval/run_eval.py --mode cot_sc
python eval/baselines.py
```

The last command writes `results/week1_strategies.csv` and `results/week1_failures.csv` from the newest complete
run of each mode. Try `--limit 5` first to see that a mode works.

## Optional: run everything with Docker

You do not need Docker for the steps above. This is a second way to start the project: one command builds a
container with Python and the libraries inside and starts the chat screen together with the search database
(Qdrant). First run by the team on 22 Nov 2026, on Windows: build under 6 minutes, chat screen opened, 204 tests passed and a short evaluation scored 5 of 5 inside the container. Not yet tried on a Mac or on a laptop that has never run the ingest.

What Docker does not contain, and you must still provide: the API key (in `.env`), the certificate file
`vm04-ca.crt`, and the report PDFs or the stores built from them. None of them is in the image or on GitHub.

1. Install Docker Desktop and start it.
2. In the project folder: `.env` with `OPENAI_API_KEY` set, and `vm04-ca.crt` beside it.
3. Build and start the app and Qdrant (the first build downloads about 2 to 3 GB and can take 15 minutes or more):

   ```
   docker compose --env-file .env up --build --wait app qdrant
   ```

4. Open http://localhost:8501 for the chat screen.
5. The ingest. **Not needed** if this laptop already ran the ingest with Qdrant in Docker from this same folder:
   the figure store and parsed text are in `store/` and `data/`, which the container shares, and the search index
   is in the Qdrant volume that Docker keeps. On a laptop that never ran the ingest (PDFs in
   `data/manual-collection/` first):

   ```
   docker compose exec app python -m ingest.run_ingest
   ```

6. Check it from inside the container:

   ```
   docker compose exec app python -m pytest -q
   docker compose exec app python eval/run_eval.py --limit 5
   ```

7. Stop: `docker compose --env-file .env down` (the volumes, and so the search index, are kept).

Notes:

- `store/`, `data/` and `results/` are shared with the laptop. Evaluation results and exported notes written
  inside the container appear in `results/`.
- Past conversations made in the Docker app are kept in a Docker volume, separate from those of the app started
  without Docker.
- The first question after a start is slow: the embedding model and the reranker are downloaded once (they are
  then kept in a Docker volume).
- Inside Docker the settings `QDRANT_URL`, `OPENAI_CA_CERT`, `MEMORY_DB` and `LANGFUSE_HOST` are set by
  `docker-compose.yml`; the values in `.env` for these are ignored.
- Langfuse is not used by the code. To start it as well, leave `app qdrant` off the command in step 3.
- Make the official evaluation runs without Docker, in the environment the practice runs were made in.
