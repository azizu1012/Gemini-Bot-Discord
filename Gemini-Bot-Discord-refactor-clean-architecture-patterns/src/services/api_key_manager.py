"""
API Key Manager - Proactive Rate Limiting System
Tham khảo từ gemini_translator_2_oneshot.py
Quản lý API keys với tracking request history và cooldown window
"""
import time
import random
import asyncio
from typing import Optional, Dict, List, Tuple
from collections import deque
from src.core.config import config
from src.core.logger import logger

# --- CẤU HÌNH RATE LIMITING ---
COOLDOWN_WINDOW = 1800  # 30 phút (giây)
MAX_REQUESTS_PER_WINDOW = 20  # 20 request/30 phút (giới hạn của Google Free Tier)
MIN_REQUEST_INTERVAL = 2.8  # Giây - Thời gian chờ tối thiểu giữa các request

# --- TRACKING STATE ---
key_request_history: Dict[str, List[float]] = {}  # {key_string: [timestamp1, timestamp2, ...]}
key_request_history_lock = asyncio.Lock()

delayed_keys_pool: Dict[str, float] = {}  # {key_string: release_time} - khi vượt quá giới hạn
delayed_keys_lock = asyncio.Lock()

# Key pool với tracking
api_keys_pool: List[Dict[str, any]] = []  # [{'key': 'xxx', 'last_used': 0.0}, ...]
api_keys_pool_lock = asyncio.Lock()

# Global throttling
last_request_time = 0.0
request_lock = asyncio.Lock()

# Logging
key_usage_log: Dict[str, Dict] = {}  # {key_string: {'usage_count': int, 'frozen_by_429': bool, ...}}
key_log_lock = asyncio.Lock()


def initialize_key_pool(keys: List[str]) -> List[Dict[str, any]]:
    """Chuyển danh sách key chuỗi thành danh sách các đối tượng để theo dõi."""
    return [{'key': k, 'last_used': 0.0} for k in keys]


async def check_key_rate_limit(key_string: str) -> Tuple[bool, float]:
    """
    Kiểm tra xem key có vượt quá giới hạn 20 request/30 phút không.
    Return: (is_available, time_to_wait_seconds)
    - is_available=True: key có thể dùng
    - is_available=False: key cần chờ (cooldown), time_to_wait_seconds là thời gian cần chờ
    """
    async with key_request_history_lock:
        now = time.time()
        
        # Lấy lịch sử request của key này
        history = key_request_history.get(key_string, [])
        
        # Xóa các request cũ hơn 30 phút
        history = [ts for ts in history if now - ts < COOLDOWN_WINDOW]
        key_request_history[key_string] = history
        
        # Nếu chưa đạt 20 request trong 30 phút -> có thể dùng
        if len(history) < MAX_REQUESTS_PER_WINDOW:
            return True, 0
        
        # Nếu đã 20 request trong 30 phút -> cần chờ
        # Thời gian chờ = (request #1 + 30 phút) - now
        oldest_request = history[0]
        wait_time = (oldest_request + COOLDOWN_WINDOW) - now
        return False, max(0, wait_time)


async def restore_delayed_keys():
    """Khôi phục các key từ delayed_keys_pool về main pool nếu đã hết thời gian delay."""
    async with delayed_keys_lock:
        now = time.time()
        ready_keys = [k for k, release_time in delayed_keys_pool.items() if now >= release_time]
        
        if ready_keys:
            async with api_keys_pool_lock:
                for key_string in ready_keys:
                    # Tìm key_obj trong api_keys_pool theo giá trị key
                    key_obj = next((k for k in api_keys_pool if k['key'] == key_string), None)
                    if not key_obj:
                        # Khôi phục lại key_obj từ dictionary
                        key_obj = {'key': key_string, 'last_used': 0.0}
                        api_keys_pool.append(key_obj)
                    del delayed_keys_pool[key_string]
                    
                    async with key_log_lock:
                        if key_string in key_usage_log:
                            key_usage_log[key_string]['frozen_by_429'] = False
                            key_usage_log[key_string]['in_cooldown'] = False


