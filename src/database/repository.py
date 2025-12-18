"""
Database Repository Pattern
Tách biệt logic truy cập database khỏi business logic
"""
import sqlite3
import os
import shutil
import json
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod

from core.config import config
from core.logger import logger


class IMessageRepository(ABC):
    """Interface cho Message Repository"""
    
    @abstractmethod
    async def log_message(self, user_id: str, role: str, content: str) -> None:
        """Log một message vào database"""
        pass
    
    @abstractmethod
    async def get_user_history(self, user_id: str, limit: int = 10) -> List[Dict[str, str]]:
        """Lấy lịch sử chat của user"""
        pass
    
    @abstractmethod
    async def clear_user_data(self, user_id: str) -> bool:
        """Xóa toàn bộ dữ liệu của user"""
        pass
    
    @abstractmethod
    async def clear_all_data(self) -> bool:
        """Xóa toàn bộ dữ liệu"""
        pass


class INoteRepository(ABC):
    """Interface cho Note Repository"""
    
    @abstractmethod
    async def add_note(self, user_id: str, note_id: str, content: str, metadata: Dict[str, Any]) -> bool:
        """Thêm một note mới"""
        pass
    
    @abstractmethod
    async def get_note_by_filename(self, user_id: str, filename: str) -> Optional[Dict[str, Any]]:
        """Lấy note theo filename"""
        pass
    
    @abstractmethod
    async def update_note(self, note_id: str, content: str, metadata: Dict[str, Any]) -> bool:
        """Cập nhật note"""
        pass
    
    @abstractmethod
    async def get_user_notes(self, user_id: str, search_query: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lấy notes của user"""
        pass


class DatabaseRepository(IMessageRepository, INoteRepository):
    """
    Repository Pattern Implementation
    Quản lý tất cả các thao tác database
    """
    
    def __init__(self):
        self.db_path = config.DB_PATH
        self.db_backup_path = config.DB_BACKUP_PATH
        self._initialized = False
    
    async def initialize(self) -> None:
        """Khởi tạo database và tạo các bảng cần thiết"""
        if self._initialized:
            return
        
        await asyncio.to_thread(self._init_db_sync)
        self._initialized = True
    
    def _init_db_sync(self) -> None:
        """Khởi tạo database (sync)"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            self._create_tables(c)
            conn.commit()
            logger.info("DB initialized (messages + user_notes tables)")
        except sqlite3.DatabaseError as e:
            logger.error(f"Cannot initialize DB: {str(e)}. Attempting to re-create DB.")
            if conn:
                conn.close()
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            self._create_tables(c)
            conn.commit()
            logger.info("New DB created (messages + user_notes tables) after error.")
        finally:
            if conn:
                conn.close()
    
    def _create_tables(self, cursor: sqlite3.Cursor) -> None:
        """Tạo các bảng trong database"""
        cursor.execute('''CREATE TABLE IF NOT EXISTS messages
                         (user_id TEXT, role TEXT, content TEXT, timestamp TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS user_notes
                         (user_id TEXT, 
                          note_id TEXT PRIMARY KEY, 
                          content TEXT, 
                          metadata TEXT, 
                          created_at TEXT)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_user_notes_user_id ON user_notes (user_id)''')
    
    async def backup(self) -> None:
        """Backup database"""
        await asyncio.to_thread(self._backup_db_sync)
    
    def _backup_db_sync(self) -> None:
        """Backup database (sync)"""
        if os.path.exists(self.db_path):
            try:
                conn = sqlite3.connect(self.db_path, timeout=10)
                try:
                    conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'")
                    shutil.copy2(self.db_path, self.db_backup_path)
                    logger.info(f"DB backed up to {self.db_backup_path}")
                finally:
                    conn.close()
            except sqlite3.DatabaseError as e:
                logger.error(f"Cannot backup DB: {str(e)}. Creating new DB.")
                self._init_db_sync()
            except Exception as e:
                logger.error(f"Lỗi không xác định khi backup DB: {e}")
    
    async def cleanup(self) -> None:
        """Dọn dẹp database: Xóa messages cũ, giữ lại notes"""
        await asyncio.to_thread(self._cleanup_db_sync)
    
    def _cleanup_db_sync(self) -> None:
        """Dọn dẹp database (sync)"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            old_date = (datetime.now() - timedelta(days=30)).isoformat()
            
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
            if c.fetchone():
                c.execute("DELETE FROM messages WHERE timestamp < ?", (old_date,))
                logger.info("DB cleaned: Old messages deleted (User notes kept).")
            
            conn.commit()
        except sqlite3.DatabaseError as e:
            logger.error(f"Cannot clean DB: {str(e)}. Creating new DB.")
            self._init_db_sync()
        finally:
            if conn:
                conn.close()
    
    async def _ensure_table_exists(self, table_name: str) -> sqlite3.Connection:
        """Đảm bảo bảng tồn tại, nếu không thì tạo lại"""
        conn = sqlite3.connect(self.db_path, timeout=10)
        c = conn.cursor()
        c.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        if not c.fetchone():
            logger.warning(f"Bảng '{table_name}' không tồn tại, đang khởi tạo lại DB...")
            if conn:
                conn.close()
            await self.initialize()
            conn = sqlite3.connect(self.db_path, timeout=10)
        return conn
    
    # IMessageRepository Implementation
    async def log_message(self, user_id: str, role: str, content: str) -> None:
        """Log một message vào database"""
        conn = None
        try:
            conn = await self._ensure_table_exists("messages")
            c = conn.cursor()
            timestamp = datetime.now().isoformat()
            c.execute(
                "INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, role, content, timestamp)
            )
            conn.commit()
        except sqlite3.DatabaseError as e:
            logger.error(f"Database error while logging message: {str(e)}")
            await self.initialize()
        finally:
            if conn:
                conn.close()
    
    async def get_user_history(self, user_id: str, limit: int = 10) -> List[Dict[str, str]]:
        """Lấy lịch sử chat của user"""
        conn = None
        history = []
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
            if not c.fetchone():
                logger.warning("Bảng 'messages' không tồn tại, không thể lấy history.")
                if conn:
                    conn.close()
                await self.initialize()
                return []
            
            c.execute(
                "SELECT role, content FROM messages WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit)
            )
            rows = c.fetchall()
            
            for row in reversed(rows):
                history.append({"role": row['role'], "content": row['content']})
                
        except sqlite3.DatabaseError as e:
            logger.error(f"Database error while getting user history: {str(e)}")
        finally:
            if conn:
                conn.close()
        return history
    
    async def clear_user_data(self, user_id: str) -> bool:
        """Xóa toàn bộ dữ liệu của user"""
        conn = None
        for attempt in range(3):
            try:
                conn = sqlite3.connect(self.db_path, timeout=10)
                c = conn.cursor()
                
                c.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
                c.execute("DELETE FROM user_notes WHERE user_id = ?", (user_id,))
                
                conn.commit()
                logger.info(f"User {user_id} history cleared from DB (messages + notes)")
                return True
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e):
                    logger.warning(f"Database locked (clear_user_data), retry {attempt + 1}/3")
                    await asyncio.sleep(1)
                    continue
                logger.error(f"Cannot clear DB history for {user_id}: {str(e)}")
                return False
            except sqlite3.DatabaseError as e:
                logger.error(f"Cannot clear DB history for {user_id}: {str(e)}")
                return False
            finally:
                if conn:
                    conn.close()
        return False
    
    async def clear_all_data(self) -> bool:
        """Xóa toàn bộ dữ liệu"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            
            c.execute("DELETE FROM messages")
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
    
    # INoteRepository Implementation
    async def add_note(self, user_id: str, note_id: str, content: str, metadata: Dict[str, Any]) -> bool:
        """Thêm một note mới"""
        conn = None
        try:
            conn = await self._ensure_table_exists("user_notes")
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
            await self.initialize()
            return False
        finally:
            if conn:
                conn.close()
    
    async def get_note_by_filename(self, user_id: str, filename: str) -> Optional[Dict[str, Any]]:
        """Lấy note theo filename"""
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
            logger.error(f"Database error while getting file note by filename: {str(e)}")
            return None
        finally:
            if conn:
                conn.close()
    
    async def update_note(self, note_id: str, content: str, metadata: Dict[str, Any]) -> bool:
        """Cập nhật note"""
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
            logger.error(f"Database error while updating note {note_id}: {str(e)}")
            return False
        finally:
            if conn:
                conn.close()
    
    async def get_user_notes(self, user_id: str, search_query: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lấy notes của user"""
        conn = None
        notes = []
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_notes'")
            if not c.fetchone():
                logger.warning("Bảng 'user_notes' không tồn tại, không thể lấy note.")
                await self.initialize()
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
            logger.error(f"Database error while getting notes: {str(e)}")
        finally:
            if conn:
                conn.close()
        return notes


# Global repository instance
db_repository = DatabaseRepository()

