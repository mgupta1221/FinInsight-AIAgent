# Small-Model Fixes (graded — keep from Day 1)

Running log: each small-model weakness we hit, the fix we applied, and the before/after metric.

<!-- OLD (empty table, kept):
| Date | Symptom | Fix | Before | After |
|------|---------|-----|--------|-------|
| | | | | |
-->

Filled on 22 Nov 2026 from `docs/CHANGES_AND_STATUS.md` and the practice runs in `results/runs/`. "Before" and
"After" give a measured number where one exists. Where a fix was not measured by itself, the column says what was
seen. The numbers are from practice runs; replace them with the official runs after the freeze.

**The model is used for three small jobs only:** filling the slots of a plan (company, year, measure), pointing at
a number on a page of text, and wording the answer. Everything else is code. The comparison below shows why.

| What | One search + one model answer (baseline) | Agent |
|---|---|---|
| All 90 questions | 37 (41.1%) | 84 (93.3%) |
| Year-on-year change (12) | 3 | 12 |
| Comparison of companies (14) | 5 | 14 |
| Ratios (16) | 9 | 15 |
| Questions that need a question back (6) | 0 | 6 |
| Cited page is the gold page | 22.4% | 91.9% |

Runs: `2026-11-21_163005_simple` and `2026-11-21_183017_agent`.

| Date | Symptom | Fix | Before | After |
|------|---------|-----|--------|-------|
| 13 Nov | The model does arithmetic wrongly or not at all (gives two figures and no percentage; divides by the wrong figure) | The model never calculates. Formulas are in `config/glossary.yaml`; the `calculate` tool does the arithmetic; the answer shows the formula and the inputs | Baseline: year-on-year 3 of 12, 12 answers labelled calculation error | Agent: year-on-year 12 of 12; 97% of computed answers show the formula |
| 13 Nov | The model invents or misreads a figure from a statement table found by text search | Figures of the statements are extracted once at ingestion into a figure store (`store/statement_lines.csv`) and read from there by name, company, year and scope | Baseline: 19 answers labelled hallucination; search finds the right statement page in the first 10 results for about a third of questions (`DECISIONS.md`) | Agent: fact 18 of 18 |
| 13 Nov | The model's wording changes a number, drops the unit or adds an opinion | A critic written in code checks every number in the answer against the figures used, the formula, the citations and the wording. Up to three attempts; the last attempt is a fixed sentence template built by code | Not measured separately | Every answered question passed the check; a failed check is shown as "Unverified, please check page ..." |
| 13 Nov | The model returns a plan that is not valid, or free text | Structured output (a small schema with slots) with retries; a failure ends as "I could not plan an answer", never as a guess | Measured 22 Nov on 83 planner questions in four ways (agent as built, enforced shape, valid JSON only, plain prompt): every reply was a readable form on the first try in all four | No planning failure in the practice runs. The faults are of content (2 of 83: a ratio returned as a figure), which the code check after the model corrects. `results/structured_output_summary.csv` |
| 13–17 Nov | The model picks a wrong slot: a measure the question did not name, or a company that is not in the question | Code decides after the model: a measure is accepted only if its words are in the question (`METRIC_WORDS`); companies come from a name list with aliases; years are read by a pattern | Seen in testing: operating margin returned for a question about something else | Clarify 6 of 6, refuse 6 of 6, not-in-corpus 2 of 2 |
| 17 Nov | The model answers a vague question instead of asking ("What was the profit?") | Code asks back when company, year, measure or scope cannot be settled; the reply completes the unfinished question | Baseline: clarify 0 of 6 | Agent: clarify 6 of 6 |
| 13–17 Nov | Advice, forecasts and instructions hidden in a question or a page ("ignore your rules") | A guard in code refuses before the model is called; report text is treated as data and cleaned of instructions | Baseline: refuse 4 of 6 | Agent: refuse 6 of 6, injection 2 of 2 |
| 19 Nov | Asked for a ratio printed in the report (CASA, net NPA), the model pointed at a neighbouring number, for example an amount where a percentage was wanted (7435.88%) | The number must be printed on the cited page; a percentage must be between 0 and 100; percentages are tried first; a rejected page is set aside and another tried, up to three times. NPA ratios are read by a text pattern, without the model | compare-004 answered 7435.88% | compare-004 correct; ratios 15 of 16 |
| 19 Nov | One private-use font in one report turned every digit into an odd character, which the model copied | The characters are mapped back to digits at parsing (`fix_glyphs`) | TCS FY2024-25 figures unreadable | Read correctly |
| 21 Nov | Summaries: asked for key points "in a few words" the model returned labels ("Cybersecurity risks") | The prompt asks for one full sentence of 15 to 35 words per point, naming one specific item; the critic rejects a point of fewer than 8 words and the reason is given to the model for the next attempt | Summaries 0 of 8 by word count | 1 of 8 |
| 21 Nov | Summaries: half the points came from single pages elsewhere in the report; a small model follows whatever passages it is given | Passages are chosen by section: pages close together are grouped, the group the search ranks best is taken, at most 9 passages; one instruction line per kind of topic (risks, segments, strategy) | Summaries 1 of 8 | 4 of 8 (HDFC Bank and Wipro one point short) |
| 21 Nov | Summaries: a strategy summary was rejected three times as "advice or a forecast", because it reported the company's own plans | For summaries the wording check rejects only text addressed to an investor (buy, sell, undervalued) | summary-004 "Unverified" | Answered |
| 13 Nov | The context of an 8B model is small; a long conversation or many passages would not fit | Memory keeps only the slots of the last verified answer, not the conversation text; one question is limited to 10 steps and 12,000 tokens; a summary reads at most 9 passages of 1,300 characters | Not measured separately | 100% of answers within the limits; average 1,991 tokens per question |
| 24 Nov | The model put a company outside the corpus into its slots for one wording and not for the next: "How the PWC perform FY25-26" was refused, "How did PWC perfom FY24-25" was not | Code recognises a company outside the corpus (possessive, company word, abbreviation in capitals, a short list of well-known names) before the model's slots are used; the guard names the company before a year that is not covered | Mentor's session: refused in 1 of 3 wordings | Refused in all of them (unit tests; to be confirmed in the app) |

What the small model still does not do well: a summary whose gold points are spread over a long section (HDFC Bank,
Wipro), a report that discusses the topic in two places (Nestlé), and a figure that needs two different pages of
text (multihop-006, where the agent declines).
