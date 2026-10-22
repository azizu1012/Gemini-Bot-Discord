"""Calculator service evaluating expressions with SymPy."""

from __future__ import annotations

import json
import re
from typing import Any

import sympy as sp
from sympy.parsing.sympy_parser import (
    parse_expr,
    standard_transformations,
    implicit_multiplication_application,
    convert_xor,
)

from src.core.config import logger

# Giới hạn độ dài để tránh biểu thức khổng lồ làm treo worker.
MAX_EXPRESSION_LENGTH = 2000

# Chặn truy cập thuộc tính nội bộ / builtins nguy hiểm trước khi đưa vào eval.
# Dấu nháy bị cấm vì biểu thức toán không cần chuỗi (chặn vector sympify('...')).
_BLOCKED_PATTERN = re.compile(
    r"""(?:__|\blambda\b|\bimport\b|\beval\b|\bexec\b|\bcompile\b|\bopen\b|"""
    r"""\bglobals\b|\blocals\b|\bvars\b|\bdir\b|\bgetattr\b|\bsetattr\b|"""
    r"""\bdelattr\b|\binput\b|\bbreakpoint\b|['"])""",
    re.IGNORECASE,
)

_TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication_application,
    convert_xor,
)

# Namespace SymPy đầy đủ nhưng tước toàn bộ builtins và các hàm có thể eval chuỗi.
_BLOCKED_GLOBAL_NAMES = {
    "sympify", "S", "parse_expr", "lambdify", "init_printing", "preview",
    "plot", "plot3d", "plot_implicit", "plot_parametric", "interactive",
    "session", "test", "doctest", "source", "jit",
}
_GLOBAL_DICT: dict[str, Any] = {
    name: getattr(sp, name)
    for name in dir(sp)
    if not name.startswith("_") and name not in _BLOCKED_GLOBAL_NAMES
}
_GLOBAL_DICT["__builtins__"] = {}

_LOCAL_DICT: dict[str, Any] = {
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
    "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
    "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh,
    "log": sp.log, "ln": sp.log, "exp": sp.exp,
    "sqrt": sp.sqrt, "pi": sp.pi, "e": sp.E,
    "factorial": sp.factorial, "abs": sp.Abs, "Abs": sp.Abs,
    "min": sp.Min, "max": sp.Max, "Min": sp.Min, "Max": sp.Max,
    "floor": sp.floor, "ceil": sp.ceiling, "ceiling": sp.ceiling,
    "gcd": sp.gcd, "lcm": sp.lcm, "mod": sp.Mod, "binomial": sp.binomial,
    "diff": sp.diff, "integrate": sp.integrate,
    "limit": sp.limit, "simplify": sp.simplify, "solve": sp.solve,
    "eq": sp.Eq, "Eq": sp.Eq, "sum": sp.Sum, "Sum": sp.Sum,
    "product": sp.Product, "Product": sp.Product,
}

_DECIMAL_COMMA_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?:\D|$))")


def _error(raw_equation: str, message: str) -> str:
    return json.dumps(
        {"equation": raw_equation, "result": f"Lỗi biểu thức: {message}", "success": False},
        ensure_ascii=False,
    )


