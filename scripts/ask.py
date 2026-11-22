"""Ask the agent a question from the command line (uses the real model set in .env).

NEW FILE (agent layer, 13 Nov 2026). WHY: the quickest way to try the agent and to debug it without the
Streamlit app. `--trace` prints every step (plan, tool calls, critic verdicts), which shows where a
question went wrong.

    python scripts/ask.py "What was Infosys' consolidated revenue from operations in FY2025-26?"
    python scripts/ask.py "And for FY2024-25?" --session demo        (follow-up in the same session)
    python scripts/ask.py "..." --trace
    python scripts/ask.py --reset --session demo                     (forget the session)
    python scripts/ask.py "..." --verbose                            (show model-loading bars and library notices)
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]      # works with or without `pip install -e .`

# NEW (18 Nov 2026): keep the output to the answer. Use --verbose to see everything again.
# WHY: with the real embedding and reranker models installed, every run printed two "Loading weights" progress
#      bars and a Hugging Face notice before the answer. They are harmless but bury the answer. The settings
#      below must be made BEFORE the libraries are imported, which is why this block sits above the imports.
if "--verbose" not in sys.argv:
    import logging
    import os
    import warnings
    os.environ.setdefault("TQDM_DISABLE", "1")                      # all progress bars (model loading, batches)
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=UserWarning, module=r"(huggingface_hub|qdrant_client|transformers|sentence_transformers).*")
    for noisy in ("huggingface_hub", "sentence_transformers", "transformers", "httpx", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    # ADDED later on 18 Nov 2026: once both models are saved on this computer, do not contact Hugging Face at all.
    # WHY: the notice "You are sending unauthenticated requests to the HF Hub" still appeared; it is printed when
    #      the library checks online whether the model has changed. With the models already downloaded, that check
    #      is not needed, and skipping it also makes each start quicker. A model that is not downloaded yet is
    #      still fetched normally.
    try:
        from finsight.config import settings as _settings
        _hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
        if all((_hub / ("models--" + name.replace("/", "--"))).exists() for name in (_settings.embedding_model, _settings.reranker_model)):
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
    except Exception:  # noqa: BLE001  never let this convenience stop a question
        pass

from finsight.agent.graph import run            # noqa: E402
from finsight.agent.memory import Memory        # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("question", nargs="?")
ap.add_argument("--session", default="cli")
ap.add_argument("--trace", action="store_true")
ap.add_argument("--reset", action="store_true")
ap.add_argument("--verbose", action="store_true", help="show model-loading bars and library notices")   # 18 Nov 2026
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
