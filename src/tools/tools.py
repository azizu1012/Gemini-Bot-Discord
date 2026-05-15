import asyncio
import json
import re
import os
import mimetypes
import time
from datetime import datetime, timedelta
import aiofiles
import requests
import sympy as sp
from google import genai
from google.genai import types as genai_types
import serpapi
from tavily import TavilyClient
import exa_py
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

from src.core.config import (
    logger,
    WEATHER_API_KEY,
    CITY,
    WEATHER_CACHE_PATH,
    SERPAPI_API_KEY,
    TAVILY_API_KEY,
    EXA_API_KEY,
    GEMINI_API_KEYS,
    MODEL_NAME,
)

class ToolsManager:
    """Manager for all AI tools and external API integrations."""
    
    # Cache configuration
    CACHE_TTL_SECONDS = 3600
    MAX_CACHE_SIZE = 1000
    
    # File size limits
    MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024
    MAX_TEXT_LENGTH = 10000
    
    # Google Drive
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
    SERVICE_ACCOUNT_FILE = 'credentials.json'
    
    # Search Topics
    SEARCH_TOPICS = {
        "gaming": {
            "keywords": ['game', 'patch', 'banner', 'update', 'release date', 'roadmap', 'leak', 'speculation', 'gacha', 'reroll', 'tier list', 'build', 'nhân vật', 'honkai', 'hsr', 'star rail', 'genshin', 'zzz', 'zenless', 'wuwa', 'wuthering waves', 'arknights', 'fgo', 'phiên bản', 'sự kiện'],
            "suffixes": ["update", "release date", "patch notes", "roadmap", "leaks", "speculation", "official", "tin tức"]
        },
        "tech": {
            "keywords": ['tech', 'công nghệ', 'ai', 'ios', 'android', 'app', 'software', 'hardware', 'card màn hình', 'cpu', 'laptop', 'phone'],
            "suffixes": ["review", "release date", "news", "vs", "benchmark", "specs", "đánh giá", "tin tức"]
        },
        "science": {
            "keywords": ['science', 'khoa học', 'space', 'vũ trụ', 'nasa', 'discovery', 'research', 'nghiên cứu', 'y tế'],
            "suffixes": ["new discovery", "latest research", "breakthrough", "study finds", "công bố", "nghiên cứu mới"]
        },
        "finance": {
            "keywords": ['finance', 'tài chính', 'stock', 'cổ phiếu', 'market', 'thị trường', 'investment', 'đầu tư', 'economy', 'kinh tế', 'lãi suất', 'ngân hàng'],
            "suffixes": ["stock price", "market analysis", "forecast", "news", "earnings report", "phân tích", "dự báo"]
        },
        "movies_tv": {
            "keywords": ['movie', 'phim', 'tv show', 'series', 'netflix', 'disney+', 'trailer', 'actor', 'diễn viên', 'đạo diễn', 'lịch chiếu'],
            "suffixes": ["review", "release date", "trailer", "cast", "ending explained", "season 2", "lịch chiếu phim", "đánh giá"]
        },
        "anime_manga": {
            "keywords": ['anime', 'manga', 'light novel', 'manhwa', 'manhua', 'chapter', 'episode', 'season', 'ova', 'phần mới', 'tập mới'],
            "suffixes": ["release date", "new season", "chapter review", "discussion", "spoiler", "tin tức anime"]
        },
        "sports": {
            "keywords": ['sports', 'thể thao', 'bóng đá', 'football', 'basketball', 'tennis', 'cầu lông', 'f1', 'đội tuyển', 'cầu thủ', 'trận đấu'],
            "suffixes": ["match result", "highlights", "live score", "news", "transfer", "lịch thi đấu", "kết quả"]
        },
        "music": {
            "keywords": ['music', 'âm nhạc', 'bài hát', 'ca sĩ', 'album', 'mv', 'concert', 'lyrics', 'lời bài hát', 'spotify', 'apple music'],
            "suffixes": ["new song", "album review", "music video", "tour dates", "lyrics meaning", "bài hát mới"]
        },
        "celebrity_gossip": {
            "keywords": ['celebrity', 'người nổi tiếng', 'showbiz', 'tin đồn', 'scandal', 'drama', 'diễn viên', 'ca sĩ'],
            "suffixes": ["scandal", "news", "gossip", "drama", "phốt", "tin đồn"]
        },
        "books_literature": {
            "keywords": ['book', 'sách', 'tiểu thuyết', 'tác giả', 'văn học', 'truyện', 'poetry', 'author', 'novel', 'đọc sách'],
            "suffixes": ["review", "summary", "recommendations", "new releases", "đánh giá sách", "tóm tắt"]
        },
        "photography_video": {
            "keywords": ['photography', 'nhiếp ảnh', 'quay phim', 'máy ảnh', 'camera', 'lens', 'drone', 'chụp ảnh', 'edit video'],
            "suffixes": ["tutorial", "gear review", "best settings", "tips and tricks", "hướng dẫn", "đánh giá thiết bị"]
        },
        "diy_crafts": {
            "keywords": ['diy', 'tự làm', 'thủ công', 'handmade', 'craft', 'tutorial', 'hướng dẫn', 'đồ handmade'],
            "suffixes": ["how to", "tutorial", "ideas", "project", "hướng dẫn làm", "ý tưởng"]
        },
        "social_media_trends": {
            "keywords": ['social media', 'mạng xã hội', 'tiktok', 'instagram', 'facebook', 'twitter', 'viral', 'meme', 'trend', 'xu hướng'],
            "suffixes": ["new trend", "viral video", "meme explained", "challenge", "xu hướng mới", "trào lưu"]
        },
        "food_cooking": {
            "keywords": ['food', 'cooking', 'recipe', 'công thức', 'nấu ăn', 'nhà hàng', 'quán ăn', 'ẩm thực', 'món ngon'],
            "suffixes": ["recipe", "how to make", "best restaurants", "review", "cách làm", "địa chỉ"]
        },
        "travel": {
            "keywords": ['travel', 'du lịch', 'phượt', 'khách sạn', 'resort', 'vé máy bay', 'địa điểm', 'kinh nghiệm'],
            "suffixes": ["travel guide", "things to do", "best places to visit", "flight deals", "kinh nghiệm du lịch", "giá vé"]
        },
        "health_wellness": {
            "keywords": ['health', 'wellness', 'sức khỏe', 'fitness', 'gym', 'yoga', 'meditation', 'dinh dưỡng', 'bệnh'],
            "suffixes": ["benefits", "how to", "symptoms", "treatment", "healthy diet", "lợi ích", "cách tập"]
        },
        "mental_health": {
            "keywords": ['mental health', 'sức khỏe tinh thần', 'tâm lý', 'stress', 'anxiety', 'therapy', 'trị liệu', 'tâm sự'],
            "suffixes": ["how to cope", "symptoms of", "self-care tips", "therapy options", "cách đối phó", "lời khuyên"]
        },
        "fashion_beauty": {
            "keywords": ['fashion', 'thời trang', 'làm đẹp', 'beauty', 'mỹ phẩm', 'quần áo', 'brand', 'style', 'makeup', 'phối đồ'],
            "suffixes": ["trends", "style guide", "product review", "tutorial", "xu hướng", "cách phối đồ"]
        },
        "home_garden": {
            "keywords": ['home', 'garden', 'nhà cửa', 'sân vườn', 'trang trí', 'nội thất', 'diy', 'gardening', 'cây cảnh'],
            "suffixes": ["decor ideas", "gardening tips", "diy project", "organization hacks", "ý tưởng trang trí", "mẹo làm vườn"]
        },
        "pets_animals": {
            "keywords": ['pet', 'animal', 'thú cưng', 'chó', 'mèo', 'dog', 'cat', 'động vật', 'chăm sóc thú cưng'],
            "suffixes": ["care tips", "breeds", "funny videos", "health problems", "cách chăm sóc", "giống loài"]
        },
        "education": {
            "keywords": ['education', 'giáo dục', 'học tập', 'school', 'university', 'trường học', 'đại học', 'khóa học', 'online course'],
            "suffixes": ["best courses", "how to learn", "study tips", "admission requirements", "khóa học tốt nhất", "mẹo học tập"]
        },
        "career_development": {
            "keywords": ['career', 'sự nghiệp', 'phát triển bản thân', 'job search', 'tìm việc', 'resume', 'cv', 'interview', 'phỏng vấn'],
            "suffixes": ["job search tips", "resume template", "interview questions", "career path", "mẹo tìm việc", "câu hỏi phỏng vấn"]
        },
        "business_entrepreneurship": {
            "keywords": ['business', 'kinh doanh', 'khởi nghiệp', 'startup', 'marketing', 'sales', 'doanh nghiệp'],
            "suffixes": ["business ideas", "how to start", "marketing strategy", "case study", "ý tưởng kinh doanh", "chiến lược marketing"]
        },
        "automotive": {
            "keywords": ['automotive', 'xe hơi', 'ô tô', 'xe máy', 'car', 'motorcycle', 'vehicle', 'xe điện', 'vinfast'],
            "suffixes": ["review", "specs", "price", "release date", "vs", "đánh giá xe", "giá bán"]
        },
        "law_politics": {
            "keywords": ['law', 'politics', 'luật', 'chính trị', 'chính phủ', 'government', 'policy', 'election', 'bầu cử', 'quy định'],
            "suffixes": ["new law", "policy explained", "election results", "legal advice", "luật mới", "giải thích chính sách"]
        },
        "real_estate": {
            "keywords": ['real estate', 'bất động sản', 'nhà đất', 'housing market', 'apartment', 'căn hộ', 'lịch sử giá nhà'],
            "suffixes": ["market trends", "how to buy", "investment tips", "apartment tour", "xu hướng thị trường", "kinh nghiệm mua nhà"]
        },
        "cryptocurrency_blockchain": {
            "keywords": ['crypto', 'bitcoin', 'ethereum', 'blockchain', 'nft', 'defi', 'web3', 'tiền ảo', 'tiền điện tử'],
            "suffixes": ["price prediction", "news", "how to buy", "wallet", "dự đoán giá", "tin tức crypto"]
        },
        "local_events": {
            "keywords": ['event', 'sự kiện', 'lễ hội', 'concert', 'workshop', 'hội thảo', 'gần đây', 'quanh đây'],
            "suffixes": ["events near me", "tickets", "schedule", "local festivals", "sự kiện sắp tới", "lịch trình"]
        },
        "shopping_deals": {
            "keywords": ['shopping', 'mua sắm', 'deal', 'giảm giá', 'khuyến mãi', 'sale', 'discount', 'black friday', 'shopee', 'lazada'],
            "suffixes": ["best deals", "discount codes", "sale on", "product review", "mã giảm giá", "đánh giá sản phẩm"]
        },
        "history": {
            "keywords": ['history', 'lịch sử', 'chiến tranh', 'ancient', 'medieval', 'modern history', 'lịch sử việt nam'],
            "suffixes": ["history of", "explained", "documentary", "key events", "lịch sử về", "giải thích"]
        },
        "environment_sustainability": {
            "keywords": ['environment', 'môi trường', 'biến đổi khí hậu', 'climate change', 'sustainability', 'năng lượng tái tạo', 'ô nhiễm'],
            "suffixes": ["latest news", "solutions", "impact of", "how to help", "tin tức môi trường", "giải pháp"]
        },
        "general": {
            "keywords": [],
            "suffixes": ["news", "latest", "update", "information", "tin tức", "thông tin", "mới nhất"]
        }
    }
    
    # City mapping
    CITY_NAME_MAP = {
        "hồ chí minh": ("Ho Chi Minh City", "Thành phố Hồ Chí Minh"),
        "tp.hcm": ("Ho Chi Minh City", "Thành phố Hồ Chí Minh"),
        "sài gòn": ("Ho Chi Minh City", "Thành phố Hồ Chí Minh"),
        "ho chi minh city": ("Ho Chi Minh City", "Thành phố Hồ Chí Minh"),
        "hcmc": ("Ho Chi Minh City", "Thành phố Hồ Chí Minh"),
        "hà nội": ("Hanoi", "Hà Nội"),
        "ha noi": ("Hanoi", "Hà Nội"),
        "danang": ("Da Nang", "Đà Nẵng"),
        "đà nẵng": ("Da Nang", "Đà Nẵng"),
        "da nang": ("Da Nang", "Đà Nẵng"),
    }
    
    def __init__(self):
        self.logger = logger
        self.web_search_cache = {}
        self.image_recognition_cache = {}
        self.weather_lock = asyncio.Lock()
        self.search_lock = asyncio.Lock()
        self.cache_lock = asyncio.Lock()
        self.search_cache = {}
        self._gemini_key_cursor = 0
        self._invalid_tool_keys = set()
        self._tool_key_cooldowns = {}
        self.google_search_streams = self._load_google_search_streams()
        self.fallback_provider_limit = self._load_fallback_provider_limit()
        self.gemini_vision_model = os.getenv("GEMINI_VISION_MODEL", MODEL_NAME or "gemini-3-flash-preview")

        if GEMINI_API_KEYS:
            self.logger.info(
                f"Search/image tools ready: provider=duckduckgo streams={self.google_search_streams} "
                f"fallback_limit={self.fallback_provider_limit} vision_model={self.gemini_vision_model}"
            )
        else:
            self.logger.warning("Không có Gemini API key cho tools; web_search/image_recognition sẽ failback.")
    
    def get_all_tools(self):
        """Return all tool definitions for Gemini."""
        return [
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name="web_search",
                    description=(
                        "Tìm kiếm thông tin cập nhật, sự kiện mới, tin tức, "
                        "dữ liệu thực tế không có trong kiến thức của AI, "
                        "hoặc để xác minh thông tin. KHÔNG DÙNG cho các tác vụ tính toán, "
                        "dịch thuật, tóm tắt, viết lại, hoặc các câu hỏi không cần dữ liệu mới."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Câu truy vấn tìm kiếm cụ thể, không để trống."
                            }
                        },
                        "required": ["query"]
                    }
                )
            ]),
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name="get_weather",
                    description="Lấy thông tin thời tiết hiện tại cho một thành phố cụ thể.",
                    parameters={
                        "type": "object",
                        "properties": {"city": {"type": "string", "description": "Tên thành phố, ví dụ: 'Hanoi', 'Tokyo'."}},
                        "required": ["city"]
                    }
                )
            ]),
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name="calculate",
                    description="Giải các bài toán số học hoặc biểu thức phức tạp, bao gồm các hàm lượng giác, logarit, và đại số.",
                    parameters={
                        "type": "object",
                        "properties": {"equation": {"type": "string", "description": "Biểu thức toán học dưới dạng string, ví dụ: 'sin(pi/2) + 2*x'."}},
                        "required": ["equation"]
                    }
                )
            ]),
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name="save_note",
                    description=(
                        "Lưu một mẩu thông tin, sở thích, sự thật, hoặc nội dung quan trọng về người dùng để bạn có thể truy cập lại sau. "
                        "Dùng khi user chia sẻ thông tin cá nhân có giá trị lâu dài (ví dụ: 'tôi thích chơi game X', 'cấu hình máy của tôi là Y')."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "note_content": {"type": "string", "description": "Nội dung thông tin cần ghi nhớ."},
                            "source": {"type": "string", "description": "Ngữ cảnh hoặc nguồn của thông tin, ví dụ: 'chat_inference', 'user_request'."}
                        },
                        "required": ["note_content", "source"]
                    }
                )
            ]),
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name="retrieve_notes",
                    description=(
                        "Truy xuất thông tin đã lưu trữ về người dùng, kiến thức cá nhân, "
                        "dữ liệu lịch sử, hoặc các sự kiện/thông tin quan trọng mà AI đã được yêu cầu ghi nhớ. "
                        "PHẢI LUÔN GỌI HÀM NÀY nếu câu hỏi liên quan đến kiến thức cá nhân, note, hoặc thông tin đã được ghi nhớ trước đó."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Từ khóa hoặc chủ đề tìm kiếm trong bộ nhớ (ví dụ: 'config', 'sở thích'). Để trống nếu muốn lấy tất cả."}
                        },
                        "required": ["query"]
                    }
                )
            ]),
            genai_types.Tool(function_declarations=[
                genai_types.FunctionDeclaration(
                    name="image_recognition",
                    description=(
                        "Nhận diện đối tượng, người nổi tiếng, nhân vật game/anime, đếm vật thể, và trích xuất văn bản (OCR) từ một hình ảnh. "
                        "Sử dụng khi người dùng tải lên một hình ảnh và hỏi các câu hỏi liên quan đến nội dung của hình ảnh đó. "
                        "Ví dụ: 'có bao nhiêu quả táo trong ảnh?', 'người này là ai?', 'đây là nhân vật gì?', 'đọc chữ trong ảnh này'."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "image_url": {"type": "string", "description": "URL công khai của hình ảnh cần nhận diện."},
                            "question": {"type": "string", "description": "Câu hỏi cụ thể của người dùng về hình ảnh (ví dụ: 'đếm số lượng', 'người này là ai?', 'đây là gì?')."}
                        },
                        "required": ["image_url", "question"]
                    }
                )
            ]),
        ]
    
    def get_web_search_cache(self, query: str):
        """Get cached web search result."""
        if query in self.web_search_cache:
            cached_item = self.web_search_cache[query]
            if datetime.now() - cached_item['timestamp'] < timedelta(hours=6):
                return cached_item['data']
            else:
                del self.web_search_cache[query]
        return None
    
    def set_web_search_cache(self, query: str, data: str):
        """Set web search cache."""
        if len(self.web_search_cache) >= self.MAX_CACHE_SIZE:
            oldest_key = min(self.web_search_cache, key=lambda k: self.web_search_cache[k]['timestamp'])
            del self.web_search_cache[oldest_key]
        self.web_search_cache[query] = {'data': data, 'timestamp': datetime.now()}
    
    def get_image_recognition_cache(self, image_url: str, question: str):
        """Get cached image recognition result."""
        key = f"{image_url}|{question}"
        if key in self.image_recognition_cache:
            cached_item = self.image_recognition_cache[key]
            if datetime.now() - cached_item['timestamp'] < timedelta(hours=1):
                return cached_item['data']
            else:
                del self.image_recognition_cache[key]
        return None
    
    def set_image_recognition_cache(self, image_url: str, question: str, data: str):
        """Set image recognition cache."""
        key = f"{image_url}|{question}"
        if len(self.image_recognition_cache) >= self.MAX_CACHE_SIZE:
            oldest_key = min(self.image_recognition_cache, key=lambda k: self.image_recognition_cache[k]['timestamp'])
            del self.image_recognition_cache[oldest_key]
        self.image_recognition_cache[key] = {'data': data, 'timestamp': datetime.now()}
    
    def _load_google_search_streams(self) -> int:
        """Load desired primary search stream count (DuckDuckGo, 1..2)."""
        raw = os.getenv("GOOGLE_SEARCH_STREAMS", "2").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 2
        return max(1, min(2, value))

    def _load_fallback_provider_limit(self) -> int:
        """Load fallback provider parallelism limit (1..3)."""
        raw = os.getenv("SEARCH_FALLBACK_PROVIDER_LIMIT", "1").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 1
        return max(1, min(3, value))

    def _next_gemini_api_key(self) -> str:
        if not GEMINI_API_KEYS:
            return ""

        now = time.time()
        total = len(GEMINI_API_KEYS)
        for _ in range(total):
            key = GEMINI_API_KEYS[self._gemini_key_cursor % total]
            self._gemini_key_cursor += 1

            if key in self._invalid_tool_keys:
                continue

            release_ts = self._tool_key_cooldowns.get(key, 0)
            if release_ts > now:
                continue

            return key

        return ""

    async def _search_duckduckgo(self, query: str, index: int = 0) -> str:
        start_ts = datetime.now().timestamp()
        try:
            def _do_search():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=5))

            results = await asyncio.to_thread(_do_search)
            formatted = []
            for item in results[:5]:
                title = item.get("title") or "Không có tiêu đề"
                snippet = (item.get("body") or "").strip()
                if len(snippet) > 330:
                    snippet = snippet[:330] + "..."

                link = item.get("href") or item.get("url") or ""
                if not link:
                    continue
                if any(ad in link.lower() for ad in ['shopee', 'lazada', 'amazon', 'tiki']):
                    continue

                formatted.append(f"**{title}**: {snippet} (Nguồn: {link})")

            primary_text = "**DuckDuckGo (Primary):**\n" + "\n".join(formatted) if formatted else ""
            latency_ms = int((datetime.now().timestamp() - start_ts) * 1000)
            self.logger.info(
                f"AB_METRIC search_primary query_idx={index} success={1 if primary_text else 0} "
                f"latency_ms={latency_ms} provider=duckduckgo"
            )
            return primary_text
        except Exception as e:
            latency_ms = int((datetime.now().timestamp() - start_ts) * 1000)
            self.logger.warning(
                f"AB_METRIC search_primary query_idx={index} success=0 latency_ms={latency_ms} "
                f"provider=duckduckgo error={str(e)[:120]}"
            )
            return ""

    def _guess_mime_type(self, image_url: str) -> str:
        mime_type, _ = mimetypes.guess_type(image_url)
        if mime_type in {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}:
            return mime_type
        return "image/jpeg"

    def _count_unique_sources(self, text: str) -> int:
        return len(set(re.findall(r"\(Nguồn: (.*?)\)", text or "")))

    def _is_search_result_sufficient(self, primary_parts: list[str], min_sources: int = 2, min_chars: int = 180) -> bool:
        merged = "\n".join(part.strip() for part in primary_parts if part)
        if not merged:
            return False
        return self._count_unique_sources(merged) >= min_sources and len(merged) >= min_chars

    def _query_contains_suffix_intent(self, query: str, suffix: str) -> bool:
        query_lower = f" {query.lower()} "
        suffix_lower = suffix.strip().lower()
        if not suffix_lower:
            return True
        if f" {suffix_lower} " in query_lower:
            return True

        suffix_tokens = [tok for tok in re.split(r"\s+", suffix_lower) if tok]
        if suffix_tokens and all(f" {tok} " in query_lower for tok in suffix_tokens):
            return True

        return False

    def _build_secondary_query(self, q1: str, suffixes: list[str]) -> str:
        q1_clean = q1.strip()
        if not q1_clean:
            return q1_clean

        for suffix in suffixes:
            suffix_clean = (suffix or "").strip()
            if not suffix_clean:
                continue
            if self._query_contains_suffix_intent(q1_clean, suffix_clean):
                return q1_clean
            return f"{q1_clean} {suffix_clean}"

        return q1_clean

    def normalize_city_name(self, city_query: str):
        """Normalize city name to English and Vietnamese."""
        if not city_query:
            return ("Ho Chi Minh City", "Thành phố Hồ Chí Minh")
        city_key = city_query.strip().lower()
        for k, v in self.CITY_NAME_MAP.items():
            if k in city_key:
                return v
        return (city_query, city_query.title())
    
    async def get_weather(self, city_query: str = None):
        """Get weather information for a city."""
        async with self.weather_lock:
            if city_query is None:
                city_query = CITY or "Ho Chi Minh City"
            city_en, city_vi = self.normalize_city_name(city_query)
            
            cache_path = WEATHER_CACHE_PATH.replace(".json", f"_{city_en.replace(' ', '_').lower()}.json")
            
            if await asyncio.to_thread(os.path.exists, cache_path):
                try:
                    async with aiofiles.open(cache_path, 'r') as f:
                        cache = json.loads(await f.read())
                    cache_time = datetime.fromisoformat(cache['timestamp'])
                    if datetime.now() - cache_time < timedelta(hours=1):
                        return {**cache['data'], "city_vi": city_vi}
                except:
                    pass
            
            if not WEATHER_API_KEY:
                default_data = {
                    'current': f'Mưa rào sáng, mây chiều ở {city_vi} (23-28°C).',
                    'forecast': [f'Ngày mai: Nắng, 26°C', f'Ngày kia: Mưa, 25°C'] * 3,
                    'timestamp': datetime.now().isoformat(),
                    'city_vi': city_vi
                }
                with open(cache_path, 'w') as f:
                    json.dump({'data': default_data, 'timestamp': datetime.now().isoformat()}, f)
                return default_data
            
            try:
                url = f"http://api.weatherapi.com/v1/forecast.json?key={WEATHER_API_KEY}&q={city_en}&days=7&aqi=no&alerts=no"
                response = requests.get(url, timeout=10)
                if response.status_code != 200:
                    raise ValueError(f"API status: {response.status_code}")
                
                data = response.json()
                if 'error' in data:
                    raise ValueError(f"API error: {data['error']['message']}")
                
                current = data['current']['condition']['text'] + f" ({data['current']['temp_c']}°C)"
                forecast = []
                for day in data['forecast']['forecastday'][1:7]:
                    forecast.append(f"Ngày {day['date']}: {day['day']['condition']['text']} ({day['day']['avgtemp_c']}°C)")
                
                weather_data = {
                    'current': current,
                    'forecast': forecast,
                    'timestamp': datetime.now().isoformat(),
                    'city_vi': city_vi
                }
                
                cache_entry = {'data': weather_data, 'timestamp': datetime.now().isoformat()}
                with open(cache_path, 'w') as f:
                    json.dump(cache_entry, f, indent=2)
                
                return weather_data
            except Exception as e:
                self.logger.error(f"Weather API error: {e}")
                fallback_data = {
                    'current': f'Lỗi API, dùng mặc định: Mưa rào ở {city_vi}, 23-28°C.',
                    'forecast': [f'Ngày mai: Nắng, 26°C', f'Ngày kia: Mưa, 25°C'] * 3,
                    'timestamp': datetime.now().isoformat(),
                    'city_vi': city_vi
                }
                with open(cache_path, 'w') as f:
                    json.dump({'data': fallback_data, 'timestamp': datetime.now().isoformat()}, f)
                return fallback_data
    
    def run_calculator(self, equation_str: str):
        """Run mathematical calculation."""
        cleaned_eq = equation_str.strip().lower().replace('x', '*').replace(',', '.')
        if cleaned_eq.endswith('='):
            cleaned_eq = cleaned_eq[:-1]
        
        try:
            expr = sp.sympify(cleaned_eq, evaluate=False)
            result = sp.N(expr)
            result_str = str(result)
            if result_str.endswith('.0'):
                result_str = result_str[:-2]
            return json.dumps({
                "equation": equation_str,
                "result": result_str,
                "success": True
            }, ensure_ascii=False)
        except (sp.SympifyError, TypeError, ZeroDivisionError, Exception) as e:
            return json.dumps({
                "equation": equation_str,
                "result": f"Lỗi biểu thức: {str(e)}",
                "success": False
            }, ensure_ascii=False)
    
    async def run_image_recognition(self, image_url: str, question: str):
        """Run image understanding using Gemini multimodal API."""
        cached_result = self.get_image_recognition_cache(image_url, question)
        if cached_result:
            self.logger.info(f"Image recognition result from cache for URL: {image_url}, Question: {question[:30]}...")
            return cached_result

        api_key = self._next_gemini_api_key()
        if not api_key:
            return "Lỗi: Không tìm thấy Gemini API key để nhận diện ảnh."

        start_ts = datetime.now().timestamp()
        try:
            image_bytes = await asyncio.to_thread(lambda: requests.get(image_url, timeout=12).content)
            if not image_bytes:
                return "Lỗi: Không tải được dữ liệu hình ảnh từ URL."

            if len(image_bytes) > self.MAX_FILE_SIZE_BYTES:
                return "Lỗi: Ảnh vượt quá giới hạn 20MB cho inline image understanding."

            mime_type = self._guess_mime_type(image_url)
            image_part = genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

            client = genai.Client(api_key=api_key)
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=self.gemini_vision_model,
                contents=[image_part, question],
            )

            final_result = (getattr(response, "text", "") or "").strip()
            if not final_result:
                final_result = "Không thể nhận diện nội dung ảnh rõ ràng từ truy vấn này."

            self.set_image_recognition_cache(image_url, question, final_result)
            latency_ms = int((datetime.now().timestamp() - start_ts) * 1000)
            self.logger.info(
                f"AB_METRIC image_tool success=1 latency_ms={latency_ms} bytes={len(image_bytes)} model={self.gemini_vision_model}"
            )
            return final_result
        except Exception as e:
            error_text = str(e)
            lowered = error_text.lower()
            if any(token in lowered for token in ["api key not found", "api_key_invalid", "invalid api key", "permission denied"]):
                self._invalid_tool_keys.add(api_key)
            elif any(token in lowered for token in ["429", "resource_exhausted", "quota", "rate limit"]):
                self._tool_key_cooldowns[api_key] = time.time() + 60

            latency_ms = int((datetime.now().timestamp() - start_ts) * 1000)
            self.logger.warning(
                f"AB_METRIC image_tool success=0 latency_ms={latency_ms} error={error_text[:120]}"
            )
            return f"Đã xảy ra lỗi khi xử lý hình ảnh bằng Gemini: {e}"
    
    def _dedupe_source_lines(self, merged: str) -> str:
        unique_lines = []
        seen_links = set()
        for line in merged.splitlines():
            match = re.search(r"\(Nguồn: (.*?)\)", line)
            if match:
                link = match.group(1)
                if link not in seen_links:
                    seen_links.add(link)
                    unique_lines.append(line)
            else:
                unique_lines.append(line)
        return "\n".join(unique_lines)

    async def _search_serpapi(self, query: str):
        """Search using SerpAPI."""
        if not SERPAPI_API_KEY:
            return ""
        
        params = {
            "q": query,
            "api_key": SERPAPI_API_KEY,
            "engine": "google",
            "num": 3,
            "gl": "vn",
            "hl": "en" if re.search(r'[a-zA-Z]{4,}', query) else "vi"
        }
        
        results = await asyncio.to_thread(serpapi.search, params)
        
        if 'organic_results' not in results:
            return ""
        
        relevant = []
        for item in results['organic_results'][:3]:
            title = item.get('title', 'Không có tiêu đề')
            snippet = item.get('snippet', '')[:330] + "..." if len(item.get('snippet', '')) > 130 else item.get('snippet', '')
            link = item.get('link', '')
            if any(ad in link.lower() for ad in ['shopee', 'lazada', 'amazon', 'tiki']):
                continue
            relevant.append(f"**{title}**: {snippet} (Nguồn: {link})")
        
        return "**Search SerpAPI (Dynamic):**\n" + "\n".join(relevant) if relevant else ""
    
    async def _search_tavily(self, query: str):
        """Search using Tavily API."""
        if not TAVILY_API_KEY:
            return ""
        
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
        params = {
            "query": query,
            "search_depth": "basic",
            "max_results": 3,
            "include_answer": False
        }
        
        results = await asyncio.to_thread(tavily.search, **params)
        
        if 'results' not in results:
            return ""
        
        relevant = []
        for item in results['results'][:3]:
            title = item.get('title', 'Không có tiêu đề')
            snippet = item.get('content', '')[:330] + "..." if len(item.get('content', '')) > 130 else item.get('content', '')
            link = item.get('url', '')
            if any(ad in link.lower() for ad in ['shopee', 'lazada', 'amazon', 'tiki']):
                continue
            relevant.append(f"**{title}**: {snippet} (Nguồn: {link})")
        
        return "**Search Tavily (Dynamic):**\n" + "\n".join(relevant) if relevant else ""
    
    async def _search_exa(self, query: str):
        """Search using Exa API."""
        if not EXA_API_KEY:
            return ""
        
        exa = exa_py.Exa(api_key=EXA_API_KEY)
        params = {
            "query": query,
            "num_results": 3,
            "type": "neural"
        }

        try:
            results = await asyncio.to_thread(exa.search, use_autoprompt=True, **params)
        except TypeError:
            results = await asyncio.to_thread(exa.search, **params)
        
        if not results.results:
            return ""
        
        relevant = []
        for item in results.results[:3]:
            title = item.title or 'Không có tiêu đề'
            text = item.text or ''
            snippet = text[:330] + "..." if len(text) > 130 else text
            link = item.url or ''
            if any(ad in link.lower() for ad in ['shopee', 'lazada', 'amazon', 'tiki']):
                continue
            relevant.append(f"**{title}**: {snippet} (Nguồn: {link})")
        
        return "**Search Exa.ai (Dynamic):**\n" + "\n".join(relevant) if relevant else ""
    
    async def _run_fallback_search(self, query: str):
        """Run fallback search using external providers in parallel and merge results."""
        providers = []
        if SERPAPI_API_KEY:
            providers.append(("SerpAPI", self._search_serpapi(query)))
        if TAVILY_API_KEY:
            providers.append(("Tavily", self._search_tavily(query)))
        if EXA_API_KEY:
            providers.append(("Exa", self._search_exa(query)))

        if not providers:
            self.logger.warning("Không có external search API key để fallback.")
            self.logger.warning("AB_METRIC search_fallback providers=0 success=0")
            return ""

        providers = providers[:self.fallback_provider_limit]
        names = [name for name, _ in providers]
        self.logger.info(f"Running fallback providers: {', '.join(names)}")

        results = await asyncio.gather(*(task for _, task in providers), return_exceptions=True)

        merged_parts = []
        for (name, _), result in zip(providers, results):
            if isinstance(result, Exception):
                self.logger.warning(f"Fallback {name} error: {result}")
                continue
            if result:
                self.logger.info(f"Fallback {name} success for query '{query[:60]}'")
                merged_parts.append(result)
            else:
                self.logger.warning(f"Fallback {name} empty.")

        if not merged_parts:
            self.logger.error("All fallback APIs failed.")
            self.logger.warning(f"AB_METRIC search_fallback providers={len(providers)} success=0")
            return ""

        self.logger.info(f"AB_METRIC search_fallback providers={len(providers)} success=1 results={len(merged_parts)}")
        return "\n\n".join(merged_parts)
    
    async def run_search_apis(self, query: str, mode: str = "general"):
        """Run DuckDuckGo primary search with external fallback APIs."""
        cached_result = self.get_web_search_cache(query)
        if cached_result:
            self.logger.info(f"Web search result from cache for query: {query[:50]}...")
            return cached_result
        
        active_primary_streams = self.google_search_streams
        self.logger.info(f"CALLING {active_primary_streams}x DuckDuckGo primary search for '{query}' (mode: {mode})")

        FORCE_FALLBACK_REQUEST = "[FORCE FALLBACK]" in query.upper()
        q_base = query.replace("[FORCE FALLBACK]", "").strip()

        sub_queries = []
        if " và " in q_base or " and " in q_base.lower() or "," in q_base:
            splitters = re.split(r"\s*(?:và|and|,)\s*", q_base, flags=re.IGNORECASE)
            sub_queries = [q.strip() for q in splitters if q.strip()]
        else:
            sub_queries = [q_base.strip()]

        if len(sub_queries) > 1:
            self.logger.info(f"Subquery fanout capped to 1 for cost control (from {len(sub_queries)}).")
            sub_queries = sub_queries[:1]

        final_results = []

        for q_sub in sub_queries:
            async with self.search_lock:
                query_lower = q_sub.lower()
                selected_topic = "general"
                for topic, data in self.SEARCH_TOPICS.items():
                    if topic == "general":
                        continue
                    if any(keyword in query_lower for keyword in data["keywords"]):
                        selected_topic = topic
                        break

                self.logger.info(f"Classified: {selected_topic.upper()}. Searching for: '{q_sub}'")

                suffixes = self.SEARCH_TOPICS[selected_topic]["suffixes"]

                q1 = q_sub.strip()
                q2 = self._build_secondary_query(q1, suffixes)

                fallback_q = q_sub.strip()
                if not any(word in fallback_q.lower() for word in ["latest", "new", "current", "mới", "hiện tại"]):
                    fallback_q = f"{fallback_q} latest OR newest OR current"

                self.logger.info(f"Queries: Q1='{q1}', Q2='{q2}'")

                primary_queries = [q1]
                if active_primary_streams > 1 and q2 and q2.lower() != q1.lower():
                    primary_queries.append(q2)
                primary_tasks = [
                    asyncio.create_task(self._search_duckduckgo(p_query, idx))
                    for idx, p_query in enumerate(primary_queries)
                ]
                primary_results = await asyncio.gather(*primary_tasks, return_exceptions=True)

                primary_parts = []
                for idx, p_result in enumerate(primary_results):
                    if isinstance(p_result, Exception):
                        self.logger.error(f"PrimarySearch{idx} error: {p_result}")
                        primary_parts.append("")
                    else:
                        primary_parts.append(p_result or "")

                has_primary_result = any(primary_parts)
                has_enough_primary_context = self._is_search_result_sufficient(primary_parts)
                should_run_fallback = (
                    FORCE_FALLBACK_REQUEST
                    or (not has_primary_result)
                    or (has_primary_result and not has_enough_primary_context)
                )

                fallback_result = ""
                fallback_trigger_reason = "none"
                if should_run_fallback:
                    if FORCE_FALLBACK_REQUEST:
                        fallback_trigger_reason = "forced"
                        reason = "AI requested [FORCE FALLBACK]"
                    elif not has_primary_result:
                        fallback_trigger_reason = "empty_primary"
                        reason = "All DuckDuckGo streams empty/error"
                    else:
                        fallback_trigger_reason = "insufficient_primary"
                        reason = "DuckDuckGo context chưa đủ thông tin"
                    self.logger.warning(f"{reason} → Running external fallback APIs.")

                    fallback_result = await self._run_fallback_search(fallback_q)
                    if fallback_result:
                        self.logger.info("Fallback success.")
                    else:
                        self.logger.warning("Fallback failed.")

                parts = [str(x) for x in [*primary_parts, fallback_result] if x]

                self.logger.info(
                    f"AB_METRIC search_query topic={selected_topic} primary_success={1 if has_primary_result else 0} "
                    f"fallback_trigger={1 if should_run_fallback else 0} fallback_reason={fallback_trigger_reason}"
                )

                if parts:
                    merged = "\n\n".join(parts)
                    final_text = self._dedupe_source_lines(merged)
                    final_results.append(f"### 🔍 [Chủ đề: {selected_topic.upper()}] Kết quả cho '{q_sub}':\n{final_text.strip()}")
        
        if final_results:
            combined_final_results = "\n\n".join(final_results)
            self.set_web_search_cache(query, combined_final_results)
            self.logger.info(f"Completed search for {len(final_results)} subqueries and cached.")
            return combined_final_results
        
        self.logger.error("All DuckDuckGo primary + fallback providers FAILED.")
        return ""
    
    async def call_tool(self, function_call, user_id: str):
        """Dispatch tool calls to appropriate handlers."""
        name = function_call.name
        args = dict(function_call.args) if function_call.args else {}
        self.logger.info(f"TOOL CALLED: {name} | Args: {args} | User: {user_id}")
        
        try:
            if name == "web_search":
                query = args.get("query", "")
                return await self.run_search_apis(query, "general")
            
            elif name == "get_weather":
                city = args.get("city", "Ho Chi Minh City")
                data = await self.get_weather(city)
                return json.dumps(data, ensure_ascii=False, indent=2)
            
            elif name == "calculate":
                eq = args.get("equation", "")
                return await asyncio.to_thread(self.run_calculator, eq)
            
            elif name == "save_note":
                content = args.get("note_content")
                source = args.get("source", "chat_inference")
                if not content:
                    return "Lỗi: 'note_content' không được rỗng."
                return f"Đã lưu note: {content}"
            
            elif name == "retrieve_notes":
                query = args.get("query", "")
                return "Không tìm thấy ghi chú nào phù hợp."
            
            elif name == "image_recognition":
                image_url = args.get("image_url")
                question = args.get("question")
                if not image_url or not question:
                    return "Lỗi: 'image_url' và 'question' không được rỗng cho image_recognition."
                return await self.run_image_recognition(image_url, question)

            else:
                return "Tool không tồn tại!"
        
        except Exception as e:
            self.logger.error(f"Tool {name} error: {e}")
            return f"Lỗi tool: {str(e)}"
