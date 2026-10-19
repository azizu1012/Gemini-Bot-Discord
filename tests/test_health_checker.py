"""Test HealthCheckerService không còn phụ thuộc api_router (offline)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.health_checker import HealthCheckerService


def test_health_checker_has_no_router_attribute():
    svc = HealthCheckerService()
    assert not hasattr(svc, "router")
    assert svc.db_repo is None


def test_health_check_cycle_returns_stub_report():
    svc = HealthCheckerService()
    result = asyncio.run(svc.run_health_check_cycle())
    assert result["model_scan"]["success"] is True
    assert result["changes"] == []
    assert result["key_checks"] == []


if __name__ == "__main__":
    test_health_checker_has_no_router_attribute()
    test_health_check_cycle_returns_stub_report()
    print("ALL PASS")
