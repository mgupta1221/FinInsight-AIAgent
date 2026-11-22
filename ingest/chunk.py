"""Cut page text into search-sized chunks, each stamped with a metadata header.

Default strategy = word-window chunks (~300 words with overlap) within a page, so every chunk maps to
exactly one page (citations stay exact). Each chunk text is PREFIXED with a metadata header
(company, FY, statement, scope, section, page) — this measurably improves retrieval on
near-identical reports. The chunking study in Week 2 compares this against page/section/table variants.
"""

from __future__ import annotations

WINDOW = 300
OVERLAP = 50


def _windows(words: list[str], size: int, overlap: int):
    step = max(1, size - overlap)
    for start in range(0, len(words), step):
        piece = words[start : start + size]
        if piece:
            yield " ".join(piece)
        if start + size >= len(words):
            break


def chunk_pages(pages: list[dict], meta: dict, keep_sections: set[str] | None = None) -> list[dict]:
    """pages: [{page, text, section}]; meta: {company, ticker, fiscal_year, scope, pdf}.

    Returns chunk dicts ready for indexing: {id, text, header + metadata fields}.
    """
    chunks: list[dict] = []
    for pg in pages:
        section = pg.get("section", "front_matter")
        if keep_sections is not None and section not in keep_sections:
            continue
        words = pg["text"].split()
        if not words:
            continue
        # CHANGED (18 Nov 2026): the scope now comes from the PAGE when the page has one.
        # OLD: every chunk took meta['scope'], which run_ingest sets to "consolidated" for the whole report, so
        #      standalone statements and all narrative pages were stamped "consolidated" too.
        scope = pg["scope"] if "scope" in pg else meta.get("scope", "")
        header = (
            f"[{meta['company']} | FY{meta['fiscal_year']} | {scope} | "
            f"{section} | p{pg['page']}]"
        )
        for i, body in enumerate(_windows(words, WINDOW, OVERLAP)):
            cid = f"{meta['ticker']}-{meta['fiscal_year']}-p{pg['page']}-{i}"       # OLD: ...-{meta.get('scope','')}-p... (scope removed: page + index is already unique)
            chunks.append(
                {
                    "id": cid,
                    "text": f"{header}\n{body}",
                    "company": meta["company"],
                    "ticker": meta["ticker"],
                    "fiscal_year": meta["fiscal_year"],
                    "scope": scope,                             # OLD: meta.get("scope", "")
                    "statement": section,
                    "section": section,
                    "page": pg["page"],
                    "pdf": meta.get("pdf", ""),
                }
            )
    return chunks
