# database.py
import sqlite3
import os
import shutil
from datetime import datetime, timedelta
from config import DB_PATH, DB_BACKUP_PATH, logger
import asyncio
import json # Import json
from typing import Any, Coroutine, List, Dict, Optional

async def init_db() -> None:
    await asyncio.to_thread(_init_db_sync)

def _create_tables(cursor: sqlite3.Cursor) -> None:
    cursor.execute('''CREATE TABLE IF NOT EXISTS messages
                     (user_id TEXT, role TEXT, content TEXT, timestamp TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_notes
                     (user_id TEXT, 
                      note_id TEXT PRIMARY KEY, 
                      content TEXT, 
                      metadata TEXT, 
                      created_at TEXT)''')
    cursor.execute('''CREATE INDEX IF NOT EXISTS idx_user_notes_user_id ON user_notes (user_id)''')

def _init_db_sync() -> None:
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        _create_tables(c)
        conn.commit()
        logger.info("DB initialized (messages + user_notes tables)")
    except sqlite3.DatabaseError as e:
        logger.error(f"Cannot initialize DB: {str(e)}. Attempting to re-create DB.")
        if conn:
            conn.close()
        # If initial connection or table creation fails, try to create a new DB
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        _create_tables(c)
        conn.commit()
        logger.info("New DB created (messages + user_notes tables) after error.")
    finally:
        if conn:
            conn.close()

async def backup_db() -> None:
    await asyncio.to_thread(_backup_db_sync)

def _backup_db_sync() -> None:
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            try:
                # Kiểm tra xem DB có hợp lệ không trước khi backup
                conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'")
                shutil.copy2(DB_PATH, DB_BACKUP_PATH)
                logger.info(f"DB backed up to {DB_BACKUP_PATH}")
            finally:
                conn.close()
        except sqlite3.DatabaseError as e:
            logger.error(f"Cannot backup DB: {str(e)}. Creating new DB.")
            _init_db_sync() # Gọi hàm sync để tạo lại
        except Exception as e:
            logger.error(f"Lỗi không xác định khi backup DB: {e}")

async def cleanup_db() -> None:
    """
    Dọn dẹp DB: Chỉ xóa messages cũ, GIỮ LẠI user_notes.
    Đây là chính sách của bạn.
    """
    await asyncio.to_thread(_cleanup_db_sync)

def _cleanup_db_sync() -> None:
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        old_date = (datetime.now() - timedelta(days=30)).isoformat()
        
        # Dọn dẹp messages (GIỮ LẠI NOTES)
        c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        if c.fetchone():
            c.execute("DELETE FROM messages WHERE timestamp < ?", (old_date, ))
            logger.info("DB cleaned: Old messages deleted (User notes kept).")
        
        conn.commit()
    except sqlite3.DatabaseError as e:
        logger.error(f"Cannot clean DB: {str(e)}. Creating new DB.")
        _init_db_sync() # Gọi hàm sync để tạo lại
    finally:
        if conn:
            conn.close()

async def _ensure_table_exists_and_get_conn(table_name: str) -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    c.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
    if not c.fetchone():
        logger.warning(f"Bảng '{table_name}' không tồn tại, đang khởi tạo lại DB...")
        if conn: conn.close() # Close current connection before init
        await init_db()
        conn = sqlite3.connect(DB_PATH, timeout=10) # Re-open connection after init
    return conn

