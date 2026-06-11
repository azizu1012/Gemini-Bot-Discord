import os
import re
import uuid
import json
import asyncio
import unicodedata
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

from src.core.config import logger, Config
from src.services.redis_service import RedisStreamService
from src.database.repository import DatabaseRepository
from src.core.api_router import get_api_router
from src.core.gemini_api_manager import GeminiApiManager
from src.core.gemini_pipeline import GeminiPipeline
from src.core.api_config import (
    DEFAULT_REASONING_MODEL_ALIAS,
    DEFAULT_FINAL_MODEL_ALIAS,
    DEFAULT_FALLBACK_MODEL_ALIAS,
    VISION_MODEL_ALIAS,
)
from src.tools.tools import ToolsManager
from src.managers.note_manager import NoteManager
from src.managers.premium_manager import PremiumManager
from src.managers.cache_manager import get_cache_manager
from src.services.file_parser import FileParserService
from src.services.file_index_service import (
    FileIndexService,
    should_use_last_index,
    build_index_context,
)
from src.services.search_subtask_client import SearchSubtaskClient
from src.managers.cleanup_manager import CleanupManager
from src.core.prompt_loader import build_identity_capability_prompt


class DummyAttachment:
    """Mock discord attachment details passed from Gateway."""
    def __init__(
        self,
        url: str,
        filename: str,
        size: int = 10 * 1024 * 1024,
        attachment_id: str = "",
        content_type: str = "",
        proxy_url: str = "",
    ):
        self.url = url
        self.filename = filename
        self.size = size
        self.id = attachment_id
        self.content_type = content_type
        self.proxy_url = proxy_url


