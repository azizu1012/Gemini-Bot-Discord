"""Offline tests for ToolsManager — tool dispatch, config loaders, mention tracking."""
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, ".")

from src.tools.manager import ToolsManager


class NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class FakeSubtools:
    def __init__(self):
        from unittest.mock import AsyncMock

        self.calculator = MagicMock()
        self.weather = MagicMock()
        self.vision = MagicMock()
        self.vision.run_image_recognition = AsyncMock(return_value="cat")
        self.search_engine = MagicMock()
        self.search_engine.run_search_apis = AsyncMock(return_value="search results")
        self.search_engine._split_multi_intents = MagicMock(return_value=["q1", "q2"])
        self.note_mgr = MagicMock()
        self.note_mgr.save_note_to_db = AsyncMock(return_value="saved")
        self.note_mgr.retrieve_notes_from_db = AsyncMock(return_value="notes")
        self.note_mgr.delete_note_from_db = AsyncMock(return_value="deleted")
        self.db_repo = MagicMock()
        self.db_repo.is_admin_user = AsyncMock(return_value=False)
        self.db_repo.add_moderator_user = AsyncMock()
        self.db_repo.add_admin_user = AsyncMock()
        self.db_repo.add_premium_user = AsyncMock()
        self.db_repo.remove_moderator_user = AsyncMock()
        self.db_repo.remove_admin_user = AsyncMock()
        self.db_repo.remove_premium_user = AsyncMock()
        self.db_repo.log_web_search = AsyncMock()
        self.search_subtask_client = MagicMock()
        self.search_subtask_client.request_search = AsyncMock(return_value="subtask result")


def make_manager():
    sub = FakeSubtools()
    mgr = ToolsManager(
        note_mgr=sub.note_mgr,
        db_repo=sub.db_repo,
        search_subtask_client=sub.search_subtask_client,
        enable_search_subtasks=False,
        gateway=None,
    )
    mgr.logger = NullLogger()
    mgr.calculator = sub.calculator
    mgr.weather = sub.weather
    mgr.vision = sub.vision
    mgr.search_engine = sub.search_engine
    return mgr, sub


def _fn(name, args=None):
    return SimpleNamespace(name=name, args=args or {})


def _await(coro):
    import asyncio
    return asyncio.run(coro)


# ---------------- config loaders ----------------
def test_load_web_mode_valid():
    mgr, _ = make_manager()
    assert mgr._load_search_web_mode() in {"grounded", "summary", "snippet", "links"}


def test_load_google_search_streams_default():
    mgr, _ = make_manager()
    assert mgr._load_google_search_streams() == 1


def test_load_google_search_streams_legacy_env(monkeypatch):
    # .env sets SEARCH_PARALLEL_STREAMS=1; unset it to exercise the legacy path.
    monkeypatch.delenv("SEARCH_PARALLEL_STREAMS", raising=False)
    monkeypatch.setenv("GOOGLE_SEARCH_STREAMS", "2")
    mgr, _ = make_manager()
    assert mgr._load_google_search_streams() == 2


def test_load_google_search_streams_modern_env(monkeypatch):
    monkeypatch.setenv("SEARCH_PARALLEL_STREAMS", "1")
    mgr, _ = make_manager()
    assert mgr._load_google_search_streams() == 1


# ---------------- mention tracking ----------------
def test_record_and_pop_allowed_mentions():
    mgr, _ = make_manager()
    mgr._record_allowed_mention("1000", "2000")
    mgr._record_allowed_mention("1000", "3000")
    mgr._record_allowed_mention("1000", "")  # ignored
    assert mgr.pop_allowed_mentions("1000") == ["2000", "3000"]
    assert mgr.pop_allowed_mentions("1000") == []


def test_pop_allowed_mentions_empty_caller():
    mgr, _ = make_manager()
    assert mgr.pop_allowed_mentions("") == []


