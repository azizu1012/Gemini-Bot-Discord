# Endpoint & Model Slots

> Áp dụng từ bản endpoint-only (2026-10-20). Thay thế hoàn toàn cơ chế xoay vòng API key cũ — xem [`deprecated.md`](deprecated.md).

## 1. Mô hình endpoint-only

- Bot KHÔNG tự quản lý pool key. Mỗi lần gọi LLM, bot đọc cấu hình endpoint đang active từ PostgreSQL.
- Cấu hình gồm: `sdk` (2 lựa chọn), `base_url`, `api_key` (mã hóa khi lưu) và 4 model slot.
- Không kiểm tra endpoint lúc khởi động. Chưa cấu hình → mọi lệnh chat trả ephemeral: `Bot chưa được cấu hình, hãy liên hệ admin.`

## 2. Hai SDK

| SDK | Dùng khi | URL mặc định | Tính năng |
|-----|----------|--------------|-----------|
| `genai` | Gọi Google Gemini trực tiếp hoặc qua proxy tương thích GenAI | `https://generativelanguage.googleapis.com` | Text, Tools, Vision |
| `openai` | Router/LLM tương thích OpenAI (`/v1/chat/completions`) | (bắt buộc nhập) | Text, Tools, Vision. KHÔNG grounding |

- `genai`: nhập **host gốc, KHÔNG kèm `/v1`, `/v1beta` hay `/v1alpha`** — google-genai SDK tự ghép `/v1beta`. Ví dụ router: `http://127.0.0.1:58100`.
- `openai`: nhập URL đầy đủ tới `/v1`, ví dụ `http://127.0.0.1:58100/v1`. Nếu chỉ nhập host, bot tự thêm `/v1`.
- Bot tự chuẩn hóa URL trước khi lưu/gọi: thêm `http://` khi thiếu scheme, bỏ đuôi `/models` hoặc `/chat/completions`; `genai` tự bóc version (`/v1`, `/v1beta`, `/v1alpha`), `openai` tự thêm `/v1` nếu thiếu.
- Đổi SDK active là thao tác thủ công (`/endpoint switch`). Runtime KHÔNG tự nhảy provider.

## 3. Lệnh /endpoint (ADMIN ONLY)

| Lệnh | Mô tả |
|------|-------|
| `/endpoint config` | Chọn SDK → nhập URL/key → chọn model cho 4 slot |
| `/endpoint view` | Xem cấu hình 2 SDK + key đã ẩn + 4 slot |
| `/endpoint switch` | Đổi SDK đang active (không cần nhập lại key) |
| `/endpoint models` | Fetch lại danh sách model của SDK active và gán lại 4 slot |
| `/endpoint test` | Ping endpoint, đo latency, xác minh 4 model slot tồn tại |

### Luồng `/endpoint config`

1. Chọn SDK (`genai` / `openai`).
2. Nhập `base_url` (bỏ trống = URL mặc định; riêng `openai` bắt buộc).
3. Nhập API key (mã hóa trước khi ghi DB).
4. Bot fetch danh sách model; lỗi → báo lỗi, không lưu.
5. Chọn model cho từng slot: Reasoning → Final → Fallback → Vision.
   - 25 model/trang, nút ◀ ▶, nút 🔍 tìm kiếm theo tên.
   - Nút "Bỏ trống" = dùng default rule (mục 4).
6. Lưu endpoint + 4 slot, đặt SDK vừa cấu hình làm active, xóa cache resolver.

## 4. Bốn model slot & default rule

| Slot | Vai trò | Default khi bỏ trống |
|------|---------|----------------------|
| `reasoning` | Vòng lặp suy luận + gọi tools | `final` |
| `final` | Tổng hợp câu trả lời cuối | Model đầu tiên trong danh sách |
| `fallback` | Thử lại khi model chính lỗi | `reasoning` → `final` |
| `vision` | Phân tích ảnh | `final` |

- `fallback` PHẢI cùng provider với endpoint active. Không tự chuyển provider — muốn đổi thì `/endpoint switch` thủ công.
- Khi model chính lỗi: retry cùng model theo `*_MAX_API_RETRIES`, sau đó thử `fallback` đúng 1 lần. Hết lượt → báo lỗi cho user.

## 5. Bảo mật API key

- Key lưu trong `llm_endpoints.api_key_encrypted`.
- Mã hóa Fernet bằng `DONATE_ENCRYPTION_KEY` trong `.env`.
- Thiếu key → lưu `plain:<key>` (chỉ dev; KHÔNG dùng production).
- `/endpoint view` chỉ hiện 4 ký tự cuối của key.

## 6. Ví dụ cấu hình

### Google Gemini trực tiếp (genai)

```text
SDK: genai
Base URL: (bỏ trống)
API key: <Google AI Studio key>
```

### Router nội bộ (genai qua proxy)

```text
SDK: genai
Base URL: http://127.0.0.1:58100     # KHÔNG thêm /v1 hay /v1beta
API key: <key do router_api cấp>
```

### LLM tương thích OpenAI

```text
SDK: openai
Base URL: http://127.0.0.1:58100/v1
API key: <key>
```

### Cấu hình trực tiếp bằng CLI (khi Discord UI lỗi)

Khi không thao tác được qua `/endpoint config`, ghi thẳng vào PostgreSQL bằng script
(idempotent, tự mã hóa key bằng `DONATE_ENCRYPTION_KEY`):

```bash
python scripts/configure_endpoint.py \
    --sdk openai \
    --base-url http://127.0.0.1:58100/v1 \
    --api-key <key> \
    --reasoning gemini-flash \
    --final gemini-flash \
    --fallback gemini-flash-lite \
    --vision gemini-flash

python scripts/configure_endpoint.py --show   # xem cấu hình hiện tại
```

Thêm `--no-active` để lưu endpoint mà không đặt làm SDK active. Có thể cấu hình
song song cả `genai` (host gốc) lẫn `openai` (`/v1`) rồi `/endpoint switch` khi cần.

## 7. Troubleshooting

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
|------------|------------------------|------------|
| `401 Unauthorized` | Key sai/hết hạn | `/endpoint config` nhập lại key |
| `Không lấy được danh sách model` | URL sai (genai lỡ thêm `/v1`, openai thiếu `/v1`), proxy chưa chạy | Kiểm tra bằng `/endpoint test`; xem lại quy tắc URL ở mục 2 |
| Slot báo ⚠️/❌ | Model không có trong danh sách endpoint | `/endpoint models` chọn lại |
| Trả lời chậm | Endpoint xa / model lớn | Xem latency ở `/endpoint test` |
| Muốn đổi provider | Chưa `/endpoint switch` | Switch thủ công — runtime không tự nhảy |
