"""Test dọn cấu hình endpoint-only (offline, không cần mạng)."""
import logging
import os
import sys

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
