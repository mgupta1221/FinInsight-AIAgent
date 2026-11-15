"""Ask the agent a question from the command line (uses the real model set in .env).

NEW FILE (agent layer, 13 Nov 2026). WHY: the quickest way to try the agent and to debug it without the
Streamlit app. `--trace` prints every step (plan, tool calls, critic verdicts), which shows where a
question went wrong.

    python scripts/ask.py "What was Infosys' consolidated revenue from operations in FY2025-26?"
    python scripts/ask.py "And for FY2024-25?" --session demo        (follow-up in the same session)
    python scripts/ask.py "..." --trace
    python scripts/ask.py --reset --session demo                     (forget the session)
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]      # works with or without `pip install -e .`

from finsight.agent.graph import run            # noqa: E402
from finsight.agent.memory import Memory        # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("question", nargs="?")
ap.add_argument("--session", default="cli")
ap.add_argument("--trace", action="store_true")
ap.add_argument("--reset", action="store_true")
a = ap.parse_args()
if a.reset:
    Memory().clear(a.session)
    print(f"session '{a.session}' cleared")
if a.question:
    ans = run(a.question, session_id=a.session)
    print(f"\n[{ans.status}] {ans.answer}")
    if ans.formula:
        print(f"formula : {ans.formula}")
    for f in ans.inputs:
        print(f"input   : {f.name:<26}{f.company:<11}FY{f.fiscal_year:<9}{f.value:>18,.2f} {f.unit:<10}{f.citation}")
    for k in ans.key_points:
        print(f"  - {k.point}  [{k.citation}]")
    if ans.caveats:
        print("caveats :", "; ".join(ans.caveats))
    print(f"verified: {ans.verified}   tokens: {ans.tokens_used}")
    if a.trace:
        print("\ntrace:")
        for t in ans.trace:
            print("  ", json.dumps(t, ensure_ascii=False, default=str)[:300])
