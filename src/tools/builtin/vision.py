"""Image recognition tool leveraging LLMGateway."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
import aiohttp

from src.core.config import logger


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
        if len(self.image_recognition_cache) >= 1000:
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

    async def run_image_recognition(self, image_url: str, question: str) -> str:
        if not image_url:
            return "Lỗi: Không tìm thấy URL hình ảnh hợp lệ để nhận diện."

        cached = self._get_cache(image_url, question)
        if cached:
            self.logger.info(f"Image recognition cache hit for {image_url}")
            return cached

        if self.gateway is None:
            return "Lỗi: Chưa cấu hình LLM Gateway cho tính năng nhận diện ảnh."

        mime_type = self._guess_mime_type(image_url)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        return f"Lỗi: Không thể tải hình ảnh từ URL (HTTP {resp.status})."
                    image_bytes = await resp.read()
                    content_type = resp.headers.get("Content-Type", "")
                    if content_type and content_type.startswith("image/"):
                        mime_type = content_type.split(";")[0].strip()

            prompt_text = question or "Mô tả chi tiết và chính xác những gì bạn nhìn thấy trong hình ảnh này."
            result_text = await self.gateway.generate_vision(image_bytes, mime_type, prompt_text)
            self._set_cache(image_url, question, result_text)
            return result_text
        except Exception as e:
            self.logger.error(f"Image recognition error via LLMGateway: {e}")
            return f"Lỗi khi xử lý hình ảnh: {e}"
