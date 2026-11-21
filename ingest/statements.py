"""Extract the primary financial statements of one report into figure-store rows.

NEW FILE (agent layer, 13 Nov 2026). It replaces the row extraction in ingest/tables.py, which is kept
unchanged for reference.

WHY it was needed
-----------------
Run on the real reports, ingest/tables.py stored no headline figure at all (revenue, profit, total assets
were "not found"); its rows were date fragments such as `march = 31`. Four causes:
  1. It expects "label  number  number" on ONE text line, but PyMuPDF returns each table cell on its own line.
  2. Where a row did match, the first number is the Note-column number, not the amount.
  3. Every row was labelled scope="consolidated", although each report has standalone statements too.
  4. Every row was labelled unit="crore", although some reports use Rs million or Rs thousand.

WHAT this file does instead
---------------------------
  1. A statement page is recognised by the TITLE at the top of the page ("Consolidated Balance Sheet"),
     and only if the page also contains the statement's characteristic rows.
  2. The scope is read from that title, per page.
  3. Rows are rebuilt from word POSITIONS, so a label and its numbers are joined.
  4. Amount columns are found by their right-aligned x position: the Note column is ignored and BOTH the
     current-year and the prior-year figure are kept.
  5. The unit is read from the page. A page with no unit printed inherits the report's most common unit,
     marked with "?" so a person confirms it; "unknown" if none is printed anywhere.
  6. Broken character maps are repaired first (finsight/textfix.py; needed for the TCS FY2024-25 report).

Output rows (the columns of store/statement_lines.parquet):
    company, ticker, fiscal_year, statement_type, scope, line_item, value, unit, page   <- as before
    report_fy, column                                                                  <- NEW
`fiscal_year` is the year the VALUE belongs to; `report_fy` is the report it was read from; `column` is
"current" or "prior". A FY2025-26 report therefore yields rows for 2025-26 (current) and 2024-25 (prior).
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pymupdf

from finsight.textfix import fix

PREV = {"2025-26": "2024-25", "2024-25": "2023-24"}

# CHANGED (15 Nov 2026): plural forms added. The old patterns are kept at the bottom of this file.
# WHY: Wipro prints "Statements of Profit and Loss" and "Statements of Cash Flows" (plural), so its
#      P&L and cash-flow pages were not recognised at all.
TITLES = [
    ("balance_sheet", re.compile(r"\bbalance sheets?\b")),
    ("pnl", re.compile(r"statements? of profit (and|&) loss|profit (and|&) loss account")),
    ("cash_flow", re.compile(r"cash flows? statements?|statements? of cash flows?")),
]
# NEW (15 Nov 2026): the same titles with the spaces removed.
# WHY: HDFC Bank FY2024-25 prints its titles letter-spaced ("S TA N D A L O N E  B A L A N C E  S H E E T").
#      No normal pattern matches that, so every primary statement of that report was missed.
#      The whole line must be the title ("^...$"): a letter-spaced heading such as "B A L A N C E  S H E E T
#      P A R A M E T E R S" in a performance review must not count.
TITLES_NOSPACE = [
    ("balance_sheet", re.compile(r"^(standalone|standlone|consolidated)?balancesheets?$")),
    ("pnl", re.compile(r"^(standalone|standlone|consolidated)?(statements?ofprofit(and|&)loss|profit(and|&)lossaccount)$")),
    ("cash_flow", re.compile(r"^(standalone|standlone|consolidated)?(cashflows?statements?|statements?ofcashflows?)$")),
]
# NEW (15 Nov 2026): a large-print heading counts as a title only if it is the statement name and nothing else.
# WHY: Wipro FY2025-26 prints the title sideways in the page margin, so it is not among the top lines.
#      Headings are searched too, but strictly, so a heading such as "Balance sheet strength" in the
#      management discussion is not mistaken for the statement.
BIG_TITLE = re.compile(r"^(standalone |consolidated )?(balance sheets?|statements? of profit (and|&) loss|"
                       r"profit (and|&) loss account|cash flows? statements?|statements? of cash flows?)\W*\d?$")
# NEW (15 Nov 2026): a page that follows a statement page is NOT its continuation if it shows any of these.
CONTINUATION_BLOCK = re.compile(r"changes in equity|schedule|notes (to|forming)|significant accounting|auditor|"
                                r"segment|directors|annexure")
# CHANGED (15 Nov 2026): "summary" added. OLD: r"abridged|summari[sz]ed|highlights|...
# WHY: HCL's board report says "A summary of the cash flows statement is given below"; with the plural
#      title patterns that line would be taken for the cash-flow statement itself.
NOT_A_STATEMENT = re.compile(r"abridged|summary|summari[sz]ed|highlights|ten year|10 year|at a glance|key ratios|"
                             r"notes (to|forming)|auditor|schedules? forming|significant accounting")
NOT_A_STATEMENT_PAGE = re.compile(r"directors.? report|board.?s report|management discussion|financial highlights|"
                                  r"financial performance|performance highlights|notes (to|forming part of) the")
ANCHORS = {
    "balance_sheet": [r"\btotal\b", r"assets|equity|liabilities|capital"],
    "pnl": [r"revenue from operations|interest earned|total income|sale of (products|goods)|income from operations",
            r"profit before|net profit|profit for the|profit after"],
    "cash_flow": [r"operating activities"],
}
NUM = re.compile(r"^\(?-?[\d,]+(\.\d+)?\)?$")
NIL = {"-", "–", "—", "nil"}
# CHANGED (15 Nov 2026): the rupee sign may be ANY one or two characters. Old patterns kept at the bottom.
# WHY: many reports lose the rupee sign when the PDF text is read: "(J in million)" (Nestle),
#      "(All amounts in H crores" (HUL), "(C in millions" (Wipro), "(C in '000)" (HDFC). ICICI and HDFC also
#      use a curly quote in "` in ‘000s", which the old pattern (straight quote only) did not accept.
#      Result before the fix: units "unknown" for ICICI, Nestle, HUL FY2025-26 and Wipro, and a WRONG guess
#      ("crore?") for HDFC FY2025-26 standalone, which is really in thousands.
_CUR = r"(?:₹|`|rs\.?|inr|\b[a-z]{1,2}\b)"
_Q = r"[‘’'`]?"
def _unit_rx(words: str) -> re.Pattern:
    return re.compile(rf"{_CUR}\s*\.?\s*in\s+(?:{words})\b|\bin\s+{_CUR}\s*(?:{words})\b|(?:₹|`|rs\.?|inr)\s*(?:{words})\b")
UNIT_PATTERNS = [
    ("crore", re.compile(_unit_rx(r"crores?").pattern + r"|crores? of (₹|rupees)|\(\s*\S{0,2}\s*(in\s+)?crores?\s*\)")),
    ("lakh", _unit_rx(r"lakhs?|lacs?")),
    ("million", _unit_rx(r"millions?|mn")),
    ("thousand", re.compile(_unit_rx(rf"{_Q}000s?|thousands?").pattern.replace(r"s?\b|", "s?|") + r"|000s? omitted|in thousands")),
]


def words_of(page) -> list[tuple]:
    """The page's words as (x0, y0, x1, y1, text), with broken character maps repaired."""
    return [(w[0], w[1], w[2], w[3], fix(w[4])) for w in page.get_text("words")]


