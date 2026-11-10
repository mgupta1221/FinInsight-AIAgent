# Convenience shortcuts. Usage: make <target>
.PHONY: install check services ingest app eval test lint

install:            ## Install the package (editable) + dev deps
	pip install -e ".[dev]"

check:              ## Day-0: verify the LLM endpoint + capabilities
	python scripts/endpoint_check.py

services:           ## Start Qdrant + Langfuse in the background
	docker compose up -d qdrant langfuse

ingest:             ## Run the one-off PDF ingestion pipeline
	python -m ingest.run_ingest

validate:           ## Check that ingestion produced all artifacts
	python scripts/validate_ingest.py

app:                ## Launch the Streamlit chat
	streamlit run app/streamlit_app.py

eval:               ## Run the evaluation over the frozen 90-question set
	python eval/run_eval.py

test:               ## Run unit tests
	pytest -q

lint:               ## Lint the codebase
	ruff check .
