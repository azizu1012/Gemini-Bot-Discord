# 🤖 AZURIS DISCORD ASSISTANT BOT

> 📖 **Tài liệu kỹ thuật đầy đủ:** Xem [`docs/`](docs/) — Nguồn Sự Thật Kỹ Thuật duy nhất. Các tính năng đã gỡ: [`docs/deprecated.md`](docs/deprecated.md).

**Azuris** là một trợ lý AI tiên tiến hoạt động trên nền tảng Discord, được xây dựng trên kiến trúc hướng sự kiện phân tán (**Event-Driven Distributed Architecture**) sử dụng **PostgreSQL**, **Redis Streams**, và pipeline lập luận đa bước qua **LLM endpoint** (Google GenAI native hoặc OpenAI-compatible). 

Hệ thống được thiết kế tối ưu hóa cho cả môi trường VPS cá nhân và doanh nghiệp vừa với cơ chế tự cấp phát hạ tầng cục bộ (**Zero-Docker Local Runtime**).

---

## ✨ TÍNH NĂNG NỔI BẬT

* **Lập luận đa bước (Contextual Chat & Reasoning)**: Pipeline 2 tầng (Reasoning Loop + Final Synthesis) giúp bot suy nghĩ sâu sắc trước khi trả lời.
* **Gọi công cụ tự động (Tool-Calling)**: Tìm kiếm web thời gian thực (Web Search), tra cứu thời tiết, ghi chú cá nhân và nhận diện hình ảnh.
* **Nhận diện hình ảnh đa phương thức (Vision)**: Đọc và phân tích ảnh đính kèm cực nhanh thông qua SDK Google GenAI chính thức.
* **Endpoint linh hoạt (Endpoint-only)**: Cấu hình URL + API key + 4 model slot ngay trong Discord qua nhóm lệnh `/endpoint`; hỗ trợ Gemini native và mọi LLM tương thích OpenAI (router nội bộ, OpenAI, LM Studio...).
* **Trí nhớ dài hạn (Long-term Memory)**: Lưu giữ sở thích và thông tin cá nhân hóa của từng người dùng thông qua cơ chế ghi chú `user_notes` tối ưu hóa bằng chỉ mục GIN.
* **Hạ tầng cục bộ tự cấp phát (Zero-Docker)**: Tự động tải và chạy Redis, PostgreSQL trực tiếp trong thư mục dự án.
* **Phân quyền lai động-tĩnh (Hybrid Roles)**: Quản lý 4 nhóm quyền (Admin, Moderator, Premium, Free User) bảo mật tuyệt đối.

---

## 🚀 HƯỚNG DẪN KHỞI CHẠY NHANH (QUICK START)

### 📋 Yêu cầu hệ thống
* **Python**: Phiên bản 3.10 trở lên.
* **Hệ điều hành**: Windows 10/11 hoặc Linux (Ubuntu/Debian).

---

### 💻 Hướng dẫn trên Windows (PowerShell Native)

1. **Tải thư viện Python và cài đặt hạ tầng cục bộ**:
   ```powershell
   # Cài đặt thư viện Python
   pip install -r requirements.txt

   # Tải và tự động cấu hình PostgreSQL, Redis cục bộ
   powershell -ExecutionPolicy Bypass -File .\install_services.ps1
   ```

2. **Cấu hình biến môi trường**:
   Mở file `.env` vừa được tạo ở thư mục gốc và điền các API keys cần thiết:
   ```env
   DISCORD_TOKEN=your_discord_bot_token
   # Sinh Fernet key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   DONATE_ENCRYPTION_KEY=your_fernet_key
   ```
   > Endpoint LLM (URL + API key + model) được cấu hình sau khi bot online bằng `/endpoint config` — không dùng biến môi trường.

3. **Chạy kiểm tra hệ thống (Preflight Check)**:
   ```powershell
   powershell .\run_bot.ps1 --preflight-only
   ```

4. **Khởi chạy Bot & Hạ tầng ngầm**:
   ```powershell
   powershell .\run_bot.ps1 --server
   ```

5. **Tắt hạ tầng an toàn khi không sử dụng**:
   ```powershell
   powershell .\stop_infra.ps1
   ```

---

### 🐧 Hướng dẫn trên Linux VPS (PM2 Production)