def lines_of(page) -> list[list[tuple]]:
    """Group the page's words into visual lines (same height on the page), left to right."""
    return lines_from_words(words_of(page))


# CHANGED (15 Nov 2026): the body of lines_of() moved here unchanged, so it can also run on HALF a page
# (see "two report pages side by side" in extract_statement_rows). The old lines_of is kept at the bottom.
def lines_from_words(words: list[tuple]) -> list[list[tuple]]:
    words = sorted(words, key=lambda w: (round((w[1] + w[3]) / 2), w[0]))
    lines: list[list[tuple]] = []
    for w in words:
        mid = (w[1] + w[3]) / 2
        if lines and abs(mid - lines[-1][0][5]) <= 3.0:
            lines[-1].append((w[0], w[1], w[2], w[3], w[4], lines[-1][0][5]))
        else:
            lines.append([(w[0], w[1], w[2], w[3], w[4], mid)])
    out = []
    for l in lines:
        l = sorted(l, key=lambda t: t[0])
        merged = [l[0]]
        for t in l[1:]:
            p = merged[-1]
            gap = t[0] - p[2]
            touching = gap < 1.2 and (p[4][-1].isdigit() or p[4][-1] in ",.(") and (t[4][0].isdigit() or t[4][0] in ",.)")
            split_number = gap < 4.5 and p[4][-1] == "," and p[4][0].isdigit() and t[4][0].isdigit()   # "2," "59," "286"
            if touching or split_number:
                merged[-1] = (p[0], min(p[1], t[1]), t[2], max(p[3], t[3]), p[4] + t[4], p[5])   # glue number pieces
            else:
                merged.append(t)
        out.append(merged)
    return out

