# file_parser.py
import discord
import os
import asyncio
import aiohttp
from typing import Optional, Dict
from core.config import config
from core.logger import logger
from managers.cleanup_manager import get_disk_free_space_mb
import pypdf

# Giới hạn kích thước file cho việc tải lên (Discord giới hạn 25MB, ta lấy 20MB)
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024 
# Giới hạn độ dài văn bản được trích xuất để gửi đến Gemini (khoảng 10k ký tự)
MAX_TEXT_LENGTH = 10000

async def parse_attachment(attachment: discord.Attachment) -> Optional[Dict[str, str]]:
    """
    Kiểm tra file, tải về local, trích xuất văn bản (nếu có thể),
    và trả về nội dung văn bản đã xử lý.
    """
    filename = attachment.filename
    
    # Tạo đường dẫn local duy nhất để tránh xung đột
    unique_filename = f"{attachment.id}_{filename}"
    local_path = os.path.join(config.FILE_STORAGE_PATH, unique_filename)
    
    if attachment.size > MAX_FILE_SIZE_BYTES:
        logger.warning(f"File {filename} ({(attachment.size / 1024 / 1024):.2f} MB) quá lớn. Bỏ qua.")
        return {"filename": filename, "content": f"[LỖI: File quá lớn, giới hạn {MAX_FILE_SIZE_BYTES // 1024 // 1024}MB]"}
    
    # --- BƯỚC 1: KIỂM TRA DUNG LƯỢNG VÀ LƯU LOCAL ---
    try:
        # Ước tính dung lượng cần thiết: kích thước file + 10MB buffer
        required_space_mb = (attachment.size // (1024 * 1024)) + 10
        if get_disk_free_space_mb(config.FILE_STORAGE_PATH) < required_space_mb:
            logger.warning(f"Ổ đĩa sắp đầy. Không thể tải file mới. Cần {required_space_mb}MB.")
            return {"filename": filename, "content": "[LỖI: Server sắp hết bộ nhớ. Vui lòng thử lại sau.]"}

        # Tải file về local
        os.makedirs(config.FILE_STORAGE_PATH, exist_ok=True)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    with open(local_path, 'wb') as f:
                        f.write(data)
                    logger.info(f"Đã lưu file local: {local_path}")
                else:
                    raise Exception(f"HTTP Error {resp.status}")
                    
    except Exception as e:
        logger.error(f"Lỗi khi tải file từ Discord về local: {e}")
        return {"filename": filename, "content": "[LỖI: Không thể tải file về local]"}

    # --- BƯỚC 2: TRÍCH XUẤT VĂN BẢN TỪ FILE LOCAL ---
    extracted_text = ""
    file_extension = os.path.splitext(filename)[1].lower()

    try:
        if file_extension == '.txt':
            with open(local_path, 'r', encoding='utf-8', errors='ignore') as f:
                extracted_text = f.read()
            logger.info(f"Đã trích xuất văn bản từ file TXT: {filename}")
        elif file_extension == '.pdf':
            try:
                reader = pypdf.PdfReader(local_path)
                for page in reader.pages:
                    extracted_text += page.extract_text() + "\n"
                logger.info(f"Đã trích xuất văn bản từ file PDF: {filename}")
            except pypdf.errors.PdfReadError:
                logger.error(f"Lỗi đọc file PDF (có thể bị hỏng hoặc mã hóa): {filename}")
                extracted_text = f"[LỖI: Không thể đọc nội dung file PDF '{filename}'. Có thể file bị hỏng hoặc được bảo vệ.]"
        else:
            extracted_text = f"[LƯU Ý: File '{filename}' có định dạng '{file_extension}' không được hỗ trợ trích xuất văn bản. Chỉ hỗ trợ .txt và .pdf.]"
            logger.warning(f"File '{filename}' có định dạng '{file_extension}' không được hỗ trợ trích xuất văn bản.")
            # Không xóa file local ở đây, cleanup_manager sẽ lo
            return {
                "filename": filename,
                "content": extracted_text
            }

        # --- Xử lý văn bản quá dài ---
        if len(extracted_text) > MAX_TEXT_LENGTH:
            original_length = len(extracted_text)
            extracted_text = extracted_text[:MAX_TEXT_LENGTH]
            extracted_text += f"\n\n[LƯU Ý: Nội dung file đã bị cắt bớt từ {original_length} ký tự xuống còn {MAX_TEXT_LENGTH} ký tự để phù hợp với giới hạn xử lý.]"
            logger.warning(f"Nội dung file '{filename}' quá dài ({original_length} ký tự), đã cắt bớt.")
        
        # Trả về nội dung đã xử lý
        return {
            "filename": filename,
            "content": f"Nội dung từ file '{filename}':\n```\n{extracted_text.strip()}\n```"
        }

    except Exception as e:
        logger.error(f"Lỗi khi trích xuất văn bản từ file '{filename}': {e}")
        # Không xóa file local ở đây, cleanup_manager sẽ lo
        return {"filename": filename, "content": f"[LỖI: Không thể trích xuất văn bản từ file '{filename}'. Lỗi: {e}]"}