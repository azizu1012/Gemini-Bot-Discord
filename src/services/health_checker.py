import asyncio
from typing import Dict, List, Optional, Any

from src.core.config import get_config
from src.database.repository import DatabaseRepository

class HealthCheckerService:
    def __init__(self):
        self.config = get_config()
        self.logger = self.config.logger
        self.is_running = False

        # db_repo được bot_core gán sau khi tạo instance
        self.db_repo: Optional[DatabaseRepository] = None

        self.key_status: Dict[str, Dict[str, Any]] = {}
        self.admin_user = None

    async def _generate_recovery_report(self, key_name: str, provider: str, downtime_start: float, uptime_time: float, downtime_str: str) -> str:
        """Generate a summary recovery report (static text, no LLM)."""
        return (
            f"Sự cố gián đoạn dịch vụ của khóa API **{key_name}** ({provider.upper()}) đã được khắc phục hoàn toàn.\n"
            f"Hệ thống tự động ghi nhận dịch vụ đã khôi phục trạng thái hoạt động bình thường sau `{downtime_str}` ngoại tuyến. "
            f"Mọi tiến trình xử lý liên quan đến khóa này đã được định tuyến trở lại bình thường."
        )

    async def run_health_check_cycle(
        self,
        force_send_alerts: bool = True,
        full_key_scan: bool = False,
        selected_model_ids: Optional[List[str]] = None,
        ping_selected_models: bool = True,
    ) -> Dict[str, Any]:
        """Health check cycle. Custom endpoint monitoring is now handled by Router API."""
        return {
            "changes": [],
            "key_checks": [],
            "model_scan": {"success": True, "note": "Health checks handled by Router API."},
            "model_ping": [],
        }

    async def _background_task(self, interval_seconds: int = 1800, admin_user: object = None):
        """Background loop to periodically check keys."""
        self.is_running = True
        self.admin_user = admin_user
        self.logger.info("Health Checker Service started.")

        # Lần chạy đầu tiên khi khởi động bot: chỉ nạp trạng thái ban đầu của keys, không spam cảnh báo down
        try:
            await self.run_health_check_cycle(force_send_alerts=False, ping_selected_models=False)
        except Exception as e:
            self.logger.error(f"Error in initial health check: {e}")

        while self.is_running:
            try:
                # Chờ chu kỳ tiếp theo
                await asyncio.sleep(interval_seconds)
                if not self.is_running:
                    break
                await self.run_health_check_cycle(force_send_alerts=True, ping_selected_models=False)
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

# Global instance pattern
_health_checker_instance = None

def get_health_checker() -> HealthCheckerService:
    global _health_checker_instance
    if _health_checker_instance is None:
        _health_checker_instance = HealthCheckerService()
    return _health_checker_instance
