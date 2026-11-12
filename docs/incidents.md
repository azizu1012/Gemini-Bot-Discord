# Sự cố & Chẩn đoán (Incident Reports)

> ⚠️ Tài liệu lịch sử: các sự cố liên quan key pool / router (INC-004...) đã lỗi thời từ bản endpoint-only (2026-10-20). Xem [`deprecated.md`](deprecated.md).

> Tài liệu này ghi lại các sự cố đã gặp, nguyên nhân gốc rễ, cách khắc phục, và kinh nghiệm để hỗ trợ bảo trì về sau. Cả con người và AI Agent đều có thể tra cứu.

---

## INC-001: Worker CPU 100% + Bot không hồi đáp

**Ngày:** 2026-07-05
**Mức độ:** Critical — bot online nhưng không phản hồi bất kỳ tin nhắn nào.

### Triệu chứng (Symptoms)
- Worker process (Python) sử dụng ~100% CPU (383s CPU trong 5 phút runtime).
- Bot nhận tin nhắn từ Discord và publish vào Redis Stream `discord-incoming` thành công (log `[REDIS-SEND]`).
- Worker không có log `[REDIS-RECV]` — không consume được message từ stream.
- `XPENDING` trên stream `discord-incoming` = 0, nhưng `XLEN` = 1 (message tồn tại nhưng chưa được đọc).
- Không có error log nào từ Redis consumer (vòng lặp chạy không exception).

### Nguyên nhân gốc rễ (Root Cause)

**File:** `src/services/redis_service.py` — method `RedisStreamConsumer.__anext__()`

```python
# Code cũ (bug)
result = await self._redis.xreadgroup(..., {self._stream: '0'}, ...)  # pending
if not result:  # ← BUG: [[stream, []]] là truthy!
    result = await self._redis.xreadgroup(..., {self._stream: '>'}, ...)  # new
    if not result:
        await asyncio.sleep(0.05)
        continue
```

Khi gọi `xreadgroup` với `'0'` (pending messages) trên stream không có pending entries, redis-py trả về:
```python
[[b'discord-incoming', []]]  # List chứa tuple (stream, empty_entries_list)
```

Giá trị này là **truthy** (`bool(...) = True`), nên `if not result:` bỏ qua nhánh đọc `'>'`. Code vào vòng lặp `for stream_entry in result`, nhưng `entries` rỗng → inner `for` không chạy → **loop về `while` không có `await`/`sleep`** → **spin loop 100% CPU**.

Message mới trong stream không bao giờ được đọc.

### Cách khắc phục (Fix)

**Sửa đổi tại `src/services/redis_service.py`:**

1. Xoá bỏ hoàn toàn việc đọc `'0'` (pending) trong `__anext__`.
2. `__anext__` chỉ đọc `'>'` (new messages) với `block=2000`.
3. Pending reclaim chỉ chạy một lần tại `start_worker()` qua `reclaim_pending()`, không lặp lại.

```python
# Code mới (fixed)
async def __anext__(self) -> _RedisMsg:
    while self._running:
        try:
            result = await self._redis.xreadgroup(
                self._group, self._consumer_name,
                {self._stream: '>'},  # chỉ đọc new messages
                count=1, block=2000,
            )
            if not result:
                await asyncio.sleep(0.05)
                continue
            # xử lý entries...
```

### Tác dụng phụ (Side Effects)
- Bot hồi đáp tin nhắn trở lại.
- Worker dùng ~0-1% CPU khi idle (chỉ block trên `xreadgroup`).
- Tin nhắn cũ trong stream bị mất (đã xoá stream để restart sạch).

---

## INC-002: Message bị re-read vô hạn (cùng một message chạy nhiều lần)

**Ngày:** 2026-07-05
**Mức độ:** Critical — Worker dispatch task cho cùng message hàng chục lần/giây.

### Triệu chứng
- Log xuất hiện `[REDIS-RECV]` cho cùng `MsgID` liên tục trong cùng mili-giây.
- CPU vẫn cao dù đã fix INC-001.
- Bot gửi typing indicator liên tục (vì mỗi lần re-read → typing signal mới).

### Nguyên nhân gốc rễ

**Thiết kế loop sai ở `message_handler.py:292-293`:**

```python
async for msg in consumer:         # consumer.__anext__()
    asyncio.create_task(self.process_message(msg))  # fire-and-forget!
```

`process_message` chạy task **không được await**. Trong khi task chưa chạy xong (chưa ACK), message vẫn còn ở trạng thái pending. Vòng lặp `async for` gọi `__anext__()` lần tiếp theo → nếu `__anext__` đọc `'0'` (pending), nó thấy message cũ, dispatch lại → loop vô hạn.

