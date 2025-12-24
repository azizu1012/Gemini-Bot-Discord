# note_manager.py
from database.repository import db_repository as db
import uuid
import json
from datetime import datetime
from core.config import config
from core.logger import logger
from typing import List, Dict, Any

async def save_note_to_db(user_id: str, content: str, source: str) -> str:
    """
    Lưu một note (thường là do AI tự nhận diện) vào DB.
    """
    try:
        note_id = str(uuid.uuid4())
        metadata = {
            "type": "auto_note" if source == "chat_inference" else "manual",
            "source": source, # "chat_inference", "tool_call", v.v.
            "timestamp": datetime.now().isoformat()
        }
        
        success = await db.add_note(user_id, note_id, content, metadata)
        
        if success:
            logger.info(f"Auto-note đã lưu cho {user_id}. Source: {source}")
            return f"Đã ghi nhớ thông tin: '{content[:50]}...'"
        else:
            logger.error(f"Lỗi khi lưu auto-note cho {user_id}")
            return "Lỗi khi cố gắng lưu note."
            
    except Exception as e:
        logger.error(f"Exception trong save_note_to_db: {e}")
        return f"Exception khi lưu note: {e}"

async def save_file_note_to_db(user_id: str, content: str, filename: str, source: str = "file_upload") -> bool:
    """
    Lưu nội dung file đã parse vào DB.
    Nếu file đã tồn tại, sẽ cập nhật nội dung.
    """
    try:
        # Kiểm tra xem đã có note cho file này chưa
        existing_note = await db.get_note_by_filename(user_id, filename)

        metadata = {
            "type": "file",
            "source": source,
            "filename": filename, # Lưu filename vào metadata
            "timestamp": datetime.now().isoformat()
        }
        
        if existing_note:
            # Cập nhật note hiện có
            success = await db.update_note(existing_note['note_id'], content, metadata)
            if success:
                logger.info(f"File note đã cập nhật cho {user_id}. File: {filename}")
            else:
                logger.error(f"Lỗi khi cập nhật file note cho {user_id}")
            return success
        else:
            # Tạo note mới
            note_id = str(uuid.uuid4())
            success = await db.add_note(user_id, note_id, content, metadata)
            
            if success:
                logger.info(f"File note đã lưu cho {user_id}. File: {filename}")
            else:
                logger.error(f"Lỗi khi lưu file note cho {user_id}")
            return success
            
    except Exception as e:
        logger.error(f"Exception trong save_file_note_to_db: {e}")
        return False

async def retrieve_notes_from_db(user_id: str, query: str) -> str:
    """
    Truy xuất các note liên quan từ DB.
    'query' được dùng để lọc (simple LIKE search).
    """
    try:
        # get_user_notes_db sẽ thực hiện tìm kiếm LIKE nếu query có
        notes: List[Dict[str, Any]] = await db.get_user_notes(user_id, search_query=query)
        
        if not notes:
            return "Không tìm thấy note nào khớp với nội dung."

        # Định dạng kết quả trả về cho Gemini
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
        
        logger.info(f"Truy xuất {len(notes)} note cho {user_id} với query: {query}")
        
        # Giới hạn tổng độ dài trả về
        result_str = "\n\n".join(formatted_notes)
        if len(result_str) > 4000:
            result_str = result_str[:4000] + "\n... (Kết quả quá dài, đã cắt bớt)"
            
        return result_str
        
    except Exception as e:
        logger.error(f"Exception trong retrieve_notes_from_db: {e}")
        return f"Exception khi truy xuất note: {e}"