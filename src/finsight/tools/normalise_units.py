"""Unit normalisation for Indian financial figures.

Reports mix ₹ crore, lakh, million, billion (and occasionally thousand / absolute rupees). Before
any arithmetic or comparison, figures must be in the same unit. This tool converts between units
and flags mismatches so the calculator never adds a crore to a million.
"""

from __future__ import annotations

from finsight.tools.base import ToolError, register

# Multipliers to a common base of absolute rupees.
_FACTORS: dict[str, float] = {
    "unit": 1.0,
    "units": 1.0,
    "absolute": 1.0,
    "rupees": 1.0,
    "rs": 1.0,
    "inr": 1.0,
    "thousand": 1e3,
    "lakh": 1e5,
    "lakhs": 1e5,
    "million": 1e6,
    "mn": 1e6,
    "crore": 1e7,
    "crores": 1e7,
    "cr": 1e7,
    "billion": 1e9,
    "bn": 1e9,
}


def _factor(unit: str) -> float:
    key = unit.strip().lower()
    if key not in _FACTORS:
        raise ToolError(f"unknown unit '{unit}'. Known: {sorted(set(_FACTORS))}")
    return _FACTORS[key]


@register("normalise_units")
def normalise(value: float, from_unit: str, to_unit: str = "crore") -> dict:
    """Convert `value` from `from_unit` to `to_unit`.

    Returns {value, unit, from_unit, factor}. Raises ToolError on an unknown unit.
    """
    converted = value * _factor(from_unit) / _factor(to_unit)
    return {
        "value": converted,
        "unit": to_unit.strip().lower(),
        "from_unit": from_unit.strip().lower(),
        "factor": _factor(from_unit) / _factor(to_unit),
    }


def to_common(values: list[tuple[float, str]], to_unit: str = "crore") -> list[float]:
    """Convert a list of (value, unit) pairs to a single common unit. Flags nothing silently —
    an unknown unit raises ToolError so a mismatch can never slip through."""
    return [normalise(v, u, to_unit)["value"] for v, u in values]
