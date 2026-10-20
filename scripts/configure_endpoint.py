"""Cấu hình endpoint LLM + 3 model slot trực tiếp vào PostgreSQL.

Dùng khi không thể thao tác qua Discord UI (`/endpoint config`), hoặc để khôi phục
cấu hình sau khi database bị xoá/trống.

Ví dụ (router_api nội bộ, giao thức OpenAI-compatible):

    python scripts/configure_endpoint.py \
        --sdk openai \
        --base-url http://127.0.0.1:58100/v1 \
        --api-key <router-key> \
        --reasoning gemini-flash \
        --final gemini-flash \
        --fallback gemini-flash-lite

Xem cấu hình hiện tại:

    python scripts/configure_endpoint.py --show
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import asyncpg  # noqa: E402

from src.core.config import config  # noqa: E402
from src.core.llm.endpoint_url import validate_endpoint_url  # noqa: E402
from src.core.llm.resolver import (  # noqa: E402
    decrypt_api_key,
    encrypt_api_key,
    is_valid_fernet_key,
    mask_api_key,
    normalize_base_url,
)

SDKS = ("openai", "genai")
SLOTS = ("reasoning", "final", "fallback")


def _database_url(explicit: str | None) -> str:
    url = explicit or (getattr(config, "DATABASE_URL", "") or os.getenv("DATABASE_URL", "")).strip()
    if not url:
        raise SystemExit("Thiếu DATABASE_URL (truyền --database-url hoặc set trong .env).")
    return url


async def show(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            "SELECT sdk, base_url, api_key_encrypted, is_active, last_check_ok, last_check_error, updated_by, updated_at "
            "FROM llm_endpoints ORDER BY sdk"
        )
        if not rows:
            print("(database trống — chưa có endpoint nào)")
        for row in rows:
            key = decrypt_api_key(
                row["api_key_encrypted"] or "", getattr(config, "DONATE_ENCRYPTION_KEY", "") or ""
            )
            print(f"\n[{row['sdk']}]{'  <-- ACTIVE' if row['is_active'] else ''}")
            print(f"  base_url : {row['base_url']}")
            print(f"  api_key  : {mask_api_key(key)}")
            print(f"  updated  : {row['updated_at']} by {row['updated_by']}")
            print(f"  last ok  : {row['last_check_ok']} / error: {row['last_check_error']}")
            slots = await conn.fetch(
                "SELECT slot, model_id FROM llm_model_slots WHERE sdk = $1 ORDER BY slot", row["sdk"]
            )
            for slot in slots:
                print(f"  {slot['slot']:<10}: {slot['model_id']}")
    finally:
        await conn.close()


async def save(args: argparse.Namespace, url: str) -> None:
    if args.sdk not in SDKS:
        raise SystemExit(f"SDK không hợp lệ: {args.sdk}. Chọn một trong {SDKS}.")

    base_url = normalize_base_url(args.sdk, args.base_url)
    url_ok, url_error = validate_endpoint_url(base_url)
    if not url_ok:
        raise SystemExit(f"Base URL không hợp lệ: {url_error}")

    if not args.api_key:
        raise SystemExit("Thiếu --api-key.")

    slots = {slot: getattr(args, slot) for slot in SLOTS if getattr(args, slot) is not None}
    if not slots:
        raise SystemExit("Cần ít nhất một slot (--reasoning/--final/--fallback).")

    fernet_key = getattr(config, "DONATE_ENCRYPTION_KEY", "") or ""
    if not fernet_key and not getattr(config, "ALLOW_PLAINTEXT_ENDPOINT_KEYS", False):
        raise SystemExit(
            "Chưa cấu hình DONATE_ENCRYPTION_KEY nên từ chối lưu API key dạng plaintext. "
            "Đặt DONATE_ENCRYPTION_KEY hoặc ALLOW_PLAINTEXT_ENDPOINT_KEYS=true nếu chấp nhận rủi ro."
        )
    if fernet_key and not is_valid_fernet_key(fernet_key):
        raise SystemExit("DONATE_ENCRYPTION_KEY không hợp lệ. Tạo key Fernet mới rồi thử lại.")

    encrypted = encrypt_api_key(args.api_key, fernet_key)

    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            if args.active:
                await conn.execute("UPDATE llm_endpoints SET is_active = FALSE WHERE is_active = TRUE")
            await conn.execute(
                """
                INSERT INTO llm_endpoints (sdk, base_url, api_key_encrypted, is_active, updated_by, updated_at)
                VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                ON CONFLICT (sdk) DO UPDATE SET
                    base_url = EXCLUDED.base_url,
                    api_key_encrypted = EXCLUDED.api_key_encrypted,
                    is_active = EXCLUDED.is_active,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                args.sdk,
                base_url,
                encrypted,
                bool(args.active),
                "cli:configure_endpoint",
            )
            for slot, model_id in slots.items():
                await conn.execute(
                    """
                    INSERT INTO llm_model_slots (sdk, slot, model_id, updated_by, updated_at)
                    VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                    ON CONFLICT (sdk, slot) DO UPDATE SET
                        model_id = EXCLUDED.model_id,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    args.sdk,
                    slot,
                    model_id or None,
                    "cli:configure_endpoint",
                )
    finally:
        await conn.close()

    print(f"✅ Đã lưu endpoint `{args.sdk}`")
    print(f"   base_url: {base_url}")
    print(f"   api_key : {mask_api_key(args.api_key)}")
    print(f"   active  : {bool(args.active)}")
    for slot in SLOTS:
        if slot in slots:
            print(f"   {slot:<10}: {slots[slot]}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cấu hình endpoint LLM trực tiếp trong PostgreSQL.")
    parser.add_argument("--sdk", choices=SDKS, help="SDK của endpoint")
    parser.add_argument("--base-url", help="Base URL, ví dụ http://127.0.0.1:58100/v1")
    parser.add_argument("--api-key", help="API key (sẽ được mã hóa Fernet nếu có DONATE_ENCRYPTION_KEY)")
    parser.add_argument("--reasoning", help="Model id cho slot reasoning")
    parser.add_argument("--final", help="Model id cho slot final")
    parser.add_argument("--fallback", help="Model id cho slot fallback")
    parser.add_argument("--database-url", help="Ghi đè DATABASE_URL")
    parser.add_argument("--no-active", dest="active", action="store_false", help="Không đặt làm SDK active")
    parser.add_argument("--show", action="store_true", help="Chỉ hiển thị cấu hình hiện tại")
    parser.set_defaults(active=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    url = _database_url(args.database_url)

    if args.show:
        asyncio.run(show(url))
        return

    if not args.sdk or not args.base_url or not args.api_key:
        raise SystemExit("Cần --sdk, --base-url và --api-key (hoặc dùng --show).")

    asyncio.run(save(args, url))


if __name__ == "__main__":
    main()
