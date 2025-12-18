"""
Key Health Checker - Parallel Testing System
Kiểm tra keys nào hoạt động nhanh bằng cách test song song
"""
import asyncio
import time
from typing import List, Dict, Tuple
try:
    import google.generativeai as genai
    from google.genai.errors import APIError
except ImportError:
    # Fallback nếu import fail
    genai = None
    APIError = Exception

from src.core.config import config
from src.core.logger import logger


async def test_single_key(key: str, timeout: float = 3.0) -> Tuple[str, bool, float]:
    """
    Test một key với timeout ngắn
    Returns: (key, is_working, response_time)
    """
    if not genai:
        return (key, False, timeout)
    
    start_time = time.time()
    try:
        # Test với một request đơn giản
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.0-flash-exp")
        
        # Gọi API với timeout
        response = await asyncio.wait_for(
            asyncio.to_thread(model.generate_content, "Hi"),
            timeout=timeout
        )
        
        response_time = time.time() - start_time
        
        # Kiểm tra response hợp lệ
        if response and response.text:
            return (key, True, response_time)
        else:
            return (key, False, response_time)
            
    except asyncio.TimeoutError:
        return (key, False, timeout)
    except Exception as e:
        # 429 hoặc quota exceeded - key vẫn hoạt động nhưng bị limit
        error_str = str(e)
        if "429" in error_str or "quota" in error_str.lower() or "rate limit" in error_str.lower():
            return (key, True, time.time() - start_time)  # Key hoạt động, chỉ bị limit
        return (key, False, time.time() - start_time)


async def check_all_keys_parallel(keys: List[str], max_concurrent: int = 10) -> Dict[str, Dict]:
    """
    Kiểm tra tất cả keys song song (parallel) để nhanh
    Returns: {key: {'working': bool, 'response_time': float, 'rank': int}}
    """
    logger.info(f"🔍 [Health Check] Bắt đầu kiểm tra {len(keys)} keys song song...")
    
    # Chia keys thành batches để không quá tải
    results = {}
    working_keys = []
    
    for i in range(0, len(keys), max_concurrent):
        batch = keys[i:i + max_concurrent]
        batch_results = await asyncio.gather(*[test_single_key(key) for key in batch])
        
        for key, is_working, response_time in batch_results:
            results[key] = {
                'working': is_working,
                'response_time': response_time
            }
            if is_working:
                working_keys.append((key, response_time))
    
    # Sắp xếp working keys theo response time (nhanh nhất trước)
    working_keys.sort(key=lambda x: x[1])
    
    # Thêm rank vào results
    for rank, (key, _) in enumerate(working_keys, 1):
        results[key]['rank'] = rank
    
    # Log kết quả
    working_count = len(working_keys)
    logger.info(f"✅ [Health Check] Hoàn tất: {working_count}/{len(keys)} keys hoạt động")
    if working_keys:
        fastest = working_keys[0]
        logger.info(f"   ⚡ Key nhanh nhất: {fastest[0][:8]}... ({fastest[1]:.2f}s)")
    
    return results


async def get_working_keys_sorted(keys: List[str]) -> List[str]:
    """
    Lấy danh sách keys hoạt động, sắp xếp theo tốc độ (nhanh nhất trước)
    """
    health_results = await check_all_keys_parallel(keys)
    
    # Lọc và sắp xếp
    working = [
        (key, data['response_time']) 
        for key, data in health_results.items() 
        if data.get('working', False)
    ]
    working.sort(key=lambda x: x[1])  # Sắp xếp theo response_time
    
    return [key for key, _ in working]


async def quick_health_check(keys: List[str]) -> List[str]:
    """
    Health check nhanh - chỉ test với timeout ngắn (1s)
    Trả về danh sách keys hoạt động
    """
    logger.info(f"⚡ [Quick Check] Kiểm tra nhanh {len(keys)} keys...")
    
    tasks = [test_single_key(key, timeout=1.0) for key in keys]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    working = []
    for result in results:
        if isinstance(result, tuple) and result[1]:  # (key, is_working, time)
            working.append(result[0])
    
    logger.info(f"✅ [Quick Check] {len(working)}/{len(keys)} keys hoạt động")
    return working

