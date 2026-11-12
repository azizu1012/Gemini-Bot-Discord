"""Tests for src/core/logger.py — LoggerService wrapper around stdlib logging."""
import logging

import pytest

from src.core.logger import LoggerService, get_logger_service


@pytest.fixture
def mock_logger():
    """A stdlib logger that records records on a list."""
    logger = logging.getLogger("test_logger_service")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    records = []

    class _Handler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Handler()
    logger.addHandler(handler)
    yield logger, records


@pytest.fixture
def service(mock_logger):
    logger, _ = mock_logger
    return LoggerService(logger)


def test_factory_returns_service(mock_logger):
    logger, _ = mock_logger
    svc = get_logger_service(logger)
    assert isinstance(svc, LoggerService)
    assert svc.logger is logger


@pytest.mark.asyncio
async def test_log_message_user_role_logs(mock_logger):
    logger, records = mock_logger
    await LoggerService(logger).log_message("u1", "user", "hello")
    assert any("u1" in r.getMessage() and "sent a message" in r.getMessage() for r in records)


@pytest.mark.asyncio
async def test_log_message_assistant_dm_logs(mock_logger):
    logger, records = mock_logger
    await LoggerService(logger).log_message("u2", "assistant", "DM reply to user")
    assert any("DM" in r.getMessage() for r in records)


@pytest.mark.asyncio
async def test_log_message_no_match_no_log(mock_logger):
    logger, records = mock_logger
    await LoggerService(logger).log_message("u3", "assistant", "plain reply")
    assert records == []


def test_info_emits_record(service, mock_logger):
    _, records = mock_logger
    service.info("an info")
    assert any(r.levelno == logging.INFO and r.getMessage() == "an info" for r in records)


def test_error_emits_record(service, mock_logger):
    _, records = mock_logger
    service.error("an error")
    assert any(r.levelno == logging.ERROR and r.getMessage() == "an error" for r in records)


def test_warning_emits_record(service, mock_logger):
    _, records = mock_logger
    service.warning("a warning")
    assert any(r.levelno == logging.WARNING and r.getMessage() == "a warning" for r in records)


def test_debug_emits_record(service, mock_logger):
    _, records = mock_logger
    service.debug("a debug")
    assert any(r.levelno == logging.DEBUG and r.getMessage() == "a debug" for r in records)