def to_float(tok: str) -> float | None:
    t = tok.strip()
    if t.lower() in NIL:
        return 0.0
    if not NUM.match(t):
        return None
    neg = t.startswith("(") or t.startswith("-")
    try:
        v = float(t.strip("()-").replace(",", ""))
    except ValueError:
        return None
    return -v if neg else v


def is_amount(tok: str) -> bool:
    """Looks like a money amount (has a thousands comma, or 3+ digits), not a note number like 2.18."""
    t = tok.strip("()-")
    return bool(NUM.match(tok)) and ("," in t or len(t.split(".")[0]) >= 3)


def despace(text: str) -> str:
    """'s ta n d a l o n e b a l a n c e s h e e t' -> 'standalonebalancesheet'; '' if not letter-spaced."""
    toks = text.split()
    if len(toks) >= 6 and sum(len(t) <= 2 for t in toks) / len(toks) >= 0.6:
        return "".join(toks)
    return ""


def title_of(text: str) -> str | None:
    """The statement this (lower-case) line is the title of, or None.

    NEW (15 Nov 2026). Differences from the old inline check in classify():
      * a line naming TWO statements is a running header, not a title. Kotak prints "Consolidated Balance
        Sheet and Profit and Loss Account" above every page, so its P&L pages were stored as balance sheet.
      * letter-spaced titles are matched with the spaces removed (HDFC Bank FY2024-25).
    """
    if len(text) > 95 or NOT_A_STATEMENT.search(text):
        return None
    hits = [(s, m) for s, rx in TITLES if (m := rx.search(text))]
    if not hits:
        tight = despace(text)
        hits = [(s, m) for s, rx in TITLES_NOSPACE if tight and (m := rx.search(tight))]
    if len(hits) != 1 or hits[0][1].start() > 45:
        return None
    return hits[0][0]


def top_lines(lines, height: float) -> list[str]:
    return [" ".join(t[4] for t in l).lower() for l in lines if l[0][1] < height * 0.30][:14]


def scope_of(text: str, context: str | None) -> str:
    """Scope from the words near the title; if the page does not say, from the auditor's report before it.

    CHANGED (15 Nov 2026). OLD rule: "consolidated" if the word is in the top lines, else "standalone".
    WHY: Nestle FY2025-26 titles its consolidated balance sheet just "BALANCE SHEET", so it was stored as a
         second standalone balance sheet and the consolidated one was missing. The statements always follow
         their own Independent Auditor's Report, so that report tells which set of statements we are in.
    """
    return stated_scope(text) or context or "standalone"