# ---------------- tool dispatch ----------------
def test_call_web_search_empty_query():
    mgr, sub = make_manager()
    result = _await(mgr.call_tool(_fn("web_search", {"query": "  "}), "u1"))
    assert "không được rỗng" in result
    sub.search_engine.run_search_apis.assert_not_called()


def test_call_web_search_runs_search():
    mgr, sub = make_manager()
    result = _await(mgr.call_tool(_fn("web_search", {"query": "weather today"}), "u1"))
    assert result == "search results"
    sub.search_engine.run_search_apis.assert_awaited_once_with("weather today", "general")
    sub.db_repo.log_web_search.assert_awaited_once()


def test_call_web_search_uses_subtask_client():
    mgr, sub = make_manager()
    mgr.search_subtasks_enabled = True
    result = _await(mgr.call_tool(_fn("web_search", {"query": "a b c"}), "u1"))
    assert result == "subtask result"
    sub.search_subtask_client.request_search.assert_awaited_once()


def test_call_get_weather():
    mgr, sub = make_manager()
    sub.weather.run_weather = MagicMock(return_value="30C")
    result = _await(mgr.call_tool(_fn("get_weather", {"city": "Hanoi"}), "u1"))
    assert result == "30C"
    sub.weather.run_weather.assert_called_once_with("Hanoi")


def test_call_calculate():
    mgr, sub = make_manager()
    sub.calculator.run_calculator = MagicMock(return_value="42")
    result = _await(mgr.call_tool(_fn("calculate", {"equation": "6*7"}), "u1"))
    assert result == "42"


def test_call_save_note_empty():
    mgr, _ = make_manager()
    result = _await(mgr.call_tool(_fn("save_note", {"note_content": " "}), "u1"))
    assert "không được rỗng" in result


def test_call_save_note_no_mgr():
    mgr, sub = make_manager()
    mgr.note_mgr = None
    result = _await(mgr.call_tool(_fn("save_note", {"note_content": "x"}), "u1"))
    assert "sẵn sàng" in result


def test_call_save_note_success():
    mgr, sub = make_manager()
    result = _await(mgr.call_tool(_fn("save_note", {"note_content": "remember"}), "u1"))
    assert result == "saved"
    sub.note_mgr.save_note_to_db.assert_awaited_once_with("u1", "remember", "chat_inference")


def test_call_retrieve_notes():
    mgr, sub = make_manager()
    result = _await(mgr.call_tool(_fn("retrieve_notes", {"query": "q"}), "u1"))
    assert result == "notes"


def test_call_delete_note_empty():
    mgr, _ = make_manager()
    result = _await(mgr.call_tool(_fn("delete_note", {"note_id": " "}), "u1"))
    assert "không được rỗng" in result


def test_call_image_recognition_empty_url():
    mgr, _ = make_manager()
    result = _await(mgr.call_tool(_fn("image_recognition", {"image_url": ""}), "u1"))
    assert "không được rỗng" in result


def test_call_image_recognition_success():
    mgr, sub = make_manager()
    result = _await(mgr.call_tool(_fn("image_recognition", {"image_url": "u", "question": "what"}), "u1"))
    assert result == "cat"
    sub.vision.run_image_recognition.assert_awaited_once_with("u", "what")


def test_call_manage_role_missing_args():
    mgr, _ = make_manager()
    result = _await(mgr.call_tool(_fn("manage_user_role", {"target_user_id": "1"}), "u1"))
    assert "Thiếu tham số" in result


def test_call_manage_role_no_db():
    mgr, sub = make_manager()
    mgr.db_repo = None
    result = _await(
        mgr.call_tool(_fn("manage_user_role", {"target_user_id": "2", "action": "add", "role": "admin"}), "u1")
    )
    assert "sẵn sàng" in result


