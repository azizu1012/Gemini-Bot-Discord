"""Đọc cấu hình endpoint + model slots từ PostgreSQL (cache TTL), mã hóa key Fernet.

Quy ước lưu key:
- `fernet:<token>`: mã hóa bằng DONATE_ENCRYPTION_KEY (Fernet).
- `plain:<raw>`: khi DONATE_ENCRYPTION_KEY trống (log warning rõ ràng).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet

from src.core.config import get_config, logger
from src.core.llm.base import SlotModel

DEFAULT_BASE_URLS: Dict[str, str] = {
    "genai": "https://generativelanguage.googleapis.com",
    "openai": "https://api.openai.com/v1",
}
SDK_ORDER = ("genai", "openai")

_ENCRYPT_PREFIX = "fernet:"
_PLAIN_PREFIX = "plain:"


def normalize_base_url(sdk: str, url: str) -> str:
    """Chuẩn hóa base URL người dùng nhập tay.

    Các lỗi thường gặp khi cấu hình endpoint qua Discord modal:
    - Dán thiếu scheme: ``127.0.0.1:58100/v1`` → tự thêm ``http://``.
    - Dán kèm đuôi API: ``.../v1/models`` hoặc ``.../v1/chat/completions``.
    - Endpoint OpenAI-compatible chỉ nhập host, thiếu ``/v1`` → tự thêm.
    """
    raw = (url or "").strip()
    if not raw:
        return DEFAULT_BASE_URLS.get(sdk, "")

    if "://" not in raw:
        raw = f"http://{raw}"

    parts = urlsplit(raw)
    path = parts.path.rstrip("/")

    for suffix in ("/chat/completions", "/completions", "/models"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break

    if sdk == "genai":
        # google-genai tự ghép /v1beta sau base_url. Nếu base_url đã có version
        # thì SDK sẽ gọi /v1beta/v1beta/... → 404. Vì vậy bóc version ở đây.
        for version in ("/v1beta", "/v1alpha", "/v1"):
            if path.endswith(version):
                path = path[: -len(version)]
                break
    elif sdk == "openai" and path in ("", "/v1beta", "/v1alpha"):
        path = "/v1"

    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def is_valid_fernet_key(fernet_key: str) -> bool:
    if not fernet_key:
        return False
    try:
        Fernet(fernet_key.encode())
        return True
    except Exception:
        return False


def encrypt_api_key(raw: str, fernet_key: str) -> str:
    if not raw:
        return raw
    if not fernet_key:
        logger.warning("DONATE_ENCRYPTION_KEY trống — API key sẽ lưu dạng plain (khuyến nghị set biến này).")
        return _PLAIN_PREFIX + raw
    token = Fernet(fernet_key.encode()).encrypt(raw.encode())
    return _ENCRYPT_PREFIX + token.decode()


def decrypt_api_key(stored: str, fernet_key: str) -> str:
    if not stored:
        return ""
    if stored.startswith(_PLAIN_PREFIX):
        return stored[len(_PLAIN_PREFIX):]
    if stored.startswith(_ENCRYPT_PREFIX):
        token = stored[len(_ENCRYPT_PREFIX):].encode()
        return Fernet(fernet_key.encode()).decrypt(token).decode()
    # Dữ liệu cũ/không tiền tố — thử plain
    return stored


def mask_api_key(key: str) -> str:
    if not key:
        return "<chưa cấu hình>"
    if len(key) <= 4:
        return "****"
    return f"...{key[-4:]}"


def resolve_model_id(slots: Dict[str, Optional[str]], role: str) -> Optional[str]:
    slots = slots or {}
    final = slots.get("final") or None
    reasoning = slots.get("reasoning") or final
    fallback = slots.get("fallback") or reasoning or final
    table = {"reasoning": reasoning, "final": final, "fallback": fallback}
    return table.get(role)


class EndpointResolver:
    def __init__(self, *, config: Any, logger: Any, cache_ttl_seconds: float = 30.0):
        self.config = config
        self.logger = logger
        self._cache_ttl = cache_ttl_seconds
        self._db_repo = None
        self._loaded_at = 0.0
        self._endpoints: Dict[str, Dict[str, Any]] = {}
        self._slots: Dict[str, Dict[str, Optional[str]]] = {}
        self._active_sdk: Optional[str] = None
        self._lock = threading.Lock()

    def set_db_repo(self, db_repo: Any) -> None:
        self._db_repo = db_repo
        self.invalidate()

    def invalidate(self) -> None:
        self._loaded_at = 0.0

    async def _ensure_loaded(self) -> None:
        if self._db_repo is None:
            raise RuntimeError("EndpointResolver chưa được gắn DatabaseRepository (set_db_repo).")
        now = time.monotonic()
        if now - self._loaded_at < self._cache_ttl:
            return
        endpoints = await self._db_repo.get_llm_endpoints()
        active = await self._db_repo.get_active_sdk()
        slots: Dict[str, Dict[str, Optional[str]]] = {}
        for sdk in SDK_ORDER:
            slots[sdk] = await self._db_repo.get_llm_model_slots(sdk)
        with self._lock:
            self._endpoints = endpoints or {}
            self._active_sdk = active
            self._slots = slots
            self._loaded_at = time.monotonic()

    async def get_active_sdk(self) -> Optional[str]:
        await self._ensure_loaded()
        return self._active_sdk

    async def is_configured(self) -> bool:
        await self._ensure_loaded()
        sdk = self._active_sdk
        if not sdk or sdk not in self._endpoints:
            return False
        return bool(resolve_model_id(self._slots.get(sdk) or {}, "final"))

    async def get_endpoint(self, sdk: str) -> Optional[Dict[str, Any]]:
        await self._ensure_loaded()
        row = self._endpoints.get(sdk)
        if not row:
            return None
        fernet_key = getattr(self.config, "DONATE_ENCRYPTION_KEY", "") or ""
        return {
            "sdk": sdk,
            "base_url": normalize_base_url(sdk, row.get("base_url") or ""),
            "api_key": decrypt_api_key(row.get("api_key_encrypted") or "", fernet_key),
            "is_active": bool(row.get("is_active")),
        }

    async def get_slot_models(self, sdk: str) -> Dict[str, Optional[str]]:
        await self._ensure_loaded()
        return dict(self._slots.get(sdk) or {})

    async def resolve_role(self, role: str) -> Optional[SlotModel]:
        await self._ensure_loaded()
        sdk = self._active_sdk
        if not sdk or sdk not in self._endpoints:
            return None
        model_id = resolve_model_id(self._slots.get(sdk) or {}, role)
        if not model_id:
            return None
        return SlotModel(sdk=sdk, model_id=model_id, role=role)


_resolver_instance: Optional[EndpointResolver] = None
_resolver_lock = threading.Lock()


def get_endpoint_resolver() -> EndpointResolver:
    global _resolver_instance
    if _resolver_instance is None:
        with _resolver_lock:
            if _resolver_instance is None:
                _resolver_instance = EndpointResolver(config=get_config(), logger=logger)
    return _resolver_instance