async def log_message_db(user_id: str, role: str, content: str) -> None:
    conn = None
    try:
        conn = await _ensure_table_exists_and_get_conn("messages")
        c = conn.cursor()
        timestamp = datetime.now().isoformat()
        c.execute(
            "INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, role, content, timestamp))
        conn.commit()
    except sqlite3.DatabaseError as e:
        logger.error(f"Database error while logging message: {str(e)}")
        # If an error occurs even after ensuring table, try to re-init as a last resort
        await init_db()
    finally:
        if conn:
            conn.close()

async def get_user_history_from_db(user_id: str, limit: int = 10) -> List[Dict[str, str]]:
    """
    HÀM MỚI (VÁ LỖI RAM): Lấy lịch sử chat của user từ DB, giới hạn 10 tin nhắn gần nhất.
    """
    conn = None
    history = []
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Đảm bảo bảng messages tồn tại
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
        if not c.fetchone():
            logger.warning("Bảng 'messages' không tồn tại, không thể lấy history.")
            if conn: conn.close()
            await init_db() # Khởi tạo nếu chưa có
            return []

        # Lấy 'limit' tin nhắn cuối cùng
        c.execute(
            "SELECT role, content FROM messages WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit)
        )
        rows = c.fetchall()
        
        # Đảo ngược lại để đúng thứ tự (cũ -> mới) cho Gemini
        for row in reversed(rows):
            history.append({"role": row['role'], "content": row['content']})
            
    except sqlite3.DatabaseError as e:
        logger.error(f"Database error while getting user history: {str(e)}")
    finally:
        if conn:
            conn.close()
    return history


async def add_user_note_db(user_id: str, note_id: str, content: str, metadata: Dict[str, Any]) -> bool:
    """Lưu một note mới vào DB."""
    conn = None
    try:
        conn = await _ensure_table_exists_and_get_conn("user_notes")
        c = conn.cursor()
        created_at = datetime.now().isoformat()
        
        metadata_str = json.dumps(metadata)
        
        c.execute(
            "INSERT INTO user_notes (user_id, note_id, content, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, note_id, content, metadata_str, created_at)
        )
        conn.commit()
        return True
    except sqlite3.DatabaseError as e:
        logger.error(f"Database error while adding user note: {str(e)}")
        await init_db() # Tự động tạo lại bảng nếu thiếu
        return False
    finally:
        if conn:
            conn.close()

# --- HÀM MỚI ---
async def get_file_note_by_filename_db(user_id: str, filename: str) -> Optional[Dict[str, Any]]:
    """
    Lấy một note file dựa trên user_id và filename từ metadata.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute(
            "SELECT note_id, content, metadata, created_at FROM user_notes WHERE user_id = ?",
            (user_id,)
        )
        rows = c.fetchall()
        
        for row in rows:
            try:
                metadata = json.loads(row['metadata'])
                if metadata.get("filename") == filename:
                    return dict(row)
            except json.JSONDecodeError:
                continue # Bỏ qua metadata bị lỗi
        return None
    except sqlite3.DatabaseError as e:
        logger.error(f"Database error while getting file note by filename: {str(e)}")
        return None
    finally:
        if conn:
            conn.close()

async def update_user_note_db(note_id: str, content: str, metadata: dict) -> bool:
    """Cập nhật nội dung và metadata của một note hiện có."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        metadata_str = json.dumps(metadata)
        
        c.execute(
            "UPDATE user_notes SET content = ?, metadata = ?, created_at = ? WHERE note_id = ?",
            (content, metadata_str, datetime.now().isoformat(), note_id)
        )
        conn.commit()
        return True
    except sqlite3.DatabaseError as e:
        logger.error(f"Database error while updating note {note_id}: {str(e)}")
        return False
    finally:
        if conn:
            conn.close()

async def get_user_notes_db(user_id: str, search_query: str = None) -> List[Dict[str, Any]]:
    """Lấy notes của user, có thể lọc bằng LIKE query."""
    conn = None
    notes = []
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row # Trả về kết quả dạng dict
        c = conn.cursor()
        
        # Kiểm tra bảng user_notes
        c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_notes'"
        )
        if not c.fetchone():
            logger.warning("Bảng 'user_notes' không tồn tại, không thể lấy note.")
            await init_db() # Khởi tạo nếu chưa có
            return []

        base_query = "SELECT note_id, content, metadata, created_at FROM user_notes WHERE user_id = ?"
        params: tuple = (user_id,)
        
        if search_query:
            base_query += " AND (content LIKE ? OR metadata LIKE ?)"
            params += (f"%{search_query}%", f"%{search_query}%")
            
        base_query += " ORDER BY created_at DESC LIMIT 20" # Giới hạn 20 note gần nhất
        
        c.execute(base_query, params)
        rows = c.fetchall()
        notes = [dict(row) for row in rows]
        
    except sqlite3.DatabaseError as e:
        logger.error(f"Database error while getting notes: {str(e)}")
    finally:
        if conn:
            conn.close()
    return notes

async def clear_user_data_db(user_id: str) -> bool:
    conn = None
    for attempt in range(3):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            c = conn.cursor()
            
            # Xóa messages (cũ)
            c.execute("DELETE FROM messages WHERE user_id = ?", (user_id, ))
            
            # Xóa notes (MỚI)
            c.execute("DELETE FROM user_notes WHERE user_id = ?", (user_id, ))
            
            conn.commit()
            logger.info(f"User {user_id} history cleared from DB (messages + notes)")
            return True
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                logger.warning(
                    f"Database locked (clear_user_data), retry {attempt + 1}/3"
                )
                await asyncio.sleep(1)
                continue
            logger.error(f"Cannot clear DB history for {user_id}: {str(e)}")
            return False # Thoát vòng lặp nếu lỗi không phải là lock
        except sqlite3.DatabaseError as e:
            logger.error(f"Cannot clear DB history for {user_id}: {str(e)}")
            return False # Thoát vòng lặp
        finally:
            if conn:
                conn.close()
    return False

async def clear_all_data_db() -> bool:
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        
        # Xóa messages (cũ)
        c.execute("DELETE FROM messages")
        
        # Xóa notes (MỚI)
        c.execute("DELETE FROM user_notes")
        
        conn.commit()
        logger.info("ADMIN: Cleared all data (messages + notes tables).")
        return True
    except sqlite3.DatabaseError as e:
        logger.error(f"ADMIN: Failed to clear DB: {e}")
        return False
    finally:
        if conn:
            conn.close()