"""Offline tests for calculator.py edge formatting and parsing."""
import sys
import sympy as sp
import pytest

sys.path.insert(0, ".")

from src.tools.builtin.calculator import (
    CalculatorService,
    _format_float,
    _format_value,
    _evaluate_expression,
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
