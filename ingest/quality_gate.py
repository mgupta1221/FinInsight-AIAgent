"""Data-quality gate — the first thing ingestion runs.

Rejects any PDF that is not a full annual report, i.e. missing the financial statements. A report
must show evidence of a balance sheet, a profit & loss statement, notes to accounts, and an
auditor's report. This stops an incomplete download from silently corrupting the figure store.
"""

from __future__ import annotations

from pathlib import Path

# (label, patterns) — a report passes only if every label is found somewhere in its text.
# Patterns are matched case-insensitively as substrings, and kept broad to tolerate the wording
# variations across companies (e.g. "Notes to Standalone Financial Statements").
_REQUIRED = {
    "balance_sheet": ["balance sheet"],
    "profit_and_loss": [
        "statement of profit and loss",
        "statement of profit & loss",
        "profit and loss account",
        "profit & loss account",
    ],
    "notes": [
        "notes to the financial statements",
        "notes to financial statements",
        "notes to standalone financial statements",
        "notes to consolidated financial statements",
        "notes to the standalone financial statements",
        "notes to the consolidated financial statements",
        "notes to the accounts",
        "notes forming part",
        "notes accompanying",
        "significant accounting policies",
    ],
    "auditor": [
        "independent auditor",
        "auditor's report",
        "auditors' report",
        "independent auditors",
    ],
}


def check_report(pages: list[dict]) -> tuple[bool, list[str]]:
    """Return (ok, missing_labels). `pages` is the output of ingest.parse.parse_pdf."""
    blob = "\n".join(p["text"] for p in pages).lower()
    missing = [label for label, pats in _REQUIRED.items() if not any(p in blob for p in pats)]
    return (len(missing) == 0, missing)


def check_file(path: str | Path) -> tuple[bool, list[str]]:
    from ingest.parse import parse_pdf

    return check_report(parse_pdf(path))