Lưu ý: bug này đã tồn tại từ lâu, nhưng trước đây redis-py 7.x với Redis 5.x trả về `[]` cho `'0'` nên không bị kích hoạt. Khi chuyển qua redis-py 8.0.0 → RESP3 → `'0'` trả `[[stream, []]]` → spin loop (INC-001). Sau fix INC-001, message được đọc từ `'>'` đúng một lần, nhưng `__anext__` kiểm tra `'0'` trước → gặp message chưa ACK → re-read (INC-002).

### Cách khắc phục

Fix ở INC-001 (xoá `'0'` khỏi `__anext__`) đã giải quyết cả INC-002.
Khi chỉ đọc `'>'`, mỗi message chỉ được deliver một lần duy nhất.

### Cải tiến bổ sung (đề xuất)
- Nên await `process_message` để đảm bảo message được xử lý xong trước khi đọc message kế tiếp, hoặc dùng queue bounded.
- Hoặc ACK ngay sau khi dispatch task để tránh re-read.

---

## INC-003: Redis-py 8.0.0 RESP3 không tương thích với Redis 5.x

**Ngày:** 2026-07-05
**Mức độ:** High — Worker không xử lý được tin nhắn, CPU 100%.

### Triệu chứng
- Worker (PID 30100) dùng 1m43s CPU trong 1 phút.
- Bot không phản hồi tin nhắn.
- `redis-py` vừa được cập nhật lên 8.0.0.

### Nguyên nhân gốc rễ
- redis-py 8.0.0 mặc định dùng RESP3 protocol.
- Redis server 5.0.14.1 chỉ hỗ trợ RESP2.
- redis-py gửi `HELLO 3` → Redis 5.x không hiểu → fallback loop.

### Cách khắc phục
- Hạ redis-py xuống `<8.0` (hiện tại `>=5.0,<8.0` trong `requirements.txt`).
- Giữ `protocol=2` trong `Redis.from_url()`.

---

---

## INC-004: Router 500 random khi 1 key pool có vấn đề

**Ngày:** 2026-07-06
**Mức độ:** High — Bot vẫn chạy được nhờ retry, nhưng response chậm hơn.

### Triệu chứng
- Bot nhận 500 từ Router không định kỳ (khoảng 40-60% request).
- 500 xuất hiện cả trên request đầu tiên lẫn sau tool-calling.
- Bot vẫn trả lời được sau 1-2 lần retry.
- 500 từ router có message `{'message': 'Internal Server Error', 'status': 'Internal Server Error'}` — generic FastAPI error, không có detail.

### Nguyên nhân gốc rễ

**File:** `src/core/providers/gemini/utils.py` — function `handle_error`

Router có cơ chế retry pool key (MAX_RETRIES=12, quét toàn bộ pool). Tuy nhiên, `handle_error` xử lý `bad_request` (code 400, như "API key not valid") và `project_denied` (code 403, GCP project bị deny) bằng cách **raise RuntimeError ngay lập tức**, không thử key tiếp theo:

```python
# Code cũ (bug)
if reason == "bad_request":
    raise RuntimeError(f"bad_request: {error_text[:500]}")
if reason == "project_denied":
    raise RuntimeError(f"project_denied: {error_text[:300]}")
```

Khi RuntimeError thoát ra ngoài `call_gemini`, FastAPI bắt và trả 500 mặc định, mất hết detail message gốc.

### Cách khắc phục

**Sửa đổi tại `src/core/providers/gemini/utils.py`:**

1. `bad_request` → freeze key 3600s + penalty, `return` (thử key tiếp theo)
2. `project_denied` → freeze key 3600s + penalty, `return` (thử key tiếp theo)

```python
# Code mới (fixed)
if reason == "bad_request":
    router.freeze_key(api_key, config.KEY_INVALID_COOLDOWN_SECONDS, model_id, "bad_request")
    apply_error_penalty(api_key, "bad_request", model_id)
    logger.warning("Key ...%s bad_request, frozen + penalty", api_key[-4:])
    await asyncio.sleep(config.GEMINI_API_KEY_INTERVAL)
    return
if reason == "project_denied":
    router.freeze_key(api_key, config.KEY_INVALID_COOLDOWN_SECONDS, model_id, "project_denied")
    apply_error_penalty(api_key, "project_denied", model_id)
    logger.warning("Key ...%s project_denied, frozen + penalty", api_key[-4:])
    await asyncio.sleep(config.GEMINI_API_KEY_INTERVAL)
    return
```

### Tác dụng phụ
- Pool vẫn còn key invalid → thi thoảng vẫn tốn thời gian scan key chết. Cần dọn key pool thủ công để tối ưu hoàn toàn.

