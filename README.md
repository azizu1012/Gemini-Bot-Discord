# 🤖 Discord AI Assistant

<p align="center">
  <a href="https://github.com/your-username/your-repo-name/blob/main/LICENSE" target="_blank">
    <img alt="License" src="https://img.shields.io/badge/License-MIT-blue.svg"/>
  </a>
  <a href="https://discord.gg/your-invite" target="_blank">
    <img alt="Discord" src="https://img.shields.io/discord/123456789012345678?label=Discord%20Server&logo=discord&color=7289DA"/>
  </a>
  <a href="https://www.python.org/" target="_blank">
    <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python"/>
  </a>
  <a href="https://render.com/" target="_blank">
    <img alt="Hosted on Render" src="https://img.shields.io/badge/Hosted%20on-Render-46E3B7?logo=render&logoColor=white"/>
  </a>
</p>

## ✨ Giới thiệu

Đây là một Discord Bot AI hiệu suất cao, được xây dựng trên nền tảng **`discord.py`** và sử dụng mô hình ngôn ngữ **Google Gemini** để xử lý các tác vụ phức tạp. Bot được thiết kế để cung cấp thông tin cập nhật, hỗ trợ tính toán, và tương tác chat đa luồng.

---

## 🛠️ Công cụ và Khả năng

Bot tận dụng nhiều API bên ngoài để mở rộng khả năng và đảm bảo thông tin luôn được cập nhật và chính xác:

### 🌐 Khả năng Tìm kiếm Web (Web Search/RAG)

Bot sử dụng nhiều công cụ tìm kiếm đồng thời để thu thập thông tin theo thời gian thực (Real-time Information) trước khi trả lời.

* **Công cụ sử dụng:** Google Custom Search Engine (CSE), SerpAPI, Tavily, Exa.ai, và Ollama Search.
* **Chức năng:** Hỗ trợ trả lời các câu hỏi về sự kiện, thời tiết, tin tức và dữ liệu mới nhất.

### 💬 Khả năng Tương tác & Xử lý Dữ liệu

* **Tương tác đa kênh:** Phản hồi khi được **Mention** (`@Bot`), **Reply** tin nhắn, hoặc trong **Tin nhắn riêng (DM)**.
* **Quản lý Chat History:** Lưu trữ lịch sử chat của từng người dùng vào **SQLite Database** để duy trì ngữ cảnh hội thoại.
* **Tính năng Toán học:** Hỗ trợ giải quyết các bài toán toán học phức tạp bằng thư viện **SymPy**.
* **Lệnh Command (Slash & Prefix):** Hỗ trợ các lệnh quản trị và tiện ích (ví dụ: `/dm`, `/history`, `/reset-all`).

---

## 🚀 Hướng dẫn Cài đặt & Triển khai

### 1. Phụ thuộc (Dependencies)

Cài đặt các thư viện cần thiết thông qua file `requirements.txt`:

```bash
pip install -r requirements.txt
````

| Thư viện chính | Vai trò |
| :--- | :--- |
| `discord.py` | Framework Discord Bot |
| `google-generativeai` | Kết nối API Gemini |
| `flask` | Tạo Web Server Keep-Alive (24/7) |
| `sympy` | Hỗ trợ tính toán toán học |
| `google-search-results` | SerpAPI Integration |
| `tavily-python` & `exa-py` | Các công cụ tìm kiếm bổ sung |

### 2\. Thiết lập Biến Môi trường (`.env`)

Tạo file `.env` và điền các khóa API/token cần thiết.

| Biến Môi Trường | Mô tả |
| :--- | :--- |
| `DISCORD_TOKEN` | Token đăng nhập Bot Discord. |
| `GEMINI_API_KEY_PROD` | Key API chính của Google Gemini. |
| `GOOGLE_CSE_ID` | ID của Google Custom Search Engine (CSE). |
| `GOOGLE_CSE_API_KEY` | Key API cho Google CSE. |
| `OLLAMA_SEARCH_API_KEY` | Key API cho dịch vụ Ollama Search. |
| `ADMIN_ID` | Discord ID của người quản trị (Admin). |
| `MODEL_NAME` | Mô hình Gemini được sử dụng (ví dụ: `gemini-2.5-flash`). |

> ⚠️ **Bảo mật:** KHÔNG bao giờ commit file `.env` chứa các API Key lên GitHub/public repository.

### 3\. Khởi động Bot

#### 💻 Chạy Local

```bash
python bot_run.py
```

#### ☁️ Triển khai trên Cloud (Render)

Dự án sử dụng module `keep_alive.py` để tạo một Web Server Flask, giúp giữ cho Bot luôn hoạt động 24/7 trên các nền tảng hosting miễn phí như Render.

1.  **Cấu hình Biến:** Thêm tất cả các biến từ file `.env` vào phần **Environment** trên Dashboard Render.
2.  **Start Command:** Thiết lập lệnh khởi chạy dịch vụ là:
    ```
    python bot_run.py
    ```
3.  **Duy trì 24/7:** Sử dụng dịch vụ giám sát bên ngoài (ví dụ: UptimeRobot) để ping endpoint `/` của Bot, ngăn dịch vụ bị idle/ngủ.

-----

## 📜 Giấy phép (License)

Dự án này được phát hành dưới Giấy phép **MIT**.

```

```