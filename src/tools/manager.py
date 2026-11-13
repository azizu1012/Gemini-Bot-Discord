"""ToolsManager coordinator for all AI tool definitions and execution."""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from src.core.config import Config, config, logger
from src.tools.search.engine import SearchEngine
from src.tools.builtin.calculator import CalculatorService
from src.tools.builtin.weather import WeatherService
from src.tools.builtin.vision import VisionTool
from src.tools.builtin.declarations import get_gemini_tools


class ToolsManager:
    """Manages tool declarations, configuration, and execution dispatching."""

    def __init__(
        self,
        note_mgr=None,
        db_repo=None,
        search_subtask_client=None,
        enable_search_subtasks: Optional[bool] = None,
        gateway=None,
    ):
        self.logger = logger
        self.note_mgr = note_mgr
        self.db_repo = db_repo
        self.search_subtask_client = search_subtask_client
        self.gateway = gateway
        self._allowed_mentions: Dict[str, set] = {}

        if enable_search_subtasks is None:
            self.search_subtasks_enabled = self._load_search_subtasks_enabled()
        else:
            self.search_subtasks_enabled = bool(enable_search_subtasks)

        self.search_subtask_timeout_seconds = self._load_search_subtask_timeout_seconds()

        # Initialize sub-tools
        self.calculator = CalculatorService(logger_override=self.logger)
        self.weather = WeatherService(logger_override=self.logger)
        self.vision = VisionTool(gateway=self.gateway, logger_override=self.logger)
        self.search_engine = SearchEngine(
            logger_override=self.logger,
            search_web_mode=self._load_search_web_mode(),
            search_grounded_top_links=self._load_search_grounded_top_links(),
            search_top_results_limit=self._load_search_top_results_limit(),
            deep_read_top_links=self._load_deep_read_top_links(),
            deep_read_max_chars=self._load_deep_read_max_chars(),
            search_semantic_cache_enabled=self._load_search_semantic_cache_enabled(),
            search_general_cache_ttl_seconds=self._load_search_general_cache_ttl_seconds(),
            search_time_sensitive_cache_ttl_seconds=self._load_search_time_sensitive_cache_ttl_seconds(),
            search_failed_query_cooldown_seconds=self._load_search_failed_query_cooldown_seconds(),
            search_empty_evidence_cache_ttl_seconds=self._load_search_empty_evidence_cache_ttl_seconds(),
            fallback_provider_limit=self._load_fallback_provider_limit(),
            intent_batch_size=self._load_intent_batch_size(),
            min_quality_sources=self._load_min_quality_sources(),
            time_sensitive_min_quality_sources=self._load_time_sensitive_min_quality_sources(),
            exa_use_autoprompt=self._load_exa_autoprompt(),
            google_search_streams=self._load_google_search_streams(),
        )

    # ── Config loaders ─────────────────────────────────────

    def _load_google_search_streams(self) -> int:
        if Config._get_str("SEARCH_PARALLEL_STREAMS"):
            return Config._get_int("SEARCH_PARALLEL_STREAMS", 1, min_value=1, max_value=2)
        if Config._get_str("GOOGLE_SEARCH_STREAMS"):
            self.logger.warning(
                "GOOGLE_SEARCH_STREAMS đã đổi tên thành SEARCH_PARALLEL_STREAMS; "
                "biến cũ vẫn được đọc trong bản này."
            )
            return Config._get_int("GOOGLE_SEARCH_STREAMS", 1, min_value=1, max_value=2)
        return 1

    def _load_fallback_provider_limit(self) -> int:
        return Config._get_int("SEARCH_FALLBACK_PROVIDER_LIMIT", 2, min_value=1, max_value=4)

    def _load_intent_batch_size(self) -> int:
        return Config._get_int("SEARCH_INTENT_BATCH_SIZE", 3, min_value=1, max_value=5)

    def _load_search_web_mode(self) -> str:
        raw = Config._get_str("SEARCH_WEB_MODE", "grounded").lower()
        return raw if raw in {"grounded", "summary", "snippet", "links"} else "grounded"

    def _load_search_grounded_top_links(self) -> int:
        return Config._get_int("SEARCH_GROUNDED_TOP_LINKS", 3, min_value=1, max_value=8)

    def _load_search_top_results_limit(self) -> int:
        return Config._get_int("SEARCH_TOP_RESULTS_LIMIT", 5, min_value=1, max_value=10)

    def _load_min_quality_sources(self) -> int:
        return Config._get_int("SEARCH_MIN_QUALITY_SOURCES", 1, min_value=1, max_value=5)

    def _load_time_sensitive_min_quality_sources(self) -> int:
        return Config._get_int("SEARCH_TIME_SENSITIVE_MIN_QUALITY_SOURCES", 2, min_value=1, max_value=6)

    def _load_search_subtasks_enabled(self) -> bool:
        return Config._get_bool("SEARCH_SUBTASKS_ENABLED", False)

    def _load_search_subtask_timeout_seconds(self) -> int:
        return Config._get_int("SEARCH_SUBTASK_TIMEOUT_SEC", 15, min_value=3, max_value=60)

    def _load_deep_read_top_links(self) -> int:
        return Config._get_int("SEARCH_DEEP_READ_TOP_LINKS", 2, min_value=0, max_value=5)

    def _load_deep_read_max_chars(self) -> int:
        return Config._get_int("SEARCH_DEEP_READ_MAX_CHARS", 1800, min_value=400, max_value=8000)

    def _load_exa_autoprompt(self) -> bool:
        return Config._get_bool("SEARCH_EXA_AUTOPROMPT", False)

    def _load_search_semantic_cache_enabled(self) -> bool:
        return Config._get_bool("SEARCH_SEMANTIC_CACHE_ENABLED", True)

    def _load_search_general_cache_ttl_seconds(self) -> int:
        return Config._get_int("SEARCH_GENERAL_CACHE_TTL_SEC", 21600, min_value=60, max_value=86400 * 7)

    def _load_search_time_sensitive_cache_ttl_seconds(self) -> int:
        return Config._get_int("SEARCH_TIME_SENSITIVE_CACHE_TTL_SEC", 1800, min_value=30, max_value=86400)

    def _load_search_failed_query_cooldown_seconds(self) -> int:
        return Config._get_int("SEARCH_FAILED_QUERY_COOLDOWN_SEC", 15, min_value=0, max_value=300)

    def _load_search_empty_evidence_cache_ttl_seconds(self) -> int:
        return Config._get_int("SEARCH_EMPTY_EVIDENCE_CACHE_TTL_SEC", 600, min_value=60, max_value=86400)

    # ── Mention tracking ───────────────────────────────────

    def _record_allowed_mention(self, caller_user_id: str, target_user_id: str) -> None:
        caller_id = str(caller_user_id or "").strip()
        target_id = str(target_user_id or "").strip()
        if not caller_id or not target_id:
            return
        bucket = self._allowed_mentions.setdefault(caller_id, set())
        bucket.add(target_id)

    def pop_allowed_mentions(self, caller_user_id: str) -> List[str]:
        caller_id = str(caller_user_id or "").strip()
        if not caller_id:
            return []
        return sorted(self._allowed_mentions.pop(caller_id, set()))

    # ── Tool definitions ───────────────────────────────────

    def get_all_tools(self, is_admin: bool = False):
        return get_gemini_tools(is_admin=is_admin)

    # ── Vision delegation ──────────────────────────────────

    async def run_image_recognition(self, image_url: str, question: str) -> str:
        """Ủy quyền cho VisionTool để chỉ tồn tại một luồng tải/nhận diện ảnh."""
        return await self.vision.run_image_recognition(image_url, question)

    # ── Search delegation ──────────────────────────────────

    async def run_search_apis(self, query: str, mode: str = "general"):
        return await self.search_engine.run_search_apis(query, mode)

    def _split_multi_intents(self, query: str):
        return self.search_engine._split_multi_intents(query)

    # ── Tool dispatch ──────────────────────────────────────

    async def call_tool(self, function_call, user_id: str):
        name = function_call.name
        args = dict(function_call.args) if function_call.args else {}
        self.logger.info(f"TOOL CALLED: {name} | Args: {args} | User: {user_id}")

        try:
            if name == "web_search":
                query = str(args.get("query") or "").strip()
                if not query:
                    return "Lỗi: 'query' không được rỗng cho web_search."
                result = ""
                if self.search_subtasks_enabled and self.search_subtask_client:
                    intents = self._split_multi_intents(query)
                    num_intents = len(intents) if intents else 1
                    dynamic_timeout = max(self.search_subtask_timeout_seconds, num_intents * 8)
                    self.logger.info(f"Dynamic timeout calculated: {dynamic_timeout}s for {num_intents} intents.")
                    try:
                        subtask_result = await self.search_subtask_client.request_search(
                            user_id=user_id,
                            query=query,
                            mode="general",
                            timeout=dynamic_timeout,
                        )
                    except asyncio.TimeoutError:
                        # The subtask timed out and may still be in-flight. Treat the
                        # inline fallback as the single execution path and ignore any
                        # late-arriving subtask result so the query is never executed
                        # twice. The client already discarded its pending future.
                        self.logger.warning(
                            f"Search subtask timed out after {dynamic_timeout}s; "
                            "running inline fallback as the single execution path."
                        )
                        subtask_result = None
                    if subtask_result:
                        result = subtask_result

                if not result:
                    result = await self.run_search_apis(query, "general")
                try:
                    if self.db_repo is not None:
                        await self.db_repo.log_web_search(user_id, query, str(result)[:2000])
                except Exception as e:
                    self.logger.error(f"Error logging web search to DB: {e}")
                return result

            elif name == "get_weather":
                city = str(args.get("city") or "").strip() or None
                return await asyncio.to_thread(self.weather.run_weather, city)

            elif name == "calculate":
                eq = str(args.get("equation") or "")
                return await asyncio.to_thread(self.calculator.run_calculator, eq)

            elif name == "save_note":
                content = str(args.get("note_content") or "").strip()
                source = str(args.get("source") or "chat_inference").strip() or "chat_inference"
                if not content:
                    return "Lỗi: 'note_content' không được rỗng."
                if not self.note_mgr:
                    return "Lỗi hệ thống: memory manager chưa sẵn sàng."
                return await self.note_mgr.save_note_to_db(user_id, content, source)

            elif name == "retrieve_notes":
                query = str(args.get("query") or "").strip()
                if not self.note_mgr:
                    return "Lỗi hệ thống: memory manager chưa sẵn sàng."
                return await self.note_mgr.retrieve_notes_from_db(user_id, query)

            elif name == "delete_note":
                note_id = str(args.get("note_id") or "").strip()
                if not note_id:
                    return "Lỗi: 'note_id' không được rỗng."
                if not self.note_mgr:
                    return "Lỗi hệ thống: memory manager chưa sẵn sàng."
                return await self.note_mgr.delete_note_from_db(user_id, note_id)

            elif name == "image_recognition":
                image_url = str(args.get("image_url") or "").strip()
                question = str(args.get("question") or "").strip()
                if not image_url:
                    return "Lỗi: 'image_url' không được rỗng cho image_recognition."
                return await self.run_image_recognition(image_url, question)

            elif name == "manage_user_role":
                target_user_id = str(args.get("target_user_id") or "").strip()
                action = str(args.get("action") or "").strip()
                role = str(args.get("role") or "").strip()
                if not target_user_id or not action or not role:
                    return "Lỗi: Thiếu tham số bắt buộc 'target_user_id', 'action' hoặc 'role'."
                if self.db_repo is None:
                    return "Lỗi hệ thống: Kết nối cơ sở dữ liệu chưa sẵn sàng."

                is_caller_admin = (user_id in config.ADMIN_USER_IDS) or (await self.db_repo.is_admin_user(user_id))
                if not is_caller_admin:
                    return "❌ Lỗi: Bạn không phải Admin hệ thống, không có quyền thăng chức hay hạ chức người khác!"

                if action == "add":
                    if role == "moderator":
                        await self.db_repo.add_moderator_user(target_user_id)
                        self._record_allowed_mention(user_id, target_user_id)
                        return f"🎉 Thăng chức thành công người dùng <@{target_user_id}> làm Moderator!"
                    elif role == "admin":
                        await self.db_repo.add_admin_user(target_user_id)
                        return f"👑 Thăng chức thành công người dùng {target_user_id} làm Admin!"
                    elif role == "premium":
                        await self.db_repo.add_premium_user(target_user_id)
                        return f"✨ Kích hoạt Premium thành công cho người dùng {target_user_id}!"
                elif action == "remove":
                    if role == "moderator":
                        await self.db_repo.remove_moderator_user(target_user_id)
                        return f"✅ Đã hạ chức người dùng {target_user_id} khỏi vai trò Moderator."
                    elif role == "admin":
                        if target_user_id in config.ADMIN_USER_IDS:
                            return "❌ Lỗi: Không thể hạ chức Admin gốc cấu hình tĩnh trong .env!"
                        await self.db_repo.remove_admin_user(target_user_id)
                        return f"✅ Đã hạ chức người dùng {target_user_id} khỏi vai trò Admin."
                    elif role == "premium":
                        await self.db_repo.remove_premium_user(target_user_id)
                        return f"✅ Đã hủy Premium của người dùng {target_user_id}."
                return "Lỗi: Hành động hoặc vai trò không hợp lệ."

            else:
                return "Tool không tồn tại!"

        except Exception as e:
            self.logger.error(f"Tool {name} error: {e}")
            return "Lỗi khi chạy tool. Vui lòng thử lại."
