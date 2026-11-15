# ORIGINAL PLACEHOLDER (kept):
# """Tool: compare_rank. See BUILD_PLAN.md (Tools table) for purpose. TODO: implement with Pydantic args + ToolError."""
#
# IMPLEMENTED (agent layer, 13 Nov 2026).
"""Tool: compare_rank. Orders companies (or years) by a value; reports ties and missing values.

The model is never asked "which is bigger": sorting is done here, in code.
"""
from __future__ import annotations

from finsight.tools.base import ToolError, register


@register("compare_rank")
def compare_rank(values: dict[str, float | None], order: str = "highest") -> dict:
    """values: {name: value or None}. order: "highest" or "lowest" first.

    Returns {ranking: [{name, value}], order, winner, tie, missing}. Raises ToolError with fewer than two values.
    """
    present = {k: v for k, v in values.items() if v is not None}
    missing = [k for k, v in values.items() if v is None]
    if len(present) < 2:
        raise ToolError(f"need at least two values to compare; missing {missing}")
    ranked = sorted(present.items(), key=lambda kv: kv[1], reverse=(order != "lowest"))
    tie = abs(ranked[0][1] - ranked[1][1]) < 1e-9
    return {"ranking": [{"name": k, "value": v} for k, v in ranked], "order": order,
            "winner": None if tie else ranked[0][0], "tie": tie, "missing": missing}
