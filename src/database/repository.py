import sqlite3
import os
import shutil
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from src.core.config import logger, DB_PATH, DB_BACKUP_PATH


class DatabaseRepository:
    """Repository for database operations - handles all SQLite interactions."""
    
    def __init__(self, db_path: str = DB_PATH, backup_path: str = DB_BACKUP_PATH):
        self.db_path = db_path
        self.backup_path = backup_path
        self.logger = logger
    
    async def init_db(self) -> None:
        """Initialize database tables."""
        await asyncio.to_thread(self._init_db_sync)
    
    def _create_tables(self, cursor: sqlite3.Cursor) -> None:
        """Create necessary tables."""
        cursor.execute('''CREATE TABLE IF NOT EXISTS messages
                         (user_id TEXT, role TEXT, content TEXT, timestamp TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS user_notes
                         (user_id TEXT, 
                          note_id TEXT PRIMARY KEY, 
                          content TEXT, 
                          metadata TEXT, 
                          created_at TEXT)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_user_notes_user_id ON user_notes (user_id)''')
    
    def _init_db_sync(self) -> None:
        """Synchronous database initialization."""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            self._create_tables(c)
            conn.commit()
            self.logger.info("DB initialized (messages + user_notes tables)")
        except sqlite3.DatabaseError as e:
            self.logger.error(f"Cannot initialize DB: {str(e)}. Attempting to re-create DB.")
            if conn:
                conn.close()
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            self._create_tables(c)
            conn.commit()
            self.logger.info("New DB created (messages + user_notes tables) after error.")
        finally:
            if conn:
                conn.close()
    
    async def backup_db(self) -> None:
        """Backup database file."""
        await asyncio.to_thread(self._backup_db_sync)
    
    def _backup_db_sync(self) -> None:
        """Synchronous database backup."""
        if os.path.exists(self.db_path):
            try:
                conn = sqlite3.connect(self.db_path, timeout=10)
                try:
                    conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'")
                    shutil.copy2(self.db_path, self.backup_path)
                    self.logger.info(f"DB backed up to {self.backup_path}")
                finally:
                    conn.close()
            except sqlite3.DatabaseError as e:
                self.logger.error(f"Cannot backup DB: {str(e)}. Creating new DB.")
                self._init_db_sync()
            except Exception as e:
                self.logger.error(f"Lỗi không xác định khi backup DB: {e}")
    
    async def cleanup_db(self) -> None:
        """Clean up old messages from database (keeps notes)."""
        await asyncio.to_thread(self._cleanup_db_sync)
    
    def _cleanup_db_sync(self) -> None:
        """Synchronous database cleanup."""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            old_date = (datetime.now() - timedelta(days=30)).isoformat()
            
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
            if c.fetchone():
                c.execute("DELETE FROM messages WHERE timestamp < ?", (old_date, ))
                self.logger.info("DB cleaned: Old messages deleted (User notes kept).")
            
            conn.commit()
        except sqlite3.DatabaseError as e:
            self.logger.error(f"Cannot clean DB: {str(e)}. Creating new DB.")
            self._init_db_sync()
        finally:
            if conn:
                conn.close()
    
    async def _ensure_table_exists_and_get_conn(self, table_name: str) -> sqlite3.Connection:
        """Ensure table exists before getting connection."""
        conn = sqlite3.connect(self.db_path, timeout=10)
        c = conn.cursor()
        c.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        if not c.fetchone():
            self.logger.warning(f"Bảng '{table_name}' không tồn tại, đang khởi tạo lại DB...")
            if conn:
                conn.close()
            await self.init_db()
            conn = sqlite3.connect(self.db_path, timeout=10)
        return conn
    
    async def log_message_db(self, user_id: str, role: str, content: str) -> None:
        """Log a message to the database."""
        conn = None
        try:
            conn = await self._ensure_table_exists_and_get_conn("messages")
            c = conn.cursor()
            timestamp = datetime.now().isoformat()
            c.execute(
                "INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, role, content, timestamp))
            conn.commit()
        except sqlite3.DatabaseError as e:
            self.logger.error(f"Database error while logging message: {str(e)}")
            await self.init_db()
        finally:
            if conn:
                conn.close()
    
    async def get_user_history_from_db(self, user_id: str, limit: int = 10) -> List[Dict[str, str]]:
        """Get user chat history from database."""
        conn = None
        history = []
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
            if not c.fetchone():
                self.logger.warning("Bảng 'messages' không tồn tại, không thể lấy history.")
                if conn:
                    conn.close()
                await self.init_db()
                return []
            
            c.execute(
                "SELECT role, content FROM messages WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit)
            )
            rows = c.fetchall()
            
            for row in reversed(rows):
                history.append({"role": row['role'], "content": row['content']})
        except sqlite3.DatabaseError as e:
            self.logger.error(f"Database error while getting user history: {str(e)}")
        finally:
            if conn:
                conn.close()
        return history
    
    async def add_user_note_db(self, user_id: str, note_id: str, content: str, metadata: Dict[str, Any]) -> bool:
        """Add a user note to the database."""
        conn = None
        try:
            conn = await self._ensure_table_exists_and_get_conn("user_notes")
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
            self.logger.error(f"Database error while adding user note: {str(e)}")
            await self.init_db()
            return False
        finally:
            if conn:
                conn.close()
    
    async def get_file_note_by_filename_db(self, user_id: str, filename: str) -> Optional[Dict[str, Any]]:
        """Get a file note by filename."""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
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
                    continue
            return None
        except sqlite3.DatabaseError as e:
            self.logger.error(f"Database error while getting file note by filename: {str(e)}")
            return None
        finally:
            if conn:
                conn.close()
    
    async def update_user_note_db(self, note_id: str, content: str, metadata: dict) -> bool:
        """Update a user note."""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            metadata_str = json.dumps(metadata)
            
            c.execute(
                "UPDATE user_notes SET content = ?, metadata = ?, created_at = ? WHERE note_id = ?",
                (content, metadata_str, datetime.now().isoformat(), note_id)
            )
            conn.commit()
            return True
        except sqlite3.DatabaseError as e:
            self.logger.error(f"Database error while updating note {note_id}: {str(e)}")
            return False
        finally:
            if conn:
                conn.close()
    
    async def get_user_notes_db(self, user_id: str, search_query: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get user notes with optional search."""
        conn = None
        notes = []
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_notes'")
            if not c.fetchone():
                self.logger.warning("Bảng 'user_notes' không tồn tại, không thể lấy note.")
                await self.init_db()
                return []
            
            base_query = "SELECT note_id, content, metadata, created_at FROM user_notes WHERE user_id = ?"
            params: tuple = (user_id,)
            
            if search_query:
                base_query += " AND (content LIKE ? OR metadata LIKE ?)"
                params += (f"%{search_query}%", f"%{search_query}%")
            
            base_query += " ORDER BY created_at DESC LIMIT 20"
            
            c.execute(base_query, params)
            rows = c.fetchall()
            notes = [dict(row) for row in rows]
        except sqlite3.DatabaseError as e:
            self.logger.error(f"Database error while getting notes: {str(e)}")
        finally:
            if conn:
                conn.close()
        return notes
    
    async def clear_user_data_db(self, user_id: str) -> bool:
        """Clear all user data from database."""
        conn = None
        for attempt in range(3):
            try:
                conn = sqlite3.connect(self.db_path, timeout=10)
                c = conn.cursor()
                
                c.execute("DELETE FROM messages WHERE user_id = ?", (user_id, ))
                c.execute("DELETE FROM user_notes WHERE user_id = ?", (user_id, ))
                
                conn.commit()
                self.logger.info(f"User {user_id} history cleared from DB (messages + notes)")
                return True
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e):
                    self.logger.warning(f"Database locked (clear_user_data), retry {attempt + 1}/3")
                    await asyncio.sleep(1)
                    continue
                self.logger.error(f"Cannot clear DB history for {user_id}: {str(e)}")
                return False
            except sqlite3.DatabaseError as e:
                self.logger.error(f"Cannot clear DB history for {user_id}: {str(e)}")
                return False
            finally:
                if conn:
                    conn.close()
        return False
    
    async def clear_all_data_db(self) -> bool:
        """Clear all data from database."""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            
            c.execute("DELETE FROM messages")
            c.execute("DELETE FROM user_notes")
            
            conn.commit()
            self.logger.info("ADMIN: Cleared all data (messages + notes tables).")
            return True
        except sqlite3.DatabaseError as e:
            self.logger.error(f"ADMIN: Failed to clear DB: {e}")
            return False
        finally:
            if conn:
                conn.close()
