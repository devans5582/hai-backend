"""A tiny safe expression language.

Used for applicability conditions (decision D5) and for the Python form of
declarative checks. The grammar is parsed with :mod:`ast` and allows only:

* boolean operators ``and``, ``or``, ``not``
* comparisons ``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=``, ``in``, ``not in``,
  ``is``, ``is not``
* names (looked up in the supplied namespace), literals, tuples and lists of
  literals, and parentheses
* calls to two whitelisted helpers: ``len(x)`` and ``nonblank(x)``

Anything else (attribute access, arbitrary calls, arithmetic, comprehensions,
lambdas, imports) is refused with :class:`UnsafeExpressionError`.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import Any

__all__ = ["UnsafeExpressionError", "evaluate", "parse"]


class UnsafeExpressionError(ValueError):
    """The expression uses a construct outside the safe subset."""


_ALLOWED_COMPARE = (
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
)
_HELPERS = frozenset({"len", "nonblank"})


def parse(expression: str) -> ast.Expression:
    """Parse and verify ``expression``; raise :class:`UnsafeExpressionError` if it strays."""
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError(f"cannot parse {expression!r}: {exc.msg}") from exc
    _check(tree.body)
    return tree


def _check(node: ast.AST) -> None:
    if isinstance(node, ast.BoolOp):
        for v in node.values:
            _check(v)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        _check(node.operand)
        return
    if isinstance(node, ast.Compare):
        for op in node.ops:
            if not isinstance(op, _ALLOWED_COMPARE):
                raise UnsafeExpressionError(f"operator {type(op).__name__} is not allowed")
        _check(node.left)
        for c in node.comparators:
            _check(c)
        return
    if isinstance(node, ast.Name):
        return
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str | int | float | bool) or node.value is None:
            return
        raise UnsafeExpressionError(f"literal {node.value!r} is not allowed")
    if isinstance(node, ast.Tuple | ast.List):
        for elt in node.elts:
            _check(elt)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _HELPERS:
            raise UnsafeExpressionError("only len() and nonblank() may be called")
        if node.keywords or len(node.args) != 1:
            raise UnsafeExpressionError(f"{node.func.id}() takes exactly one positional argument")
        _check(node.args[0])
        return
    raise UnsafeExpressionError(f"{type(node).__name__} is not allowed")


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _safe_len(value: Any) -> int:
    if value is None:
        return 0
    return len(value)


def evaluate(expression: str, namespace: Mapping[str, Any]) -> bool:
    """Evaluate a parsed-safe expression against ``namespace``.

    Unknown names evaluate to ``None`` so a missing optional field reads as null.
    """
    tree = parse(expression)
    return bool(_eval(tree.body, namespace))


def _eval(node: ast.AST, ns: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for v in node.values:
                result = _eval(v, ns)
                if not result:
                    return result
            return result
        result = False
        for v in node.values:
            result = _eval(v, ns)
            if result:
                return result
        return result
    if isinstance(node, ast.UnaryOp):
        return not _eval(node.operand, ns)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, ns)
        for op, comp in zip(node.ops, node.comparators, strict=True):
            right = _eval(comp, ns)
            if not _compare(op, left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Name):
        return ns.get(node.id)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple | ast.List):
        return tuple(_eval(e, ns) for e in node.elts)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        arg = _eval(node.args[0], ns)
        return _nonblank(arg) if node.func.id == "nonblank" else _safe_len(arg)
    raise UnsafeExpressionError(type(node).__name__)


def _compare(op: ast.cmpop, left: Any, right: Any) -> bool:
    if isinstance(op, ast.Eq):
        return bool(left == right)
    if isinstance(op, ast.NotEq):
        return bool(left != right)
    if isinstance(op, ast.In):
        return right is not None and left in right
    if isinstance(op, ast.NotIn):
        return right is None or left not in right
    if isinstance(op, ast.Is):
        return left is right
    if isinstance(op, ast.IsNot):
        return left is not right
    if left is None or right is None:
        return False
    if isinstance(op, ast.Lt):
        return bool(left < right)
    if isinstance(op, ast.LtE):
        return bool(left <= right)
    if isinstance(op, ast.Gt):
        return bool(left > right)
    return bool(left >= right)