def _split_top_level(text: str, separator: str = ",") -> list[str]:
    """Split text on a separator that is not inside parentheses/brackets."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in text:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        if char == separator and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _top_level_index(text: str, target: str) -> int:
    depth = 0
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == target and depth == 0:
            return index
    return -1


def _normalize_decimal_commas(expr: str) -> str:
    """Convert Vietnamese decimal commas to dots, keeping thousands separators intact."""
    # 1,000,000 -> 1000000 (nhóm đúng 3 chữ số)
    normalized = _DECIMAL_COMMA_THOUSANDS.sub("", expr)
    # 1,5 -> 1.5
    return normalized.replace(",", ".")


def _rewrite_solve_equations(expr: str) -> str:
    """Turn solve(a = b, x) into solve(Eq(a, b), x) so SymPy does not choke on '='."""
    match = re.fullmatch(r"solve\s*\((.*)\)", expr, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return expr
    args = _split_top_level(match.group(1))
    rewritten: list[str] = []
    changed = False
    for arg in args:
        eq_index = _top_level_index(arg, "=")
        if eq_index > 0:
            lhs = arg[:eq_index].strip()
            rhs = arg[eq_index + 1:].strip()
            if lhs and rhs:
                rewritten.append(f"Eq({lhs}, {rhs})")
                changed = True
                continue
        rewritten.append(arg)
    if not changed:
        return expr
    return f"solve({', '.join(rewritten)})"


def _parse(expr: str):
    return parse_expr(
        expr,
        local_dict=dict(_LOCAL_DICT),
        global_dict=dict(_GLOBAL_DICT),
        transformations=_TRANSFORMATIONS,
        evaluate=True,
    )


def _evaluate_expression(text: str):
    """Parse text, retrying with decimal-comma normalization when commas were misread."""
    try:
        expr = _parse(text)
    except Exception:
        normalized = _normalize_decimal_commas(text)
        if normalized == text:
            raise
        expr = _parse(normalized)
    else:
        # "1,5 + sin(2)" bị Python hiểu thành tuple; thử lại với dấu phẩy thập phân.
        if isinstance(expr, (sp.Tuple, tuple)):
            normalized = _normalize_decimal_commas(text)
            if normalized != text:
                candidate = _parse(normalized)
                if not isinstance(candidate, (sp.Tuple, tuple)):
                    expr = candidate
    if hasattr(expr, "doit"):
        expr = expr.doit()
    return expr


def _format_float(value: float) -> str:
    if value != value:  # NaN
        raise ValueError("Không xác định (NaN)")
    if value in (float("inf"), float("-inf")):
        return "∞" if value > 0 else "-∞"
    text = f"{value:.12g}"
    if "e" not in text and "E" not in text and "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _format_value(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{_format_value(k)} = {_format_value(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple, set)):
        return "[" + ", ".join(_format_value(item) for item in value) + "]"
    if isinstance(value, bool):
        return "Đúng" if value else "Sai"
    if value is sp.true:
        return "Đúng"
    if value is sp.false:
        return "Sai"
    if isinstance(value, sp.Basic):
        if value is sp.zoo or value is sp.nan:
            raise ValueError("Không xác định (chia cho 0)")
        if value is sp.oo:
            return "∞"
        if value is -sp.oo:
            return "-∞"
        if value.is_Integer:
            return str(int(value))
        if value.is_Rational:
            return str(value)
        if value.is_Float:
            return _format_float(float(value))
        if getattr(value, "free_symbols", set()):
            simplified = sp.simplify(value)
            if simplified.is_Integer:
                return str(int(simplified))
            if simplified.is_Rational:
                return str(simplified)
            if simplified.is_Float:
                return _format_float(float(simplified))
            return str(simplified)
        try:
            return _format_float(float(value.evalf(15)))
        except (TypeError, ValueError):
            return str(value)
    return str(value)


class CalculatorService:
    """Evaluate mathematical expressions using SymPy."""

    def __init__(self, logger_override=None):
        self.logger = logger_override or logger

    def run_calculator(self, equation_str: str) -> str:
        raw_eq = str(equation_str or "").strip()
        if not raw_eq:
            return _error(equation_str, "Biểu thức rỗng.")
        if len(raw_eq) > MAX_EXPRESSION_LENGTH:
            return _error(equation_str, "Biểu thức quá dài.")

        cleaned_eq = raw_eq.lower()
        cleaned_eq = (
            cleaned_eq.replace("×", "*").replace("·", "*").replace("÷", "/")
            .replace("−", "-").replace("–", "-")
        )

        if _BLOCKED_PATTERN.search(cleaned_eq):
            return _error(equation_str, "Biểu thức chứa thành phần không được phép.")

        try:
            cleaned_eq = cleaned_eq.strip()
            if cleaned_eq.endswith("="):
                cleaned_eq = cleaned_eq[:-1].strip()

            # solve(a = b, x) -> solve(Eq(a, b), x)
            cleaned_eq = _rewrite_solve_equations(cleaned_eq)

            eq_index = _top_level_index(cleaned_eq, "=")
            if eq_index > 0:
                lhs_text = cleaned_eq[:eq_index].strip()
                rhs_text = cleaned_eq[eq_index + 1:].strip()
                if not lhs_text or not rhs_text:
                    return _error(equation_str, "Phương trình thiếu vế trái hoặc vế phải.")
                lhs = _evaluate_expression(lhs_text)
                rhs = _evaluate_expression(rhs_text)
                symbols = sorted(lhs.free_symbols | rhs.free_symbols, key=str)
                if symbols:
                    solutions = sp.solve(sp.Eq(lhs, rhs), *symbols)
                    result_str = _format_value(solutions)
                else:
                    is_equal = sp.simplify(lhs - rhs) == 0
                    result_str = "Đúng" if is_equal else "Sai"
            else:
                expr = _evaluate_expression(cleaned_eq)
                result_str = _format_value(expr)

            return json.dumps(
                {"equation": equation_str, "result": result_str, "success": True},
                ensure_ascii=False,
            )
        except Exception as exc:  # SymPy raises many concrete error types
            return _error(equation_str, str(exc))
