"""Thinking Cache Service - Cache THINKING blocks to optimize API calls"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
import asyncio

class ThinkingCache:
    def __init__(self, cache_dir: str = "data/thinking_cache"):
        self.cache_dir = cache_dir
        self.in_memory_cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = timedelta(hours=1)
        os.makedirs(cache_dir, exist_ok=True)
        
    async def save_thinking(self, user_id: str, thinking_content: str, query: str) -> str:
        """Save THINKING block to cache"""
        cache_key = f"{user_id}_{hash(query) % 100000}"
        cache_entry = {
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "query": query,
            "thinking": thinking_content,
            "status": self._extract_status(thinking_content),
            "ttl": (datetime.now() + self.cache_ttl).isoformat()
        }
        
        # Lưu vào memory
        self.in_memory_cache[cache_key] = cache_entry
        
        # Lưu vào file
        await self._save_to_file(cache_key, cache_entry)
        
        return cache_key
    
    async def get_thinking(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Lấy THINKING block từ cache"""
        # Check memory trước
        if cache_key in self.in_memory_cache:
            entry = self.in_memory_cache[cache_key]
            if self._is_valid(entry):
                return entry
            else:
                del self.in_memory_cache[cache_key]
                return None
        
        # Check file
        entry = await self._load_from_file(cache_key)
        if entry and self._is_valid(entry):
            self.in_memory_cache[cache_key] = entry
            return entry
        
        return None
    
    def _extract_status(self, thinking_content: str) -> str:
        """Trích xuất trạng thái từ THINKING block
        
        Returns: "SEARCHING" nếu cần tìm kiếm, "READY" nếu sẵn sàng trả lời, "UNKNOWN" nếu không chắc
        """
        thinking_lower = thinking_content.lower()
        
        # Check markers
        if any(marker in thinking_lower for marker in ["cần tìm kiếm", "need to search", "cần search", "web search", "tool_search"]):
            return "SEARCHING"
        
        if any(marker in thinking_lower for marker in ["có đủ thông tin", "ready to answer", "sẵn sàng", "đủ thông tin"]):
            return "READY"
        
        return "UNKNOWN"
    
    def _is_valid(self, entry: Dict[str, Any]) -> bool:
        """Kiểm tra entry còn hợp lệ hay không (chưa hết TTL)"""
        try:
            ttl = datetime.fromisoformat(entry["ttl"])
            return datetime.now() < ttl
        except:
            return False
    
    async def _save_to_file(self, cache_key: str, entry: Dict[str, Any]):
        """Lưu entry vào file"""
        file_path = os.path.join(self.cache_dir, f"{cache_key}.json")
        try:
            await asyncio.to_thread(
                lambda: json.dump(entry, open(file_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
            )
        except Exception as e:
            print(f"Lỗi lưu cache: {e}")
    
    async def _load_from_file(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Tải entry từ file"""
        file_path = os.path.join(self.cache_dir, f"{cache_key}.json")
        try:
            if os.path.exists(file_path):
                return await asyncio.to_thread(
                    lambda: json.load(open(file_path, 'r', encoding='utf-8'))
                )
        except Exception as e:
            print(f"Lỗi tải cache: {e}")
        return None
    
    async def cleanup_expired(self):
        """Dọn dẹp cache hết hạn"""
        expired_keys = []
        for key, entry in self.in_memory_cache.items():
            if not self._is_valid(entry):
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.in_memory_cache[key]
            try:
                os.remove(os.path.join(self.cache_dir, f"{key}.json"))
            except:
                pass

# Global instance
_cache_instance: Optional[ThinkingCache] = None

async def get_thinking_cache() -> ThinkingCache:
    """Lấy singleton instance của ThinkingCache"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = ThinkingCache()
    return _cache_instance
