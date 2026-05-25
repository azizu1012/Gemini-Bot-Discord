import asyncio
import os
import time
from datetime import datetime
from typing import Dict, List, Optional
import aiohttp

from src.core.config import get_config
from src.core.api_router import get_api_router
from src.core.gemini_api_manager import GeminiApiManager

class HealthCheckerService:
    def __init__(self):
        self.config = get_config()
        self.router = get_api_router()
        self.gemini_mgr = GeminiApiManager(self.config, self.router)
        self.logger = self.config.logger
        self.is_running = False
        
        # Track status: key -> {'status': 'alive'/'dead', 'last_check': timestamp}
        self.key_status: Dict[str, Dict] = {}
        
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
            self.logger.warning(f"Health ping failed for key {self.router.get_key_name(api_key)}: {e}")
            return False

    async def _generate_health_report(self, changes: List[str]) -> Optional[str]:
        """Generate a summary report using LLM."""
        if not changes:
            return None
            
        prompt = (
            "Bạn là trợ lý theo dõi hệ thống. Dưới đây là log thay đổi trạng thái của các API keys (chết/sống lại). "
            "Hãy viết một báo cáo ngắn gọn, rõ ràng bằng tiếng Việt tổng hợp lại thời điểm key nào chết, key nào phục hồi. "
            "Giữ cho báo cáo thật ngắn gọn, chỉ liệt kê các thông tin quan trọng nhất.\n\n"
            "Dữ liệu log:\n" + "\n".join(changes)
        )
        
        try:
            # We use a fallback model from the pool, not the one that might be dead
            messages = [{"role": "user", "parts": [{"text": prompt}]}]
            response_text = await self.gemini_mgr.call_gemini_direct(prompt)
            return response_text
        except Exception as e:
            self.logger.error(f"Failed to generate health report via LLM: {e}")
            return "❌ Không thể tạo báo cáo bằng LLM. Log thô:\n" + "\n".join(changes)

    async def run_health_check_cycle(self) -> Optional[str]:
        """Run a single check cycle over custom endpoint keys and return a report if state changed."""
        if os.getenv("ENABLE_CUSTOM_ENDPOINT", "false").lower() != "true" or not self.config.OPENAI_CUSTOM_ENDPOINT:
            return None
            
        custom_keys = [
            k for k in self.router.main_keys 
            if k.startswith("sk-") and self.config.OPENAI_CUSTOM_ENDPOINT
        ]
        
        if not custom_keys:
            return None
            
        changes_detected = []
        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
        
        for key in custom_keys:
            key_name = self.router.get_key_name(key)
            is_alive = await self._ping_openai_key(key, self.config.OPENAI_CUSTOM_ENDPOINT)
            
            prev_status = self.key_status.get(key, {}).get("status", "unknown")
            current_status = "alive" if is_alive else "dead"
            
            if prev_status != "unknown" and prev_status != current_status:
                if current_status == "dead":
                    msg = f"[{timestamp_str}] Key {key_name} ĐÃ CHẾT (Mất kết nối/Hết hạn)."
                else:
                    msg = f"[{timestamp_str}] Key {key_name} ĐÃ PHỤC HỒI (Hoạt động bình thường)."
                changes_detected.append(msg)
                
            self.key_status[key] = {
                "status": current_status,
                "last_check": time.time()
            }
            
        if changes_detected:
            return await self._generate_health_report(changes_detected)
            
        return None

    async def _background_task(self, interval_seconds: int = 1800, admin_user: object = None):
        """Background loop to periodically check keys."""
        self.is_running = True
        self.logger.info("Health Checker Service started.")
        
        while self.is_running:
            try:
                report = await self.run_health_check_cycle()
                if report and admin_user:
                    decorated = f"━━━━━━━━━━━━━━━━━━━━━━\n🚨 **API HEALTH REPORT** 🚨\n\n{report}\n\n━━━━━━━━━━━━━━━━━━━━━━"
                    await admin_user.send(decorated)
            except Exception as e:
                self.logger.error(f"Error in health check cycle: {e}")
                
            # Sleep until next check
            await asyncio.sleep(interval_seconds)
            
    def start_background_check(self, admin_user, interval_seconds: int = 1800):
        """Start the background check task."""
        if not self.is_running:
            asyncio.create_task(self._background_task(interval_seconds, admin_user))
            
    def stop(self):
        """Stop the background check task."""
        self.is_running = False

# Global instance pattern similar to APIRouter
_health_checker_instance = None

def get_health_checker() -> HealthCheckerService:
    global _health_checker_instance
    if _health_checker_instance is None:
        _health_checker_instance = HealthCheckerService()
    return _health_checker_instance
