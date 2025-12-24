import discord
import os
import aiohttp
from typing import Optional, Dict
from src.core.config import logger, FILE_STORAGE_PATH, MIN_FREE_SPACE_MB
from src.managers.cleanup_manager import CleanupManager

try:
    import pypdf
except ImportError:
    pypdf = None


class FileParserService:
    """Service for parsing and extracting text from uploaded files."""
    
    MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024
    MAX_TEXT_LENGTH = 10000
    
    def __init__(self, storage_path: str = FILE_STORAGE_PATH, cleanup_mgr: Optional[CleanupManager] = None):
        self.storage_path = storage_path
        self.cleanup_mgr = cleanup_mgr or CleanupManager(storage_path, MIN_FREE_SPACE_MB)
        self.logger = logger
    
    async def parse_attachment(self, attachment: discord.Attachment) -> Optional[Dict[str, str]]:
        """Parse and extract text from attachment."""
        filename = attachment.filename
        unique_filename = f"{attachment.id}_{filename}"
        local_path = os.path.join(self.storage_path, unique_filename)
        
        if attachment.size > self.MAX_FILE_SIZE_BYTES:
            self.logger.warning(f"File {filename} ({(attachment.size / 1024 / 1024):.2f} MB) too large. Skipping.")
            return {"filename": filename, "content": f"[LỖI: File quá lớn, giới hạn {self.MAX_FILE_SIZE_BYTES // 1024 // 1024}MB]"}
        
        # STEP 1: Download and save locally
        try:
            required_space_mb = (attachment.size // (1024 * 1024)) + 10
            if self.cleanup_mgr.get_disk_free_space_mb() < required_space_mb:
                self.logger.warning(f"Disk full. Cannot download new file. Need {required_space_mb}MB.")
                return {"filename": filename, "content": "[LỖI: Server sắp hết bộ nhớ. Vui lòng thử lại sau.]"}
            
            os.makedirs(self.storage_path, exist_ok=True)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(attachment.url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        with open(local_path, 'wb') as f:
                            f.write(data)
                        self.logger.info(f"Saved local file: {local_path}")
                    else:
                        raise Exception(f"HTTP Error {resp.status}")
        
        except Exception as e:
            self.logger.error(f"Error downloading file from Discord: {e}")
            return {"filename": filename, "content": "[LỖI: Không thể tải file về local]"}
        
        # STEP 2: Extract text
        extracted_text = ""
        file_extension = os.path.splitext(filename)[1].lower()
        
        try:
            if file_extension == '.txt':
                with open(local_path, 'r', encoding='utf-8', errors='ignore') as f:
                    extracted_text = f.read()
                self.logger.info(f"Extracted text from TXT: {filename}")
            
            elif file_extension == '.pdf':
                if not pypdf:
                    extracted_text = "[LỖI: pypdf library not installed for PDF parsing]"
                else:
                    try:
                        reader = pypdf.PdfReader(local_path)
                        for page in reader.pages:
                            extracted_text += page.extract_text() + "\n"
                        self.logger.info(f"Extracted text from PDF: {filename}")
                    except Exception as e:
                        self.logger.error(f"Error reading PDF {filename}: {e}")
                        extracted_text = f"[LỖI: Không thể đọc nội dung file PDF '{filename}'. Có thể file bị hỏng hoặc được bảo vệ.]"
            
            else:
                extracted_text = f"[LƯU Ý: File '{filename}' có định dạng '{file_extension}' không được hỗ trợ trích xuất văn bản. Chỉ hỗ trợ .txt và .pdf.]"
                self.logger.warning(f"File '{filename}' format '{file_extension}' not supported for text extraction.")
                return {
                    "filename": filename,
                    "content": extracted_text
                }
            
            # Handle overly long text
            if len(extracted_text) > self.MAX_TEXT_LENGTH:
                original_length = len(extracted_text)
                extracted_text = extracted_text[:self.MAX_TEXT_LENGTH]
                extracted_text += f"\n\n[LƯU Ý: Nội dung file đã bị cắt bớt từ {original_length} ký tự xuống còn {self.MAX_TEXT_LENGTH} ký tự để phù hợp với giới hạn xử lý.]"
                self.logger.warning(f"File '{filename}' content too long ({original_length} chars), truncated.")
            
            return {
                "filename": filename,
                "content": f"Nội dung từ file '{filename}':\n```\n{extracted_text.strip()}\n```"
            }
        
        except Exception as e:
            self.logger.error(f"Error extracting text from '{filename}': {e}")
            return {"filename": filename, "content": f"[LỖI: Không thể trích xuất văn bản từ file '{filename}'. Lỗi: {e}]"}
