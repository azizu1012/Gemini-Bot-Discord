# CLAUDE.md - THỦ TỤC VẬN HÀNH VÀ ĐẶC TẢ HẠ TẦNG TỐI CAO

## 🚨 QUY TẮC TUÂN THỦ TUYỆT ĐỐI (HARD RULES)

1. **User Is Always Right**: Khi User thông báo hệ thống có lỗi, ĐỒNG NGHĨA LÀ CÓ LỖI. Tuyệt đối không được nghi ngờ, không giải thích vòng vo. Lập tức chạy full kịch bản test từ đầu đến cuối để định vị và sửa lỗi dựa trên niềm tin tuyệt đối vào thông tin của user.
2. **Strict Language Consistency**: Toàn bộ quá trình lên kế hoạch (planning), xuất văn bản, báo cáo, giải thích logic hoặc ghi vết tiến trình chạy **BẮT BUỘC phải viết hoàn toàn bằng Tiếng Việt có dấu** một cách nhất quán từ đầu đến cuối. CẤM tuyệt đối tình trạng lên plan bằng tiếng Anh rồi viết nội dung thực thi bằng tiếng Việt gây hỗn loạn ngữ cảnh. Các thuật ngữ kỹ thuật (Kafka, JSON, Backend, venv...) giữ nguyên danh từ gốc, nhưng toàn bộ câu chữ bổ trợ phải là tiếng Việt chuẩn chỉnh.
3. **Sub-Agent Inheritance**: Mọi Agent con hoặc quy trình phụ được gọi ra bắt buộc phải thừa kế và áp dụng chính xác 100% các quy tắc trong file này.
4. **No Git Workspace**: Workspace hiện tại không phải là Git repository, tránh gọi các lệnh `git` trừ khi có chỉ thị trực tiếp. Khi rà soát/code-review, lọc file theo mốc thời gian `LastWriteTime`.

---

## 🔍 QUY TRÌNH PHÂN TÍCH VÀ ĐỒNG BỘ TÀI LIỆU (PRE & POST WORKFLOW)

### Bước 1: Đọc tài liệu nền tảng (Trước khi làm)

- **BẮT BUỘC:** Trước khi đụng vào code, phải đọc và phân tích kỹ 3 file tài liệu cốt lộ của dự án: `PROJECT_INFO.txt`, các file hướng dẫn và `AGENT_HANDOFF_PROJECT_CONTEXT.md`.
- Được phép tự do đọc file (`/read`) để hiểu sâu kiến trúc hệ thống, phân tích logic vận hành hiện tại, ghi nhận các module phụ thuộc trước khi chỉnh sửa.

### Bước 2: Nguyên tắc Chỉnh sửa "Cục bộ" (Anti-Brick)

- **CẤM** thay đổi cấu trúc hoặc logic nghiệp vụ cốt lõi không liên quan đến yêu cầu hoặc phần bị hỏng. Chỉ edit đúng phần được chỉ định hoặc phần đang lỗi.
- **Cross-Check bắt buộc:** Nếu sửa lỗi logic liên quan đến kiểu dữ liệu trả về, tên hàm hoặc tham số, phải kiểm tra chéo toàn bộ hệ thống. Tránh tuyệt đối tình trạng sửa module này làm sập (brick) module khác gọi đến nó.

### Bước 3: Đóng gói code chỉnh sửa và Kiểm tra tính toàn vẹn

- Khi chỉnh sửa file, không dùng cơ chế edit mù (blind edit). Phải tạo ra khối mã nguồn hoàn chỉnh rõ ràng để thay thế.
- Sau khi tạo mã nguồn mới, phải đối chiếu lại với code cũ: Kiểm tra xem có bị mất hàm cũ không, thiếu lệnh import không. Đảm bảo tính toàn vẹn 100% rồi mới xóa file nháp/file chỉnh sửa tạm thời.

### Bước 4: Cập nhật tài liệu ngược (Sau khi xong)

- **BẮT BUỘC:** Sau khi edit code và chạy test thành công, phải cập nhật (edit ngược) các thay đổi về mặt kiến trúc, logic, trạng thái hoặc hàm mới vào lại 3 file: `PROJECT_INFO.txt`, các hướng dẫn trong và `AGENT_HANDOFF_PROJECT_CONTEXT.md` bằng Tiếng Việt có dấu để tài liệu luôn đồng bộ với mã nguồn thực tế.

---

## 🧪 QUY TRÌNH KIỂM THỬ KHÔNG GIỚI HẠN (UNRESTRICTED TESTING)

### 1. Môi trường và Công cụ thực thi

- **Tự do kịch bản:** Được phép sử dụng **Bash** và viết các script test Python custom một cách linh hoạt, không giới hạn kịch bản testing để bao phủ toàn bộ các trường hợp lỗi (Edge cases).

### 2. Tiêu chuẩn kiểm thử gắt gao

- Áp dụng nguyên lý: **"Thà test nhầm, test thừa còn hơn bỏ sót"**. 
- Phải đảm bảo tất cả các hàm được gọi đầy đủ, hoạt động chính xác trong luồng Event-Driven thực tế, không bị mất mát hay missing bất kỳ thành phần nào.
- **Tiêu chuẩn sạch:** Đảm bảo hệ thống đạt 0 lỗi Syntax và 0 lỗi Pylance (Type/Import checking) sau khi chỉnh sửa.
- **Gotcha**: Pytest và Unittest không được cấu hình sẵn; thực thi kiểm thử thông qua chạy trực tiếp các script test python độc lập (ví dụ `test_dynamic_roles.py`).

### 3. Vòng đời của File Test tạm thời

- Sau khi chạy xong các script test tự tạo bằng bash/python và xác nhận kết quả thành công, **BẮT BUỘC** phải xóa sạch toàn bộ các file test tạm thời đó, trả lại không gian dự án sạch sẽ.

---

## 🛠️ HƯỚNG DẪN LỆNH HỆ THỐNG

- Khởi chạy hạ tầng: `powershell ./run_bot.ps1` hoặc các script launcher tương đương.
- Thực thi test: Sử dụng `pytest` hoặc chạy trực tiếp các script test python/bash custom.

---

## 💾 QUY TẮC PHÁT TRIỂN CƠ SỞ DỮ LIỆU & BỘ NHỚ (DB & MEMORY RULES)

1. **JSONB Query**: Cột `metadata` của `user_notes` là kiểu JSONB. Tuyệt đối không dùng vòng lặp Python trên RAM để lọc thuộc tính JSON, hãy lọc trực tiếp từ PostgreSQL (`metadata->>'key' = $val`).
2. **GIN Index Preservation**: Không sử dụng ép kiểu `metadata::text ILIKE $1` để tìm kiếm vì nó vô hiệu hóa chỉ mục GIN (`idx_user_notes_metadata_gin`). Thay vào đó hãy dùng trích xuất cụ thể `metadata->>'key' ILIKE $1`.
3. **No Wiki/Knowledge Plugin**: Thư mục `wiki/` và `.understand-anything/` đã bị gỡ bỏ. Tránh gọi các plugin tri thức hay dashboard trực quan hóa đồ thị tri thức.