def stated_scope(text: str) -> str | None:
    """'consolidated' / 'standalone' if the text says so (also letter-spaced, and HDFC's typo 'standlone')."""
    tight = text.replace(" ", "")
    if "consolidated" in text or "consolidated" in tight:
        return "consolidated"
    if "standalone" in text or "standalone" in tight or "standlone" in tight:
        return "standalone"
    return None


def classify(lines, height: float, context: str | None = None, headings: list[tuple[str, bool]] | None = None) -> tuple[str, str] | None:
    """Return (statement, scope) if the page's TITLE says it is a primary statement.

    CHANGED (15 Nov 2026): uses title_of() and scope_of() (see their notes), and can also look at large-print
    `headings` (Wipro FY2025-26 prints the title sideways in the margin). Old version kept at the bottom.
    """
    top = top_lines(lines, height)
    top_text = " | ".join(top)
    if NOT_A_STATEMENT_PAGE.search(top_text):
        return None
    if re.search(r"keyperformance|performancereview|ataglance", top_text.replace(" ", "")):
        return None                                     # NEW (15 Nov 2026): letter-spaced "K E Y  P E R F O R M A N C E ..."
    # NEW (17 Nov 2026): a SCHEDULE page is not the statement, even though its heading names the statement
    # ("Schedules to the Consolidated Balance Sheet", "Schedule 3 - Deposits").
    # WHY: schedule pages repeat the statement's row names with sub-totals ("Deposits ... (i) From banks"). When
    #      the statement page itself was not found, the lookup read a schedule row and returned a part of the
    #      figure as if it were the whole (see the note in extract_statement_rows). Better no figure than that one.
    # Only a line that BEGINS with "Schedule ..." counts: "refer Schedule 18" inside a cash-flow row, or the
    # column header "Schedule No.", must not exclude the statement itself.
    if any(re.match(r"\W*schedules? (to|forming|annexed|\d)", t) for t in top):
        return None
    # NEW (15 Nov 2026): a bare title ("Balance Sheet", no standalone/consolidated anywhere near it) is accepted
    # only AFTER an auditor's report has been seen. WHY: performance-review pages in the front of a report
    # (Axis Bank "Key performance indicators") carry a sub-heading "Balance Sheet" above a small table. They
    # come before the real statements, so the lookup would have cited them instead of the statement.
    if not stated_scope(top_text) and context is None and not any(stated_scope(h) for h, _ in headings or []):
        return None
    for statement, _ in TITLES:
        for text in top:
            if title_of(text) == statement:
                return statement, scope_of(top_text, context)
    for text, sideways in headings or []:
        if sideways and BIG_TITLE.match(text):          # only SIDEWAYS headings: a normal heading "Balance Sheet"
            return title_of(text), scope_of(text + " | " + top_text, context)   # also occurs in performance reviews
    return None


