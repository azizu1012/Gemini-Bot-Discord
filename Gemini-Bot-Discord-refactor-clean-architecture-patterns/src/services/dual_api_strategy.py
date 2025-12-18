"""Dual API Strategy Service - Optimize API calls to max 2 calls"""

from typing import Optional, Dict, Any, Tuple
import re
import asyncio
from src.core.logger import logger
from src.services.thinking_cache import get_thinking_cache

# ============ SEARCH_TOPICS MAPPING (Learned from best practices) ============
# Organized by category + keywords (EN + VI) + suffixes for smarter queries
SEARCH_TOPICS = {
    "gaming": {
        "keywords": ['game', 'patch', 'banner', 'update', 'release', 'roadmap', 'leak', 'gacha', 'tier list', 'build',
                     'nhân vật', 'honkai', 'hsr', 'star rail', 'genshin', 'zzz', 'zenless', 'wuwa', 'wuthering waves', 
                     'ww', 'arknights', 'fgo', 'ff', 'final fantasy', 'elden', 'elden ring', 'phiên bản', 'sự kiện'],
        "suffixes": ["update", "release date", "patch notes", "roadmap", "leaks", "official", "tin tức"]
    },
    "tech": {
        "keywords": ['tech', 'công nghệ', 'ios', 'android', 'app', 'software', 'hardware', 'gpu', 'cpu', 'laptop', 'phone'],
        "suffixes": ["review", "release date", "news", "vs", "benchmark", "specs", "đánh giá", "tin tức"]
    },
    "anime_manga": {
        "keywords": ['anime', 'manga', 'light novel', 'manhwa', 'manhua', 'chapter', 'episode', 'season', 'ova', 'phần mới', 'tập mới'],
        "suffixes": ["release date", "new season", "chapter review", "spoiler", "tin tức anime"]
    },
    "news_politics": {
        "keywords": ['tổng thống', 'president', 'bầu cử', 'election', 'chính trị', 'politics', 'tin tức', 'news',
                     'chính phủ', 'government', 'quốc hội', 'parliament', 'luật', 'law', 'dự luật'],
        "suffixes": ["news", "latest", "today", "2025", "update", "tin tức mới nhất"]
    },
}

