"""Validate that ingestion (step 4) ran successfully.

Checks the three artifacts ingestion produces and prints a PASS/FAIL report:
  1. store/statement_lines.parquet  — the exact-figure store (rows, companies, years)
  2. data/parsed/chunks.jsonl       — the chunk corpus for BM25 (count, companies, years)
  3. Qdrant collection              — the vector index (point count), plus a sample search

Run:  python scripts/validate_ingest.py
Note: with embedded Qdrant (QDRANT_URL=./store/qdrant), close the app first — the folder locks
to one process at a time.
"""

from __future__ import annotations

import json
import sys

from finsight.config import settings

PASS, FAIL = "PASS", "FAIL"


def _check_figures() -> bool:
    path = settings.store_dir / "statement_lines.parquet"
    if not path.exists():
        print(f"[{FAIL}] figure store missing: {path}")
        return False
    import pandas as pd

    df = pd.read_parquet(path)
    if df.empty:
        print(f"[{FAIL}] figure store is empty")
        return False
    companies = sorted(df["ticker"].unique())
    years = sorted(df["fiscal_year"].unique())
    print(f"[{PASS}] figure store: {len(df)} rows · {len(companies)} companies {companies} · years {years}")
    print(f"        sample: {df.iloc[0]['ticker']} {df.iloc[0]['fiscal_year']} "
          f"'{df.iloc[0]['line_item'][:40]}' = {df.iloc[0]['value']} {df.iloc[0]['unit']} (p{df.iloc[0]['page']})")
    return True


def _check_chunks() -> bool:
    path = settings.data_dir / "parsed" / "chunks.jsonl"
    if not path.exists():
        print(f"[{FAIL}] chunk corpus missing: {path}")
        return False
    with open(path, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    if not rows:
        print(f"[{FAIL}] chunk corpus is empty")
        return False
    companies = sorted({r["ticker"] for r in rows})
    years = sorted({r["fiscal_year"] for r in rows})
    print(f"[{PASS}] chunk corpus: {len(rows)} chunks · {len(companies)} companies · years {years}")
    return True


def _check_index() -> bool:
    try:
        from finsight.retrieval.qdrant_store import QdrantStore

        store = QdrantStore()
        try:
            count = store.count()
        except Exception:  # collection not created yet
            print(f"[{FAIL}] Qdrant collection '{settings.qdrant_collection}' not found")
            return False
        if count == 0:
            print(f"[{FAIL}] Qdrant collection '{settings.qdrant_collection}' is empty")
            return False
        print(f"[{PASS}] Qdrant index: {count} vectors in '{settings.qdrant_collection}'")

        from finsight.tools.search_report import search_report
        import finsight.tools.search_report as sr

        sr._store = store
        hits = search_report("revenue from operations", top_k=3)
        print(f"[{PASS}] sample search returned {len(hits)} passages"
              + (f" (top: {hits[0]['citation']})" if hits else ""))
        return bool(hits)
    except Exception as e:  # noqa: BLE001
        print(f"[{FAIL}] could not query Qdrant: {e}")
        return False


def main() -> int:
    print(f"Validating ingestion artifacts (QDRANT_URL={settings.qdrant_url})\n")
    results = [_check_figures(), _check_chunks(), _check_index()]
    ok = all(results)
    print("\n" + ("INGESTION OK - all artifacts present." if ok
                  else "INGESTION INCOMPLETE - see FAIL lines above; re-run step 4."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
