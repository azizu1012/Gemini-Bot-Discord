"""Offline tests for HealthCheckerService."""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.services.health_checker import HealthCheckerService


class NullLogger:
    def info(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_checker():
    checker = HealthCheckerService()
    checker.logger = NullLogger()
    checker.config = MagicMock()
    return checker


@pytest.mark.asyncio
async def test_generate_recovery_report():
    checker = make_checker()
    report = await checker._generate_recovery_report("key1", "google", 0, 0, "5 phút")
    assert "key1" in report
    assert "GOOGLE" in report
    assert "5 phút" in report


@pytest.mark.asyncio
async def test_run_health_check_cycle_returns_router_note():
    checker = make_checker()
    result = await checker.run_health_check_cycle()
    assert result["model_scan"]["success"] is True
    assert "Router API" in result["model_scan"]["note"]


@pytest.mark.asyncio
async def test_start_background_check_creates_task():
    checker = make_checker()
    checker._background_task = AsyncMock()
    checker.start_background_check(admin_user="admin", interval_seconds=1)
    assert checker.is_running is True
    assert checker.admin_user == "admin"
    assert checker._background_task_task is not None
    checker.stop()


def test_stop_cancels_task():
    checker = make_checker()
    task = MagicMock()
    checker._background_task_task = task
    checker.is_running = True
    checker.stop()
    assert checker.is_running is False
    task.cancel.assert_called_once()
    assert checker._background_task_task is None


def test_stop_no_task():
    checker = make_checker()
    checker._background_task_task = None
    checker.stop()  # no exception


@pytest.mark.asyncio
async def test_background_task_runs_cycle():
    checker = make_checker()
    cycles = {"n": 0}

    async def fake_cycle(*a, **kw):
        cycles["n"] += 1
        if cycles["n"] >= 1:
            checker.is_running = False  # stop after first cycle

    checker.run_health_check_cycle = fake_cycle
    await checker._background_task(interval_seconds=0.01)
    assert cycles["n"] >= 1


@pytest.mark.asyncio
async def test_background_task_handles_error():
    checker = make_checker()

    async def boom(*a, **kw):
        checker.is_running = False
        raise RuntimeError("cycle failed")

    checker.run_health_check_cycle = boom
    await checker._background_task(interval_seconds=0.01)  # no exception


def test_get_health_checker_singleton():
    from src.services.health_checker import get_health_checker

    a = get_health_checker()
    b = get_health_checker()
    assert a is b