class DualAPIStrategy:
    """Manage 2-call strategy: Gemini + Search API"""
    
    def __init__(self):
        self.thinking_cache = None
    
    async def initialize(self):
        """Initialize cache"""
        self.thinking_cache = await get_thinking_cache()
    
    async def analyze_thinking_for_next_action(self, thinking_content: str) -> Tuple[str, Optional[str]]:
        """Phân tích THINKING block để xác định hành động tiếp theo
        
        Args:
            thinking_content: Nội dung khối THINKING
            
        Returns:
            (status, search_query)
            - status: "READY" (sẵn sàng trả lời), "NEED_SEARCH" (cần tìm kiếm)
            - search_query: Query để search (nếu NEED_SEARCH)
        """
        thinking_lower = thinking_content.lower()
        
        # Pattern tìm dấu hiệu cần search - VỚI NEW PATTERNS cho abbreviations + update info
        search_patterns = [
            # Original patterns
            r'(?:cần|need)\s+(?:tìm|search|kiếm)(?:\s+kiếm)?',
            r'(?:phải|bắt buộc|must)\s+(?:search|web_search)',
            r'(?:kết quả|information)\s+(?:cần|mới|mới nhất)',
            r'(?:không|no)\s+(?:thông tin|information|data)',
            r'(?:tìm|search).*(?:web|internet|google)',
            r'\[NEXT\].*(?:search|web)',
            r'(?:status|trạng thái).*SEARCHING',
            
            # NEW: Detect abbreviations that need expansion + search
            r'(?:ww|wuthering|ff|final|hn|honkai|gl|cs|ow|lol|dota)',
            
            # NEW: Detect version/update/new info requests
            r'(?:bản|version|update|3\.\d|release|patch|new|latest|mới)',
            r'(?:có gì|thế nào|như thế nào|chi tiết|info|information)',
        ]
        
        needs_search = any(re.search(pattern, thinking_lower) for pattern in search_patterns)
        
        if needs_search:
            # Trích xuất search query từ THINKING
            search_query = self._extract_search_query(thinking_content)
            return "NEED_SEARCH", search_query
        
        return "READY", None
    
    def _extract_search_query(self, thinking_content: str) -> Optional[str]:
        """Trích xuất search query từ THINKING content
        
        Tìm các pattern như:
        - "Search for: ..."
        - "Query: ..."
        - "[SEARCH]..."
        - "Tìm: ..."
        """
        patterns = [
            r'(?:Search for|Query|Tìm|web_search)\s*:\s*"?([^"\n]+)"?',
            r'\[(?:SEARCH|WEB_SEARCH)\]\s*([^\n]+)',
            r'search.*?(?:for|query|về|thế)?\s+([^\n]+?)(?:\.|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, thinking_content, re.IGNORECASE)
            if match:
                query = match.group(1).strip()
                if query and len(query) > 5:  # Tránh query quá ngắn
                    return query
        
        return None
    
    def _build_search_only_message(self, thinking_content: str, search_results: str) -> str:
        """Xây dựng message để gửi lần thứ 2 (chỉ có search results, không THINKING)
        
        Mục đích: Model chỉ cần format lại kết quả, không phải suy nghĩ lại
        """
        message = f"""Based on search results, provide a direct answer:

SEARCH RESULTS:
{search_results}

USER CONTEXT FROM THINKING:
{thinking_content[:500]}

TASK: Format the search results into a natural, friendly response in Vietnamese. Keep it concise and helpful."""
        
        return message
    
    async def call_search_api(self, query: str, api_type: str = "tavily") -> str:
        """Gọi Search API (không phải Gemini)
        
        Args:
            query: Search query
            api_type: "tavily" hoặc "google" (mở rộng sau)
            
        Returns:
            Search results as string
        """
        if api_type == "tavily":
            return await self._call_tavily(query)
        else:
            logger.warning(f"Unknown API type: {api_type}")
            return ""
    
    async def _call_tavily(self, query: str) -> str:
        """Gọi Tavily Search API
        
        Tavily là search engine được cấu hình cho Gemini tools
        Tuy nhiên nếu muốn dùng API riêng:
        - Lấy từ environment variable TAVILY_API_KEY
        - Gọi API endpoint
        """
        # TODO: Implement khi có TAVILY_API_KEY
        # Hiện tại chỉ là placeholder - có thể dùng các search tool khác
        try:
            import aiohttp
            from src.core.config import config
            
            # Check if we have Tavily key
            tavily_key = getattr(config, 'TAVILY_API_KEY', None)
            if not tavily_key:
                logger.warning("TAVILY_API_KEY not configured")
                return f"[Search results unavailable - please configure TAVILY_API_KEY]"
            
            async with aiohttp.ClientSession() as session:
                url = "https://api.tavily.com/search"
                payload = {
                    "api_key": tavily_key,
                    "query": query,
                    "max_results": 5,
                    "include_answer": True
                }
                
                async with session.post(url, json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # Format results
                        results_text = data.get("answer", "")
                        if not results_text:
                            results_text = "\n".join([
                                f"- {r['title']}: {r['content'][:200]}"
                                for r in data.get("results", [])[:5]
                            ])
                        return results_text
                    else:
                        logger.error(f"Tavily API error: {resp.status}")
                        return ""
        except Exception as e:
            logger.error(f"Tavily search failed: {e}")
            return ""
    
    def _should_use_cache(self, query: str, previous_cache_key: str) -> bool:
        """Kiểm tra xem có nên dùng cache THINKING không
        
        Dùng cache nếu:
        - Query tương tự (hash giống)
        - Cache chưa hết hạn
        """
        # TODO: Implement fuzzy matching cho queries
        return False  # Để mở rộng sau
    
    async def check_search_needed_from_query(self, user_query: str) -> Tuple[bool, Optional[str]]:
        """PRE-CHECK: Kiểm tra từ user query xem có cần search ngay lập tức không
        
        Không cần đợi THINKING block, kiểm tra trực tiếp query của user.
        
        Learning from old codebase:
        - Check SEARCH_TOPICS keywords for category matching
        - Look for version/update/new info keywords
        - Expand abbreviations when detected
        
        Args:
            user_query: Query từ user (ví dụ: "tìm bản 3.0 ww có gì")
            
        Returns:
            (needs_search, search_query)
            - needs_search: True nếu cần search ngay lập tức
            - search_query: Query để search (hoặc None)
        """
        query_lower = user_query.lower()
        
        # 1. Check if query matches any SEARCH_TOPICS category keywords
        for category, topic_data in SEARCH_TOPICS.items():
            if any(keyword in query_lower for keyword in topic_data["keywords"]):
                # Found relevant category - check if need search
                break
        else:
            category = None
        
        # 2. Keywords that definitively trigger search
        search_trigger_patterns = [
            # Version/Update/New info
            r'(?:bản|version|update|release|patch|3\.\d|latest|mới)',
            r'(?:có gì|thế nào|như thế nào|chi tiết)',
            
            # Search keywords
            r'(?:tìm|search|kiếm).*(?:cho|for)?',
            r'(?:thông tin|information|info).*(?:về|about)',
            
            # Game-specific (from SEARCH_TOPICS)
            r'(?:roadmap|leak|speculation|official)',
            
            # News/Politics keywords (NEW - fixes "tổng thống mỹ" issue)
            r'(?:tổng thống|president|bầu cử|election|chính trị|politics)',
            r'(?:quốc hội|parliament|chính phủ|government)',
            
            # Abbreviations from SEARCH_TOPICS
            r'(?:ww|wuwa|ff|hn|hsr|gl|cs|ow|lol|d2|dota|elden|bg3|fgo|zzz)',
        ]
        
        # Check if any pattern matches
        found_search_trigger = False
        for pattern in search_trigger_patterns:
            if re.search(pattern, query_lower):
                found_search_trigger = True
                break
        
        if not found_search_trigger:
            return False, None
        
        # Extract clean search query
        search_query = self._clean_and_expand_query(user_query)
        
        if search_query and len(search_query) > 3:
            logger.info(f"🔍 PRE-CHECK: User query cần search: '{user_query}' → Search: '{search_query}'")
            return True, search_query
        
        return False, None
    
    def _clean_and_expand_query(self, user_query: str) -> str:
        """Làm sạch và mở rộng abbreviations trong query
        
        VD: "tìm bản 3.0 ww" → "tìm bản 3.0 Wuthering Waves release notes"
        
        Learning from old codebase:
        - Match against SEARCH_TOPICS keywords for category detection
        - Add appropriate suffixes based on category
        - Expand abbreviations intelligently
        """
        abbreviations = {
            r'\bww\b': 'Wuthering Waves',
            r'\bwuwa\b': 'Wuthering Waves',
            r'\bff\b': 'Final Fantasy',
            r'\bhn\b': 'Honkai Star Rail',
            r'\bhsr\b': 'Honkai Star Rail',
            r'\bgl\b': 'Genshin Legends',
            r'\bcs\b': 'Counter-Strike',
            r'\bow\b': 'Overwatch',
            r'\blol\b': 'League of Legends',
            r'\bd2\b|dota': 'Dota 2',
            r'\belden\b': 'Elden Ring',
            r'\bbg3\b': 'Baldur\'s Gate 3',
            r'\bfgo\b': 'Fate Grand Order',
            r'\bzzz\b': 'Zenless Zone Zero',
            # REMOVED: r'\bai\b' - Too generic, causes false expansion (Vietnamese "ai" = who)
        }
        
        expanded_query = user_query
        
        # 1. Expand abbreviations
        for abbr, full in abbreviations.items():
            expanded_query = re.sub(abbr, full, expanded_query, flags=re.IGNORECASE)
        
        # 2. Detect category from SEARCH_TOPICS keywords
        detected_category = None
        query_lower = expanded_query.lower()
        
        for category, topic_data in SEARCH_TOPICS.items():
            if any(keyword in query_lower for keyword in topic_data["keywords"]):
                detected_category = category
                break
        
        # 3. Add appropriate suffix based on category/keywords
        if not re.search(r'release\s+notes|patch|update|news|đánh giá|tin tức', expanded_query, re.IGNORECASE):
            if re.search(r'bản|version|update|3\.\d', expanded_query, re.IGNORECASE):
                # Version/update search → add "release notes"
                if detected_category == "gaming":
                    expanded_query += ' release notes patch'
                elif detected_category == "tech":
                    expanded_query += ' release date specs'
                elif detected_category == "anime_manga":
                    expanded_query += ' new episode release'
                else:
                    expanded_query += ' release notes'
            
            elif re.search(r'có gì|thế nào|như thế nào|chi tiết', expanded_query, re.IGNORECASE):
                # Details search → add category-specific suffix
                if detected_category == "gaming":
                    expanded_query += ' patch notes'
                elif detected_category == "anime_manga":
                    expanded_query += ' episode summary'
                else:
                    expanded_query += ' info'
        
        return expanded_query

# Global instance
_strategy_instance: Optional[DualAPIStrategy] = None

async def get_dual_api_strategy() -> DualAPIStrategy:
    """Lấy singleton instance"""
    global _strategy_instance
    if _strategy_instance is None:
        _strategy_instance = DualAPIStrategy()
        await _strategy_instance.initialize()
    return _strategy_instance