---

## Checklist kiểm tra khi bot không hồi đáp

1. **Check CPU**: process Python `run_bot` > 50% CPU → có thể đang spin.
2. **Check Redis Streams**:
   ```bash
   python -c "import asyncio, redis.asyncio as r; ...
   await r.xpending('discord-incoming', 'azuris_worker_group')"
   ```
3. **Check log**: có `[REDIS-RECV]` không? Nếu chỉ có `[REDIS-SEND]` → Worker không consume.
4. **Check `__anext__`**: đảm bảo code không còn đọc `'0'` pending.
5. **Restart sạch**: `DEL discord-incoming discord-outgoing` trong Redis, restart bot.

---

## Lịch sử sửa lỗi & thay đổi (Changelog)

> Lịch sử các bug đã gặp và cách đã sửa (file/location cụ thể). Giữ lại để tra cứu bảo trì; không xóa.
## Lịch sử thay đổi

### Session 2 — APIConnectionError & Timeout
Thêm `_is_connection_error` handler, mark key `endpoint_down` (120s) + rotate.

### Session 3 — Health Check UI
Health checker xóa LLM report, `/health_check` dùng Embed ✅/❌.

### Session 7 — Real Streaming
Final synthesis gọi stream real, MockResponse wrapper.

### Session 8 — Cost Tracking
Log usage cho streaming, dùng model_id thực tế.

### Session 9 — Gỡ bỏ Custom Endpoint
Xóa `api_proxy.py`, `custom_endpoint.py`. `GEMINI_BASE_URL` mới. Chỉ hỗ trợ Gemini SDK.

### Session 10 — Fix crash + Redis upgrade
Fix NameError/IndentationError bot_core.py. Redis 3.2.100 → 5.0.14.1 (Streams).

### Session 11 — Validate endpoint 500
Chấp nhận HTTP 500 thành công. Model test đổi `gemini-2.5-flash` → `gemini-flash`.

### Session 12 — SDK crash TypeError
Bắt TypeError `'<=' not supported`, coi như connection error.

### Session 13 — Router Bypass + Timeout
Bypass Router 30s khi ConnectError. Timeout 15000ms (int).

### Session 14 — Redis Streams ACK fix + LSP cleanup
- **Redis ACK bug fix**: Xoá `xack()` khỏi `__anext__()` → ACK chỉ sau khi `_publish_outgoing` thành công
- **PEL reclaim**: Thêm `reclaim_pending()` (XCLAIM) + đọc pending trước new (`'0'` → `'>'`)
- **Gateway ACK**: BotCore ACK `discord-outgoing` chỉ sau khi Discord API trả về thành công
- **0 LSP errors**: Fix 48 type errors (import stubs, Optional guards, type narrowing, discord.py stub mismatches)

### Session 15 — Xoá DummyAttachment, refactor FileParserService
- **Xoá `DummyAttachment`**: Class mock giả lập `discord.Attachment` bị xoá hoàn toàn
- **`FileParserService` không còn phụ thuộc `discord`**: `_download_attachment`, `parse_attachment`, `prepare_file_for_indexing` nhận `url: str`, `filename: str`, `size: int` trực tiếp thay vì `discord.Attachment`
- **Xoá `import discord` khỏi `file_parser.py`**: Module thuần utility, không biết gì về Discord model
- **Caller sửa native**: `message_handler.py` gọi `prepare_file_for_indexing(url, filename, size=...)` trực tiếp, không qua DummyAttachment wrapper

### Session 16 — Router 500 isolation + google-genai 2.8.0
- **Xoá `router_bypass_until`**: Loại bỏ hybrid fallback router→Google direct khỏi `gemini_api_manager.py`
- **Xoá 500→endpoint_down handlers**: 3 handler trong `gemini_pipeline.py` removed — không còn fallback router→direct khi 500
- **Fix config.py log**: Hiển thị "Router mode" / "Direct mode" thay vì "Smart Rotation" gây hiểu nhầm
- **Upgrade google-genai**: `1.52.0` → `2.8.0` (khớp version router, internal tenacity retry mạnh hơn)
- **Clean test scripts**: Xoá 14 test script tạm thời khỏi project root
- **Router fix**: `handle_error` trong router không còn raise RuntimeError cho `bad_request`/`project_denied` — freeze key + thử key tiếp theo, không ngắt retry loop

