"""The calculator — the model never does arithmetic; this does.

`calculate(metric, inputs, is_bank)` looks up the formula from the glossary, checks every required
input is present, evaluates it with a *safe* expression evaluator (no builtins, no attribute access,
only +-*/ and parentheses over the named inputs), and returns the value **with the formula it used**
so the answer is auditable. A logged free-form `evaluate_expression` path exists for one-offs.
"""

from __future__ import annotations

import ast
import logging
import operator as op

from finsight.tools.base import ToolError, register
from finsight.tools.glossary import get_metric

logger = logging.getLogger(__name__)

# Only these AST node types / operators are allowed in a formula.
_BIN_OPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
}
_UNARY_OPS = {ast.UAdd: op.pos, ast.USub: op.neg}


def _eval_node(node: ast.AST, names: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, names)
    if isinstance(node, ast.Constant):  # numbers only
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise ToolError(f"disallowed constant: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise ToolError(f"missing input '{node.id}'")
        return float(names[node.id])
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval_node(node.left, names), _eval_node(node.right, names)
        if type(node.op) is ast.Div and right == 0:
            raise ToolError("division by zero")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand, names))
    raise ToolError(f"disallowed expression element: {type(node).__name__}")


def evaluate_expression(expr: str, variables: dict[str, float]) -> float:
    """Safely evaluate a plain arithmetic expression over `variables`. Logged (free-form path)."""
    logger.info("free-form calculate: %s with %s", expr, variables)
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ToolError(f"invalid expression: {expr!r}") from e
    return _eval_node(tree, variables)


@register("calculate")
def calculate(metric: str, inputs: dict[str, float], is_bank: bool = False) -> dict:
    """Compute a glossary metric from named inputs.

    Returns {metric, value, unit, formula, inputs}. Raises ToolError if the metric is unknown or a
    required input is missing. All inputs must already be in a consistent unit (use normalise_units).
    """
    spec = get_metric(metric, is_bank)
    required = spec.get("inputs", [])
    missing = [name for name in required if name not in inputs]
    if missing:
        raise ToolError(f"metric '{metric}' needs inputs {required}; missing {missing}")

    value = evaluate_expression(spec["formula"], inputs)
    return {
        "metric": metric,
        "value": value,
        "unit": spec.get("unit", ""),
        "formula": spec["formula"],
        "inputs": {k: inputs[k] for k in required},
    }
