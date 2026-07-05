# Sự cố & Chẩn đoán (Incident Reports)

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
