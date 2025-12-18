"""
Prompt Builder - Builder Pattern
Xây dựng system prompt một cách linh hoạt và có cấu trúc
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from core.config import config


class PromptBuilder:
    """
    Builder Pattern cho System Prompt
    Cho phép xây dựng prompt từng phần một cách linh hoạt
    """
    
    def __init__(self):
        self.prompt_parts = []
        self.variables = {}
    
    def load_base_prompt(self) -> 'PromptBuilder':
        """Load base prompt từ file"""
        try:
            with open(config.PROMPT_PATH, 'r', encoding='utf-8') as f:
                base_prompt = f.read()
            self.prompt_parts.append(base_prompt)
        except FileNotFoundError:
            self.prompt_parts.append("Base prompt not found. Using default.")
        return self
    
    def add_time_info(self, user_id: str) -> 'PromptBuilder':
        """Thêm thông tin thời gian"""
        now_utc = datetime.now(timezone.utc)
        current_datetime_utc = now_utc.strftime("%d/%m/%Y %H:%M:%S UTC")
        
        current_time_gmt7 = datetime.now(timezone(timedelta(hours=7)))
        date_for_comparison = current_time_gmt7.strftime("%B %d, %Y")
        current_date_vi = current_time_gmt7.strftime("%A, ngày %d tháng %m năm %Y")
        
        time_info = (
            f'Current UTC Time (Máy chủ): {current_datetime_utc}. '
            f'Current User Time (VN): {current_date_vi}. '
            f'Kiến thức cutoff: 2024.\n'
            f'QUAN TRỌNG: Mọi thông tin về thời gian (hôm nay, bây giờ) PHẢI dựa trên thời gian VN ({date_for_comparison}).\n\n'
        )
        
        self.variables['current_datetime_utc'] = current_datetime_utc
        self.variables['current_date_vi'] = current_date_vi
        self.variables['date_for_comparison'] = date_for_comparison
        self.variables['user_id'] = user_id
        
        self.prompt_parts.insert(0, time_info)
        return self
    
    def add_memory_context(self, all_memory: Dict, user_id: str) -> 'PromptBuilder':
        """Thêm ngữ cảnh từ memory"""
        if not all_memory:
            return self
        
        memory_text = "\n\nLỊCH SỬ CHAT CỦA CÁC USER KHÁC TRONG SERVER (để tham khảo ngữ cảnh):\n"
        for mem_user_id, mem_messages in all_memory.items():
            if mem_user_id == user_id:
                continue
            if mem_messages:
                memory_text += f"\n--- User ID: {mem_user_id} (KHÔNG PHẢI user đang chat) ---\n"
                for msg in mem_messages[-3:]:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")[:150]
                    memory_text += f"[{role}]: {content}\n"
        
        if len(memory_text) > len("\n\nLỊCH SỬ CHAT CỦA CÁC USER KHÁC TRONG SERVER (để tham khảo ngữ cảnh):\n"):
            self.prompt_parts.append(memory_text)
        
        return self
    
    def add_image_instructions(self, image_url: str, query: str) -> 'PromptBuilder':
        """Thêm hướng dẫn xử lý ảnh"""
        comprehensive_image_question = (
            "Phân tích toàn bộ nội dung trong ảnh này một cách chi tiết nhất có thể. "
            "Trích xuất tất cả văn bản, nhận diện các đối tượng, nhân vật, thương hiệu, và mô tả ngữ cảnh. "
            "Nếu là hóa đơn, đơn hàng, hoặc giao diện ứng dụng, hãy đọc và tóm tắt các thông tin chính như sản phẩm, giá cả, ưu đãi, tổng tiền, trạng thái, v.v. "
            "Cung cấp một bản tóm tắt đầy đủ và có cấu trúc."
        )
        
        image_instruction = (
            f"\n\nUser vừa gửi một hình ảnh có URL: {image_url}. "
            f"**BƯỚC 1 (CƯỠNG CHẾ):** Bạn BẮT BUỘC phải gọi tool `image_recognition(image_url='{image_url}', question='{comprehensive_image_question}')` để phân tích ảnh.\n\n"
            
            f"**BƯỚC 2 (CƯỠNG CHẾ - TUYỆT ĐỐI):** Sau khi nhận được `function_response` (kết quả phân tích ảnh từ tool), bạn BẮT BUỘC phải tạo câu trả lời cuối cùng cho user và TUÂN THỦ **3 LUẬT** SAU (KHÔNG CÓ NGOẠI LỆ):\n\n"
            
            f"   1. **LUẬT THINKING (BẮT BUỘC):** Câu trả lời CUỐI CÙNG của bạn PHẢI BẮT ĐẦU bằng khối `<THINKING>` (theo LUẬT CƯỠNG CHẾ OUTPUT trong system prompt chính).\n"
            f"   2. **LUẬT TÍNH CÁCH (BẮT BUỘC):** Bạn PHẢI áp dụng TÍNH CÁCH (e-girl, vui vẻ, emoji) khi diễn giải kết quả tool, KHÔNG ĐƯỢC tóm tắt thô/robot.\n"
            f"   3. **LUẬT NGÔN NGỮ (TUYỆT ĐỐI):** BẠN PHẢI TRẢ LỜI BẰNG **TIẾNG VIỆT 100%**. Bất kể `function_response` (kết quả tool) là tiếng Anh hay tiếng gì, **CẢ KHỐI `<THINKING>` VÀ CÂU TRẢ LỜI CUỐI CÙNG** của bạn BẮT BUỘC phải là **TIẾNG VIỆT**.\n\n"
            
            f"**YÊU CẦU CỦA USER (SAU KHI PHÂN TÍCH ẢNH):** '{query}'"
        )
        
        self.prompt_parts.append(image_instruction)
        return self
    
    def build(self) -> str:
        """Build final prompt với variable substitution"""
        final_prompt = "\n".join(self.prompt_parts)
        
        # Replace variables
        for key, value in self.variables.items():
            final_prompt = final_prompt.replace(f"{{{key}}}", str(value))
        
        return final_prompt
    
    def reset(self) -> 'PromptBuilder':
        """Reset builder để tạo prompt mới"""
        self.prompt_parts = []
        self.variables = {}
        return self

