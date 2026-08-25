"""Small, deterministic arithmetic helper for conversational queries.

Local language models are useful for explanation but should not be trusted to
evaluate even a short expression.  This module deliberately accepts only a
plain arithmetic expression and a small AST allow-list; it never calls eval.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from typing import Optional


_ALLOWED_CHARS = re.compile(r"^[0-9()+\-*/.=?\s]+$")
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left = _eval(node.left)
        right = _eval(node.right)
        if isinstance(node.op, (ast.Div, ast.Mod)) and right == 0:
            raise ValueError("division by zero")
        return _OPS[type(node.op)](left, right)
    raise ValueError("unsupported arithmetic expression")


def calculate_expression(text: str) -> Optional[str]:
    """Return a Vietnamese answer for a plain expression, otherwise ``None``."""
    raw = str(text or "").strip()
    if not raw or len(raw) > 120 or not _ALLOWED_CHARS.fullmatch(raw):
        return None
    candidate = re.sub(r"\s+", "", raw)
    # Accept common forms such as ``1+2=?`` and ``1+2=``.
    candidate = re.sub(r"=\?$", "", candidate)
    candidate = re.sub(r"[?=]$", "", candidate)
    if not candidate or not re.search(r"[+\-*/]", candidate) or not re.search(r"\d", candidate):
        return None
    try:
        tree = ast.parse(candidate, mode="eval")
        value = _eval(tree)
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError):
        return None
    if not math.isfinite(value) or abs(value) > 1_000_000_000_000:
        return None
    if value.is_integer():
        rendered = str(int(value))
    else:
        rendered = format(value, ".12g")
    return f"Kết quả là {rendered}."