def headings_of(page, x_lo: float | None = None, x_hi: float | None = None) -> list[tuple[str, bool]]:
    """Large-print lines (12 pt or more) as (lower-case text, printed sideways?); optionally one half only."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans or max(s["size"] for s in spans) < 12:
                continue
            mid = (line["bbox"][0] + line["bbox"][2]) / 2
            if x_lo is not None and not (x_lo <= mid < x_hi):
                continue
            sideways = abs(line["dir"][0]) < 0.5
            out.append((re.sub(r"\s+", " ", fix(" ".join(s["text"] for s in spans))).strip().lower(), sideways))
    return out

def amount_columns(lines) -> list[float]:
    """x position (right edge) of the amount columns, found by clustering right-aligned numbers."""
    edges = sorted(t[2] for l in lines for t in l if is_amount(t[4]))
    clusters: list[list[float]] = []
    for x in edges:
        if clusters and x - clusters[-1][-1] <= 9:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    cols = [sum(c) / len(c) for c in clusters if len(c) >= 5]
    return cols[-2:]                                   # the two right-most = current year, prior year


def column_groups(lines) -> list[list[float]]:
    """Amount columns grouped by year: [[current-year columns], [prior-year columns]] (or one group, or []).

    NEW (15 Nov 2026). OLD rule (amount_columns above, still used as the fallback): the two right-most columns
    are current year and prior year.
    WHY: ITC's balance sheet prints THREE columns per year (item amount, sub-total, total). The two
         right-most columns are then both PRIOR-year columns, so prior-year figures were stored as current
         year and "Total assets", "Borrowings", "Cash and cash equivalents" were not stored at all.
    HOW: with 4 or 6 columns where most rows fill only one or two of them, the left half is the current
         year and the right half the prior year. A table that fills all four columns on most rows (for
         example standalone and consolidated side by side) keeps the old rule.
    """
    edges = sorted(t[2] for l in lines for t in l if is_amount(t[4]))
    clusters: list[list[float]] = []
    for x in edges:
        if clusters and x - clusters[-1][-1] <= 9:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    cols = [sum(c) / len(c) for c in clusters if len(c) >= 5]
    if len(cols) in (4, 6):
        filled = [sum(1 for cx in cols if any(abs(t[2] - cx) <= 9 and to_float(t[4]) is not None for t in l)) for l in lines]
        filled = [n for n in filled if n]
        if filled and sum(1 for n in filled if n <= 2) / len(filled) >= 0.6:
            half = len(cols) // 2
            return [cols[:half], cols[half:]]
    return [[c] for c in cols[-2:]]


def page_unit(text: str) -> str | None:
    low = text.lower()
    found = [(rx.search(low).start(), u) for u, rx in UNIT_PATTERNS if rx.search(low)]
    return min(found)[1] if found else None


def extract_statement_rows(pdf: str | Path, meta: dict) -> tuple[list[dict], list[dict]]:
    """meta: {company, ticker, fiscal_year} with fiscal_year like "2025-26" (the report's year).

    Returns (rows, pages_found). pages_found lists every statement page with its scope and unit, for logging.

    CHANGED (15 Nov 2026) - the old version is kept at the bottom of this file. Five additions, each for a
    gap found in the real reports:
      1. Two report pages side by side on one PDF page (Britannia): each half is read separately. Before,
         the balance sheet (left half) was lost and its labels leaked into the P&L rows (right half).
      2. Titles: plural, letter-spaced, sideways in the margin, running headers (see title_of, classify).
      3. Scope from the preceding auditor's report when the title does not say (see scope_of).
      4. Continuation page: the page right after a statement page, with the same kind of table and no
         title of its own, belongs to that statement (Wipro FY2025-26 balance sheet, liabilities side).
      5. Unit: a page with no unit line takes the unit of the statement page just before it (same scope).
         Only if there is none does it fall back to the report's most common unit marked "?".
    """
    fy = meta["fiscal_year"]
    doc = pymupdf.open(str(pdf))
    rows, pages_found = [], []
    context = None                                      # "standalone"/"consolidated": last auditor's report seen
    for i in range(doc.page_count):
        page = doc[i]
        text = fix(page.get_text("text"))
        low = text.lower()
        if "independent auditor" in low:
            c, s = low.count("consolidated financial statements"), low.count("standalone financial statements")
            if c or s:
                context = "consolidated" if c > s else "standalone"
        after_statement = bool(pages_found) and pages_found[-1]["page"] == i      # previous PDF page was a statement
        # CHANGED (17 Nov 2026): the quick filter also looks at the text with spaces removed.
        # OLD: if not ("balance sheet" in low or "profit" in low or "cash flow" in low or after_statement):
        # WHY: HDFC Bank FY2024-25 prints "C O N S O L I D A T E D  B A L A N C E  S H E E T" letter-spaced and the
        #      page has no other occurrence of these words, so the page was skipped before its title was even
        #      read. The consolidated balance sheet (p441) was missing, and "deposits" was then read from a
        #      schedule page (p447): Rs 24,105 crore instead of about Rs 27 lakh crore. A wrong answer.
        tight = low.replace(" ", "")
        if not ("balance sheet" in low or "profit" in low or "cash flow" in low or after_statement
                or "balancesheet" in tight or "profitandloss" in tight or "cashflow" in tight):
            continue                                    # (a continuation page may contain none of these words)
        words = words_of(page)
        width, height = page.rect.width, page.rect.height

        def view(ws, x_lo=None, x_hi=None, page_text=None):
            lines = lines_from_words(ws) if ws else []
            vtext = page_text if page_text is not None else "\n".join(" ".join(t[4] for t in l) for l in lines)
            enough = bool(lines) and sum(1 for l in lines for t in l if is_amount(t[4])) >= 12
            cols = column_groups(lines) if enough else []     # OLD: amount_columns(lines)
            kind, heads = None, None
            if cols:
                # scope hint when the page itself does not say: the statement page just before it (SBI prints
                # "Profit and Loss Account" right after the standalone balance sheet), else the auditor's report
                last = pages_found[-1] if pages_found else None
                # OLD: hint = last["scope"] if last and i + 1 - last["page"] <= 3 else context
                # CHANGED (17 Nov 2026): if no auditor's report has been seen yet, fall back to the last statement
                # page however far back. WHY: SBI FY2024-25 prints balance sheet (p168), nine pages of schedules,
                # then "Profit and Loss Account" (p177) with no scope word, and its auditor's report comes later.
                hint = last["scope"] if last and i + 1 - last["page"] <= 3 else (context or (last["scope"] if last else None))
                kind = classify(lines, height, hint)
                if not kind:
                    heads = headings_of(page, x_lo, x_hi)
                    kind = classify(lines, height, hint, heads)
            return {"lines": lines, "text": vtext, "cols": cols, "kind": kind, "heads": heads, "x": (x_lo, x_hi)}

        views = []
        if width > 1.3 * height:                        # two report pages printed side by side
            half = width / 2
            halves = [view([w for w in words if (w[0] + w[2]) / 2 < half], 0, half),
                      view([w for w in words if (w[0] + w[2]) / 2 >= half], half, width)]
            if any(v["kind"] for v in halves):
                views = halves
        if not views:
            views = [view(words, page_text=text)]

        for v in views:
            lines, cols, kind = v["lines"], v["cols"], v["kind"]
            if not cols:
                continue                                # a title but no table: not a statement page
            vlow = v["text"].lower()
            prev = pages_found[-1] if pages_found else None
            continued = False
            if not kind and prev and not prev["continued"] and prev["page"] in (i, i + 1):
                top_text = " | ".join(top_lines(lines, height))
                heads = v["heads"] if v["heads"] is not None else headings_of(page, *v["x"])
                other_heading = any(re.search(r"[a-z]{4}", h) and title_of(h) != prev["statement"] for h, _ in heads)
                if not other_heading and not CONTINUATION_BLOCK.search(top_text) and not NOT_A_STATEMENT_PAGE.search(top_text):
                    kind, continued = (prev["statement"], prev["scope"]), True
            if not kind:
                continue
            statement, scope = kind
            if not continued and not all(re.search(a, vlow) for a in ANCHORS[statement]):
                continue                                # title matched but the characteristic rows are absent
            unit = page_unit(v["text"])
            if not unit and prev and prev["unit"] and prev["scope"] == scope and i + 1 - prev["page"] <= 2:
                unit = prev["unit"]                     # same set of statements, a page or two later
            pages_found.append({"page": i + 1, "statement": statement, "scope": scope, "unit": unit, "continued": continued})
            first_x = cols[0][0]
            for l in lines:
                label_parts, values = [], {}
                for t in l:
                    # CHANGED (15 Nov 2026): `cols` is now a list of year groups (see column_groups).
                    # OLD: ci = next((k for k, cx in enumerate(cols) if abs(t[2] - cx) <= 9), None)
                    ci = next((k for k, group in enumerate(cols) if any(abs(t[2] - cx) <= 9 for cx in group)), None)
                    val = to_float(t[4]) if ci is not None else None
                    if val is not None and t[0] > first_x - 90:
                        values.setdefault(ci, val)      # left-most amount of the year = the row's own figure;
                    elif not values and to_float(t[4]) is None:      # amounts further right are unlabelled sub-totals
                        label_parts.append(t[4])
                label = re.sub(r"\s+", " ", " ".join(label_parts)).strip(" .:-")
                if not values or len(label) < 3 or not re.search(r"[A-Za-z]{3}", label):
                    continue
                for ci, val in values.items():
                    current = ci == 0 or len(cols) == 1
                    rows.append({"company": meta["company"], "ticker": meta["ticker"],
                                 "fiscal_year": fy if current else PREV.get(fy, ""),
                                 "statement_type": statement, "scope": scope, "line_item": label, "value": val,
                                 "unit": unit or "", "page": i + 1, "report_fy": fy,
                                 "column": "current" if current else "prior"})
    doc.close()
    common = Counter(p["unit"] for p in pages_found if p["unit"]).most_common(1)
    for r in rows:
        if not r["unit"]:
            r["unit"] = (common[0][0] + "?") if common else "unknown"
    return rows, pages_found


# ============================ OLD VERSIONS (kept for reference, 13 Nov 2026) ============================
# Replaced on 15 Nov 2026. The reason for each change is written beside the new code above.
#
# TITLES = [
#     ("balance_sheet", re.compile(r"\bbalance sheet\b")),
#     ("pnl", re.compile(r"statement of profit (and|&) loss|profit (and|&) loss account")),
#     ("cash_flow", re.compile(r"cash flow statement|statement of cash flows?")),
# ]
#
# UNIT_PATTERNS = [
#     ("crore", re.compile(r"(₹|`|rs\.?|inr)\s*(in\s+)?crores?|in\s+(₹|`|rs\.?)\s*crores?|crores? of (₹|rupees)|"
#                          r"\(\s*\S{0,2}\s*(in\s+)?crores?\s*\)")),           # "(H crores)": rupee sign lost in the PDF
#     ("lakh", re.compile(r"(₹|`|rs\.?|inr)\s*(in\s+)?(lakhs?|lacs?)|in\s+(₹|`|rs\.?)\s*(lakhs?|lacs?)")),
#     ("million", re.compile(r"(₹|`|rs\.?|inr)\s*(in\s+)?(millions?|mn)|in\s+(₹|`|rs\.?)\s*millions?")),
#     ("thousand", re.compile(r"(₹|`|rs\.?)\s*(in\s+)?('?000s?|thousands?)|000s? omitted|in thousands")),
# ]
#
# def lines_of(page) -> list[list[tuple]]:
#     """Group the page's words into visual lines (same height on the page), left to right."""
#     words = [(w[0], w[1], w[2], w[3], fix(w[4])) for w in page.get_text("words")]
#     words = sorted(words, key=lambda w: (round((w[1] + w[3]) / 2), w[0]))
#     lines: list[list[tuple]] = []
#     for w in words:
#         mid = (w[1] + w[3]) / 2
#         if lines and abs(mid - lines[-1][0][5]) <= 3.0:
#             lines[-1].append((w[0], w[1], w[2], w[3], w[4], lines[-1][0][5]))
#         else:
#             lines.append([(w[0], w[1], w[2], w[3], w[4], mid)])
#     out = []
#     for l in lines:
#         l = sorted(l, key=lambda t: t[0])
#         merged = [l[0]]
#         for t in l[1:]:
#             p = merged[-1]
#             gap = t[0] - p[2]
#             touching = gap < 1.2 and (p[4][-1].isdigit() or p[4][-1] in ",.(") and (t[4][0].isdigit() or t[4][0] in ",.)")
#             split_number = gap < 4.5 and p[4][-1] == "," and p[4][0].isdigit() and t[4][0].isdigit()   # "2," "59," "286"
#             if touching or split_number:
#                 merged[-1] = (p[0], min(p[1], t[1]), t[2], max(p[3], t[3]), p[4] + t[4], p[5])   # glue number pieces
#             else:
#                 merged.append(t)
#         out.append(merged)
#     return out
#
# def classify(lines, height: float) -> tuple[str, str] | None:
#     """Return (statement, scope) if the page's TITLE says it is a primary statement."""
#     top = [" ".join(t[4] for t in l).lower() for l in lines if l[0][1] < height * 0.30][:14]
#     top_text = " | ".join(top)
#     if NOT_A_STATEMENT_PAGE.search(top_text):
#         return None
#     for statement, rx in TITLES:
#         for text in top:
#             m = rx.search(text)
#             if m and m.start() <= 45 and len(text) <= 95 and not NOT_A_STATEMENT.search(text):
#                 if statement == "balance_sheet" and ("statement of profit" in text or "cash flow" in text):
#                     continue
#                 scope = "consolidated" if "consolidated" in top_text else "standalone"
#                 return statement, scope
#     return None
#
# def extract_statement_rows(pdf: str | Path, meta: dict) -> tuple[list[dict], list[dict]]:
#     """meta: {company, ticker, fiscal_year} with fiscal_year like "2025-26" (the report's year).
#
#     Returns (rows, pages_found). pages_found lists every statement page with its scope and unit, for logging.
#     """
#     fy = meta["fiscal_year"]
#     doc = pymupdf.open(str(pdf))
#     rows, pages_found = [], []
#     for i in range(doc.page_count):
#         page = doc[i]
#         text = fix(page.get_text("text"))
#         low = text.lower()
#         if not ("balance sheet" in low or "profit" in low or "cash flow" in low):
#             continue
#         lines = lines_of(page)
#         kind = classify(lines, page.rect.height)
#         if not kind:
#             continue
#         cols = amount_columns(lines)
#         if not cols or sum(1 for l in lines for t in l if is_amount(t[4])) < 12:
#             continue                                    # a title but no table: not a statement page
#         statement, scope = kind
#         if not all(re.search(a, low) for a in ANCHORS[statement]):
#             continue                                    # title matched but the characteristic rows are absent
#         unit = page_unit(text)
#         pages_found.append({"page": i + 1, "statement": statement, "scope": scope, "unit": unit})
#         for l in lines:
#             label_parts, values = [], {}
#             for t in l:
#                 ci = next((k for k, cx in enumerate(cols) if abs(t[2] - cx) <= 9), None)
#                 v = to_float(t[4]) if ci is not None else None
#                 if v is not None and t[0] > cols[0] - 90:
#                     values[ci] = v
#                 elif not values and to_float(t[4]) is None:
#                     label_parts.append(t[4])
#             label = re.sub(r"\s+", " ", " ".join(label_parts)).strip(" .:-")
#             if not values or len(label) < 3 or not re.search(r"[A-Za-z]{3}", label):
#                 continue
#             for ci, v in values.items():
#                 current = ci == 0 or len(cols) == 1
#                 rows.append({"company": meta["company"], "ticker": meta["ticker"],
#                              "fiscal_year": fy if current else PREV.get(fy, ""),
#                              "statement_type": statement, "scope": scope, "line_item": label, "value": v,
#                              "unit": unit or "", "page": i + 1, "report_fy": fy,
#                              "column": "current" if current else "prior"})
#     doc.close()
#     common = Counter(p["unit"] for p in pages_found if p["unit"]).most_common(1)
#     for r in rows:
#         if not r["unit"]:
#             r["unit"] = (common[0][0] + "?") if common else "unknown"
#     return rows, pages_found
