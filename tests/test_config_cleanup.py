"""Test dọn cấu hình endpoint-only (offline, không cần mạng)."""
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import get_config
from src.tools.tools import ToolsManager


def _make_manager():
    mgr = ToolsManager.__new__(ToolsManager)
    mgr.logger = logging.getLogger("test_config_cleanup")
    return mgr


def _with_env(values, fn):
    saved = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return fn()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_config_no_longer_exposes_legacy_key_settings():
    cfg = get_config()
    for attr in (
        "GEMINI_API_KEYS",
        "GEMINI_BASE_URL",
        "ROUTER_AUTH_KEY",
        "MODEL_NAME",
        "OPENAI_API_KEY",
        "OPENAI_CUSTOM_ENDPOINT",
        "GEMINI_CIRCUIT_ENABLED",
        "GEMINI_CIRCUIT_FAILURE_THRESHOLD",
        "GEMINI_CIRCUIT_WINDOW_SECONDS",
        "GEMINI_CIRCUIT_OPEN_SECONDS",
    ):
        assert not hasattr(cfg, attr), attr


def test_config_keeps_endpoint_refactor_settings():
    cfg = get_config()
    assert hasattr(cfg, "DONATE_ENCRYPTION_KEY")
    assert hasattr(cfg, "ALLOW_PLAINTEXT_ENDPOINT_KEYS")
    assert hasattr(cfg, "GEMINI_TIMEOUT_MS")


def test_search_parallel_streams_new_env_wins():
    value = _with_env(
        {"SEARCH_PARALLEL_STREAMS": "2", "GOOGLE_SEARCH_STREAMS": "1"},
        lambda: _make_manager()._load_google_search_streams(),
    )
    assert value == 2


def test_search_streams_legacy_env_still_read():
    value = _with_env(
        {"SEARCH_PARALLEL_STREAMS": None, "GOOGLE_SEARCH_STREAMS": "2"},
        lambda: _make_manager()._load_google_search_streams(),
    )
    assert value == 2


def test_search_streams_default_and_clamp():
    assert _with_env(
        {"SEARCH_PARALLEL_STREAMS": None, "GOOGLE_SEARCH_STREAMS": None},
        lambda: _make_manager()._load_google_search_streams(),
    ) == 1
    assert _with_env(
        {"SEARCH_PARALLEL_STREAMS": "9", "GOOGLE_SEARCH_STREAMS": None},
        lambda: _make_manager()._load_google_search_streams(),
    ) == 2


if __name__ == "__main__":
    test_config_no_longer_exposes_legacy_key_settings()
    test_config_keeps_endpoint_refactor_settings()
    test_search_parallel_streams_new_env_wins()
    test_search_streams_legacy_env_still_read()
    test_search_streams_default_and_clamp()
    print("ALL PASS")


def test_config_get_int_and_float_invalid_and_clamps():
    from src.core.config import Config

    # invalid int -> default
    assert _with_env({"TEST_INT_VAR": "not_an_int"}, lambda: Config._get_int("TEST_INT_VAR", 42)) == 42
    # invalid float -> default
    assert _with_env({"TEST_FLOAT_VAR": "not_a_float"}, lambda: Config._get_float("TEST_FLOAT_VAR", 3.14)) == 3.14
    # float max_value clamp
    assert _with_env({"TEST_FLOAT_VAR": "99.9"}, lambda: Config._get_float("TEST_FLOAT_VAR", 1.0, max_value=5.0)) == 5.0
    assert _with_env({"TEST_FLOAT_VAR": "0.1"}, lambda: Config._get_float("TEST_FLOAT_VAR", 1.0, min_value=0.5)) == 0.5


@pytest.mark.parametrize(
    "raw, expected",
    [(None, True), ("", True), ("true", True), ("1", True), ("yes", True), (" ON ", True),
     ("false", False), ("0", False), ("no", False), (" OFF ", False)],
)
def test_chat_limits_enabled_reads_environment(monkeypatch, raw, expected):
    from src.core.config import Config

    monkeypatch.setattr("src.core.config._load_runtime_env", lambda root: None)
    if raw is None:
        monkeypatch.delenv("CHAT_LIMITS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("CHAT_LIMITS_ENABLED", raw)
    assert Config().CHAT_LIMITS_ENABLED is expected


def test_chat_limit_configuration_reads_environment(monkeypatch):
    from src.core.config import Config

    monkeypatch.setattr("src.core.config._load_runtime_env", lambda root: None)
    for name, value in {
        "SPAM_THRESHOLD": "4", "SPAM_WINDOW": "20", "DEFAULT_RATE_LIMIT": "12/60",
        "PREMIUM_RATE_LIMIT": "30/90", "DEFAULT_DM_LIMIT": "8", "PREMIUM_DM_LIMIT": "25",
    }.items():
        monkeypatch.setenv(name, value)
    cfg = Config()
    assert (cfg.SPAM_THRESHOLD, cfg.SPAM_WINDOW) == (4, 20)
    assert (cfg.DEFAULT_RATE_LIMIT, cfg.PREMIUM_RATE_LIMIT) == ("12/60", "30/90")
    assert (cfg.DEFAULT_DM_LIMIT, cfg.PREMIUM_DM_LIMIT) == (8, 25)
    for invalid in ("bad", "0/60", "10/0", "-1/60", "10/60/90"):
        monkeypatch.setenv("DEFAULT_RATE_LIMIT", invalid)
        assert Config._get_rate_limit("DEFAULT_RATE_LIMIT", "10/60") == "10/60"


def test_config_db_pool_accessors():
    from src.core.config import get_db_pool, set_db_pool

    old = get_db_pool()
    try:
        set_db_pool("mock_pool")
        assert get_db_pool() == "mock_pool"
    finally:
        set_db_pool(old)


def test_config_resolve_absolute_path(tmp_path):
    cfg = get_config()
    abs_path = str(tmp_path / "custom.log")
    resolved = _with_env({"TEST_ABS_PATH": abs_path}, lambda: cfg._resolve_runtime_path("TEST_ABS_PATH", "default.log"))
    assert resolved == abs_path