async def get_next_api_key() -> Optional[Dict[str, any]]:
    """
    Lấy một API key ngẫu nhiên từ pool, đảm bảo key không vượt quá giới hạn cooldown 30 phút.
    Trả về một đối tượng key.
    Nếu tất cả key đều trong cooldown, sẽ chờ key soonest-to-be-available.
    """
    # Trước tiên, khôi phục delayed keys nếu đã sẵn sàng
    await restore_delayed_keys()
    
    async with api_keys_pool_lock:
        if not api_keys_pool:
            return None
        
        while True:  # Vòng lặp để chọn key có sẵn
            now = time.time()
            available_keys = []
            
            # Tìm các key không trong cooldown 30 phút
            for key_obj in api_keys_pool:
                is_avail, wait_time = await check_key_rate_limit(key_obj['key'])
                if is_avail:
                    available_keys.append((key_obj, wait_time))
            
            if available_keys:
                # Chọn ngẫu nhiên từ các key có sẵn
                chosen_key_obj, _ = random.choice(available_keys)
                
                # Cập nhật thời điểm sử dụng và ghi vào lịch sử
                async with key_request_history_lock:
                    key_str = chosen_key_obj['key']
                    if key_str not in key_request_history:
                        key_request_history[key_str] = []
                    key_request_history[key_str].append(now)
                
                # Log tracking
                async with key_log_lock:
                    if key_str not in key_usage_log:
                        key_usage_log[key_str] = {
                            'usage_count': 0,
                            'frozen_by_429': False,
                            'frozen_time': 0,
                            'in_cooldown': False
                        }
                    key_usage_log[key_str]['usage_count'] += 1
                
                return chosen_key_obj
            
            # Không có key sẵn sàng -> tìm key soonest-to-be-available và chờ
            min_wait = float('inf')
            for key_obj in api_keys_pool:
                is_avail, wait_time = await check_key_rate_limit(key_obj['key'])
                if not is_avail and wait_time < min_wait:
                    min_wait = wait_time
            
            if min_wait < float('inf'):
                # Chờ key soonest để sẵn sàng
                wait_duration = min(min_wait + 1, 5)  # Chờ tối đa 5s
                logger.info(f"⏳ [COOLDOWN] Tất cả key đang trong cooldown. Chờ {wait_duration:.1f}s...")
                
                # Update log
                async with key_log_lock:
                    for key_obj in api_keys_pool:
                        is_avail, _ = await check_key_rate_limit(key_obj['key'])
                        if not is_avail and key_obj['key'] in key_usage_log:
                            key_usage_log[key_obj['key']]['in_cooldown'] = True
                
                await asyncio.sleep(wait_duration)
            else:
                # Không có key nào -> fallback sleep 0.5s
                await asyncio.sleep(0.5)


async def make_throttled_api_call(call_func, *args, **kwargs):
    """
    Thực hiện một lệnh gọi API với throttling toàn cục.
    Đảm bảo khoảng cách tối thiểu giữa các request.
    """
    global last_request_time
    async with request_lock:
        current_time = time.time()
        time_since_last = current_time - last_request_time
        if time_since_last < MIN_REQUEST_INTERVAL:
            sleep_duration = MIN_REQUEST_INTERVAL - time_since_last
            await asyncio.sleep(sleep_duration)
        last_request_time = time.time()
    
    # Thực hiện API call
    return await call_func(*args, **kwargs)


async def handle_429_error(key_obj: Dict[str, any], error_str: str):
    """
    Xử lý lỗi 429 - đưa key vào delayed pool và freeze nó.
    """
    key_string = key_obj['key']
    
    # Tính toán thời gian chờ dựa trên cooldown window
    is_avail, wait_time = await check_key_rate_limit(key_string)
    if not is_avail:
        release_time = time.time() + wait_time + 2  # Thêm 2s buffer
        
        # Log freeze event
        async with key_log_lock:
            if key_string not in key_usage_log:
                key_usage_log[key_string] = {
                    'usage_count': 0,
                    'frozen_by_429': False,
                    'frozen_time': 0,
                    'in_cooldown': False
                }
            key_usage_log[key_string]['frozen_by_429'] = True
            key_usage_log[key_string]['frozen_time'] = wait_time
        
        logger.warning(f"❌ [429 LIMIT] Key {key_string[:8]}... vượt quá 20 req/30 phút. Freeze {wait_time:.1f}s")
        
        async with delayed_keys_lock:
            delayed_keys_pool[key_string] = release_time
        
        async with api_keys_pool_lock:
            if key_obj in api_keys_pool:
                api_keys_pool.remove(key_obj)


async def initialize_api_key_manager():
    """Khởi tạo API key manager với danh sách keys từ config và health check."""
    global api_keys_pool
    
    if not config.GEMINI_API_KEYS:
        logger.error("Không tìm thấy Gemini API keys! Bot sẽ không thể hoạt động.")
        return False
    
    # Health check nhanh để chỉ dùng keys hoạt động
    from src.services.key_health_checker import quick_health_check
    working_keys = await quick_health_check(config.GEMINI_API_KEYS)
    
    if not working_keys:
        logger.error("⚠️ Không có key nào hoạt động sau health check!")
        # Fallback: dùng tất cả keys nếu health check fail
        working_keys = config.GEMINI_API_KEYS
        logger.warning("   → Fallback: Sử dụng tất cả keys (có thể có key không hoạt động)")
    else:
        logger.info(f"✅ [Health Check] {len(working_keys)}/{len(config.GEMINI_API_KEYS)} keys hoạt động")
    
    api_keys_pool = initialize_key_pool(working_keys)
    logger.info(f"✅ [API Manager] Đã khởi tạo {len(api_keys_pool)} API keys với Proactive Rate Limiting")
    logger.info(f"   - Cooldown Window: {COOLDOWN_WINDOW}s ({COOLDOWN_WINDOW//60} phút)")
    logger.info(f"   - Max Requests/Window: {MAX_REQUESTS_PER_WINDOW}")
    logger.info(f"   - Min Request Interval: {MIN_REQUEST_INTERVAL}s")
    return True


async def get_key_usage_stats() -> Dict:
    """Lấy thống kê sử dụng keys."""
    async with key_log_lock:
        return key_usage_log.copy()

