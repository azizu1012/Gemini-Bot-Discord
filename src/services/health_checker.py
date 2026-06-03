import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import aiohttp

from src.core.config import get_config
from src.core.api_router import get_api_router
from src.core.custom_endpoint import custom_models_url, normalize_custom_endpoint
from src.database.repository import DatabaseRepository

class HealthCheckerService:
    def __init__(self):
        self.config = get_config()
        self.router = get_api_router()
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

    async def _fetch_openai_models(self, api_key: str, endpoint: str) -> Dict[str, Any]:
        """Fetch /v1/models for a specific OpenAI-compatible key."""
        if not endpoint:
            return {"alive": False, "models": [], "scan_success": False, "error": "missing_endpoint"}

        try:
            normalized_endpoint = normalize_custom_endpoint(endpoint)
        except ValueError as endpoint_error:
            return {"alive": False, "models": [], "scan_success": False, "error": str(endpoint_error)}

        url = custom_models_url(normalized_endpoint)
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status != 200:
                        body = await response.text()
                        return {
                            "alive": False,
                            "models": [],
                            "scan_success": False,
                            "error": f"HTTP {response.status}: {body[:180]}",
                        }
                    try:
                        payload = await response.json(content_type=None)
                    except Exception as json_error:
                        return {
                            "alive": True,
                            "models": [],
                            "scan_success": False,
                            "error": f"invalid_models_json: {json_error}",
                        }

                    data = payload.get("data", []) if isinstance(payload, dict) else []
                    models: List[Dict[str, Any]] = []
                    for item in data:
                        if isinstance(item, dict):
                            model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
                            if model_id:
                                models.append(item)
                        else:
                            model_id = str(item or "").strip()
                            if model_id:
                                models.append({"id": model_id})
                    return {"alive": True, "models": models, "scan_success": True, "error": ""}
        except Exception as e:
            self.logger.warning(f"Health ping failed for OpenAI key {f'...{api_key[-4:]}'}: {e}")
            return {"alive": False, "models": [], "scan_success": False, "error": str(e)}

    async def scan_openai_models(self, api_key: str, endpoint: str) -> Dict[str, Any]:
        return await self._fetch_openai_models(api_key, endpoint)

    async def _ping_openai_key(self, api_key: str, endpoint: str) -> bool:
        result = await self._fetch_openai_models(api_key, endpoint)
        return bool(result.get("alive"))

    async def _ping_openai_model(self, api_key: str, endpoint: str, model_id: str) -> Dict[str, Any]:
        if not model_id:
            return {"alive": False, "error": "missing_model"}
        try:
            normalized_endpoint = normalize_custom_endpoint(endpoint)
        except ValueError as endpoint_error:
            return {"alive": False, "error": str(endpoint_error)}

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, base_url=normalized_endpoint)
            await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": "ping"}],
                temperature=0.0,
                max_tokens=4,
            )
            return {"alive": True, "error": ""}
        except Exception as e:
            return {"alive": False, "error": str(e)}

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
        """Run a single check cycle over API keys and return a structured report."""
        changes_detected: List[str] = []
        key_checks: List[Dict[str, Any]] = []
        model_ping_reports: List[Dict[str, Any]] = []
        alive_key_count = 0
        dead_key_count = 0
        model_payload_by_id: Dict[str, Dict[str, Any]] = {}
        seen_model_ids = set()
        model_scan_success = False
        last_scan_error = ""
        active_key_id = None
        endpoint_preset = "manual"
        selected_model_ids = [str(m).strip() for m in (selected_model_ids or []) if str(m).strip()]
        selected_model_ids = list(dict.fromkeys(selected_model_ids))

        report: Dict[str, Any] = {
            "changes": changes_detected,
            "key_checks": key_checks,
            "model_scan": {},
            "model_ping": model_ping_reports,
        }

        try:
            provider_config = await self.db_repo.get_custom_provider_config(provider="openai")
        except Exception as e:
            self.logger.warning(f"[HealthChecker] Không đọc được custom provider config từ DB: {e}")
            provider_config = None

        if provider_config is not None:
            endpoint = str(provider_config.get("normalized_base_url") or "").strip()
            active_key_id = provider_config.get("active_key_id")
            endpoint_preset = str(provider_config.get("endpoint_preset") or "manual").strip().lower()
            if not provider_config.get("is_enabled"):
                report["model_scan"] = {"error": "custom_provider_disabled"}
                return report
            if not endpoint or active_key_id is None:
                last_scan_error = "custom_provider_config_incomplete"
                await self.db_repo.update_custom_provider_scan_status("openai", False, last_scan_error)
                report["model_scan"] = {"error": last_scan_error}
                return report
        else:
            try:
                endpoint = normalize_custom_endpoint(getattr(self.config, 'OPENAI_CUSTOM_ENDPOINT', '').strip())
            except ValueError as endpoint_error:
                self.logger.warning(
                    f"[HealthChecker] Custom API Endpoint rỗng hoặc không hợp lệ ({endpoint_error}). "
                    f"Tạm dừng chu kỳ ping các Custom API key để tránh phát ra cảnh báo giả."
                )
                report["model_scan"] = {"error": "invalid_custom_endpoint"}
                return report

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
            report["model_scan"] = {"error": "no_keys"}
            return report

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
            if not full_key_scan and active_key_id is not None and entry.get("key_id") != active_key_id:
                continue

            key_name = f'...{api_key[-4:]}'

            # Ping tương ứng theo loại provider (ở đây chắc chắn là openai do đã lọc ở trên)
            fetch_result = await self._fetch_openai_models(api_key, endpoint)
            fetch_error = str(fetch_result.get("error") or "")[:500]
            if fetch_error:
                last_scan_error = fetch_error
            is_alive = bool(fetch_result.get("alive"))
            if is_alive:
                alive_key_count += 1
                if fetch_result.get("scan_success"):
                    model_scan_success = True
                    for model in fetch_result.get("models", []):
                        model_id = str(model.get("id") or model.get("model") or model.get("name") or "").strip()
                        if model_id:
                            seen_model_ids.add(model_id)
                            if model_id not in model_payload_by_id:
                                model_payload_by_id[model_id] = model
            else:
                dead_key_count += 1

            key_checks.append({
                "key": key_name,
                "provider": provider,
                "alive": is_alive,
                "error": fetch_error if not is_alive else "",
            })

            if ping_selected_models and is_alive:
                ping_models: List[str] = []
                if selected_model_ids:
                    ping_models = selected_model_ids if not full_key_scan else selected_model_ids[:1]
                if not ping_models and fetch_result.get("models"):
                    first_model = fetch_result.get("models", [])[0]
                    first_model_id = str(first_model.get("id") or first_model.get("model") or first_model.get("name") or "").strip()
                    if first_model_id:
                        ping_models = [first_model_id]

                if endpoint_preset in {"lm_studio", "ollama"} and not selected_model_ids:
                    ping_models = []

                for model_id in ping_models:
                    ping_result = await self._ping_openai_model(api_key, endpoint, model_id)
                    model_ping_reports.append({
                        "key": key_name,
                        "model_id": model_id,
                        "alive": bool(ping_result.get("alive")),
                        "error": str(ping_result.get("error") or "")[:500],
                    })

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

        scanned_model_payloads = list(model_payload_by_id.values())

        if active_key_id is not None and not model_scan_success and alive_key_count == 0 and dead_key_count == 0:
            last_scan_error = "active_custom_key_not_found_or_inactive"
            await self.db_repo.update_custom_provider_scan_status("openai", False, last_scan_error)
            changes_detected.append("[MODEL SCAN] Không tìm thấy custom API key active đã lưu trong provider config.")
            report["model_scan"] = {
                "success": False,
                "error": last_scan_error,
                "alive_keys": alive_key_count,
                "dead_keys": dead_key_count,
                "models_alive": len(seen_model_ids),
            }

        if model_scan_success:
            checked_at = datetime.now(timezone.utc)
            try:
                upsert_result = await self.db_repo.upsert_custom_api_models(
                    provider="openai",
                    models=scanned_model_payloads,
                    checked_at=checked_at,
                )
                dead_models = await self.db_repo.mark_missing_custom_api_models_dead(
                    provider="openai",
                    seen_model_ids=sorted(seen_model_ids),
                    checked_at=checked_at,
                )
                await self.db_repo.update_custom_provider_scan_status("openai", True, "")
                await self.router.refresh_custom_models_from_db(force=True)
                await self.router.refresh_custom_provider_config(force=True)
                changes_detected.append(
                    "[MODEL SCAN] "
                    f"Custom API keys sống/chết: {alive_key_count}/{dead_key_count}; "
                    f"models alive: {len(seen_model_ids)}; "
                    f"upserted: {upsert_result.get('upserted', 0)}; "
                    f"vừa mark dead: {len(dead_models)}"
                )
                report["model_scan"] = {
                    "success": True,
                    "alive_keys": alive_key_count,
                    "dead_keys": dead_key_count,
                    "models_alive": len(seen_model_ids),
                    "upserted": upsert_result.get("upserted", 0),
                    "marked_dead": len(dead_models),
                }
            except Exception as e:
                self.logger.error(f"Error saving custom API model scan: {e}")
                await self.db_repo.update_custom_provider_scan_status("openai", False, str(e))
                changes_detected.append(f"[MODEL SCAN ERROR] Không lưu được danh sách model: {e}")
                report["model_scan"] = {
                    "success": False,
                    "error": str(e),
                    "alive_keys": alive_key_count,
                    "dead_keys": dead_key_count,
                    "models_alive": len(seen_model_ids),
                }
        elif alive_key_count or dead_key_count:
            await self.db_repo.update_custom_provider_scan_status("openai", False, last_scan_error or "invalid_models_response")
            changes_detected.append(
                "[MODEL SCAN] "
                f"Custom API keys sống/chết: {alive_key_count}/{dead_key_count}; "
                "không có response /v1/models hợp lệ để cập nhật DB."
            )
            report["model_scan"] = {
                "success": False,
                "error": last_scan_error or "invalid_models_response",
                "alive_keys": alive_key_count,
                "dead_keys": dead_key_count,
                "models_alive": len(seen_model_ids),
            }

        return report

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

# Global instance pattern similar to APIRouter
_health_checker_instance = None

def get_health_checker() -> HealthCheckerService:
    global _health_checker_instance
    if _health_checker_instance is None:
        _health_checker_instance = HealthCheckerService()
    return _health_checker_instance
