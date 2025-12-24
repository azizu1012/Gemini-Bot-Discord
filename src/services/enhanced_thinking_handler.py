"""Enhanced Thinking Handler - Handle THINKING block with 2-call strategy"""

import re
from typing import Optional, Dict, Any, Tuple
from src.core.logger import logger

async def precheck_search_needed(query: str, user_id: str) -> Tuple[bool, Optional[str]]:
    """PRE-CHECK: Before calling Gemini, detect if search is needed from user query
    
    Returns: (needs_search, search_query_expanded)
    """
    from src.services.dual_api_strategy import get_dual_api_strategy
    
    strategy = await get_dual_api_strategy()
    needs_search, search_query = await strategy.check_search_needed_from_query(query)
    
    if needs_search:
        logger.info(f"🔍 PRE-CHECK: Search needed from query. User: {user_id}")
        return True, search_query
    
    return False, None

async def handle_thinking_with_dual_strategy(
    reply: str,
    user_id: str,
    query: str,
    messages: list,
    model_name: str,
    run_gemini_api_func,
) -> str:
    """Handle THINKING block with 2-call strategy
    
    Returns: Final response for user
    """
    from src.services.thinking_cache import get_thinking_cache
    from src.services.dual_api_strategy import get_dual_api_strategy
    
    thinking_cache = await get_thinking_cache()
    strategy = await get_dual_api_strategy()
    
    # 1. Extract THINKING block
    thinking_block_pattern = r'<THINKING>(.*?)</THINKING>'
    thinking_match = re.search(thinking_block_pattern, reply, re.DOTALL)
    
    original_thinking_content = ""
    default_thinking_content = ""
    
    if thinking_match:
        original_thinking_content = thinking_match.group(1).strip()
        logger.info(f"--- BẮT ĐẦU THINKING DEBUG CHO USER: {user_id} ---")
        logger.info(original_thinking_content)
        logger.info(f"--- KẾT THÚC THINKING DEBUG ---")
    else:
        logger.warning(f"Không có THINKING block từ model. User: {user_id}")
        return reply  # Return as-is nếu không có THINKING
    
    # 2. Cache THINKING block
    cache_key = await thinking_cache.save_thinking(user_id, original_thinking_content, query)
    logger.info(f"💾 Cached THINKING block: {cache_key}")
    
    # 3. Kiểm tra xem có reply content ngoài THINKING không
    reply_final = re.sub(thinking_block_pattern, '', reply, flags=re.DOTALL).strip()
    
    if reply_final:
        # Model đã trả response → không cần gọi lại
        logger.info(f"✅ Model trả response kèm THINKING. User: {user_id}")
        return reply_final
    
    # 4. Chỉ có THINKING → phân tích xem cần search không
    logger.warning(f"⚠️ Mô hình chỉ trả THINKING mà không có response. Phân tích NEXT action. User: {user_id}")
    
    status, search_query = await strategy.analyze_thinking_for_next_action(original_thinking_content)
    
    if status == "READY":
        # Model sẵn sàng trả lời dựa trên THINKING
        logger.info(f"Model sẵn sàng trả lời từ THINKING. User: {user_id}")
        return _extract_answer_from_thinking(original_thinking_content)
    
    elif status == "NEED_SEARCH":
        # ==================== CALL 2: Search API ====================
        logger.info(f"🔍 Cần tìm kiếm thêm. Query: {search_query}. User: {user_id}")
        
        if not search_query:
            search_query = query  # Fallback to original query
        
        search_results = await strategy.call_search_api(search_query, api_type="tavily")
        
        if not search_results:
            logger.warning(f"Search API trả về kết quả rỗng")
            search_results = "[Không tìm được thông tin mới]"
        
        # 5. Pass search results về Gemini (lần 2)
        logger.info(f"📤 Gửi search results lần 2 đến Gemini. User: {user_id}")
        
        # Build message cho call 2
        search_message = strategy._build_search_only_message(original_thinking_content, search_results)
        
        # Prepare messages để gọi lần 2 (chỉ cần user message + search results)
        messages_for_second_call = [
            {
                "role": "system",
                "content": "Based on search results, provide a direct answer in Vietnamese. Keep it friendly and concise."
            },
            {
                "role": "user",
                "content": search_message
            }
        ]
        
        # Call Gemini lần 2 (TỚI ĐA 2 CALLS!)
        final_response = await run_gemini_api_func(
            messages=messages_for_second_call,
            model_name=model_name,
            user_id=user_id,
            temperature=0.5,  # Lower temperature để tránh lạc đề
            max_tokens=1500
        )
        
        if final_response and not final_response.startswith("Lỗi:"):
            # Loại bỏ THINKING block nếu có
            final_response = re.sub(thinking_block_pattern, '', final_response, flags=re.DOTALL).strip()
            logger.info(f"✅ Call 2 thành công. User: {user_id}")
            return final_response
        else:
            logger.error(f"Call 2 thất bại: {final_response}")
            return _extract_answer_from_thinking(original_thinking_content)
    
    else:
        # UNKNOWN state
        logger.warning(f"Không xác định được hành động. Trích xuất answer từ THINKING.")
        return _extract_answer_from_thinking(original_thinking_content)


def _extract_answer_from_thinking(thinking_content: str) -> str:
    """Trích xuất câu trả lời từ khối THINKING
    
    Tìm các section:
    - Kết luận / Conclusion
    - Đáp án / Answer
    - Phần cuối cùng (fallback)
    """
    thinking_lines = thinking_content.strip().split('\n')
    
    # Tìm các marker
    markers = [
        "Kết luận:",
        "KẾT LUẬN:",
        "Conclusion:",
        "CONCLUSION:",
        "Đáp án:",
        "Answer:",
        "**Kết quả:**",
    ]
    
    for marker in markers:
        for i, line in enumerate(thinking_lines):
            if marker in line:
                # Lấy từ dòng này trở đi
                result = '\n'.join(thinking_lines[i+1:]).strip()
                if result:
                    return result
    
    # Fallback: lấy 50% phần cuối
    middle = len(thinking_lines) // 2
    result = '\n'.join(thinking_lines[middle:]).strip()
    
    if not result:
        # Last resort
        result = thinking_lines[-1] if thinking_lines else "Xin lỗi, không thể xử lý yêu cầu của bạn"
    
    return result


def _is_only_thinking(reply: str) -> bool:
    """Kiểm tra xem reply chỉ có THINKING block không"""
    thinking_pattern = r'<THINKING>.*?</THINKING>'
    # Remove THINKING block
    without_thinking = re.sub(thinking_pattern, '', reply, flags=re.DOTALL).strip()
    
    # Nếu chỉ còn whitespace → là "only thinking"
    return len(without_thinking) < 50
