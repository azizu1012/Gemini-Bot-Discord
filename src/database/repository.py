"""Direct asyncpg repository composed of domain-specific mixins."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

import asyncpg  # type: ignore[reportMissingImports]

from src.core.config import logger
from src.database.mixins import (
    SchemaMixin,
    StateMixin,
    RolesMixin,
    AuditMixin,
    ChatMixin,
    NotesMixin,
    EndpointsMixin,
)


class DatabaseRepository(
    SchemaMixin,
    StateMixin,
    RolesMixin,
    AuditMixin,
    ChatMixin,
    NotesMixin,
    EndpointsMixin,
):
    """Direct asyncpg repository composed of domain-specific mixins."""

    def __init__(self, db_url: str = os.getenv("DATABASE_URL", "postgresql://localhost:5432/azuris")):
        self.db_url = db_url
        self.logger = logger
        self.pool: Optional[asyncpg.Pool] = None
        self._init_lock = asyncio.Lock()
        self._schema_ready = False

    async def init_db(self) -> None:
        if self.pool is not None and self._schema_ready:
            return

        async with self._init_lock:
            if self.pool is None:
                async def init_connection(conn):
                    # Register JSON/JSONB codecs for automatic python dict <-> postgres jsonb translation
                    await conn.set_type_codec(
                        "json",
                        encoder=json.dumps,
                        decoder=json.loads,
                        schema="pg_catalog"
                    )
                    await conn.set_type_codec(
                        "jsonb",
                        encoder=json.dumps,
                        decoder=json.loads,
                        schema="pg_catalog"
                    )

                self.pool = await asyncpg.create_pool(
                    dsn=self.db_url,
                    min_size=2,
                    max_size=10,
                    max_inactive_connection_lifetime=300.0,
                    command_timeout=60.0,
                    ssl=False,
                    init=init_connection,
                )
            if not self._schema_ready:
                await self._initialize_schema()
                self._schema_ready = True

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
            self._schema_ready = False

    async def _ensure_pool(self) -> asyncpg.Pool:
        await self.init_db()
        if self.pool is None:
            raise RuntimeError("Database pool is not initialized")
        return self.pool

    @staticmethod
    def _command_count(command_tag: str) -> int:
        try:
            return int(str(command_tag).split()[-1])
        except (IndexError, TypeError, ValueError):
            return 0
