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
