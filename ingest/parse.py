"""Parse a PDF into page-numbered text.

Week-1 baseline uses PyMuPDF (fast, light, reliable page numbers) so the pipeline runs on a CPU
laptop. Docling (+OCR) is the drop-in upgrade for graphic-heavy reports: set use_docling=True once
the heavier stack is installed. Either way the output shape is identical:

    [{"page": 1, "text": "..."}, {"page": 2, "text": "..."}, ...]

Page numbers are 1-based and match the PDF, so citations stay correct.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_pymupdf(path: str | Path) -> list[dict]:
    import pymupdf

    doc = pymupdf.open(str(path))
    pages = [{"page": i + 1, "text": doc[i].get_text("text") or ""} for i in range(doc.page_count)]
    doc.close()
    return pages


def parse_docling(path: str | Path) -> list[dict]:
    """Optional higher-quality parse (layout + tables + OCR). Requires `docling`."""
    from docling.document_converter import DocumentConverter

    conv = DocumentConverter()
    result = conv.convert(str(path))
    pages: dict[int, list[str]] = {}
    for item, _level in result.document.iterate_items():
        page_no = getattr(getattr(item, "prov", [None])[0], "page_no", None) if getattr(item, "prov", None) else None
        text = getattr(item, "text", "") or ""
        if page_no and text:
            pages.setdefault(page_no, []).append(text)
    return [{"page": p, "text": "\n".join(t)} for p, t in sorted(pages.items())]


def parse_pdf(path: str | Path, use_docling: bool = False) -> list[dict]:
    if use_docling:
        try:
            return parse_docling(path)
        except Exception as e:  # noqa: BLE001
            logger.warning("docling parse failed (%s); falling back to PyMuPDF", e)
    return parse_pymupdf(path)
