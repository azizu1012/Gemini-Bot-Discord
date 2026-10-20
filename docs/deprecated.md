# Tính năng & cấu hình đã gỡ (Deprecated)

> Tổng hợp thành phần bị loại bỏ trong bản **endpoint-only** (2026-10-20). Tài liệu/script nào còn nhắc tới các mục dưới đây được coi là tài liệu cũ.

## 1. Xoay vòng API key (đã gỡ hoàn toàn)

| Thành phần | Tình trạng | Thay thế |
|------------|-----------|----------|
| `src/core/gemini_api_manager.py` | Đã xóa | `src/core/llm/gateway.py` (retry + 1 fallback cùng provider) |
| `src/core/api_router.py` | Đã xóa | `src/core/llm/resolver.py` + `gateway.py` |
| `src/core/api_config.py` | Đã xóa | Model chọn trực tiếp trong DB (`llm_model_slots`) |
| `src/core/gemini_rate_limiter.py` | Đã xóa | Retry/backoff trong gateway |
| Key pool, cooldown, key reservation | Đã xóa | Endpoint-only, 1 key/SDK |
| Circuit breaker, router bypass | Đã xóa | Fallback 1 lần cùng provider |
| Alias model tĩnh (`gemini-flash`, `gemini-flash-lite`...) | Đã xóa | `model_id` thật lấy từ endpoint |
| Bảng DB `api_key_pool`, `api_key_rate_limits`, `custom_api_models`, `bot_model_config`, `custom_api_provider_config` | `init_db()` tự `DROP ... CASCADE` (kể cả bản `_deprecated_*`) | `llm_endpoints` + `llm_model_slots` |

## 2. Biến môi trường đã gỡ

| Biến | Ghi chú |
|------|---------|
| `GEMINI_API_KEY_*` (PROD/TEST/BACKUP/EXTRA...) | Không còn đọc; cấu hình key qua `/endpoint` |
| `GEMINI_API_KEYS` | Không còn tồn tại |
| `GEMINI_BASE_URL`, `ROUTER_AUTH_KEY` | URL/key lưu trong `llm_endpoints` |
| `MODEL_NAME` | Không còn dùng |
| `OPENAI_API_KEY`, `OPENAI_CUSTOM_ENDPOINT` | Không còn dùng |
| `REASONING_MODEL_ALIAS`, `FINAL_MODEL_ALIAS`, `FALLBACK_MODEL_ALIAS` | Thay bằng 4 slot trong DB |
| `GEMINI_CIRCUIT_*` | Circuit breaker đã gỡ |
| `HABE_USER_ID`, `MIRA_USER_ID`, `ADO_FAT_USER_ID`, `MUC_RIM_USER_ID`, `SUC_VIEN_USER_ID`, `CHUI_USER_ID` | Chưa từng được code sử dụng; đã xóa khỏi `Config` và `.env` |
| `ADMIN_USER_IDS` (dạng biến môi trường) | Không đọc trực tiếp; dùng `ADMIN_IDS` (chuỗi phân tách bằng dấu phẩy) |

## 3. Lệnh & hành vi đã đổi

| Cũ | Mới |
|----|-----|
| `/endpoint <url> <auth_key>` | Nhóm `/endpoint config|view|switch|models|test` |
| `/health_check` quét API key | `/health_check` kiểm tra endpoint active + latency + 4 slot + PostgreSQL |
| Bot fail-fast lúc khởi động nếu thiếu key | Bot vẫn chạy; chat trả "chưa cấu hình" |
| Tự chuyển provider khi lỗi | Không tự chuyển; `/endpoint switch` thủ công |

## 4. Biến môi trường đổi tên

| Cũ | Mới |
|----|-----|
| `GOOGLE_SEARCH_STREAMS` | `SEARCH_PARALLEL_STREAMS` (biến cũ vẫn đọc + warning, sẽ bỏ ở bản sau) |

## 5. Migration sau khi update

1. Xóa/để nguyên các biến cũ trong `.env` — bot bỏ qua, không lỗi. Bảng key-rotation cũ
   (`api_key_pool`, ...) sẽ bị `init_db()` xóa vĩnh viễn bằng `DROP ... CASCADE`.
2. Chạy bot, dùng `/endpoint config` cấu hình lại endpoint + 4 model slot — hoặc ghi
   trực tiếp bằng `python scripts/configure_endpoint.py ...` khi không vào được Discord.
3. `/endpoint test` để xác minh, sau đó chat thử.
