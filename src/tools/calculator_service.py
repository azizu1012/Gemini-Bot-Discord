import json

import sympy as sp
from sympy.parsing.sympy_parser import (
    parse_expr,
    standard_transformations,
    implicit_multiplication_application,
    convert_xor,
)

from src.core.config import logger


class CalculatorService:
    """Evaluate mathematical expressions using SymPy."""

    def __init__(self):
        self.logger = logger

    def run_calculator(self, equation_str: str):
        raw_eq = (equation_str or "").strip()
        if not raw_eq:
            return json.dumps({
                "equation": equation_str,
                "result": "Lỗi biểu thức: Biểu thức rỗng.",
                "success": False
            }, ensure_ascii=False)

        cleaned_eq = raw_eq.strip().lower().replace(',', '.')
        cleaned_eq = cleaned_eq.replace('×', '*').replace('·', '*').replace('÷', '/')
        cleaned_eq = cleaned_eq.replace('−', '-')
        if cleaned_eq.endswith('='):
            cleaned_eq = cleaned_eq[:-1].strip()
        if '=' in cleaned_eq:
            cleaned_eq = cleaned_eq.split('=', 1)[1].strip()

        transformations = standard_transformations + (
            implicit_multiplication_application,
            convert_xor,
        )
        local_dict = {
            "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
            "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
            "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh,
            "log": sp.log, "ln": sp.log, "exp": sp.exp,
            "sqrt": sp.sqrt, "pi": sp.pi, "e": sp.E,
            "diff": sp.diff, "integrate": sp.integrate,
            "limit": sp.limit, "simplify": sp.simplify,
        }

        try:
            expr = parse_expr(
                cleaned_eq,
                local_dict=local_dict,
                transformations=transformations,
                evaluate=True,
            )
            if hasattr(expr, "doit"):
                expr = expr.doit()
            if getattr(expr, "free_symbols", set()):
                result = sp.simplify(expr)
            else:
                result = sp.N(expr)
            result_str = str(result)
            if result_str.endswith('.0'):
                result_str = result_str[:-2]
            return json.dumps({
                "equation": equation_str,
                "result": result_str,
                "success": True
            }, ensure_ascii=False)
        except (sp.SympifyError, TypeError, ZeroDivisionError, Exception) as e:
            return json.dumps({
                "equation": equation_str,
                "result": f"Lỗi biểu thức: {str(e)}",
                "success": False
            }, ensure_ascii=False)
