import uuid
import json
from datetime import datetime
from typing import List, Dict, Any
from src.core.config import logger
from src.database.repository import DatabaseRepository


class NoteManager:
    """Manager for user notes and memory management."""
    
    def __init__(self, db_repo: DatabaseRepository):
        self.db_repo = db_repo
        self.logger = logger
    
    async def save_note_to_db(self, user_id: str, content: str, source: str) -> str:
        """Save an auto-note to database."""
        try:
            note_id = str(uuid.uuid4())
            metadata = {
                "type": "auto_note" if source == "chat_inference" else "manual",
                "source": source,
                "timestamp": datetime.now().isoformat()
            }
            
            success = await self.db_repo.add_user_note_db(user_id, note_id, content, metadata)
            
            if success:
                self.logger.info(f"Auto-note saved for {user_id}. Source: {source}")
                return f"Đã ghi nhớ thông tin: '{content[:50]}...'"
            else:
                self.logger.error(f"Error saving auto-note for {user_id}")
                return "Lỗi khi cố gắng lưu note."
        
        except Exception as e:
            self.logger.error(f"Exception in save_note_to_db: {e}")
            return f"Exception when saving note: {e}"
    
    async def save_file_note_to_db(self, user_id: str, content: str, filename: str, source: str = "file_upload") -> bool:
        """Save parsed file content to database. Updates if file already exists."""
        try:
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
                success = await self.db_repo.add_user_note_db(user_id, note_id, content, metadata)
                
                if success:
                    self.logger.info(f"File note saved for {user_id}. File: {filename}")
                else:
                    self.logger.error(f"Error saving file note for {user_id}")
                return success
        
        except Exception as e:
            self.logger.error(f"Exception in save_file_note_to_db: {e}")
            return False
    
    async def retrieve_notes_from_db(self, user_id: str, query: str) -> str:
        """Retrieve notes from database with optional search."""
        try:
            notes: List[Dict[str, Any]] = await self.db_repo.get_user_notes_db(user_id, search_query=query)
            
            if not notes:
                return "Không tìm thấy note nào khớp với nội dung."
            
            formatted_notes = []
            for note in notes:
                try:
                    metadata = json.loads(note['metadata'])
                    meta_str = f"Loại: {metadata.get('type', 'N/A')}, Nguồn: {metadata.get('source', 'N/A')}"
                except Exception:
                    meta_str = "Metadata lỗi"
                
                formatted_notes.append(
                    f"--- [Note (ID: {note['note_id']}) ---\n"
                    f"[Thông tin: {meta_str}, Ngày lưu: {note['created_at']}]\n"
                    f"[Nội dung]:\n{note['content']}\n"
                    f"---"
                )
            
            self.logger.info(f"Retrieved {len(notes)} notes for {user_id} with query: {query}")
            
            result_str = "\n\n".join(formatted_notes)
            if len(result_str) > 4000:
                result_str = result_str[:4000] + "\n... (Result too long, truncated)"
            
            return result_str
        
        except Exception as e:
            self.logger.error(f"Exception in retrieve_notes_from_db: {e}")
            return f"Exception when retrieving notes: {e}"
