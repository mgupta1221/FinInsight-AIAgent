"""Loads config/glossary.yaml and serves the metric formulas the calculator is allowed to use.

The glossary is the single source of truth for every formula. `calculate` asks this module for a
metric's formula + required inputs; it never invents a formula. Bank and non-bank metrics are kept
in separate sets so the same name can't be applied to the wrong company type.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from finsight.config import settings
from finsight.tools.base import ToolError


@lru_cache(maxsize=1)
def _load(path: str | None = None) -> dict:
    gpath = Path(path) if path else settings.config_dir / "glossary.yaml"
    if not gpath.exists():
        raise ToolError(f"glossary file not found: {gpath}")
    with open(gpath, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if "bank" not in data or "non_bank" not in data:
        raise ToolError("glossary.yaml must contain 'bank' and 'non_bank' sections")
    return data


def get_metric(metric: str, is_bank: bool) -> dict:
    """Return the metric definition {inputs, formula, unit, note} for the right company type.

    Looks in the primary set (bank vs non-bank) first, then the other set, so shared metrics
    (e.g. return_on_assets, yoy_change) resolve regardless. Raises ToolError if unknown.
    """
    data = _load()
    primary, secondary = ("bank", "non_bank") if is_bank else ("non_bank", "bank")
    for section in (primary, secondary):
        if metric in data[section]:
            spec = dict(data[section][metric])
            spec["metric"] = metric
            spec["section"] = section
            return spec
    raise ToolError(
        f"unknown metric '{metric}'. Known: {sorted(set(data['bank']) | set(data['non_bank']))}"
    )


def list_metrics(is_bank: bool | None = None) -> list[str]:
    data = _load()
    if is_bank is True:
        return sorted(data["bank"])
    if is_bank is False:
        return sorted(data["non_bank"])
    return sorted(set(data["bank"]) | set(data["non_bank"]))


# =====================================================================================================
# ADDED (agent layer, 13 Nov 2026). The functions above are unchanged.
# WHY: config/glossary.yaml gained three sections (line_items, derived_inputs, reported). The agent needs
# them to (a) know which statement lines exist, (b) turn an abstract formula input such as `ebit` into
# statement lines, and (c) know which ratios must be looked up as reported instead of calculated.
# =====================================================================================================
def line_items() -> dict:
    """canonical item -> {statement, labels, applies?, occurrence?} from the `line_items` section."""
    return dict(_load().get("line_items", {}))


def derived_inputs() -> dict:
    """abstract input (ebit, total_debt, ...) -> {inputs, formula} from the `derived_inputs` section."""
    return dict(_load().get("derived_inputs", {}))


def reported_metrics() -> dict:
    """metric -> {unit, search, keywords, hint} for ratios the company states itself."""
    return dict(_load().get("reported", {}))


def not_for_banks() -> set[str]:
    """Metrics defined only in the non_bank set: asking for one about a bank triggers a clarification."""
    data = _load()
    return set(data["non_bank"]) - set(data["bank"]) - {"yoy_change", "return_on_equity", "earnings_per_share"}
