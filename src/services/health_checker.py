import asyncio
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
import aiohttp

from src.core.config import get_config
from src.core.api_router import get_api_router
from src.core.gemini_api_manager import GeminiApiManager
from src.database.repository import DatabaseRepository

class HealthCheckerService:
    def __init__(self):
        self.config = get_config()
        self.router = get_api_router()
        self.gemini_mgr = GeminiApiManager(self.config, self.router)
        self.logger = self.config.logger
        self.is_running = False

        # Sử dụng db_repo của router hoặc tự tạo mới
        self.db_repo = getattr(self.router, 'db_repo', None)
        if self.db_repo is None:
            self.db_repo = DatabaseRepository()

        # Theo dõi trạng thái chi tiết của từng API key
        # self.key_status[api_key] = {
        #     'provider': 'gemini' / 'openai',
        #     'status': 'alive' / 'dead',
        #     'downtime_start': float (timestamp khi bắt đầu phát hiện chết, None nếu đang sống),
        #     'last_check': float
        # }
        self.key_status: Dict[str, Dict[str, Any]] = {}
        self.admin_user = None

    async def _ping_openai_key(self, api_key: str, endpoint: str) -> bool:
        """Ping a specific OpenAI-compatible key to check if it's alive."""
        if not endpoint:
            return False

        base_url = endpoint
        if not base_url.endswith("/"):
            base_url += "/"
        if not base_url.endswith("v1/"):
            base_url += "v1/"

        url = f"{base_url}models"
        headers = {
            "Authorization": f"Bearer {api_key}"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    return response.status == 200
        except Exception as e:
            self.logger.warning(f"Health ping failed for OpenAI key {f'...{api_key[-4:]}'}: {e}")
            return False

    async def _generate_recovery_report(self, key_name: str, provider: str, downtime_start: float, uptime_time: float, downtime_str: str) -> str:
        """Generate a summary recovery report using LLM."""
        prompt = (
            f"Bạn là trợ lý theo dõi hệ thống bot Azuris.\n"
            f"Hệ thống vừa phát hiện khóa API sau đây đã phục hồi thành công:\n"
            f"- Loại khóa (Provider): {provider.upper()}\n"
            f"- Mã khóa che bớt: {key_name}\n"
            f"- Thời gian gián đoạn hoạt động (Downtime): {downtime_str}\n\n"
            f"Hãy viết một báo cáo phân tích khôi phục ngắn gọn, sinh động, chuyên nghiệp bằng tiếng Việt có dấu. "
            f"Đánh giá sức khỏe của khóa API đó, phân tích ảnh hưởng nhẹ và gửi lời chúc mừng hệ thống hoạt động ổn định trở lại. "
            f"Đảm bảo báo cáo súc tích, chỉ từ 3-5 câu chất lượng."
        )

        try:
            response_text = await self.gemini_mgr.call_gemini_direct(prompt)
            if response_text and "Error calling LLM" not in response_text:
                return response_text
            raise ValueError("LLM returned empty or error response")
        except Exception as e:
            self.logger.error(f"Failed to generate health recovery report via LLM: {e}")
            # Fallback report if LLM fails
            return (
                f"Sự cố gián đoạn dịch vụ của khóa API **{key_name}** ({provider.upper()}) đã được khắc phục hoàn toàn.\n"
                f"Hệ thống tự động ghi nhận dịch vụ đã khôi phục trạng thái hoạt động bình thường sau `{downtime_str}` ngoại tuyến. "
                f"Mọi tiến trình xử lý liên quan đến khóa này đã được định tuyến trở lại bình thường."
            )

    async def run_health_check_cycle(self, force_send_alerts: bool = True) -> List[str]:
        """Run a single check cycle over all API keys in database pool and return logs if status changed."""
        changes_detected = []

        # Kiểm tra tính hợp lệ của Custom API Endpoint để tránh phát ra cảnh báo giả
        endpoint = getattr(self.config, 'OPENAI_CUSTOM_ENDPOINT', '').strip()
        if not endpoint or not (endpoint.startswith("http://") or endpoint.startswith("https://")):
            self.logger.warning(
                f"[HealthChecker] Custom API Endpoint rỗng hoặc không hợp lệ ('{endpoint}'). "
                f"Tạm dừng chu kỳ ping các Custom API key để tránh phát ra cảnh báo giả."
            )
            return changes_detected

        try:
            # Lấy tất cả các keys từ database pool
            db_keys = await self.db_repo.get_all_keys_from_pool()
        except Exception as e:
            self.logger.error(f"Error fetching API keys from DB pool: {e}")
            # Fallback lấy key từ config nếu DB lỗi
            db_keys = []
            if self.config.GEMINI_API_KEYS:
                for idx, key in enumerate(self.config.GEMINI_API_KEYS):
                    db_keys.append({
                        "key_id": idx,
                        "api_key": key,
                        "provider": "gemini",
                        "is_active": True,
                        "cooldown_until": None
                    })

        if not db_keys:
            return changes_detected

        for entry in db_keys:
            api_key = entry.get("api_key")
            provider = entry.get("provider", "gemini")
            is_active = entry.get("is_active", True)

            # Chỉ giám sát custom API keys (OpenAI-compatible)
            # Bỏ qua hoàn toàn key Gemini (GenAI SDK) để loại bỏ nguy cơ lãng phí quota và nghẽn Event Loop
            if provider != "openai":
                continue

            # Chỉ ping các keys đang hoạt động (không bị vô hiệu hóa hẳn)
            if not is_active:
                continue

            key_name = f'...{api_key[-4:]}'

            # Ping tương ứng theo loại provider (ở đây chắc chắn là openai do đã lọc ở trên)
            is_alive = await self._ping_openai_key(api_key, self.config.OPENAI_CUSTOM_ENDPOINT)

            prev_info = self.key_status.get(api_key)
            prev_status = prev_info.get("status", "unknown") if prev_info else "unknown"
            current_status = "alive" if is_alive else "dead"

            now_ts = time.time()

            # Đăng ký trạng thái ban đầu nếu chưa có trong memory
            if prev_status == "unknown":
                self.key_status[api_key] = {
                    "provider": provider,
                    "status": current_status,
                    "downtime_start": None if is_alive else now_ts,
                    "last_check": now_ts
                }

                # Nếu lần đầu check phát hiện key chết, báo động ngay
                if current_status == "dead" and force_send_alerts and self.admin_user:
                    downtime_start = now_ts
                    discord_ts_start = f"<t:{int(downtime_start)}:F> (<t:{int(downtime_start)}:R>)"
                    alert_msg = (
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🚨 **API ALERT: KEY DOWN** 🚨\n\n"
                        f"🔑 **Key**: `{key_name}`\n"
                        f"🌐 **Provider**: `{provider.upper()}`\n"
                        f"📉 **Trạng thái**: Đã mất kết nối / Chết.\n"
                        f"⏰ **Thời điểm bắt đầu**: {discord_ts_start}\n\n"
                        f"Bot sẽ tự động cảnh báo khi khóa này khôi phục trở lại.\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )
                    try:
                        await self.admin_user.send(alert_msg)
                    except Exception as err:
                        self.logger.error(f"Error sending down alert to admin: {err}")
                continue

            # Phát hiện chuyển đổi trạng thái
            if prev_status != current_status:
                if current_status == "dead":
                    # Chuyển từ sống sang chết
                    downtime_start = now_ts
                    self.key_status[api_key] = {
                        "provider": provider,
                        "status": "dead",
                        "downtime_start": downtime_start,
                        "last_check": now_ts
                    }

                    discord_ts_start = f"<t:{int(downtime_start)}:F> (<t:{int(downtime_start)}:R>)"
                    alert_msg = (
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🚨 **API ALERT: KEY DOWN** 🚨\n\n"
                        f"🔑 **Key**: `{key_name}`\n"
                        f"🌐 **Provider**: `{provider.upper()}`\n"
                        f"📉 **Trạng thái**: Đã mất kết nối / Chết.\n"
                        f"⏰ **Thời điểm bắt đầu**: {discord_ts_start}\n\n"
                        f"Bot sẽ tự động cảnh báo khi khóa này khôi phục trở lại.\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )
                    changes_detected.append(f"[KEY DOWN] Key {key_name} ({provider.upper()}) đã chết lúc {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

                    if force_send_alerts and self.admin_user:
                        try:
                            await self.admin_user.send(alert_msg)
                        except Exception as err:
                            self.logger.error(f"Error sending down alert to admin: {err}")

                else:
                    # Chuyển từ chết sang sống (Phục hồi!)
                    downtime_start = prev_info.get("downtime_start") if prev_info else now_ts
                    if downtime_start is None:
                        downtime_start = now_ts

                    downtime_seconds = int(now_ts - downtime_start)

                    # Định dạng chuỗi downtime
                    if downtime_seconds < 60:
                        downtime_str = f"{downtime_seconds}s"
                    elif downtime_seconds < 3600:
                        downtime_str = f"{downtime_seconds // 60}m {downtime_seconds % 60}s"
                    else:
                        hours = downtime_seconds // 3600
                        minutes = (downtime_seconds % 3600) // 60
                        seconds = downtime_seconds % 60
                        downtime_str = f"{hours}h {minutes}m {seconds}s"

                    self.key_status[api_key] = {
                        "provider": provider,
                        "status": "alive",
                        "downtime_start": None,
                        "last_check": now_ts
                    }

                    discord_ts_start = f"<t:{int(downtime_start)}:F> (<t:{int(downtime_start)}:R>)"
                    discord_ts_end = f"<t:{int(now_ts)}:F> (<t:{int(now_ts)}:R>)"

                    changes_detected.append(f"[KEY RECOVERED] Key {key_name} ({provider.upper()}) đã khôi phục lúc {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} sau {downtime_str} downtime.")

                    if force_send_alerts and self.admin_user:
                        # Sinh báo cáo khôi phục bằng LLM
                        llm_summary = await self._generate_recovery_report(key_name, provider, downtime_start, now_ts, downtime_str)

                        recovery_msg = (
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🎉 **API RECOVERY REPORT** 🎉\n\n"
                            f"🔑 **Key**: `{key_name}`\n"
                            f"🌐 **Provider**: `{provider.upper()}`\n"
                            f"📈 **Trạng thái**: Đã phục hồi và hoạt động ổn định!\n\n"
                            f"⏰ **Thời điểm chết**: {discord_ts_start}\n"
                            f"⏰ **Thời điểm phục hồi**: {discord_ts_end}\n"
                            f"⏱️ **Tổng thời gian ngoại tuyến (Downtime)**: `{downtime_str}`\n\n"
                            f"--- \n"
                            f"🤖 *Phân tích hệ thống (LLM Generated):*\n"
                            f"{llm_summary}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━"
                        )
                        try:
                            await self.admin_user.send(recovery_msg)
                        except Exception as err:
                            self.logger.error(f"Error sending recovery report to admin: {err}")
            else:
                # Trạng thái không đổi, chỉ cập nhật thời điểm check
                if prev_info:
                    self.key_status[api_key]["last_check"] = now_ts

        return changes_detected

    async def _background_task(self, interval_seconds: int = 1800, admin_user: object = None):
        """Background loop to periodically check keys."""
        self.is_running = True
        self.admin_user = admin_user
        self.logger.info("Health Checker Service started.")

        # Lần chạy đầu tiên khi khởi động bot: chỉ nạp trạng thái ban đầu của keys, không spam cảnh báo down
        try:
            await self.run_health_check_cycle(force_send_alerts=False)
        except Exception as e:
            self.logger.error(f"Error in initial health check: {e}")

        while self.is_running:
            try:
                # Chờ chu kỳ tiếp theo
                await asyncio.sleep(interval_seconds)
                if not self.is_running:
                    break
                await self.run_health_check_cycle(force_send_alerts=True)
            except Exception as e:
                self.logger.error(f"Error in health check cycle: {e}")

    def start_background_check(self, admin_user, interval_seconds: int = 1800):
        """Start the background check task."""
        if hasattr(self, "_background_task_task") and self._background_task_task and not self._background_task_task.done():
            self.logger.info("Health checker background task is already running. Stopping it first to restart safely.")
            self.stop()

        self.is_running = True
        self.admin_user = admin_user
        # Lưu giữ tham chiếu mạnh để tránh bị Garbage Collector tự động thu dọn
        self._background_task_task = asyncio.create_task(self._background_task(interval_seconds, admin_user))

    def stop(self):
        """Stop the background check task."""
        self.is_running = False
        if hasattr(self, "_background_task_task") and self._background_task_task:
            self._background_task_task.cancel()
            self._background_task_task = None

# Global instance pattern similar to APIRouter
_health_checker_instance = None

def get_health_checker() -> HealthCheckerService:
    global _health_checker_instance
    if _health_checker_instance is None:
        _health_checker_instance = HealthCheckerService()
    return _health_checker_instance
