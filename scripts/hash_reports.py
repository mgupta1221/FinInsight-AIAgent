# ORIGINAL PLACEHOLDER (kept):
# """Fill data/report_sources.csv with each PDF's SHA-256 checksum (and placeholders for url/date).
# TODO (Week 1): walk data/manual-collection/, hash each file, write/update the CSV.
# """
# if __name__ == "__main__":
#     print("TODO: implement report hashing -> data/report_sources.csv")
#
# IMPLEMENTED (15 Nov 2026).
"""Fill data/report_sources.csv: one row per PDF in data/manual-collection/ with its SHA-256 checksum.

WHY: the checksum proves which exact file an answer was read from. If a PDF is replaced later (as happened
with the Axis Bank FY2025-26 report), its checksum changes and this script shows it.

The script only fills `filename` and `sha256`. `url` and `download_date` are typed in by the team and are
KEPT on every run: a row is matched by file name, and only its checksum is refreshed.

Run from the project root:   python scripts/hash_reports.py
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "data" / "manual-collection"
CSV_PATH = ROOT / "data" / "report_sources.csv"
FIELDS = ["filename", "url", "download_date", "sha256"]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):       # 1 MB at a time: reports are 5-40 MB
            h.update(block)
    return h.hexdigest()


def update_sources(pdf_dir: Path = PDF_DIR, csv_path: Path = CSV_PATH) -> list[str]:
    """Write the CSV and return one message per file: 'new', 'unchanged', 'CHANGED' or 'MISSING'."""
    rows: dict[str, dict] = {}
    if csv_path.exists():
        with open(csv_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("filename"):
                    rows[r["filename"]] = {k: (r.get(k) or "") for k in FIELDS}
    messages = []
    pdfs = sorted(pdf_dir.glob("*.pdf"), key=lambda p: p.name.lower())
    for pdf in pdfs:
        digest = sha256_of(pdf)
        old = rows.get(pdf.name)
        if old is None:
            rows[pdf.name] = {"filename": pdf.name, "url": "", "download_date": "", "sha256": digest}
            messages.append(f"new        {pdf.name}")
        elif old["sha256"] and old["sha256"] != digest:
            old["sha256"] = digest
            messages.append(f"CHANGED    {pdf.name}  (the file was replaced: check url and download_date)")
        else:
            old["sha256"] = digest
            messages.append(f"unchanged  {pdf.name}")
    present = {p.name for p in pdfs}
    messages += [f"MISSING    {name}  (listed in the CSV, not in {pdf_dir.name}/)" for name in rows if name not in present]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for name in sorted(rows, key=str.lower):
            w.writerow(rows[name])
    return messages


if __name__ == "__main__":
    out = update_sources()
    print("\n".join(out))
    print(f"\n{len(out)} files listed in {CSV_PATH.relative_to(ROOT)}. Fill in url and download_date by hand; they are kept on the next run.")
