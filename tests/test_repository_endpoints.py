import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg
from dotenv import load_dotenv

load_dotenv()

from src.database.repository import DatabaseRepository

DSN = os.getenv("DATABASE_URL", "postgresql://localhost:5432/azuris")


async def cleanup_test_rows():
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute("DELETE FROM llm_model_slots WHERE updated_by = 'self-test'")
        await conn.execute("DELETE FROM llm_endpoints WHERE updated_by = 'self-test'")
    finally:
        await conn.close()


async def main():
    repo = DatabaseRepository(DSN)
    await repo.init_db()

    conn = await asyncpg.connect(DSN)
    try:
        tables = await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        names = {row["table_name"] for row in tables}
        assert "llm_endpoints" in names, "llm_endpoints chưa được tạo"
        assert "llm_model_slots" in names, "llm_model_slots chưa được tạo"
        legacy_tables = {
            "api_key_pool",
            "api_key_rate_limits",
            "custom_api_models",
            "bot_model_config",
            "custom_api_provider_config",
            "_deprecated_api_key_pool",
            "_deprecated_api_key_rate_limits",
            "_deprecated_custom_api_models",
            "_deprecated_bot_model_config",
            "_deprecated_custom_api_provider_config",
        }
        assert not (legacy_tables & names), f"Bảng key-rotation cũ chưa bị xóa: {legacy_tables & names}"
    finally:
        await conn.close()

    endpoints = await repo.get_llm_endpoints()
    assert isinstance(endpoints, dict)
    active = await repo.get_active_sdk()
    assert active in (None, "genai", "openai")
    slots_genai = await repo.get_llm_model_slots("genai")
    assert isinstance(slots_genai, dict)

    already_configured = bool(endpoints) or bool(active) or any(slots_genai.values())
    if already_configured:
        print("SKIP write-test: DB đã có cấu hình thật")
    else:
        await cleanup_test_rows()
        await repo.upsert_llm_endpoint("genai", "https://example.test", "plain:test-key", "self-test")
        await repo.upsert_llm_model_slots(
            "genai",
            {"reasoning": "m-reasoning", "final": "m-final", "fallback": None},
            "self-test",
        )
        ok = await repo.set_active_sdk("genai", "self-test")
        assert ok is True

        eps = await repo.get_llm_endpoints()
        assert eps["genai"]["base_url"] == "https://example.test"
        assert await repo.get_active_sdk() == "genai"
        assert (await repo.get_llm_model_slots("genai")).get("final") == "m-final"

        await repo.update_endpoint_check_status("genai", True, None)
        eps2 = await repo.get_llm_endpoints()
        assert eps2["genai"]["last_check_ok"] is True

        await cleanup_test_rows()
        assert "genai" not in (await repo.get_llm_endpoints())
        print("WRITE-TEST PASS")

    await repo.close()
    print("ALL PASS")


def test_repository_endpoints():
    try:
        asyncio.run(main())
    except (ConnectionRefusedError, OSError, Exception) as e:
        # If DB connection failed, skip test gracefully if DB offline
        if "connect" in str(e).lower() or "connection" in str(e).lower() or isinstance(e, (ConnectionRefusedError, OSError)):
            import pytest
            pytest.skip(f"PostgreSQL not available: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
