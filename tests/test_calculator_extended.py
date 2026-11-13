"""Offline tests for calculator.py edge formatting and parsing."""
import sys
import json
from types import ModuleType

import sympy as sp
import pytest

sys.path.insert(0, ".")

from src.tools.builtin.calculator import (
    CalculatorService,
    _format_float,
    _format_value,
    _evaluate_expression,
    _GLOBAL_DICT,
)

def test_format_float_nan():
    with pytest.raises(ValueError, match="NaN"):
        _format_float(float("nan"))

def test_format_float_inf():
    assert _format_float(float("inf")) == "∞"
    assert _format_float(float("-inf")) == "-∞"

def test_format_float_clean_zeros():
    assert _format_float(1.500000) == "1.5"
    assert _format_float(2.000) == "2"

def test_format_value_dict():
    assert "x = 1" in _format_value({"x": 1})

def test_format_value_bool():
    assert _format_value(True) == "Đúng"
    assert _format_value(False) == "Sai"
    assert _format_value(sp.true) == "Đúng"
    assert _format_value(sp.false) == "Sai"

def test_format_value_zoo_nan():
    with pytest.raises(ValueError):
        _format_value(sp.zoo)
    with pytest.raises(ValueError):
        _format_value(sp.nan)

def test_format_value_infinities():
    assert _format_value(sp.oo) == "∞"
    assert _format_value(-sp.oo) == "-∞"

def test_parse_with_commas_tuple_retry():
    expr = _evaluate_expression("1,5 + 2")
    assert float(expr) == 3.5

def test_calculator_too_long():
    svc = CalculatorService()
    res = svc.run_calculator("1+" * 1001)
    assert "quá dài" in res

def test_calculator_empty():
    svc = CalculatorService()
    assert "rỗng" in svc.run_calculator("")
    assert "rỗng" in svc.run_calculator("   ")


@pytest.mark.parametrize("name", [
    "init_session", "interactive_traversal", "var", "lazy_function", "public",
    "pager_print", "print_gtk", "print_ccode", "pprint", "pretty_print", "textplot",
])
def test_calculator_excludes_interactive_and_io_helpers(name):
    assert name not in _GLOBAL_DICT


def test_calculator_excludes_module_aliases():
    assert not any(isinstance(value, ModuleType) for value in _GLOBAL_DICT.values())


def test_calculator_init_session_returns_error():
    # Check the namespace first so a regression cannot launch a real interactive session.
    assert "init_session" not in _GLOBAL_DICT
    result = json.loads(CalculatorService().run_calculator("init_session()"))
    assert result["success"] is False
    assert "Lỗi" in result["result"]


@pytest.mark.parametrize("expression", ["pager_print(1)", "print_gtk(1)", "var(x)", "lazy_function(x, y)"])
def test_calculator_rejects_blocked_helpers_as_symbols(expression):
    result = json.loads(CalculatorService().run_calculator(expression))
    assert result["success"] is False
    assert "không được phép" in result["result"]


@pytest.mark.parametrize("exception", [SystemExit, KeyboardInterrupt])
def test_calculator_contains_exit_exceptions(monkeypatch, exception):
    def interrupted_parse(*args, **kwargs):
        raise exception("interrupted evaluation")

    calc = CalculatorService()
    with monkeypatch.context() as patch:
        patch.setattr("src.tools.builtin.calculator.parse_expr", interrupted_parse)
        result = json.loads(calc.run_calculator("2 + 2"))
    assert result["success"] is False
    assert "interrupted evaluation" in result["result"]
    assert json.loads(calc.run_calculator("2 + 2"))["result"] == "4"


@pytest.mark.parametrize(("expression", "expected"), [
    ("sqrt(16) + 2", "6"),
    ("solve(x**2 - 4, x)", "[-2, 2]"),
    ("integrate(x**2, (x, 0, 1))", "1/3"),
])
def test_calculator_normal_math_remains_available(expression, expected):
    assert _GLOBAL_DICT["symbols"] is sp.symbols
    result = json.loads(CalculatorService().run_calculator(expression))
    assert result["success"] is True
    assert result["result"] == expected
