"""Tests for src/core/preflight.py — startup preflight checks (offline)."""
import importlib.metadata
import logging
from types import SimpleNamespace

import pytest

import src.core.preflight as preflight
from src.core.preflight import (
    _ensure_writable_dir,
    _ensure_writable_file_path,
    _mask_database_url,
    _verify_database_connection,
    emit_startup_banner,
    get_dependency_versions,
    run_preflight_checks,
)


# --- _mask_database_url ---
def test_mask_url_missing():
    assert _mask_database_url("") == "<missing>"


def test_mask_url_no_password_unchanged():
    assert _mask_database_url("postgresql://host:5432/db") == "postgresql://host:5432/db"


def test_mask_url_redacts_password():
    masked = _mask_database_url("postgresql://user:secret@host:5432/db?sslmode=disable")
    assert "secret" not in masked
    assert "user:***@host:5432" in masked


def test_mask_url_malformed_without_password_returns_unchanged():
    # urlsplit is lenient; a parsable-but-odd URL without a password is
    # returned as-is (nothing to redact). This must never raise.
    assert _mask_database_url("://://bad") == "://://bad"
    assert _mask_database_url("") == "<missing>"


# --- get_dependency_versions ---
def test_dependency_versions_returns_installed(monkeypatch):
    versions = get_dependency_versions()
    assert isinstance(versions, dict)
    assert "asyncpg" in versions
    assert all(isinstance(v, str) for v in versions.values())


def test_dependency_versions_marks_missing(monkeypatch):
    def fake_version(pkg):
        raise importlib.metadata.PackageNotFoundError(pkg)

    monkeypatch.setattr(importlib.metadata, "version", fake_version)
    versions = get_dependency_versions()
    assert versions["asyncpg"] == "<missing>"


# --- emit_startup_banner ---
def test_emit_startup_banner_logs(caplog, monkeypatch):
    cfg = SimpleNamespace(
        PROJECT_ROOT="/proj",
        DATABASE_URL="postgresql://u:secret@h:1/db",
        REDIS_URL="redis://localhost:6379/0",
        get_runtime_paths=lambda: {"log_path": "/proj/logs/bot.log"},
    )
    with caplog.at_level(logging.INFO, logger="bot_gemini"):
        emit_startup_banner(cfg)
    assert any("AZURIS STARTUP CONTEXT" in r.message for r in caplog.records)
    # Password must never appear in logs.
    assert not any("secret" in r.message for r in caplog.records)


# --- writable path/dir helpers ---
def test_ensure_writable_file_path_creates(tmp_path):
    target = tmp_path / "nested" / "bot.log"
    _ensure_writable_file_path(str(target))
    assert target.parent.exists()
    assert target.exists()


def test_ensure_writable_dir_creates_and_removes_probe(tmp_path):
    target = tmp_path / "sub" / "dir"
    _ensure_writable_dir(str(target))
    assert target.is_dir()
    # Probe file is cleaned up.
    assert not (target / ".write_probe").exists()


# --- _verify_database_connection ---
class _FakeConn:
    def __init__(self):
        self.closed = False

    async def fetchval(self, sql):
        return 1

    async def close(self):
        self.closed = True


def test_verify_db_success(monkeypatch):
    conn = _FakeConn()

    async def fake_connect(**kwargs):
        return conn

    monkeypatch.setattr(preflight.asyncpg, "connect", fake_connect)

    async def run():
        await _verify_database_connection("postgresql://u:h@host:5432/db", retries=1)

    import asyncio

    asyncio.run(run())
    assert conn.closed


def test_verify_db_fails_after_retries(monkeypatch):
    async def fake_connect(**kwargs):
        raise ConnectionError("boom")

    monkeypatch.setattr(preflight.asyncpg, "connect", fake_connect)

    async def run():
        await _verify_database_connection("postgresql://u:h@host:5432/db", retries=3, delay_seconds=0.01)

    import asyncio

    with pytest.raises(ConnectionError, match="3 attempts"):
        asyncio.run(run())


# --- run_preflight_checks ---
def _stub_config(tmp_path):
    return SimpleNamespace(
        TOKEN="token123",
        DATABASE_URL="postgresql://u:h@host:5432/db",
        WEATHER_CACHE_PATH=str(tmp_path / "data" / "weather_cache.json"),
        LOCKED_CHANNELS_FILE=str(tmp_path / "data" / "voice_lock" / "locked_channels.json"),
        ENFORCED_NAMES_FILE=str(tmp_path / "data" / "voice_lock" / "enforced_names.json"),
        VOICE_WHITELIST_FILE=str(tmp_path / "data" / "voice_lock" / "users.json"),
        VOICE_LOCK_LOG_FILE=str(tmp_path / "data" / "voice_lock" / "voice_lock.log"),
        LOG_PATH=str(tmp_path / "logs" / "bot.log"),
        FILE_STORAGE_PATH=str(tmp_path / "uploaded_files"),
    )


def test_preflight_passes_when_all_ok(tmp_path, caplog, monkeypatch):
    cfg = _stub_config(tmp_path)

    async def fake_verify(*args, **kwargs):
        return None

    monkeypatch.setattr(preflight, "_verify_database_connection", fake_verify)

    ok, errors = run_preflight_checks(cfg)
    assert ok is True
    assert errors == []


def test_preflight_requires_token(tmp_path, monkeypatch):
    cfg = _stub_config(tmp_path)
    cfg.TOKEN = ""

    async def fake_verify(*args, **kwargs):
        return None

    monkeypatch.setattr(preflight, "_verify_database_connection", fake_verify)

    ok, errors = run_preflight_checks(cfg, require_token=True)
    assert ok is False
    assert "DISCORD_TOKEN is missing" in errors


def test_preflight_reports_missing_dependency(tmp_path, monkeypatch):
    cfg = _stub_config(tmp_path)

    def fake_version(pkg):
        raise importlib.metadata.PackageNotFoundError(pkg)

    monkeypatch.setattr(importlib.metadata, "version", fake_version)

    async def fake_verify(*args, **kwargs):
        return None

    monkeypatch.setattr(preflight, "_verify_database_connection", fake_verify)

    ok, errors = run_preflight_checks(cfg)
    assert ok is False
    assert any("Missing dependency" in e for e in errors)


def test_preflight_catches_runtime_path_error(tmp_path, monkeypatch):
    """Writable-path probe failure → error reported, not raised."""
    cfg = _stub_config(tmp_path)

    def boom(path_str):
        raise OSError("cannot create")

    monkeypatch.setattr(preflight, "_ensure_writable_file_path", boom)

    async def fake_verify(*args, **kwargs):
        return None

    monkeypatch.setattr(preflight, "_verify_database_connection", fake_verify)

    ok, errors = run_preflight_checks(cfg)
    assert ok is False
    assert any("Runtime path check failed" in e for e in errors)
