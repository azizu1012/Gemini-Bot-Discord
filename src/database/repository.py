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
        db_dir = os.path.dirname(self.db_path)
        backup_dir = os.path.dirname(self.backup_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        if backup_dir:
            os.makedirs(backup_dir, exist_ok=True)
    
    async def init_db(self) -> None:
        """Initialize database tables."""
        await asyncio.to_thread(self._init_db_sync)
    
    def _create_tables(self, cursor: sqlite3.Cursor) -> None:
        """Create necessary tables with the latest schema."""
        cursor.execute('''CREATE TABLE IF NOT EXISTS messages
                         (user_id TEXT, role TEXT, content TEXT, timestamp TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS user_notes
                         (user_id TEXT,
                          note_id TEXT PRIMARY KEY,
                          content TEXT,
                          metadata TEXT,
                          created_at TEXT,
                          scope TEXT DEFAULT 'user',
                          importance INTEGER DEFAULT 0,
                          updated_at TEXT,
                          is_active INTEGER DEFAULT 1,
                          note_type TEXT DEFAULT 'personal_preference',
                          fact_hash TEXT DEFAULT '')''')

        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_messages_user_ts ON messages (user_id, timestamp)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_user_notes_user_id ON user_notes (user_id)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_user_notes_user_created ON user_notes (user_id, created_at)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_user_notes_scope_created ON user_notes (scope, created_at)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_user_notes_user_active_created ON user_notes (user_id, is_active, created_at)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_user_notes_fact_hash ON user_notes (fact_hash)''')

    def _schema_is_fresh_compatible(self, cursor: sqlite3.Cursor) -> bool:
        """Validate expected columns for the current schema."""
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_notes'")
        if not cursor.fetchone():
            return False

        cursor.execute("PRAGMA table_info(user_notes)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {
            'user_id',
            'note_id',
            'content',
            'metadata',
            'created_at',
            'scope',
            'importance',
            'updated_at',
            'is_active',
            'note_type',
            'fact_hash',
        }
        return expected.issubset(columns)
    
    def _init_db_sync(self) -> None:
        """Synchronous database initialization."""
        conn = None
        try:
            db_dir = os.path.dirname(self.db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            self._create_tables(c)
            if not self._schema_is_fresh_compatible(c):
                raise sqlite3.DatabaseError("Legacy/invalid schema detected")
            conn.commit()
            self.logger.info("DB initialized with fresh schema (messages + user_notes tables)")
        except sqlite3.DatabaseError as e:
            self.logger.error(f"Cannot initialize DB with current schema: {str(e)}. Rebuilding DB file.")
            if conn:
                conn.close()
            self._rebuild_db_sync()
        finally:
            if conn:
                conn.close()

    def _rebuild_db_sync(self) -> None:
        """Recreate DB file from scratch using current schema."""
        conn = None
        try:
            db_dir = os.path.dirname(self.db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)

            if os.path.exists(self.db_path):
                broken_copy = f"{self.db_path}.broken.{datetime.now().strftime('%Y%m%d%H%M%S')}"
                try:
                    shutil.move(self.db_path, broken_copy)
                    self.logger.warning(f"Moved incompatible DB to {broken_copy}")
                except Exception:
                    os.remove(self.db_path)
                    self.logger.warning("Removed incompatible DB file.")

            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            self._create_tables(c)
            conn.commit()
            self.logger.info("Created fresh DB with latest schema.")
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
        last_error: Optional[Exception] = None

        for attempt in range(3):
            conn: Optional[sqlite3.Connection] = None
            try:
                conn = sqlite3.connect(self.db_path, timeout=10)
                c = conn.cursor()
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
                table_exists = bool(c.fetchone())
                schema_ok = self._schema_is_fresh_compatible(c)

                if not table_exists or not schema_ok:
                    self.logger.warning(f"DB schema/table missing for '{table_name}', reinitializing fresh DB...")
                    conn.close()
                    await self.init_db()
                    conn = sqlite3.connect(self.db_path, timeout=10)
                    c = conn.cursor()
                    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
                    if not c.fetchone():
                        raise sqlite3.DatabaseError(f"Table {table_name} still missing after init")

                return conn

            except sqlite3.OperationalError as e:
                last_error = e
                if conn:
                    conn.close()
                if "database is locked" in str(e).lower() and attempt < 2:
                    self.logger.warning(f"DB locked while ensuring table {table_name}, retry {attempt + 1}/3")
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                self.logger.error(f"DB operational error while ensuring table {table_name}: {e}")
                break

            except sqlite3.DatabaseError as e:
                last_error = e
                if conn:
                    conn.close()
                self.logger.error(f"DB schema check failed while ensuring table {table_name}: {e}")
                if attempt < 2:
                    await self.init_db()
                    continue
                break

        if isinstance(last_error, Exception):
            raise last_error

        return sqlite3.connect(self.db_path, timeout=10)
    
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
    
    def _get_user_history_from_db_sync(self, user_id: str, limit: int = 10) -> List[Dict[str, str]]:
        conn = None
        history = []
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()

            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
            if not c.fetchone():
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

    async def get_user_history_from_db(self, user_id: str, limit: int = 10) -> List[Dict[str, str]]:
        """Get user chat history from database."""
        history = await asyncio.to_thread(self._get_user_history_from_db_sync, user_id, limit)
        if history:
            return history

        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
            if not c.fetchone():
                self.logger.warning("Bảng 'messages' không tồn tại, không thể lấy history.")
                await self.init_db()
        except sqlite3.DatabaseError:
            pass
        finally:
            if conn:
                conn.close()
        return history
    
    async def add_user_note_db(
        self,
        user_id: str,
        note_id: str,
        content: str,
        metadata: Dict[str, Any],
        scope: str = "user",
        importance: int = 0,
        note_type: str = "personal_preference",
        fact_hash: str = "",
    ) -> bool:
        """Add a user note to the database."""
        conn = None
        try:
            conn = await self._ensure_table_exists_and_get_conn("user_notes")
            c = conn.cursor()
            created_at = datetime.now().isoformat()
            metadata_str = json.dumps(metadata)

            c.execute(
                """INSERT INTO user_notes
                (user_id, note_id, content, metadata, created_at, updated_at, scope, importance, is_active, note_type, fact_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (user_id, note_id, content, metadata_str, created_at, created_at, scope, importance, note_type, fact_hash)
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
    
    def _get_file_note_by_filename_sync(self, user_id: str, filename: str) -> Optional[Dict[str, Any]]:
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

    async def get_file_note_by_filename_db(self, user_id: str, filename: str) -> Optional[Dict[str, Any]]:
        """Get a file note by filename."""
        return await asyncio.to_thread(self._get_file_note_by_filename_sync, user_id, filename)
    
    def _update_user_note_sync(self, note_id: str, content: str, metadata: dict) -> bool:
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            metadata_str = json.dumps(metadata)

            c.execute(
                "UPDATE user_notes SET content = ?, metadata = ?, updated_at = ? WHERE note_id = ?",
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

    async def update_user_note_db(self, note_id: str, content: str, metadata: dict) -> bool:
        """Update a user note."""
        return await asyncio.to_thread(self._update_user_note_sync, note_id, content, metadata)
    
    def _get_user_notes_sync(
        self,
        user_id: str,
        search_query: Optional[str] = None,
        include_global: bool = False,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        conn = None
        notes = []
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()

            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_notes'")
            if not c.fetchone():
                return []

            if include_global:
                base_query = (
                    "SELECT note_id, content, metadata, created_at, updated_at, scope, importance, note_type, fact_hash "
                    "FROM user_notes WHERE is_active = 1 AND (user_id = ? OR scope = 'global')"
                )
            else:
                base_query = (
                    "SELECT note_id, content, metadata, created_at, updated_at, scope, importance, note_type, fact_hash "
                    "FROM user_notes WHERE is_active = 1 AND user_id = ?"
                )
            params: tuple = (user_id,)

            if search_query:
                base_query += " AND (content LIKE ? OR metadata LIKE ?)"
                params += (f"%{search_query}%", f"%{search_query}%")

            safe_limit = max(1, min(limit, 100))
            base_query += " ORDER BY importance DESC, COALESCE(updated_at, created_at) DESC LIMIT ?"
            params += (safe_limit,)

            c.execute(base_query, params)
            rows = c.fetchall()
            notes = [dict(row) for row in rows]
        except sqlite3.DatabaseError as e:
            self.logger.error(f"Database error while getting notes: {str(e)}")
        finally:
            if conn:
                conn.close()
        return notes

    async def get_user_notes_db(
        self,
        user_id: str,
        search_query: Optional[str] = None,
        include_global: bool = False,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Get user notes with optional search."""
        notes = await asyncio.to_thread(self._get_user_notes_sync, user_id, search_query, include_global, limit)
        if notes:
            return notes

        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_notes'")
            if not c.fetchone():
                self.logger.warning("Bảng 'user_notes' không tồn tại, không thể lấy note.")
                await self.init_db()
        except sqlite3.DatabaseError:
            pass
        finally:
            if conn:
                conn.close()
        return notes

    def _count_distinct_users_by_fact_hash_sync(self, fact_hash: str) -> int:
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            c.execute(
                """SELECT COUNT(DISTINCT user_id)
                FROM user_notes
                WHERE is_active = 1 AND note_type = 'global_knowledge' AND fact_hash = ?""",
                (fact_hash,)
            )
            row = c.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        except sqlite3.DatabaseError as e:
            self.logger.error(f"Database error while counting fact_hash users: {str(e)}")
            return 0
        finally:
            if conn:
                conn.close()

    async def count_distinct_users_by_fact_hash_db(self, fact_hash: str) -> int:
        return await asyncio.to_thread(self._count_distinct_users_by_fact_hash_sync, fact_hash)

    def _promote_fact_hash_to_global_sync(self, fact_hash: str) -> int:
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            c.execute(
                """UPDATE user_notes
                SET scope = 'global', updated_at = ?
                WHERE is_active = 1 AND note_type = 'global_knowledge' AND fact_hash = ?""",
                (datetime.now().isoformat(), fact_hash)
            )
            conn.commit()
            return c.rowcount if c.rowcount is not None else 0
        except sqlite3.DatabaseError as e:
            self.logger.error(f"Database error while promoting fact_hash to global: {str(e)}")
            return 0
        finally:
            if conn:
                conn.close()

    async def promote_fact_hash_to_global_db(self, fact_hash: str) -> int:
        return await asyncio.to_thread(self._promote_fact_hash_to_global_sync, fact_hash)

    def _get_global_notes_sync(self, limit: int = 20) -> List[Dict[str, Any]]:
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            safe_limit = max(1, min(limit, 100))
            c.execute(
                """SELECT note_id, user_id, content, created_at, updated_at, scope, importance, note_type, fact_hash
                FROM user_notes
                WHERE is_active = 1 AND scope = 'global'
                ORDER BY COALESCE(updated_at, created_at) DESC
                LIMIT ?""",
                (safe_limit,)
            )
            rows = c.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.DatabaseError as e:
            self.logger.error(f"Database error while listing global notes: {str(e)}")
            return []
        finally:
            if conn:
                conn.close()

    async def get_global_notes_db(self, limit: int = 20) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._get_global_notes_sync, limit)

    def _demote_global_note_by_id_sync(self, note_id: str) -> bool:
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            c.execute(
                """UPDATE user_notes
                SET scope = 'user', updated_at = ?
                WHERE note_id = ? AND scope = 'global'""",
                (datetime.now().isoformat(), note_id)
            )
            conn.commit()
            return (c.rowcount or 0) > 0
        except sqlite3.DatabaseError as e:
            self.logger.error(f"Database error while demoting global note by id: {str(e)}")
            return False
        finally:
            if conn:
                conn.close()

    async def demote_global_note_by_id_db(self, note_id: str) -> bool:
        return await asyncio.to_thread(self._demote_global_note_by_id_sync, note_id)

    def _demote_global_fact_hash_sync(self, fact_hash: str) -> int:
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            c = conn.cursor()
            c.execute(
                """UPDATE user_notes
                SET scope = 'candidate_global', updated_at = ?
                WHERE is_active = 1 AND scope = 'global' AND fact_hash = ?""",
                (datetime.now().isoformat(), fact_hash)
            )
            conn.commit()
            return c.rowcount or 0
        except sqlite3.DatabaseError as e:
            self.logger.error(f"Database error while demoting global notes by fact_hash: {str(e)}")
            return 0
        finally:
            if conn:
                conn.close()

    async def demote_global_fact_hash_db(self, fact_hash: str) -> int:
        return await asyncio.to_thread(self._demote_global_fact_hash_sync, fact_hash)

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
    
    def _clear_all_data_sync(self) -> bool:
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

    async def clear_all_data_db(self) -> bool:
        """Clear all data from database."""
        return await asyncio.to_thread(self._clear_all_data_sync)
