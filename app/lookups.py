"""Quick lookup: the lists behind the sidebar pickers, and the question they build.

NEW FILE (19 Nov 2026).
WHY: a user who does not know what to ask, or how a figure is named, can now pick a sector, one or more
     companies, a figure or ratio and a year, and press one button. The lists depend on the sector: banks get
     bank figures (deposits, advances, CASA ratio, gross NPA ...), the other companies get revenue, net profit,
     operating margin and so on. A figure that does not exist for the chosen kind of company cannot be picked.

     The pickers do NOT read the figure store themselves. They only write a normal question in plain English
     ("Which of HDFC Bank and ICICI Bank had the highest CASA ratio in FY2025-26?") and hand it to the same
     agent as a typed question. So a lookup goes through the same guard, the same formulas, the same checks
     and shows the same page citations. There is one way to get an answer, not two.

No Streamlit import here, so the lists can be unit-tested without a browser (tests/test_app.py).
"""

from __future__ import annotations

SECTOR_NAMES = {"it_services": "IT services", "fmcg": "FMCG", "banking": "Banks", "banks": "Banks", "bank": "Banks"}

# (what the user sees, the id in config/glossary.yaml). The wording on the left is also what is written into the
# question, so each one must be a phrase the planner recognises; the unit test checks every entry.
NON_BANK_RATIOS = [("Operating margin", "operating_margin"), ("EBITDA margin", "ebitda_margin"),
                   ("Net profit margin", "net_profit_margin"), ("Return on equity", "return_on_equity"),
                   ("Return on capital employed", "return_on_capital_employed"),
                   ("Debt-to-equity ratio", "debt_to_equity"), ("Current ratio", "current_ratio"),
                   ("Earnings per share", "earnings_per_share"),
                   ("Effective tax rate", "effective_tax_rate")]           # added 19 Nov 2026
NON_BANK_FIGURES = [("Revenue from operations", "revenue_from_operations"), ("Net profit", "net_profit"),
                    ("Profit before tax", "profit_before_tax"), ("Total income", "total_income"),
                    ("Total expenses", "total_expenses"), ("Employee benefits expense", "employee_benefits_expense"),
                    ("Finance costs", "finance_costs"), ("Total assets", "total_assets"),
                    ("Total equity", "total_equity"), ("Cash and cash equivalents", "cash_and_cash_equivalents")]
BANK_RATIOS = [("CASA ratio", "casa_ratio"), ("Gross NPA ratio", "gross_npa_ratio"), ("Net NPA ratio", "net_npa_ratio"),
               ("Net interest margin", "net_interest_margin"), ("Capital adequacy ratio", "crar"),
               ("Cost-to-income ratio", "cost_to_income"), ("Return on assets", "return_on_assets"),
               ("Earnings per share", "earnings_per_share"),
               ("Provision coverage ratio", "provision_coverage_ratio")]   # added 19 Nov 2026
BANK_FIGURES = [("Deposits", "deposits"), ("Advances", "advances"), ("Interest earned", "interest_earned"),
                ("Interest expended", "interest_expended"), ("Net interest income", "net_interest_income"),
                ("Operating expenses", "operating_expenses"), ("Total income", "total_income"),
                ("Net profit", "net_profit"), ("Total assets", "total_assets")]


# NEW (19 Nov 2026, later): ratios a bank states for the bank itself only.
# WHY: "ICICI Bank's consolidated CASA ratio" ended in "could not find casa ratio". That is true: the report gives
#      CASA, NPA, NIM, capital adequacy and return on assets for the bank alone (standalone), not for the group
#      with its insurance and broking subsidiaries. So for these the Scope picker is not shown and the question
#      is written without a scope; the agent then looks in the standalone pages, as it does for a typed question.
BANK_STANDALONE_ONLY = {"provision_coverage_ratio", "casa_ratio", "gross_npa_ratio", "net_npa_ratio", "net_interest_margin", "crar", "return_on_assets"}


def scope_is_fixed(ident: str, is_bank: bool) -> bool:
    return is_bank and ident in BANK_STANDALONE_ONLY


def sectors(profiles: list[dict]) -> list[str]:
    """Sector names for the first picker, in the order of config/companies.yaml."""
    out: list[str] = []
    for p in profiles:
        name = SECTOR_NAMES.get(p.get("sector", ""), "Banks" if p.get("is_bank") else str(p.get("sector", "Other")))
        if name not in out:
            out.append(name)
    return out


def companies_in(profiles: list[dict], sector: str) -> list[dict]:
    return [p for p in profiles
            if SECTOR_NAMES.get(p.get("sector", ""), "Banks" if p.get("is_bank") else str(p.get("sector", "Other"))) == sector]


def figure_options(is_bank: bool) -> list[tuple[str, str, str]]:
    """(label, id, kind) for the figure picker; kind is "ratio" or "figure"."""
    ratios, figures = (BANK_RATIOS, BANK_FIGURES) if is_bank else (NON_BANK_RATIOS, NON_BANK_FIGURES)
    return [(label, i, "ratio") for label, i in ratios] + [(label, i, "figure") for label, i in figures]


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def build_question(names: list[str], label: str, years: list[str], scope: str = "", order: str = "highest") -> str:
    """The plain-English question for the picked values.

    one company, one year   -> "What was Wipro's consolidated operating margin in FY2025-26?"
    several companies       -> "Which of HDFC Bank and ICICI Bank had the highest CASA ratio in FY2025-26?"
    one company, two years  -> "How did Wipro's consolidated net profit change from FY2024-25 to FY2025-26?"
    """
    what = f"{scope.lower()} {label.lower()}".strip() if scope else label.lower()
    what = what.replace("casa", "CASA").replace("npa", "NPA").replace("ebitda", "EBITDA")
    if len(years) >= 2:
        return f"How did {names[0]}'s {what} change from FY{years[0]} to FY{years[-1]}?"
    if len(names) > 1:
        return f"Which of {_join(names)} had the {order} {what} in FY{years[0]}?"
    return f"What was {names[0]}'s {what} in FY{years[0]}?"
