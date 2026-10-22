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


class TestCalculatorRegressions:
    """Các lỗi thực tế gặp trong log: dấu phẩy tham số, giải phương trình, RCE."""

    def test_multi_argument_calculus_keeps_commas(self):
        calc = CalculatorService()
        diff_res = json.loads(calc.run_calculator("diff(x**3, x, 2)"))
        assert diff_res["success"] is True
        assert diff_res["result"] == "6*x"

        integral_res = json.loads(calc.run_calculator("integrate(x**2, (x, 0, 1))"))
        assert integral_res["success"] is True
        assert integral_res["result"] == "1/3"

        limit_res = json.loads(calc.run_calculator("limit(sin(x)/x, x, 0)"))
        assert limit_res["success"] is True
        assert limit_res["result"] == "1"

    def test_equation_with_symbols_is_solved(self):
        calc = CalculatorService()
        res = json.loads(calc.run_calculator("2x = 10"))
        assert res["success"] is True
        assert res["result"] == "[5]"

        res = json.loads(calc.run_calculator("solve(x**2 - 4 = 0, x)"))
        assert res["success"] is True
        assert res["result"] == "[-2, 2]"

    def test_numeric_equality_is_checked(self):
        calc = CalculatorService()
        assert json.loads(calc.run_calculator("2+2 = 4"))["result"] == "Đúng"
        assert json.loads(calc.run_calculator("2+2 = 5"))["result"] == "Sai"

    def test_decimal_comma_and_thousands_separator(self):
        calc = CalculatorService()
        assert json.loads(calc.run_calculator("1,5 + 2,5"))["result"] == "4"
        assert json.loads(calc.run_calculator("1,000 + 2"))["result"] == "1002"

        mixed = json.loads(calc.run_calculator("1,5 + sin(2)"))
        assert mixed["success"] is True
        assert float(mixed["result"]) == pytest.approx(2.40929742683, rel=1e-6)

    def test_code_injection_is_blocked(self):
        calc = CalculatorService()
        for payload in (
            "__import__('os').system('echo HACKED')",
            "(1).__class__.__bases__",
            "sympify('1+1')",
            "S('1+1')",
            "lambda: 1",
        ):
            res = json.loads(calc.run_calculator(payload))
            assert res["success"] is False
            assert "không được phép" in res["result"]


class TestWeatherService:
    def test_weather_empty_city_fallback(self, monkeypatch):
        import tempfile
        import src.tools.builtin.weather as weather_mod

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "current": {
                        "temp_c": 30,
                        "condition": {"text": "Nắng"},
                        "humidity": 50,
                        "wind_kph": 5,
                    },
                    "location": {"name": "Ho Chi Minh City"},
                }

        with tempfile.TemporaryDirectory() as tmp_dir:
            monkeypatch.setattr(weather_mod, "WEATHER_CACHE_PATH", f"{tmp_dir}/weather_cache.json")
            monkeypatch.setattr(weather_mod, "CITY", "Ho Chi Minh City")
            monkeypatch.setattr(weather_mod, "WEATHER_API_KEY", "test-key")
            monkeypatch.setattr(weather_mod.requests, "get", lambda *args, **kwargs: FakeResponse())
            ws = WeatherService()
            res = ws.run_weather(None)

        assert "Ho Chi Minh City" in res
        assert "30" in res

    def test_bad_cache_entries_are_ignored(self, monkeypatch):
        import json as json_lib
        import tempfile
        import src.tools.builtin.weather as weather_mod

        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_file = f"{tmp_dir}/weather_cache.json"
            with open(cache_file, "w", encoding="utf-8") as f:
                json_lib.dump({
                    "Hanoi": {"timestamp": 12345, "data": "bad"},
                    "SaiGon": {"timestamp": "not-a-date", "data": "bad"},
                    "Danang": {"timestamp": "2026-10-22T00:00:00", "data": "ok"},
                }, f)
            monkeypatch.setattr(weather_mod, "WEATHER_CACHE_PATH", cache_file)

            ws = WeatherService()
            assert "hanoi" not in ws.weather_cache
            assert "saigon" not in ws.weather_cache
            assert ws.weather_cache["danang"]["data"] == "ok"

    def test_cache_key_is_case_insensitive(self, monkeypatch):
        import json as json_lib
        import tempfile
        from datetime import datetime
        import src.tools.builtin.weather as weather_mod

        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_file = f"{tmp_dir}/weather_cache.json"
            with open(cache_file, "w", encoding="utf-8") as f:
                json_lib.dump({"Hanoi": {"timestamp": datetime.now().isoformat(), "data": "cached"}}, f)
            monkeypatch.setattr(weather_mod, "WEATHER_CACHE_PATH", cache_file)

            ws = WeatherService()
            assert ws.run_weather("  hAnOi  ") == "cached"


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
