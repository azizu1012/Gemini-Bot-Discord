"""Unit tests for builtin tools (calculator, weather, declarations)."""

import json
import pytest
from src.tools.builtin.calculator import CalculatorService
from src.tools.builtin.weather import WeatherService
from src.tools.builtin.declarations import get_gemini_tools
from src.tools.manager import ToolsManager


class TestCalculatorService:
    def test_simple_arithmetic(self):
        calc = CalculatorService()
        res = json.loads(calc.run_calculator("2 + 2"))
        assert res["success"] is True
        assert res["result"] == "4"

    def test_advanced_math(self):
        calc = CalculatorService()
        res = json.loads(calc.run_calculator("sqrt(16) * 5"))
        assert res["success"] is True
        assert res["result"] == "20"

    def test_invalid_equation(self):
        calc = CalculatorService()
        res = json.loads(calc.run_calculator("invalid syntax @@@"))
        assert res["success"] is False
        assert "Lỗi" in res["result"]


class TestWeatherService:
    def test_weather_empty_city_fallback(self):
        ws = WeatherService()
        res = ws.run_weather(None)
        assert isinstance(res, str)
        assert len(res) > 0


class TestToolDeclarations:
    def test_tools_list_standard_and_admin(self):
        normal_tools = get_gemini_tools(is_admin=False)
        assert len(normal_tools) == 7
        admin_tools = get_gemini_tools(is_admin=True)
        assert len(admin_tools) == 8


class TestToolsManagerFacade:
    def test_tools_manager_instantiation(self):
        mgr = ToolsManager()
        assert mgr.calculator is not None
        assert mgr.weather is not None
        assert mgr.search_engine is not None
        assert mgr.vision is not None
