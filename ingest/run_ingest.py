"""Orchestrate the one-off ingestion pipeline over the report corpus.

For each company in config/companies.yaml and each fiscal year, find its PDF in
data/manual-collection/, then:
  quality_gate -> parse (+sections) -> tables (figure store) -> chunk -> embed_index.

Writes:
  - store/statement_lines.parquet   (exact figures)
  - data/parsed/chunks.jsonl        (chunk corpus for BM25)
  - Qdrant collection               (vector index)

Usage:
  Run from the project root:
  python -m ingest.run_ingest                 # all companies, all years
  python -m ingest.run_ingest --only INFY     # one ticker
  python -m ingest.run_ingest --limit-pages 60 --no-index   # quick smoke test
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from finsight.config import settings
from finsight.tools.get_company_profile import _load as load_companies

from ingest.chunk import chunk_pages
from ingest.embed_index import index_chunks, write_chunk_corpus
from ingest.parse import parse_pdf
from ingest.quality_gate import check_report
from ingest.sections import assign_sections, keep_keys
from ingest.tables import extract_statement_lines

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ingest")

PDF_DIR = settings.data_dir / "manual-collection"


def _find_pdf(prefix: str, fy: str) -> Path | None:
    for p in PDF_DIR.glob(f"{prefix}*{fy}*.pdf"):
        return p
    return None


def _companies():
    index, _ = load_companies()
    # de-duplicate (index maps several keys to the same profile)
    seen, out = set(), []
    for prof in index.values():
        if prof["ticker"] not in seen:
            seen.add(prof["ticker"])
            out.append(prof)
    return out


def run(only: str | None, use_docling: bool, do_index: bool, limit_pages: int | None,
        skip_quality_gate: bool = False) -> None:
    all_rows: list[dict] = []
    all_chunks: list[dict] = []
    keep = keep_keys()

    for prof in _companies():
        if only and prof["ticker"].upper() != only.upper():
            continue
        for fy in prof.get("fiscal_years", ["2024-25", "2025-26"]):
            pdf = _find_pdf(prof["pdf_prefix"], fy)
            if not pdf:
                logger.warning("MISSING pdf: %s FY%s", prof["ticker"], fy)
                continue
            logger.info("parsing %s FY%s (%s)", prof["ticker"], fy, pdf.name)
            pages = parse_pdf(pdf, use_docling=use_docling)
            if limit_pages:
                pages = pages[:limit_pages]

            ok, missing = check_report(pages)
            if not ok and not limit_pages:
                if skip_quality_gate:
                    logger.warning("QUALITY GATE bypassed for %s FY%s — missing %s; ingesting anyway",
                                   prof["ticker"], fy, missing)
                else:
                    logger.error("QUALITY GATE FAILED for %s FY%s — missing %s; skipping "
                                 "(use --no-quality-gate to override)", prof["ticker"], fy, missing)
                    continue

            pages = assign_sections(pages, is_bank=prof.get("is_bank", False))
            meta = {
                "company": prof["name"],
                "ticker": prof["ticker"],
                "fiscal_year": fy,
                "scope": "consolidated",
                "unit": prof.get("reporting_units", "crore"),
                "pdf": pdf.name,
            }
            all_rows.extend(extract_statement_lines(pages, meta))
            all_chunks.extend(chunk_pages(pages, meta, keep_sections=keep))

    # write figure store
    if all_rows:
        settings.store_dir.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(all_rows)
        df.to_parquet(settings.store_dir / "statement_lines.parquet", index=False)
        logger.info("wrote %d statement-line rows", len(df))
    else:
        logger.warning("no statement-line rows extracted")

    # write chunk corpus (for BM25) and index (for dense search)
    write_chunk_corpus(all_chunks)
    logger.info("wrote %d chunks", len(all_chunks))
    if do_index:
        n = index_chunks(all_chunks)
        logger.info("indexed %d vectors into Qdrant", n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="limit to one ticker (e.g. INFY)")
    ap.add_argument("--docling", action="store_true", help="use Docling+OCR parser")
    ap.add_argument("--no-index", action="store_true", help="skip Qdrant indexing")
    ap.add_argument("--limit-pages", type=int, help="only first N pages per report (smoke test)")
    ap.add_argument("--no-quality-gate", action="store_true",
                    help="ingest even reports that fail the completeness check")
    args = ap.parse_args()
    run(args.only, args.docling, not args.no_index, args.limit_pages, args.no_quality_gate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