def test_call_manage_role_non_admin():
    mgr, sub = make_manager()
    result = _await(
        mgr.call_tool(_fn("manage_user_role", {"target_user_id": "2", "action": "add", "role": "admin"}), "u1")
    )
    assert "không phải Admin" in result


def test_call_manage_role_add_moderator():
    mgr, sub = make_manager()
    sub.db_repo.is_admin_user = AsyncMock(return_value=True)
    result = _await(
        mgr.call_tool(_fn("manage_user_role", {"target_user_id": "2", "action": "add", "role": "moderator"}), "u1")
    )
    assert "Moderator" in result
    sub.db_repo.add_moderator_user.assert_awaited_once_with("2")
    assert "2" in mgr.pop_allowed_mentions("u1")


def test_call_manage_role_remove_static_admin():
    mgr, sub = make_manager()
    sub.db_repo.is_admin_user = AsyncMock(return_value=True)
    # make config.ADMIN_USER_IDS contain target
    import src.tools.manager as mgr_mod

    old = mgr_mod.config.ADMIN_USER_IDS
    mgr_mod.config.ADMIN_USER_IDS = ["2"]
    try:
        result = _await(
            mgr.call_tool(_fn("manage_user_role", {"target_user_id": "2", "action": "remove", "role": "admin"}), "u1")
        )
        assert "gốc cấu hình" in result
    finally:
        mgr_mod.config.ADMIN_USER_IDS = old


def test_call_known_tool_returns_error():
    mgr, _ = make_manager()
    result = _await(mgr.call_tool(_fn("does_not_exist"), "u1"))
    assert "không tồn tại" in result


def test_manage_role_add_admin():
    mgr, sub = make_manager()
    sub.db_repo.is_admin_user = AsyncMock(return_value=True)
    res = _await(mgr.call_tool(_fn("manage_user_role", {"target_user_id": "2", "action": "add", "role": "admin"}), "u1"))
    assert "Admin" in res
    sub.db_repo.add_admin_user.assert_awaited_once_with("2")


def test_manage_role_add_premium():
    mgr, sub = make_manager()
    sub.db_repo.is_admin_user = AsyncMock(return_value=True)
    res = _await(mgr.call_tool(_fn("manage_user_role", {"target_user_id": "2", "action": "add", "role": "premium"}), "u1"))
    assert "Premium" in res
    sub.db_repo.add_premium_user.assert_awaited_once_with("2")


def test_manage_role_remove_moderator():
    mgr, sub = make_manager()
    sub.db_repo.is_admin_user = AsyncMock(return_value=True)
    res = _await(mgr.call_tool(_fn("manage_user_role", {"target_user_id": "2", "action": "remove", "role": "moderator"}), "u1"))
    assert "Đã hạ chức" in res
    sub.db_repo.remove_moderator_user.assert_awaited_once_with("2")


def test_manage_role_remove_admin():
    mgr, sub = make_manager()
    sub.db_repo.is_admin_user = AsyncMock(return_value=True)
    res = _await(mgr.call_tool(_fn("manage_user_role", {"target_user_id": "2", "action": "remove", "role": "admin"}), "u1"))
    assert "Đã hạ chức" in res
    sub.db_repo.remove_admin_user.assert_awaited_once_with("2")


def test_manage_role_remove_premium():
    mgr, sub = make_manager()
    sub.db_repo.is_admin_user = AsyncMock(return_value=True)
    res = _await(mgr.call_tool(_fn("manage_user_role", {"target_user_id": "2", "action": "remove", "role": "premium"}), "u1"))
    assert "Đã hủy Premium" in res
    sub.db_repo.remove_premium_user.assert_awaited_once_with("2")


def test_manage_role_invalid_action():
    mgr, sub = make_manager()
    sub.db_repo.is_admin_user = AsyncMock(return_value=True)
    res = _await(mgr.call_tool(_fn("manage_user_role", {"target_user_id": "2", "action": "invalid", "role": "unknown"}), "u1"))
    assert "không hợp lệ" in res