1. **Cấp quyền thực thi và cài đặt hạ tầng cục bộ**:
   ```bash
   chmod +x install_services.sh run_bot.sh stop_infra.sh
   ./install_services.sh
   ```

2. **Cấu hình môi trường ảo Python và cài đặt thư viện**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Cấu hình biến môi trường**:
   Chỉnh sửa file `.env` để điền các token bảo mật:
   ```bash
   nano .env
   ```

4. **Khởi chạy Bot & Hạ tầng với PM2**:
   ```bash
   # Chạy kiểm tra preflight trước
   ./run_bot.sh --preflight-only

   # Khởi chạy bot và hạ tầng ngầm dưới sự giám sát của PM2
   ./run_bot.sh --pm2 --server
   ```

5. **Xem logs hoạt động**:
   ```bash
   pm2 logs azuris-bot --lines 100
   ```

6. **Tắt hạ tầng an toàn**:
   ```bash
   ./stop_infra.sh
   ```

---

## 📡 CẤU HÌNH LLM ENDPOINT (`/endpoint`)

Azuris chạy theo mô hình **endpoint-only**: không còn xoay vòng API key trong code. Toàn bộ cấu hình LLM lưu trong PostgreSQL và thay đổi trực tiếp trong Discord.

**Cách cấu hình (Admin):**
1. `/endpoint config` → chọn SDK: `genai` (Gemini native) hoặc `openai` (LLM tương thích OpenAI).
2. Nhập URL endpoint (bỏ trống = mặc định Google; `openai` bắt buộc, ví dụ `http://127.0.0.1:58100/v1`).
3. Nhập API key — key được mã hóa bằng `DONATE_ENCRYPTION_KEY` trước khi ghi DB.
4. Chọn model cho 4 slot: Reasoning → Final → Fallback → Vision (25 model/trang, có tìm kiếm theo tên).
5. Kiểm tra bằng `/endpoint test`; xem lại bằng `/endpoint view`.

Chi tiết đầy đủ: [`docs/endpoint_and_models.md`](docs/endpoint_and_models.md) · Tính năng đã gỡ: [`docs/deprecated.md`](docs/deprecated.md).

---

## 💬 DANH SÁCH LỆNH SLASH COMMANDS THÔNG DỤNG

### 🛠️ Lệnh Quản trị & Cấu hình (Admin/Moderator)
* `/endpoint`: Nhóm lệnh cấu hình LLM endpoint — `config`, `view`, `switch`, `models`, `test` (ADMIN ONLY).
* `/health_check`: Kiểm tra endpoint đang active, latency, 4 model slot và kết nối PostgreSQL.
* `/moderator`: Thăng chức hoặc hạ chức Moderator động (Chỉ dành cho Admin).
* `/premium`: Thêm hoặc xóa trạng thái thành viên Premium cho người dùng.
* `/reset-all`: Reset toàn bộ cơ sở dữ liệu và xóa sạch cache (Chỉ dành cho Admin).
* `/global-notes`: Xem và quản lý các ghi chú chung của hệ thống.

### 🎨 Lệnh Giải trí & Tiện ích
* `/imagine`: Tạo ảnh nghệ thuật bằng AI (Hỗ trợ custom image generator hoặc Gemini Imagen mặc định).
* `/ping`: Kiểm tra độ trễ kết nối mạng của bot.
* `/reset-chat`: Xóa sạch lịch sử trò chuyện của bạn để bắt đầu cuộc hội thoại mới.
* `/donate`: Hiển thị mã QR ủng hộ duy trì bot (tự động xóa sau 2 phút để bảo mật).

### 🔊 Lệnh Phòng thoại (Voice Room Management)
* `/lock` / `/unlock`: Khóa hoặc mở khóa phòng thoại cá nhân của bạn.
* `/set_room`: Đặt giới hạn số lượng thành viên tối đa cho phòng thoại.
* `/add_privet` / `/remove_privet`: Thêm hoặc xóa người dùng khỏi danh sách được phép vào phòng thoại riêng tư.
* `/move` / `/move_all`: Di chuyển thành viên hoặc toàn bộ phòng sang kênh thoại khác.

---

---

*Chúc bạn có những trải nghiệm tuyệt vời cùng trợ lý thông minh **Azuris**!*
