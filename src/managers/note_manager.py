import uuid
import json
import re
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Tuple
from src.core.config import logger, get_config
from src.core.api_router import get_api_router
from src.core.gemini_api_manager import GeminiApiManager
from src.database.repository import DatabaseRepository


class NoteManager:
    """Manager for user notes and memory management."""

    GLOBAL_PROMOTE_DISTINCT_USERS = 3

    def __init__(self, db_repo: DatabaseRepository):
        self.db_repo = db_repo
        self.logger = logger
        self.config = get_config()
        self.router = get_api_router()
        self.gemini_mgr = GeminiApiManager(self.config, self.router)

    def _normalize_fact_text(self, text: str) -> str:
        normalized = (text or "").strip().lower()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = re.sub(r"[^\w\s]", "", normalized)
        return normalized

    def _classify_note(self, content: str) -> Tuple[str, str, int, str]:
        text = (content or "").strip()
        lowered = text.lower()

        blocked_markers = [
            "dox",
            "doxxing",
            "mạo danh",
            "impersonat",
            "xúc phạm",
            "lăng mạ",
            "số điện thoại",
            "địa chỉ nhà",
            "cccd",
            "cmnd",
        ]
        if any(marker in lowered for marker in blocked_markers):
            return "blocked", "blocked", 0, ""

        forced_alias_pattern = re.search(r"\bgọi\s+.+\s+là\s+", lowered)
        if forced_alias_pattern and ("người" in lowered or "user" in lowered or "thằng" in lowered):
            return "blocked", "blocked", 0, ""

        personal_markers = [
            "tôi thích",
            "mình thích",
            "my favorite",
            "i prefer",
            "gọi tôi",
            "call me",
            "cấu hình máy",
            "tên tôi",
            "my name",
            "tôi là",
            "tên mình là",
        ]

        if any(marker in lowered for marker in personal_markers):
            return "personal_preference", "user", 6, ""

        normalized = self._normalize_fact_text(text)
        fact_hash = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:20] if normalized else ""
        return "global_knowledge", "candidate_global", 4, fact_hash

    
    async def get_user_identity(self, user_id: str) -> str:
        """
        Nhanh chóng lấy định danh và sở thích cá nhân của user
        (note_type="personal_preference") để nhúng vào system prompt.
        """
        notes = await self.db_repo.get_user_notes_db(
            user_id=user_id,
            search_query=None,
            include_global=False,
            limit=10,
            note_type="personal_preference"
        )
        if not notes:
            return ""
        
        return "\n".join(f"- {n.get('content', '')}" for n in notes)

    async def save_note_to_db(self, user_id: str, content: str, source: str) -> str:
        """Save an auto-note to database."""
        try:
            # Tự động tóm tắt thông minh bằng LLM Lite khi ghi chú vượt quá 1000 ký tự
            if content and len(content) > 1000:
                self.logger.info(f"Ghi chú tự động của user {user_id} dài ({len(content)} ký tự). Đang gọi LLM Lite tóm tắt...")
                prompt = (
                    f"Bạn là trợ lý quản lý trí nhớ của hệ thống Azuris.\n"
                    f"Hãy tóm tắt và rút gọn ghi chú/thông tin dưới đây thành một đoạn ngắn gọn, súc tích bằng tiếng Việt có dấu. "
                    f"Hãy giữ nguyên các từ khóa quan trọng, sở thích cốt lõi và các sự thật (facts) cần ghi nhớ. "
                    f"Đặc biệt chú ý: Độ dài kết quả BẮT BUỘC phải dưới 500 ký tự để lưu trữ tối ưu.\n\n"
                    f"Nội dung ghi chú cần tóm tắt:\n\"{content}\""
                )
                try:
                    summary = await self.gemini_mgr.call_gemini_direct(prompt)
                    if summary and "Error calling LLM" not in summary:
                        content = summary.strip()
                        self.logger.info(f"Đã tóm tắt ghi chú bằng LLM Lite thành công. Độ dài mới: {len(content)} ký tự.")
                    else:
                        raise ValueError("LLM returned empty or error response")
                except Exception as err:
                    self.logger.error(f"Không thể tóm tắt bằng LLM Lite: {err}. Fallback cắt chuỗi thô.")
                    content = content[:1000] + "..."

            note_id = str(uuid.uuid4())
            note_type, scope, importance, fact_hash = self._classify_note(content)

            if note_type == "blocked":
                self.logger.warning(f"Blocked unsafe note for user {user_id}")
                return "Mình không thể lưu note này vì nội dung không an toàn hoặc có dấu hiệu lạm dụng."

            metadata = {
                "type": "auto_note" if source == "chat_inference" else "manual",
                "source": source,
                "timestamp": datetime.now().isoformat(),
                "note_type": note_type,
                "scope": scope,
                "fact_hash": fact_hash,
            }

            success = await self.db_repo.add_user_note_db(
                user_id,
                note_id,
                content,
                metadata,
                scope=scope,
                importance=importance,
                note_type=note_type,
                fact_hash=fact_hash,
            )

            if not success:
                self.logger.error(f"Error saving auto-note for {user_id}")
                return "Lỗi khi cố gắng lưu note."

            if note_type == "global_knowledge" and fact_hash:
                distinct_users = await self.db_repo.count_distinct_users_by_fact_hash_db(fact_hash)
                if distinct_users >= self.GLOBAL_PROMOTE_DISTINCT_USERS:
                    promoted_count = await self.db_repo.promote_fact_hash_to_global_db(fact_hash)
                    self.logger.info(
                        f"Auto-promoted fact_hash={fact_hash} to global after {distinct_users} users. rows={promoted_count}"
                    )
                    return f"Đã lưu note và nâng thành kiến thức chung sau khi được nhiều user xác nhận ({distinct_users})."

                return f"Đã lưu note dạng candidate chung ({distinct_users}/{self.GLOBAL_PROMOTE_DISTINCT_USERS} user xác nhận)."

            self.logger.info(f"Auto-note saved for {user_id}. Source: {source}, type={note_type}, scope={scope}")
            return f"Đã ghi nhớ thông tin: '{content[:50]}...'"

        except Exception as e:
            self.logger.error(f"Exception in save_note_to_db: {e}")
            return f"Exception when saving note: {e}"
    
    async def save_file_note_to_db(self, user_id: str, content: str, filename: str, source: str = "file_upload") -> bool:
        """Save parsed file content to database. Updates if file already exists."""
        try:
            # Tóm tắt tệp tin cực lớn (> 20,000 ký tự) bằng LLM Lite
            if content and len(content) > 20000:
                self.logger.info(f"Nội dung tệp {filename} quá lớn ({len(content)} ký tự). Đang gọi LLM Lite tổng hợp tóm tắt chất lượng cao...")
                prompt = (
                    f"Bạn là chuyên gia phân tích tài liệu của hệ thống Azuris.\n"
                    f"Tệp tin '{filename}' tải lên có dung lượng rất lớn. Hãy đọc nội dung tệp dưới đây và viết một bản tóm tắt phân tích chất lượng cao bằng tiếng Việt có dấu.\n"
                    f"Bản tóm tắt cần nêu bật:\n"
                    f"1. Chủ đề cốt lõi của tài liệu.\n"
                    f"2. Các thông tin quan trọng nhất, công thức, quy ước hoặc logic nghiệp vụ chính.\n"
                    f"3. Tóm lược các hướng dẫn hành vi chính.\n\n"
                    f"Đảm bảo kết quả chặt chẽ, súc tích và BẮT BUỘC có độ dài dưới 2000 ký tự để nạp ngữ cảnh hội thoại tối ưu.\n\n"
                    f"Nội dung tệp tin:\n\"{content[:30000]}\""
                )
                try:
                    summary = await self.gemini_mgr.call_gemini_direct(prompt)
                    if summary and "Error calling LLM" not in summary:
                        content = summary.strip()
                        self.logger.info(f"Đã tổng hợp tóm tắt tệp thành công bằng LLM Lite. Độ dài: {len(content)} ký tự.")
                    else:
                        raise ValueError("LLM returned empty or error response")
                except Exception as err:
                    self.logger.error(f"Không thể tóm tắt tệp bằng LLM Lite: {err}. Fallback cắt chuỗi thô.")
                    content = content[:20000] + "\n[Nội dung bị cắt bớt do vượt quá giới hạn 20,000 ký tự]"

            existing_note = await self.db_repo.get_file_note_by_filename_db(user_id, filename)
            
            metadata = {
                "type": "file",
                "source": source,
                "filename": filename,
                "timestamp": datetime.now().isoformat()
            }
            
            if existing_note:
                success = await self.db_repo.update_user_note_db(existing_note['note_id'], content, metadata)
                if success:
                    self.logger.info(f"File note updated for {user_id}. File: {filename}")
                else:
                    self.logger.error(f"Error updating file note for {user_id}")
                return success
            else:
                note_id = str(uuid.uuid4())
                success = await self.db_repo.add_user_note_db(
                    user_id,
                    note_id,
                    content,
                    metadata,
                    scope="user",
                    importance=5,
                    note_type="file_note",
                    fact_hash="",
                )
                
                if success:
                    self.logger.info(f"File note saved for {user_id}. File: {filename}")
                else:
                    self.logger.error(f"Error saving file note for {user_id}")
                return success
        
        except Exception as e:
            self.logger.error(f"Exception in save_file_note_to_db: {e}")
            return False
    
    def _should_include_global(self, query: str) -> bool:
        lowered = (query or "").strip().lower()
        if not lowered:
            return False

        personal_markers = [
            "tôi",
            "mình",
            "my",
            "me",
            "của tôi",
            "cá nhân",
        ]
        if any(marker in lowered for marker in personal_markers):
            return False

        global_markers = [
            "chung",
            "mọi người",
            "toàn server",
            "global",
            "best practice",
            "kinh nghiệm",
            "quy ước",
        ]
        return any(marker in lowered for marker in global_markers)

    async def retrieve_notes_from_db(self, user_id: str, query: str) -> str:
        """Retrieve notes from database with optional search."""
        try:
            include_global = self._should_include_global(query)
            notes: List[Dict[str, Any]] = await self.db_repo.get_user_notes_db(
                user_id,
                search_query=query,
                include_global=include_global,
                limit=20,
            )

            if not notes and include_global and query:
                notes = await self.db_repo.get_user_notes_db(
                    user_id,
                    search_query=None,
                    include_global=True,
                    limit=10,
                )

            if not notes:
                return "Không tìm thấy note nào khớp với nội dung."

            formatted_notes = []
            for note in notes:
                try:
                    metadata_val = note.get('metadata')
                    if isinstance(metadata_val, str):
                        metadata = json.loads(metadata_val) if metadata_val else {}
                    elif isinstance(metadata_val, (dict, list)):
                        metadata = metadata_val
                    else:
                        metadata = {}

                    meta_str = (
                        f"Loại: {metadata.get('type', note.get('note_type', 'N/A'))}, "
                        f"Nguồn: {metadata.get('source', 'N/A')}, "
                        f"Scope: {note.get('scope', 'user')}"
                    )
                except Exception:
                    meta_str = f"Scope: {note.get('scope', 'user')}"

                formatted_notes.append(
                    f"--- [Note (ID: {note['note_id']}) ---\n"
                    f"[Thông tin: {meta_str}, Ngày lưu: {note['created_at']}]\n"
                    f"[Nội dung]:\n{note['content']}\n"
                    f"---"
                )

            self.logger.info(
                f"Retrieved {len(notes)} notes for {user_id} with query: {query}, include_global={include_global}"
            )

            result_str = "\n\n".join(formatted_notes)
            if len(result_str) > 4000:
                result_str = result_str[:4000] + "\n... (Result too long, truncated)"

            return result_str

        except Exception as e:
            self.logger.error(f"Exception in retrieve_notes_from_db: {e}")
            return f"Exception when retrieving notes: {e}"

    async def delete_note_from_db(self, user_id: str, note_id: str) -> str:
        """Delete a specific note from the database."""
        try:
            success = await self.db_repo.delete_user_note_db(note_id, user_id)
            if success:
                self.logger.info(f"Note {note_id} deleted for user {user_id}")
                return "Đã xóa note thành công."
            else:
                self.logger.warning(f"Failed to delete note {note_id} for user {user_id}")
                return "Không thể xóa note. Có thể note_id không đúng hoặc bạn không có quyền xóa note này."
        except Exception as e:
            self.logger.error(f"Exception in delete_note_from_db: {e}")
            return f"Exception when deleting note: {e}"