### Session 17 — Endpoint-only refactor
- Gỡ key rotation: `gemini_api_manager.py`, `api_router.py`, `api_config.py`, `gemini_rate_limiter.py`
- Thêm `src/core/llm/` (2 SDK: genai/openai), bảng `llm_endpoints` + `llm_model_slots`
- Nhóm lệnh `/endpoint` + `/health_check` mới; gate "chưa cấu hình"
- 3 model slot + fallback 1 lần cùng provider; key mã hóa Fernet
  (lúc ship là 4 slot; slot `vision` bỏ ở PR #27, resolve về `final`)
- Test mới trong `tests/`; CI + security scan ở Phase 2, tách god-file ở Phase 3

### Session 18 — NLP gate + google-genai 2.33.0 + đánh giá ADK
- **Đường tắt EASY**: `src/core/nlp_gate.py` (pure stdlib, ~1ms, offline — bỏ dấu/teencode + char 3-gram cosine, ngưỡng 0.50, precision 1.00 trên golden set `tests/test_nlp_gate.py`). Chào hỏi/xã giao → 1 call lite + sandwich rút gọn, không tool; fail-open COMPLEX.
- **Wire vào `message_handler.process_message`**: `_call_easy_with_deadline` (timeout 60s), phân loại trên raw text trước intent cues, loại trừ attachment/RAG context.
- **Upgrade google-genai**: `2.8.0` → `2.33.0` (`requirements.txt`); batch test xanh (llm base/genai/openai/gateway, nlp_gate, layering, handler timeout+concurrency — 16 passed).
- **Đánh giá Google ADK 2.13.0 rồi KHÔNG chọn**: spike đối đầu (`LlmAgent`+`Runner`+`FunctionTool` vs pipeline thật, chung sandwich final thật) cho transcript tương đương nhưng không thêm capability; 1-model multi-pass lộ lỗi trả lời nhầm meta-prompt; debug xuyên abstraction đắt; framework còn xoay. Chi tiết: `docs/architecture.md` (§Quyết định kiến trúc).

### Session 19 — Docker hóa + DB seed portable + dọn script infra cũ
- **Chuẩn runtime mới**: `Dockerfile` (py3.12-slim, non-root UID 1000, không bake secret) + `docker-compose.yml` (bot 1 replica + `postgres:16` + `redis:7-alpine` ephemeral, không publish port) + `.dockerignore` (chặn `.env`, `.venv/`, `src/.runtime/`).
- **DB ngoài image**: seed `data/db_seed/azuris.sql` qua `/docker-entrypoint-initdb.d`; data live trong bind `./data/postgres` (subfolder của `/data`, tách riêng khỏi file app của bot). Verify: 208 messages / 2 endpoints / 6 slots / 1 note khớp DB cũ. Lệnh 1-phát: `run_bot.ps1` / `run_bot.sh` (`up|down|stop-bot|stop-infra|rebuild|restart|logs|ps|seed|backup|update` — tách dừng bot/infra như cơ chế cũ).
- **Giới hạn RAM** (Docker Desktop cap 4GB): postgres 768m, redis 256m (+`tmpfs /data` chặn volume mồ côi), bot 1g.

### Session 20 — Trivy gate xanh (bài học về false positive)
- Trivy fail 26 HIGH thật → nâng dependency (`aiohttp` 3.14.4, `cryptography` 50.0.0, `pypdf` 6.21.2, `urllib3` 2.8.0, `msgpack` 1.2.3, `setuptools` 84.2.1, `wheel` 0.46.2, `jaraco.context` 6.1.0).
- 7 HIGH còn lại KHÔNG phải package cũ: 2 từ dist-info vendored trong `setuptools/_vendor` (jaraco 5.3.0, wheel 0.45.1 — `setuptools` 84.2.1 vendor bản đã vá nên tự hết), 5 từ `pip/_vendor/bom.cdx.json` (SBOM của deps vendored trong pip, chỉ dùng lúc build) → `skip-files` file SBOM này, dist-info thật vẫn quét.
- Bài học: đừng tin ngay "cache cũ" — moi log `pip install` trong CI ra đối chiếu mới thấy root cause thật (vendored/SBOM). Build CI để `no-cache` cho tính đúng đắn tuyệt đối.
- **Compose override URL**: `DATABASE_URL`/`REDIS_URL` trong `environment` thắng `.env` (trỏ sang service nội bộ); `BOT_LOG_PATH=/app/logs/bot.log` tránh ghi writable layer; healthcheck bot = `run_bot.py --preflight`.
- **Dọn code**: xóa `install_services.*`, `stop_infra.*`, `stop_bot.ps1`, `ecosystem.config.js`; `run_bot.ps1/.sh` giữ lại cho dev local (đường thiếu runtime/pm2 giờ báo lỗi trỏ sang Docker); `.env.example` thêm `AZURIS_DB_USER/PASSWORD/NAME`.
- **Verify**: 3 service healthy, bot `is online and ready!`, slash sync đủ 26.
