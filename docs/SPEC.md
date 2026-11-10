# SPEC — FinSight (Track B, item I)

> Status: **APPROVED** (2026-11-10). Frozen for the build. Changes require re-approval and a note here.

FinSight answers questions about a fixed corpus of Indian listed-company annual reports. Every
factual answer carries a page-level citation; every computed answer shows its formula and inputs.
This document is the authoritative rulebook — the agents, tools, and evaluation all follow it.

---

## 1. Scope

**In scope:** the 15 companies in `config/companies.yaml` (IT services, FMCG, Banks), for fiscal
years **FY2024-25** and **FY2025-26**, using the ingested report sections in `config/sections.yaml`
(financial statements, notes, MD&A, risk management, key ratios/highlights, and — for banks — Basel
III/Pillar 3).

**Question types handled:** `fact`, `ratio`, `yoy`, `compare`, `rank`, `summary`, plus `clarify`,
`refuse`, and out-of-corpus (`unanswerable`) handling.

**Out of scope (refuse):** see §3.

---

## 2. What "correct" means (acceptance criteria)

- **Numeric answers** are within **±0.5% relative** of the gold value (or exact after rounding to the
  reported precision), with the **correct unit and fiscal year**.
- **The cited page actually contains** every input figure used.
- **Computed answers** use the glossary formula (§5) and **show the formula + inputs**.
- **Qualitative (summary) answers** cover the gold key points and cite them (key-point recall ≥ 0.7).
- **Refusals and clarifications** fire exactly when the gold says so.

---

## 3. Refusal policy

Refuse (politely, with a pointer to what the corpus *can* answer):

- Buy / sell / hold recommendations, price targets.
- Forecasts or predictions of future results.
- Non-public or insider information.
- Companies or fiscal years **outside the corpus**.
- Tax or legal advice.

The assistant is **not** an investment adviser and must never phrase an answer as investment advice.

---

## 4. Conventions

- **Fiscal year:** 1 April – 31 March. Labels: `FY2024-25`, `FY2025-26` (the "FY25-26" report's
  current column = FY2025-26; its prior-year column = FY2024-25).
- **Statement scope:** default **consolidated**. If the question is ambiguous or asks for standalone,
  the planner fills the slot or asks back.
- **Units:** figures carry a unit at all times; convert via the `normalise_units` tool (crore / lakh /
  million / billion). Never mix units in a calculation.
- **Restated figures:** when a prior year is restated, use the value **as reported in the latest
  (FY2025-26) report**, and note the restatement.
- **Banks vs non-banks:** `is_bank` (from `config/companies.yaml`) selects the bank metric set and
  statement formats (Banking Regulation Act 3rd Schedule); debt-to-equity is **not** a meaningful bank
  metric and is handled as a `clarify`/explain case.

---

## 5. Metric glossary

The authoritative, machine-readable formulas live in **`config/glossary.yaml`** — the `calculate`
tool may use **only** these, and every computed answer states the formula used. Summary:

**Non-bank (IT, FMCG):**

| Metric | Formula | Unit |
|---|---|---|
| operating_margin | EBIT / revenue_from_operations × 100 | % |
| ebitda_margin | EBITDA / revenue_from_operations × 100 | % |
| net_profit_margin | net_profit / revenue_from_operations × 100 | % |
| yoy_change | (current − previous) / previous × 100 (+ absolute change) | % |
| debt_to_equity | total_debt / total_equity | ratio |
| current_ratio | current_assets / current_liabilities | ratio |
| return_on_equity | net_profit / total_equity × 100 | % |
| return_on_capital_employed | EBIT / capital_employed × 100 | % |
| earnings_per_share | net_profit_attributable / weighted_avg_shares | ₹/share |

**Bank:**

| Metric | Formula | Unit |
|---|---|---|
| gross_npa_ratio | gross_npa / gross_advances × 100 | % |
| net_npa_ratio | net_npa / net_advances × 100 | % |
| net_interest_margin | net_interest_income / avg_interest_earning_assets × 100 | % |
| casa_ratio | casa_deposits / total_deposits × 100 | % |
| cost_to_income | operating_expenses / net_total_income × 100 | % |
| return_on_assets | net_profit / avg_total_assets × 100 | % |
| crar | total_capital / risk_weighted_assets × 100 | % |

`operating_margin` is defined on an **EBIT basis, excluding other income** (the single operating-margin
definition for this project). Where a company reports a metric directly (e.g. basic EPS, CRAR), prefer
the reported figure and only compute if it is not reported.

---

## 6. Answer format

Every answer is a structured object (see `src/finsight/schemas.py`):

```
{
  "answer":   "<plain-language answer>",
  "formula":  "<glossary formula, if computed>",
  "inputs":   [{"name","value","unit","page","citation"}],
  "citations":["<citation>", ...],
  "caveats":  ["..."],
  "status":   "answered | clarify | refused | escalated"
}
```

Numbers in `answer` must come from `get_financial_item` or a cited table — never from the model.

---

## 7. Citation format

`TICKER-FYxxyy-pNNN` — e.g. `INFY-FY2526-p214` (Infosys, FY2025-26, page 214);
`INFY-FY2425-p210` (Infosys, FY2024-25, page 210).

---

## 8. Human-in-the-loop boundary

- Answers the critic cannot verify are shown as **"Unverified — please check page X"**, never as facts.
- Exported analyst notes (`create_note_draft`) are **DRAFTs** with an "AI-generated, verify before use,
  not investment advice" banner; the user must click **Approve** to export a final version.
- The UI always shows the source page so a human can check.

---

## 9. Error handling

Malformed model JSON → 2 retries (error fed back) then escalate; a tool error becomes an observation
fed back to the planner; a repeated identical tool call is blocked; the 10-step cap and the per-question
token budget (12,000) escalate; endpoint 429/503/timeouts retry with backoff (2s, 4s, 8s) then escalate.
