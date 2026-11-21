"""Tests for scripts/hash_reports.py (the report source list with SHA-256 checksums).

NEW FILE (15 Nov 2026). Uses tiny made-up files in a temporary folder.
"""
import csv
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from hash_reports import update_sources  # noqa: E402


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return {r["filename"]: r for r in csv.DictReader(f)}


def test_hashes_are_filled_and_typed_in_columns_are_kept(tmp_path):
    pdfs, out = tmp_path / "pdfs", tmp_path / "sources.csv"
    pdfs.mkdir()
    (pdfs / "A-Annual-Report-2025-26.pdf").write_bytes(b"report A")
    (pdfs / "B-Annual-Report-2025-26.pdf").write_bytes(b"report B")
    assert [m.split()[0] for m in update_sources(pdfs, out)] == ["new", "new"]
    rows = read(out)
    assert rows["A-Annual-Report-2025-26.pdf"]["sha256"] == hashlib.sha256(b"report A").hexdigest()

    rows["A-Annual-Report-2025-26.pdf"].update(url="https://example.com/a.pdf", download_date="2026-11-10")   # typed in by a person
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "url", "download_date", "sha256"])
        w.writeheader()
        w.writerows(rows.values())
    (pdfs / "B-Annual-Report-2025-26.pdf").write_bytes(b"report B, corrected file")
    (pdfs / "C-Annual-Report-2025-26.pdf").write_bytes(b"report C")
    assert [m.split()[0] for m in update_sources(pdfs, out)] == ["unchanged", "CHANGED", "new"]
    rows = read(out)
    assert rows["A-Annual-Report-2025-26.pdf"]["url"] == "https://example.com/a.pdf" and rows["A-Annual-Report-2025-26.pdf"]["download_date"] == "2026-11-10"
    assert rows["B-Annual-Report-2025-26.pdf"]["sha256"] == hashlib.sha256(b"report B, corrected file").hexdigest()

    (pdfs / "C-Annual-Report-2025-26.pdf").rename(tmp_path / "moved.pdf")
    assert any(m.startswith("MISSING") and "C-Annual" in m for m in update_sources(pdfs, out))
    assert "C-Annual-Report-2025-26.pdf" in read(out)                                  # the row is kept, only reported