class MessageHandler:
    """Worker core message processing with Gemini API integration.

    In the current architecture, this is purely a Redis Streams consumer/producer that doesn't
    interact directly with Discord APIs.
    """

    def __init__(self, config: Config):
        self.config = config
        self.logger = logger
        self.db_repo = DatabaseRepository(self.config.DATABASE_URL)
        self.cache_mgr = get_cache_manager()

        # Tools and API setup
        self.note_mgr = NoteManager(self.db_repo)
        self.kafka_service = RedisStreamService(redis_url=self.config.REDIS_URL, client_id="worker")
        self.search_subtask_client = SearchSubtaskClient(self.kafka_service)
        self.tools_mgr = ToolsManager(
            note_mgr=self.note_mgr,
            db_repo=self.db_repo,
            search_subtask_client=self.search_subtask_client,
        )
        self.api_router = get_api_router()
        self.api_router.set_db_repo(self.db_repo)
        self._api_mgr: Optional[GeminiApiManager] = None
        self._pipeline: Optional[GeminiPipeline] = None
        self._file_index_svc: Optional[FileIndexService] = None

        self.premium_mgr = PremiumManager()
        self.file_parser = FileParserService(cleanup_mgr=CleanupManager())
        self.file_chunk_dir = self.config.FILE_CHUNK_DIR
        self._image_download_sem = asyncio.Semaphore(3)


    async def _publish_outgoing(self, payload: Dict[str, Any], user_id: Optional[str]) -> bool:
        ok = await self.kafka_service.publish("discord-outgoing", payload=payload, key=user_id)
        if not ok:
            action = payload.get("action") or payload.get("type") or "unknown"
            raise RuntimeError(f"Failed to publish outgoing Redis payload action={action} user={user_id}")
        return ok

    async def _download_file(self, url: str) -> Optional[bytes]:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as response:
                    if response.status == 200:
                        return await response.read()
        except Exception as e:
            self.logger.error(f"Failed to download attachment: {e}")
        return None

    async def _download_file_with_sem(self, url: str) -> Optional[bytes]:
        async with self._image_download_sem:
            return await self._download_file(url)

    @property
    def api_mgr(self) -> GeminiApiManager:
        if self._api_mgr is None:
            self._api_mgr = GeminiApiManager(config=self.config, api_router=self.api_router)
        return self._api_mgr

    @property
    def file_index_svc(self) -> FileIndexService:
        if self._file_index_svc is None:
            self._file_index_svc = FileIndexService(
                config=self.config,
                db_repo=self.db_repo,
                file_parser=self.file_parser,
                api_generate_fn=self.api_mgr._generate_gemini_content,
                api_get_key_fn=self.api_mgr._get_best_api_key,
                api_commit_key_fn=self.api_mgr._commit_selected_key,
                api_throttle_fn=self.api_mgr._throttle_api_request,
                api_acquire_quota_fn=self.api_mgr._acquire_gemini_quota,
                api_log_exception_fn=self.api_mgr._log_gemini_exception,
                reasoning_model_alias=self.pipeline.reasoning_model_alias,
                final_model_alias=self.pipeline.final_model_alias,
            )
        return self._file_index_svc

    @property
    def pipeline(self) -> GeminiPipeline:
        if self._pipeline is None:
            self._pipeline = GeminiPipeline(
                config=self.config,
                api_mgr=self.api_mgr,
                tools_mgr=self.tools_mgr,
                identity_builder=self._build_identity_instruction,
                reasoning_model_alias=DEFAULT_REASONING_MODEL_ALIAS,
                final_model_alias=DEFAULT_FINAL_MODEL_ALIAS,
                fallback_model_alias=DEFAULT_FALLBACK_MODEL_ALIAS,
            )
        return self._pipeline

    async def _refresh_pipeline_model_aliases(self, force_vision_model: bool = False) -> None:
        pipeline = self.pipeline
        if force_vision_model:
            pipeline.reasoning_model_alias = VISION_MODEL_ALIAS
            pipeline.final_model_alias = VISION_MODEL_ALIAS
            pipeline.fallback_model_alias = VISION_MODEL_ALIAS
            return
        selected = await self.api_router.get_selected_model_aliases()
        pipeline.reasoning_model_alias = str(selected.get("reasoning") or DEFAULT_REASONING_MODEL_ALIAS)
        pipeline.final_model_alias = str(selected.get("final") or DEFAULT_FINAL_MODEL_ALIAS)
        pipeline.fallback_model_alias = str(selected.get("fallback") or DEFAULT_FALLBACK_MODEL_ALIAS)

    def _normalize_intent_text(self, text: str) -> str:
        lowered = (text or "").lower()
        no_diacritics = "".join(
            ch for ch in unicodedata.normalize("NFD", lowered)
            if unicodedata.category(ch) != "Mn"
        )
        normalized = re.sub(r"[^a-z0-9\s]", " ", no_diacritics)
        return re.sub(r"\s+", " ", normalized).strip()

    def _detect_user_correction(self, text: str) -> Dict[str, Any]:
        raw = (text or "").strip()
        if not raw:
            return {}

        normalized = self._normalize_intent_text(raw)
        markers = (
            "bia",
            "sai roi",
            "khong phai",
            "khong dung",
            "nham",
            "y toi la",
            "dinh chinh",
            "wrong",
            "correction",
        )
        has_marker = any(marker in normalized for marker in markers)
        has_emphatic_definition = bool(re.search(r"\b[a-z0-9]{2,12}\s+la\s+.+\bma\b", normalized))

        correction_text = ""
        match = re.search(r"\b([A-Za-z][A-Za-z0-9]{1,12})\s+(?:là|la|=)\s+([^\n\r?!.,]{2,120})", raw, re.IGNORECASE)
        if match and (has_marker or has_emphatic_definition):
            subject = match.group(1).strip().upper()
            value = re.sub(r"\s+(?:mà|ma|đó|do)\s*$", "", match.group(2).strip(), flags=re.IGNORECASE)
            correction_text = f"{subject} = {value}"

        if not (has_marker or correction_text):
            return {}

        return {
            "is_user_correction": True,
            "active_user_correction": correction_text or raw[:300],
        }

    def _is_identity_question(self, text: str) -> bool:
        normalized = self._normalize_intent_text(text)
        patterns = ["bạn là ai", "ban la ai", "who are you", "what is your name", "your name"]
        return any(p in normalized for p in patterns)

    def _is_capability_question(self, text: str) -> bool:
        normalized = self._normalize_intent_text(text)
        patterns = ["bạn làm được gì", "ban lam duoc gi", "what can you do", "capabilities"]
        return any(p in normalized for p in patterns)

    def _is_cross_user_presence_question(self, text: str) -> bool:
        normalized = self._normalize_intent_text(text)
        patterns = ["chat với ai khác", "chat voi ai khac", "talk to other users"]
        return any(p in normalized for p in patterns)

    def _get_runtime_tool_capabilities(self, is_admin: bool) -> List[Tuple[str, str]]:
        capabilities = []
        seen = set()
        for tool in self.tools_mgr.get_all_tools(is_admin):
            decls = getattr(tool, "function_declarations", [])
            for decl in decls:
                name = getattr(decl, "name", "")
                desc = getattr(decl, "description", "")
                if name == "manage_user_role" and not is_admin:
                    continue
                if name and name not in seen:
                    seen.add(name)
                    capabilities.append((name, desc or "Runtime utility"))
        capabilities.sort()
        return capabilities

    def _build_identity_instruction(self, privacy_context: Dict[str, Any]) -> str:
        is_admin = bool(privacy_context.get("is_admin"))
        capabilities = self._get_runtime_tool_capabilities(is_admin)
        tool_lines = "\n".join([f"- {name}: {desc}" for name, desc in capabilities]) if capabilities else "- No tools available."
        prompt = build_identity_capability_prompt(
            is_admin=is_admin,
            has_other_users=bool(privacy_context.get("has_other_users")),
            distinct_user_count=int(privacy_context.get("distinct_user_count") or 0),
            tool_lines=tool_lines
        )
        user_identity = privacy_context.get("user_identity", "")
        if user_identity:
            prompt += f"\n[USER PERSONAL IDENTITIES & PREFERENCES]\n{user_identity}\n"

        # Thay thế động tên bot
        bot_name = privacy_context.get("bot_name", "Chad Gibiti")
        prompt = prompt.replace("Chad Gibiti", bot_name)
        return prompt

    async def _build_admin_cross_user_evidence(self, content: str, user_id: str) -> str:
        rows = await self.db_repo.search_user_messages_db(content, limit=15, exclude_user_id=user_id)
        if not rows:
            return "[ADMIN EVIDENCE] No matching records from other users."

        lines = ["[ADMIN CROSS-USER EVIDENCE] Verified rows:"]
        for i, row in enumerate(rows, start=1):
            content = row.get('content') or ''
            lines.append(f"{i}. user={row.get('user_id')} | content={content[:100]}")
        return "\n".join(lines)

    def _split_text(self, text: str, limit: int = 1800) -> List[str]:
        chunks = []
        current_text = text.strip()

        while len(current_text) > limit:
            split_idx = current_text.rfind('\n', 0, limit)
            if split_idx == -1:
                split_idx = current_text.rfind(' ', 0, limit)
            if split_idx == -1 or split_idx <= 0:
                split_idx = limit

            chunk = current_text[:split_idx].strip()
            if chunk:
                chunks.append(chunk)
            current_text = current_text[split_idx:].strip()

        if current_text:
            chunks.append(current_text)
        return chunks

    async def start_worker(self):
        """Start the Redis Streams consumer and listen for incoming messages."""
        self.logger.info("Starting Worker...")

        await self.db_repo.init_db()

        try:
            await self.kafka_service.start_producer()
            consumer = await self.kafka_service.start_consumer("discord-incoming", group_id="azuris_worker_group")
        except Exception as e:
            self.logger.error(f"Failed to start worker Redis services: {e}")
            await self.shutdown()
            return

        self.logger.info("Worker started. Listening for messages...")

        try:
            async for msg in consumer:
                payload = msg.value
                asyncio.create_task(self.process_message(payload))
        except asyncio.CancelledError:
            self.logger.info("Worker task cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Error in Redis consumer loop: {e}")
        finally:
            await self.shutdown()

    async def shutdown(self):
        try:
            await self.search_subtask_client.close()
        except Exception:
            pass
        await self.kafka_service.stop()

        try:
            await self.db_repo.close()
        except Exception as e:
            self.logger.warning(f"Failed to close DB pool cleanly: {e}")

    async def process_message(self, payload: dict):
        """Process a single message payload from Redis."""
        msg_type = payload.get("type")
        user_id = payload.get('user_id')

        # Handle cache invalidation events via Redis
        if msg_type == "invalidate_cache":
            if user_id:
                self.cache_mgr.invalidate_chat_history(user_id)
                self.logger.info(f"[CACHE] Invalidated chat history cache for user {user_id} via Redis event.")
            return

        if msg_type == "invalidate_all_cache":
            self.cache_mgr.clear_all_caches()
            self.logger.info("[CACHE] Cleared all in-memory caches via Redis event.")
            return

        if not user_id:
            return

        if msg_type == "slash_command":
            await self.process_slash_command(payload)
            return

        content = payload.get('content', '').strip()
        self.logger.info(f"[REDIS-RECV] Consumed message from 'discord-incoming' | User: {user_id} | MsgID: {payload.get('message_id')} | Content Length: {len(content)}")

        try:
            is_admin = await self.premium_mgr.is_admin_user(user_id)
            is_moderator = await self.premium_mgr.is_moderator_user(user_id)
            is_premium = await self.premium_mgr.is_premium_user(user_id)

            # 1. Daily Limit Validation for Free Tier users
            if not is_admin and not is_moderator and not is_premium:
                daily_count = await self.db_repo.count_user_messages_today_db(user_id)
                if daily_count >= 50:
                    await self._publish_outgoing({
                        "action": "reply",
                        "channel_id": payload.get('channel_id'),
                        "user_id": user_id,
                        "content": "Bạn đã sử dụng hết giới hạn tin nhắn hôm nay (50/50). Hãy nâng cấp Premium bằng lệnh `/premium buy` để tiếp tục dùng không giới hạn nhé! 🛑",
                        "reference_message_id": payload.get('message_id')
                    }, user_id)
                    return

            # 2. Publish Typing Signal
            await self._publish_outgoing(
                {
                    "action": "typing",
                    "typing": True,
                    "channel_id": payload.get("channel_id"),
                    "user_id": user_id,
                    "reference_message_id": payload.get("message_id"),
                },
                user_id,
            )

            # 3. Process Attachments / RAG Indexing & Download Images In Parallel (RAM-Only)
            attachment_data = ""
            attachments = payload.get("attachments", [])
            image_tasks = []
            image_metas = []

            # Map extensions to standard mime types
            MIME_MAP = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".gif": "image/gif",
                ".bmp": "image/bmp"
            }

            for att in attachments:
                original_filename = att.get("filename") or "attachment"
                filename = original_filename.lower()
                url = att.get("url") or att.get("proxy_url") or ""
                if not url:
                    attachment_data += f"\n[System Error: File {original_filename} không có URL tải về từ Discord]\n"
                    continue

                # Check if it is an image
                is_image = False
                for ext, mime in MIME_MAP.items():
                    if filename.endswith(ext):
                        image_tasks.append(self._download_file_with_sem(url))
                        image_metas.append((filename, url, mime))
                        is_image = True
                        break

                if is_image:
                    continue

                SUPPORTED_TEXT_EXTS = ('.pdf', '.txt', '.md', '.py', '.json', '.js', '.html', '.css', '.csv')
                if filename.endswith(SUPPORTED_TEXT_EXTS):
                    try:
                        doc_id = str(uuid.uuid4())
                        dummy_att = DummyAttachment(
                            url,
                            original_filename,
                            int(att.get("size") or 10 * 1024 * 1024),
                            str(att.get("id") or ""),
                            str(att.get("content_type") or ""),
                            str(att.get("proxy_url") or ""),
                        )

                        file_meta = await self.file_parser.prepare_file_for_indexing(
                            dummy_att,
                            base_name=doc_id,
                            chunk_dir=os.path.join(self.file_chunk_dir, doc_id),
                        )
                        if not file_meta or file_meta.get("error"):
                            attachment_data += f"\n[System Error: Lỗi file {att.get('filename')}]\n"
                            continue

                        index_data = await self.file_index_svc.build_file_index(
                            file_meta=file_meta,
                            document_id=doc_id,
                            user_id=user_id,
                        )
                        validation = await self.file_index_svc.validate_file_index(index_data, user_id)
                        self.file_index_svc.set_latest_index(user_id, doc_id, att.get("filename"))

                        if validation.get("status") == "block":
                            attachment_data += f"\n[System Note: Blocked index: {validation.get('reason')}]\n"
                        else:
                            attachment_data += await build_index_context(
                                doc_id, content, db_repo=self.db_repo, file_parser=self.file_parser
                            )
                    except Exception as e:
                        self.logger.error(f"Error indexing: {e}")
                        attachment_data += f"\n[System Error: Không thể index file {att.get('filename')}]\n"

            # Run parallel download for images
            downloaded_images = []
            if image_tasks:
                downloaded_results = await asyncio.gather(*image_tasks)
                for img_bytes, (fname, img_url, mime) in zip(downloaded_results, image_metas):
                    if img_bytes:
                        downloaded_images.append({
                            "inline_data": {
                                "data": img_bytes,
                                "mime_type": mime
                            }
                        })
                        # Log text thô kèm URL vào DB/Cache
                        attachment_data += f"\n[System Note: User uploaded an image: {fname}. URL: {img_url}]\n"
                    else:
                        attachment_data += f"\n[System Error: Không thể tải ảnh {fname}]\n"

            # 4. Reroute last RAG index if keyword matches
            if not attachments and should_use_last_index(content):
                last_index = self.file_index_svc.get_latest_index_for_user(user_id)
                if last_index and last_index.get("document_id"):
                    attachment_data += await build_index_context(
                        last_index["document_id"], content, db_repo=self.db_repo, file_parser=self.file_parser
                    )

            # 5. Intent Detection & Dynamic context builder
            bot_name = payload.get("bot_name", "Chad Gibiti")
            correction_context = self._detect_user_correction(content)
            intent_cues = []
            if self._is_identity_question(content):
                intent_cues.append(f"[SYSTEM NOTE: Identity query. Respond in 1-2 sentences as {bot_name}.]")
            if self._is_capability_question(content):
                intent_cues.append("[SYSTEM NOTE: Provide tool capabilities summary.]")
            if intent_cues:
                content += "\n\n" + "\n".join(intent_cues)

            user_message = content + attachment_data

            # 6. Database Logs & RAM Cache (done with final consolidated message)
            await self.db_repo.log_message_db(user_id, "user", user_message)
            self.cache_mgr.add_chat_message(user_id, "user", user_message)

            distinct_user_count = await self.db_repo.count_distinct_message_users_db()
            has_other_users = await self.db_repo.has_other_users_history_db(user_id)
            user_identity = await self.note_mgr.get_user_identity(user_id)

            admin_cross_user_evidence = ""
            if is_admin:
                admin_cross_user_evidence = await self._build_admin_cross_user_evidence(user_message, user_id)

            privacy_context = {
                "is_admin": is_admin,
                "discord_display_name": payload.get("author_display_name", payload.get("author_name", "")),
                "distinct_user_count": distinct_user_count,
                "has_other_users": has_other_users,
                "admin_cross_user_evidence": admin_cross_user_evidence,
                "is_cross_user_presence_question": self._is_cross_user_presence_question(user_message),
                "user_identity": user_identity,
                "bot_name": bot_name,
                **correction_context,
            }

            # 7. Get History & Call Gemini Pipeline
            # Tận dụng In-memory KV Cache từ RAM
            history = self.cache_mgr.get_chat_history(user_id, limit=12)
            if history is None:
                # Cache miss: query PostgreSQL
                history = await self.db_repo.get_user_history_from_db(user_id, limit=12)
                self.cache_mgr.set_chat_history(user_id, history)
                self.logger.info(f"[CACHE MISS] Loaded chat history for user {user_id} from PostgreSQL.")
            else:
                self.logger.info(f"[CACHE HIT] Loaded chat history for user {user_id} from in-memory RAM cache.")

            messages = []
            for msg in history:
                role = "model" if msg["role"] == "assistant" else msg["role"]
                messages.append({"role": role, "parts": [{"text": msg["content"]}]})

            # Tin nhắn user cuối cùng chứa text và toàn bộ inline_data của ảnh tải được
            user_parts = [{"text": user_message}]
            if downloaded_images:
                user_parts.extend(downloaded_images)
            messages.append({"role": "user", "parts": user_parts})

            await self._refresh_pipeline_model_aliases(force_vision_model=bool(downloaded_images))
            response_text = await self.pipeline.call_gemini_api(messages, user_id, privacy_context)

            # 8. Log reply and Split response chunks sequentially
            await self.db_repo.log_message_db(user_id, "assistant", response_text)
            self.cache_mgr.add_chat_message(user_id, "assistant", response_text)

            allowed_mentions = self.tools_mgr.pop_allowed_mentions(user_id)
            chunks = self._split_text(response_text)
            reply_group_id = str(uuid.uuid4())
            chunk_items = [{"index": idx, "content": chunk} for idx, chunk in enumerate(chunks)]
            reply_payload = {
                "action": "reply_batch",
                "reply_group_id": reply_group_id,
                "channel_id": payload.get('channel_id'),
                "user_id": user_id,
                "chunks": chunks,
                "chunk_items": chunk_items,
                "chunk_total": len(chunks),
                "mode_hint": "edit_then_batch",
                "allow_user_mentions": allowed_mentions,
                "reference_message_id": payload.get('message_id'),
                "created_at": datetime.utcnow().isoformat(),
            }
            await self._publish_outgoing(reply_payload, user_id)

            self.logger.info(f"Published outgoing reply_batch ({len(chunks)} chunks) to Redis for user {user_id}")

        except Exception as e:
            self.logger.error(f"Error processing message for {user_id}: {e}")
            await self._publish_outgoing({
                "action": "reply",
                "channel_id": payload.get('channel_id'),
                "user_id": user_id,
                "content": "Hệ thống đang bận, vui lòng thử lại sau! 😓",
                "reference_message_id": payload.get('message_id')
            }, user_id)
        finally:
            if user_id:
                try:
                    await self._publish_outgoing(
                        {
                            "action": "typing",
                            "typing": False,
                            "channel_id": payload.get("channel_id"),
                            "user_id": user_id,
                            "reference_message_id": payload.get("message_id"),
                        },
                        user_id,
                    )
                except Exception:
                    pass

                await self.db_repo.clear_user_processing_state(user_id)

    async def process_slash_command(self, payload: dict):
        """Process a slash command payload from Redis."""
        command = payload.get("command")
        user_id = payload.get("user_id")
        self.logger.info(f"[REDIS-RECV] Consumed slash command '{command}' from 'discord-incoming' | User: {user_id}")

        try:
            if command == "imagine":
                await self._process_imagine_command(payload)
            else:
                self.logger.warning(f"Unknown slash command: {command}")
        except Exception as e:
            self.logger.error(f"Error handling slash command '{command}': {e}")

    async def _process_imagine_command(self, payload: dict):
        """Process an imagine slash command (AI image generation with Gemini)."""
        import base64
        import io
        import os
        from pathlib import Path

        user_id = payload.get("user_id")
        prompt = payload.get("prompt")
        interaction_id = payload.get("interaction_id")
        channel_id = payload.get("channel_id")
        author_display_name = payload.get("author_display_name", "User")

        if not prompt:
            await self._publish_outgoing({
                "action": "slash_reply",
                "interaction_id": interaction_id,
                "user_id": user_id,
                "content": "⚠️ Prompt không hợp lệ.",
                "ephemeral": True
            }, user_id)
            return

        max_attempts = 3
        success = False
        error_message = ""
        image_bytes = None

        for attempt in range(1, max_attempts + 1):
            api_key, model_id, final_alias, reservation = await self.api_mgr._get_best_api_key(preferred_model_alias="gemini-flash")

            if not api_key:
                error_message = "Không có API keys khả dụng."
                self.logger.error("No API keys available for image generation.")
                break

            await self.api_mgr._throttle_api_request(api_key)

            try:
                has_quota = await self.api_mgr._acquire_gemini_quota(
                    messages=[{"role": "user", "parts": [{"text": prompt}]}],
                    max_output_tokens=0,
                    model_alias=final_alias,
                    extra_text="image_generation"
                )
                if not has_quota:
                    self.logger.warning(f"Quota check failed for key: ...{api_key[-4:]} on attempt {attempt}")
                    self.api_mgr._mark_key_as_failed(api_key, final_alias, reason="rate_limit", reservation=reservation)
                    continue

                self.logger.info(f"Generating image on key ...{api_key[-4:]} with prompt: '{prompt}' (Attempt {attempt}/{max_attempts})")

                client = self.api_mgr._get_or_create_gemini_client(api_key)

                from google.genai import types

                response = await asyncio.to_thread(
                    client.models.generate_images,
                    model='imagen-3.0-generate-002',
                    prompt=prompt,
                    config=types.GenerateImagesConfig(
                        number_of_images=1,
                        output_mime_type="image/png",
                        aspect_ratio="1:1"
                    )
                )

                if response and response.generated_images:
                    generated_image = response.generated_images[0]
                    if generated_image.image and generated_image.image.image_bytes:
                        self.api_mgr._commit_selected_key(reservation)
                        image_bytes = generated_image.image.image_bytes
                        success = True
                        break
                    elif generated_image.rai_filtered_reason:
                        error_message = f"Ảnh bị chặn bởi bộ lọc an toàn AI (RAI): {generated_image.rai_filtered_reason}"
                        self.logger.warning(f"Image generation safety filtered on key ...{api_key[-4:]}: {generated_image.rai_filtered_reason}")
                        break

                error_message = "Google API returned an empty response."

            except Exception as e:
                error_str = str(e)
                self.api_mgr._log_gemini_exception(
                    stage="IMAGINE_GEN",
                    error=e,
                    user_id=user_id,
                    model_alias=final_alias,
                    model_name="imagen-3.0-generate-002",
                    api_key=api_key,
                    attempt=attempt,
                    max_attempts=max_attempts
                )

                if self.api_mgr._is_invalid_key_error(error_str):
                    self.api_mgr._mark_key_as_failed(api_key, final_alias, reason="invalid_key", reservation=reservation, permanently_exhaust=True)
                elif self.api_mgr._is_rate_limit_error(error_str):
                    self.api_mgr._mark_key_as_failed(api_key, final_alias, reason="rate_limit", reservation=reservation)
                elif self.api_mgr._is_unavailable_error(error_str):
                    self.api_mgr._mark_key_as_failed(api_key, final_alias, reason="unavailable", reservation=reservation, duration=5)
                else:
                    self.api_mgr._mark_key_as_failed(api_key, final_alias, reason="rate_limit", reservation=reservation, duration=10)

                error_message = f"{type(e).__name__}: {error_str}"

        if success and image_bytes:
            # 1. Encode image to base64
            base64_image_str = base64.b64encode(image_bytes).decode("utf-8")

            # 2. Save physical file locally so history command can access it
            os.makedirs(self.config.FILE_STORAGE_PATH, exist_ok=True)
            local_filename = f"imagine_{interaction_id}.png"
            local_filepath = str(Path(self.config.FILE_STORAGE_PATH) / local_filename)
            try:
                with open(local_filepath, "wb") as f:
                    f.write(image_bytes)
                self.logger.info(f"Saved generated image locally to: {local_filepath}")
            except Exception as fe:
                self.logger.error(f"Failed to save generated image to disk: {fe}")

            # 3. Save to database
            # We save the local file path as image_url in the database so that bot_core can read and upload it during history retrieval
            db_save_path = local_filepath if os.path.exists(local_filepath) else f"attachment://{local_filename}"
            db_success = await self.db_repo.save_generated_image(user_id, prompt, db_save_path)
            if db_success:
                self.logger.info(f"Saved image details to DB for user {user_id}")
            else:
                self.logger.error(f"Failed to save image details to DB for user {user_id}")

            # 4. Publish reply
            await self._publish_outgoing({
                "action": "slash_reply",
                "interaction_id": interaction_id,
                "channel_id": channel_id,
                "user_id": user_id,
                "content": f"🎨 **{author_display_name}** đã tạo ảnh thành công với prompt: *\"{prompt}\"*",
                "file_base64": base64_image_str,
                "file_name": local_filename,
                "embed_title": f"🎨 {prompt[:200]}",
                "embed_footer": "Tạo bởi Gemini Imagen 3"
            }, user_id)
        else:
            await self._publish_outgoing({
                "action": "slash_reply",
                "interaction_id": interaction_id,
                "channel_id": channel_id,
                "user_id": user_id,
                "content": f"❌ Không thể tạo ảnh sau {max_attempts} lần thử. Lý do: {error_message}",
                "ephemeral": False
            }, user_id)
