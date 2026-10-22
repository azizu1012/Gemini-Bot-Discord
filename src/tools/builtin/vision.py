"""Image recognition tool leveraging LLMGateway."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin

import aiohttp

from src.core.config import logger
from src.tools.search.url_safety import is_safe_url

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_CACHE_ENTRIES = 1000
MAX_REDIRECTS = 3
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_FALLBACK_CONTENT_TYPES = {"", "application/octet-stream"}


class VisionTool:
    """Tool for analyzing images via LLMGateway."""

    def __init__(self, gateway=None, logger_override=None):
        self.gateway = gateway
        self.logger = logger_override or logger
        self.image_recognition_cache: Dict[str, Any] = {}

    def _get_cache(self, image_url: str, question: str) -> Optional[str]:
        cache_key = f"{image_url}:{question}"
        return self.image_recognition_cache.get(cache_key)

    def _set_cache(self, image_url: str, question: str, data: str) -> None:
        cache_key = f"{image_url}:{question}"
        if len(self.image_recognition_cache) >= MAX_CACHE_ENTRIES:
            oldest_key = next(iter(self.image_recognition_cache))
            del self.image_recognition_cache[oldest_key]
        self.image_recognition_cache[cache_key] = data

    def _guess_mime_type(self, image_url: str) -> str:
        lowered = (image_url or "").lower().split("?")[0]
        if lowered.endswith(".png"):
            return "image/png"
        if lowered.endswith(".webp"):
            return "image/webp"
        if lowered.endswith(".gif"):
            return "image/gif"
        return "image/jpeg"

    async def _download_image(self, image_url: str) -> Tuple[Optional[bytes], str, Optional[str]]:
        """Tải ảnh và trả về (bytes, mime_type, error_message)."""
        target_url = image_url
        mime_type = self._guess_mime_type(image_url)

        async with aiohttp.ClientSession() as session:
            for _ in range(MAX_REDIRECTS + 1):
                safe, reason = await asyncio.to_thread(is_safe_url, target_url)
                if not safe:
                    return None, "", f"Lỗi: URL hình ảnh không hợp lệ hoặc bị chặn ({reason})."

                async with session.get(
                    target_url,
                    timeout=aiohttp.ClientTimeout(total=20),
                    allow_redirects=False,
                ) as resp:
                    if resp.status in _REDIRECT_STATUSES:
                        location = resp.headers.get("Location") or ""
                        if not location:
                            return None, "", "Lỗi: Phản hồi chuyển hướng không có Location."
                        target_url = urljoin(target_url, location)
                        continue

                    if resp.status != 200:
                        return None, "", f"Lỗi: Không thể tải hình ảnh từ URL (HTTP {resp.status})."

                    content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                    if content_type.startswith("image/"):
                        mime_type = content_type
                    elif content_type in _FALLBACK_CONTENT_TYPES:
                        mime_type = self._guess_mime_type(target_url)
                    else:
                        return None, "", f"Lỗi: URL không trả về hình ảnh (Content-Type: {content_type})."

                    declared_size = resp.headers.get("Content-Length")
                    if declared_size and declared_size.isdigit() and int(declared_size) > MAX_IMAGE_BYTES:
                        return None, "", "Lỗi: Hình ảnh vượt quá giới hạn 20 MB."

                    image_bytes = await resp.read()

                if not image_bytes:
                    return None, "", "Lỗi: Hình ảnh tải về rỗng."
                if len(image_bytes) > MAX_IMAGE_BYTES:
                    return None, "", "Lỗi: Hình ảnh vượt quá giới hạn 20 MB."
                return image_bytes, mime_type, None

        return None, "", "Lỗi: URL chuyển hướng quá số lần cho phép."

    async def run_image_recognition(self, image_url: str, question: str) -> str:
        if not image_url:
            return "Lỗi: Không tìm thấy URL hình ảnh hợp lệ để nhận diện."

        cached = self._get_cache(image_url, question)
        if cached:
            self.logger.info(f"Image recognition cache hit for {image_url}")
            return cached

        if self.gateway is None:
            return "Lỗi: Chưa cấu hình LLM Gateway cho tính năng nhận diện ảnh."

        try:
            image_bytes, mime_type, error = await self._download_image(image_url)
            if error:
                return error

            prompt_text = question or "Mô tả chi tiết và chính xác những gì bạn nhìn thấy trong hình ảnh này."
            result_text = await self.gateway.generate_vision(
                image_bytes=image_bytes,
                mime_type=mime_type,
                question=prompt_text,
            )
            self._set_cache(image_url, question, result_text)
            return result_text
        except Exception as e:
            self.logger.error(f"Image recognition error via LLMGateway: {e}")
            return f"Lỗi khi xử lý hình ảnh: {e}"
