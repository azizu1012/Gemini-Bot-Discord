import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set

import requests
from google import genai
from google.genai import types as genai_types

from src.core.config import logger, GEMINI_API_KEYS
import src.core.config as config
from src.core.api_router import get_api_router
from src.core.api_config import VISION_MODEL_ALIAS
from src.tools.constants import (
    MAX_CACHE_SIZE,
    MAX_FILE_SIZE_BYTES,
    MAX_TEXT_LENGTH,
)
from src.tools.helpers import (
    HtmlParser,
    DateParser,
    TextProcessor,
    UrlUtils,
    CityNameHelper,
)
from src.tools.search_engine import SearchEngine
from src.tools.weather_service import WeatherService
from src.tools.calculator_service import CalculatorService


class ToolsManager:
    """Orchestrator for all AI tools and external API integrations."""

    CACHE_TTL_SECONDS = 3600
    MAX_CACHE_SIZE = 1000
    MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024
    MAX_TEXT_LENGTH = 10000
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
    SERVICE_ACCOUNT_FILE = 'credentials.json'

    def __init__(self, note_mgr=None, db_repo=None, search_subtask_client=None, enable_search_subtasks: Optional[bool] = None):
        self.logger = logger
        self.api_router = get_api_router()
        self.note_mgr = note_mgr
        self.db_repo = db_repo
        self.search_subtask_client = search_subtask_client
        if enable_search_subtasks is None:
            self.search_subtasks_enabled = os.getenv("SEARCH_SUBTASKS_ENABLED", "false").lower() == "true"
        else:
            self.search_subtasks_enabled = bool(enable_search_subtasks)
        self.search_subtask_timeout_seconds = int(os.getenv("SEARCH_SUBTASK_TIMEOUT_SEC", "18"))
        self._allowed_mentions: Dict[str, Set[str]] = {}
        self.image_recognition_cache = {}
        self.weather = WeatherService()
        self.calculator = CalculatorService()
        self.search_lock = asyncio.Lock()
        self._gemini_key_cursor = 0
        self._invalid_tool_keys = set()
        self._tool_key_cooldowns = {}

        self.search_engine = SearchEngine(
            logger_override=logger,
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

        if GEMINI_API_KEYS:
            self.logger.info(
                f"Search/image tools ready: provider=duckduckgo streams={self.search_engine.google_search_streams} "
                f"fallback_limit={self.search_engine.fallback_provider_limit} batch={self.search_engine.intent_batch_size} "
                f"web_mode={self.search_engine.search_web_mode} grounded_links={self.search_engine.search_grounded_top_links} "
                f"top_results_limit={self.search_engine.search_top_results_limit} "
                f"quality_sources={self.search_engine.min_quality_sources}/{self.search_engine.time_sensitive_min_quality_sources} "
                f"deep_read_top_links={self.search_engine.deep_read_top_links} "
                f"semantic_cache={self.search_engine.search_semantic_cache_enabled} "
                f"general_ttl={self.search_engine.search_general_cache_ttl_seconds}s "
                f"time_ttl={self.search_engine.search_time_sensitive_cache_ttl_seconds}s "
                f"cooldown={self.search_engine.search_failed_query_cooldown_seconds}s"
            )
        else:
            self.logger.warning("Không có Gemini API key cho tools; web_search/image_recognition sẽ failback.")

    # ── Config loaders ─────────────────────────────────────

    def _load_google_search_streams(self) -> int:
        raw = os.getenv("GOOGLE_SEARCH_STREAMS", "1").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 1
        return max(1, min(2, value))

    def _load_fallback_provider_limit(self) -> int:
        raw = os.getenv("SEARCH_FALLBACK_PROVIDER_LIMIT", "2").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 2
        return max(1, min(3, value))

    def _load_intent_batch_size(self) -> int:
        raw = os.getenv("SEARCH_INTENT_BATCH_MAX", "3").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 3
        return max(2, min(3, value))

    def _load_search_web_mode(self) -> str:
        mode = (os.getenv("SEARCH_WEB_MODE", "grounded") or "grounded").strip().lower()
        if mode not in {"grounded", "fast"}:
            return "grounded"
        return mode

    def _load_search_grounded_top_links(self) -> int:
        raw = os.getenv("SEARCH_GROUNDED_TOP_LINKS", "3").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 3
        return max(2, min(5, value))

    def _load_search_top_results_limit(self) -> int:
        raw = os.getenv("SEARCH_TOP_RESULTS_LIMIT", "5").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 5
        return max(3, min(5, value))

    def _load_min_quality_sources(self) -> int:
        raw = os.getenv("SEARCH_MIN_QUALITY_SOURCES", os.getenv("SEARCH_MIN_REPUTABLE_SOURCES", "1")).strip()
        try:
            value = int(raw)
        except ValueError:
            value = 1
        return max(1, min(5, value))

    def _load_time_sensitive_min_quality_sources(self) -> int:
        raw = os.getenv(
            "SEARCH_TIME_SENSITIVE_MIN_QUALITY_SOURCES",
            os.getenv("SEARCH_TIME_SENSITIVE_MIN_REPUTABLE_SOURCES", "2"),
        ).strip()
        try:
            value = int(raw)
        except ValueError:
            value = 2
        return max(max(1, self._load_min_quality_sources()), min(6, value))

    def _load_deep_read_top_links(self) -> int:
        raw = os.getenv("SEARCH_DEEP_READ_TOP_LINKS", "2").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 2
        return max(1, min(5, value))

    def _load_deep_read_max_chars(self) -> int:
        raw = os.getenv("SEARCH_DEEP_READ_MAX_CHARS", "1800").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 1800
        return max(600, min(5000, value))

    def _load_exa_autoprompt(self) -> bool:
        return (os.getenv("SEARCH_EXA_AUTOPROMPT", "false") or "false").strip().lower() == "true"

    def _load_search_semantic_cache_enabled(self) -> bool:
        return (os.getenv("SEARCH_SEMANTIC_CACHE_ENABLED", "true") or "true").strip().lower() in {"1", "true", "yes", "on"}

    def _load_search_general_cache_ttl_seconds(self) -> int:
        raw = os.getenv("SEARCH_GENERAL_CACHE_TTL_SEC", "21600").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 21600
        return max(300, min(43200, value))

    def _load_search_time_sensitive_cache_ttl_seconds(self) -> int:
        raw = os.getenv("SEARCH_TIME_SENSITIVE_CACHE_TTL_SEC", "1800").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 1800
        return max(120, min(self._load_search_general_cache_ttl_seconds(), value))

    def _load_search_failed_query_cooldown_seconds(self) -> int:
        raw = os.getenv("SEARCH_FAILED_QUERY_COOLDOWN_SEC", "15").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 15
        return max(0, min(120, value))

    def _load_search_empty_evidence_cache_ttl_seconds(self) -> int:
        raw = os.getenv("SEARCH_EMPTY_EVIDENCE_CACHE_TTL_SEC", "600").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 600
        return max(60, min(7200, value))

    # ── Gemini key rotation ────────────────────────────────

    def _next_gemini_api_key(self) -> str:
        if not GEMINI_API_KEYS:
            return ""
        now = time.time()
        total = len(GEMINI_API_KEYS)
        for _ in range(total):
            key = GEMINI_API_KEYS[self._gemini_key_cursor]
            self._gemini_key_cursor = (self._gemini_key_cursor + 1) % total
            if key in self._invalid_tool_keys:
                continue
            if key in self._tool_key_cooldowns and now < self._tool_key_cooldowns[key]:
                continue
            return key
        for _ in range(total):
            key = GEMINI_API_KEYS[self._gemini_key_cursor]
            self._gemini_key_cursor = (self._gemini_key_cursor + 1) % total
            if key in self._invalid_tool_keys:
                continue
            return key
        return GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""

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

    # ── Vision alias ───────────────────────────────────────

    async def _resolve_router_model_alias_for_vision(self) -> str:
        return VISION_MODEL_ALIAS

    # ── Tool definitions (Gemini) ─────────────────────────

    def get_all_tools(self, is_admin: bool = False):
        tools_list = [
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name="web_search",
                    description=(
                        "Tìm kiếm thông tin cập nhật, sự kiện mới, tin tức, "
                        "dữ liệu thực tế không có trong kiến thức của AI, "
                        "hoặc để xác minh thông tin. KHÔNG DÙNG cho các tác vụ tính toán, "
                        "dịch thuật, tóm tắt, viết lại, hoặc các câu hỏi không cần dữ liệu mới.\n\n"
                        "QUAN TRỌNG: Nếu người dùng hỏi nhiều chủ đề, hãy gọi web_search "
                        "NHIỀU LẦN — mỗi lần một chủ đề riêng, KHÔNG gộp chung vào một query.\n"
                        "LUÔN dùng ngày đầy đủ từ `Current time:` (DD Month YYYY) trong query "
                        "cho tin tức hoặc thông tin thời gian thực."
                    ),
                    parameters={  # type: ignore[arg-type]
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Truy vấn tìm kiếm cụ thể, KHÔNG gộp nhiều chủ đề. "
                                    "Dùng đúng ngày từ `Current time:` (DD Month YYYY) cho tin tức."
                            }
                        },
                        "required": ["query"]
                    }
                )
            ]),
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name="get_weather",
                    description="Lấy thông tin thời tiết hiện tại cho một thành phố cụ thể.",
                    parameters={  # type: ignore[arg-type]
                        "type": "object",
                        "properties": {"city": {"type": "string", "description": "Tên thành phố, ví dụ: 'Hanoi', 'Tokyo'."}},
                        "required": ["city"]
                    }
                )
            ]),
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name="calculate",
                    description=(
                        "Giải các bài toán số học hoặc biểu thức phức tạp (đại số, lượng giác, logarit). "
                        "Hỗ trợ đạo hàm/tích phân/rút gọn bằng cú pháp SymPy (vd: diff(x**3*exp(sin(x)), x))."
                    ),
                    parameters={  # type: ignore[arg-type]
                        "type": "object",
                        "properties": {"equation": {"type": "string", "description": "Biểu thức toán học dưới dạng string, ví dụ: 'sin(pi/2) + 2*x'."}},
                        "required": ["equation"]
                    }
                )
            ]),
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name="save_note",
                    description=(
                        "Lưu một mẩu thông tin, sở thích, sự thật, hoặc nội dung quan trọng về người dùng để bạn có thể truy cập lại sau. "
                        "Dùng khi user chia sẻ thông tin cá nhân có giá trị lâu dài (ví dụ: 'tôi thích chơi game X', 'cấu hình máy của tôi là Y')."
                    ),
                    parameters={  # type: ignore[arg-type]
                        "type": "object",
                        "properties": {
                            "note_content": {"type": "string", "description": "Nội dung thông tin cần ghi nhớ."},
                            "source": {"type": "string", "description": "Ngữ cảnh hoặc nguồn của thông tin, ví dụ: 'chat_inference', 'user_request'."}
                        },
                        "required": ["note_content", "source"]
                    }
                )
            ]),
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name="retrieve_notes",
                    description=(
                        "Truy xuất thông tin đã lưu trữ về người dùng, kiến thức cá nhân, "
                        "dữ liệu lịch sử, hoặc các sự kiện/thông tin quan trọng mà AI đã được yêu cầu ghi nhớ. "
                        "PHẢI LUÔN GỌI HÀM NÀY nếu câu hỏi liên quan đến kiến thức cá nhân, note, hoặc thông tin đã được ghi nhớ trước đó."
                    ),
                    parameters={  # type: ignore[arg-type]
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Từ khóa hoặc chủ đề tìm kiếm trong bộ nhớ (ví dụ: 'config', 'sở thích'). Để trống nếu muốn lấy tất cả."}
                        },
                        "required": ["query"]
                    }
                )
            ]),
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name="delete_note",
                    description=(
                        "Xóa một ghi chú/thông tin cụ thể đã lưu trữ của người dùng dựa vào note_id. "
                        "Thường sử dụng kết hợp sau khi gọi retrieve_notes để lấy chính xác note_id cần xóa."
                    ),
                    parameters={  # type: ignore[arg-type]
                        "type": "object",
                        "properties": {
                            "note_id": {"type": "string", "description": "ID của note cần xóa (UUID)."}
                        },
                        "required": ["note_id"]
                    }
                )
            ]),
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name="image_recognition",
                    description=(
                        "Nhận diện đối tượng, người nổi tiếng, nhân vật game/anime, đếm vật thể, và trích xuất văn bản (OCR) từ một hình ảnh. "
                        "Sử dụng khi người dùng tải lên một hình ảnh và hỏi các câu hỏi liên quan đến nội dung của hình ảnh đó. "
                        "Ví dụ: 'có bao nhiêu quả táo trong ảnh?', 'người này là ai?', 'đây là nhân vật gì?', 'đọc chữ trong ảnh này'."
                    ),
                    parameters={  # type: ignore[arg-type]
                        "type": "object",
                        "properties": {
                            "image_url": {"type": "string", "description": "URL công khai của hình ảnh cần nhận diện."},
                            "question": {"type": "string", "description": "Câu hỏi cụ thể của người dùng về hình ảnh (ví dụ: 'đếm số lượng', 'người này là ai?', 'đây là gì?')."}
                        },
                        "required": ["image_url", "question"]
                    }
                )
            ]),
        ]

        if is_admin:
            tools_list.append(
                genai_types.Tool(function_declarations=[
                    genai_types.FunctionDeclaration(
                        name="manage_user_role",
                        description=(
                            "Quản lý vai trò (roles) của người dùng: Thăng chức làm Moderator, Premium hoặc Admin, "
                            "hoặc hạ chức người dùng về User thông thường. Lệnh này chỉ thực hiện được khi người gọi lệnh "
                            "(tham số user_id của chat context) là Admin thực tế của bot."
                        ),
                        parameters={  # type: ignore[arg-type]
                            "type": "object",
                            "properties": {
                                "target_user_id": {"type": "string", "description": "ID Discord số của người dùng cần thay đổi vai trò."},
                                "action": {"type": "string", "description": "Hành động: 'add' (thăng chức/thêm) hoặc 'remove' (hạ chức/xóa).", "enum": ["add", "remove"]},
                                "role": {"type": "string", "description": "Vai trò cần thiết lập: 'moderator', 'premium', hoặc 'admin'.", "enum": ["moderator", "premium", "admin"]}
                            },
                            "required": ["target_user_id", "action", "role"]
                        }
                    )
                ])
            )

        return tools_list

    # ── Weather / Calculator delegated to services ──────────

    # ── Image recognition ─────────────────────────────────

    def _get_image_recognition_cache(self, image_url: str, question: str):
        key = f"{image_url}|{question[:50]}"
        item = self.image_recognition_cache.get(key)
        if item:
            if datetime.now() - item["timestamp"] < timedelta(hours=1):
                return item["data"]
            del self.image_recognition_cache[key]
        return None

    def _set_image_recognition_cache(self, image_url: str, question: str, data: str):
        key = f"{image_url}|{question[:50]}"
        if len(self.image_recognition_cache) >= MAX_CACHE_SIZE:
            oldest = min(self.image_recognition_cache, key=lambda k: self.image_recognition_cache[k]["timestamp"])
            del self.image_recognition_cache[oldest]
        self.image_recognition_cache[key] = {"data": data, "timestamp": datetime.now()}

    def _guess_mime_type(self, image_url: str) -> str:
        return CityNameHelper.guess_mime_type(image_url)

    async def run_image_recognition(self, image_url: str, question: str):
        cached = self._get_image_recognition_cache(image_url, question)
        if cached:
            self.logger.info(f"Image recognition result from cache for URL: {image_url}, Question: {question[:30]}...")
            return cached

        start_ts = datetime.now().timestamp()
        vision_alias = await self._resolve_router_model_alias_for_vision()
        vision_model_id = self.api_router.get_model_id(vision_alias)
        attempt_budget = max(1, min(5, len(GEMINI_API_KEYS) if GEMINI_API_KEYS else 1))
        last_error = ""
        try:
            image_bytes = await asyncio.to_thread(lambda: requests.get(image_url, timeout=12).content)
            if not image_bytes:
                return "Lỗi: Không tải được dữ liệu hình ảnh từ URL."
            if len(image_bytes) > MAX_FILE_SIZE_BYTES:
                return "Lỗi: Ảnh vượt quá giới hạn 20MB cho inline image understanding."

            mime_type = self._guess_mime_type(image_url)
            image_part = genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

            quota_ok = await self.api_router.acquire_gemini_quota(question, 2000, model_alias=vision_alias, image_count=1)
            if not quota_ok:
                return "⚠️ Hệ thống đang quá tải (vượt giới hạn truy vấn ảnh), vui lòng thử lại sau vài giây."

            for attempt in range(1, attempt_budget + 1):
                reservation = await self.api_router.get_next_key_for_model_reservation(vision_alias)
                api_key = (reservation or {}).get("key") or self._next_gemini_api_key()
                if not api_key:
                    break

                key_alias = f"...{api_key[-4:]}" if len(api_key) >= 4 else "<short>"
                try:
                    if reservation:
                        self.api_router.commit_key_usage(reservation)

                    client = genai.Client(api_key=api_key)
                    response = await asyncio.to_thread(
                        client.models.generate_content,
                        model=vision_model_id,
                        contents=[image_part, question],
                    )
                    final_result = (getattr(response, "text", "") or "").strip()
                    if not final_result:
                        final_result = "Không thể nhận diện nội dung ảnh rõ ràng từ truy vấn này."

                    self._invalid_tool_keys.discard(api_key)
                    self._tool_key_cooldowns.pop(api_key, None)
                    self._set_image_recognition_cache(image_url, question, final_result)
                    return final_result
                except Exception as attempt_error:
                    error_text = str(attempt_error)
                    lowered = error_text.lower()
                    last_error = error_text

                    if any(token in lowered for token in ["api key not found", "api_key_invalid", "invalid api key", "permission denied"]):
                        self._invalid_tool_keys.add(api_key)
                        if reservation:
                            self.api_router.mark_key_exhausted(
                                api_key,
                                reservation.get("model_alias", vision_alias),
                                pool=reservation.get("pool", "main"),
                                counter_key=reservation.get("counter_key"),
                            )
                    elif any(token in lowered for token in ["429", "resource_exhausted", "quota", "rate limit"]):
                        self._tool_key_cooldowns[api_key] = time.time() + 60
                        if reservation:
                            self.api_router.mark_key_cooldown(
                                api_key,
                                reservation.get("model_alias", vision_alias),
                                60,
                                pool=reservation.get("pool", "main"),
                                counter_key=reservation.get("counter_key"),
                            )

                    if attempt >= attempt_budget:
                        raise
                    continue
        except Exception as e:
            error_text = str(e)
            self.logger.warning(
                f"AB_METRIC image_tool success=0 "
                f"attempts={attempt_budget} model={vision_model_id} alias={vision_alias} "
                f"error={(last_error or error_text)[:180]}"
            )
            return f"Đã xảy ra lỗi khi xử lý hình ảnh bằng Gemini: {last_error or e}"

    # ── Search delegation ──────────────────────────────────

    async def run_search_apis(self, query: str, mode: str = "general"):
        return await self.search_engine.run_search_apis(query, mode)

    # ── Call tool (dispatch) ───────────────────────────────

    def _split_multi_intents(self, query: str):
        return self.search_engine._split_multi_intents(query)

    async def call_tool(self, function_call, user_id: str):
        name = function_call.name
        args = dict(function_call.args) if function_call.args else {}
        self.logger.info(f"TOOL CALLED: {name} | Args: {args} | User: {user_id}")

        try:
            if name == "web_search":
                query = args.get("query", "")
                result = ""
                if self.search_subtasks_enabled and self.search_subtask_client:
                    intents = self._split_multi_intents(query)
                    num_intents = len(intents) if intents else 1
                    dynamic_timeout = max(self.search_subtask_timeout_seconds, num_intents * 8)
                    self.logger.info(f"Dynamic timeout calculated: {dynamic_timeout}s for {num_intents} intents.")
                    subtask_result = await self.search_subtask_client.request_search(
                        user_id=user_id,
                        query=query,
                        mode="general",
                        timeout=dynamic_timeout,
                    )
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
                city = args.get("city", "Ho Chi Minh City")
                data = await self.weather.get_weather(city)
                return json.dumps(data, ensure_ascii=False, indent=2)

            elif name == "calculate":
                eq = args.get("equation", "")
                return await asyncio.to_thread(self.calculator.run_calculator, eq)

            elif name == "save_note":
                content = (args.get("note_content") or "").strip()
                source = (args.get("source") or "chat_inference").strip() or "chat_inference"
                if not content:
                    return "Lỗi: 'note_content' không được rỗng."
                if not self.note_mgr:
                    return "Lỗi hệ thống: memory manager chưa sẵn sàng."
                return await self.note_mgr.save_note_to_db(user_id, content, source)

            elif name == "retrieve_notes":
                query = (args.get("query") or "").strip()
                if not self.note_mgr:
                    return "Lỗi hệ thống: memory manager chưa sẵn sàng."
                return await self.note_mgr.retrieve_notes_from_db(user_id, query)

            elif name == "delete_note":
                note_id = (args.get("note_id") or "").strip()
                if not note_id:
                    return "Lỗi: 'note_id' không được rỗng."
                if not self.note_mgr:
                    return "Lỗi hệ thống: memory manager chưa sẵn sàng."
                return await self.note_mgr.delete_note_from_db(user_id, note_id)

            elif name == "image_recognition":
                image_url = args.get("image_url")
                question = args.get("question")
                if not image_url or not question:
                    return "Lỗi: 'image_url' và 'question' không được rỗng cho image_recognition."
                return await self.run_image_recognition(image_url, question)

            elif name == "manage_user_role":
                target_user_id = (args.get("target_user_id") or "").strip()
                action = (args.get("action") or "").strip()
                role = (args.get("role") or "").strip()
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
            return f"Lỗi tool: {str(e)}"
