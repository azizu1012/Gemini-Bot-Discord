import asyncio
import json
import re
import os
import mimetypes
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from typing import Dict, List, Any
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
    
    def __init__(self, note_mgr=None):
        self.logger = logger
        self.note_mgr = note_mgr
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
        self.intent_batch_size = self._load_intent_batch_size()
        self.trusted_mode = self._load_trusted_mode()
        self.min_reputable_sources = self._load_min_reputable_sources()
        self.time_sensitive_min_reputable_sources = self._load_time_sensitive_min_reputable_sources()
        self.deep_read_top_links = self._load_deep_read_top_links()
        self.deep_read_max_chars = self._load_deep_read_max_chars()
        self.exa_use_autoprompt = self._load_exa_autoprompt()
        self.trusted_profiles = self._load_trusted_profiles()
        self.deep_read_cache = {}
        self.gemini_vision_model = os.getenv("GEMINI_VISION_MODEL", MODEL_NAME or "gemini-3-flash-preview")

        if GEMINI_API_KEYS:
            self.logger.info(
                f"Search/image tools ready: provider=duckduckgo streams={self.google_search_streams} "
                f"fallback_limit={self.fallback_provider_limit} batch={self.intent_batch_size} "
                f"trusted_mode={self.trusted_mode} deep_read_top_links={self.deep_read_top_links} "
                f"vision_model={self.gemini_vision_model}"
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
        raw = os.getenv("GOOGLE_SEARCH_STREAMS", "2").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 2
        return max(1, min(2, value))

    def _load_fallback_provider_limit(self) -> int:
        raw = os.getenv("SEARCH_FALLBACK_PROVIDER_LIMIT", "1").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 1
        return max(1, min(3, value))

    def _load_intent_batch_size(self) -> int:
        raw = os.getenv("SEARCH_INTENT_BATCH_MAX", "3").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 3
        return max(2, min(3, value))

    def _load_trusted_mode(self) -> str:
        mode = (os.getenv("SEARCH_TRUSTED_MODE", "balanced") or "balanced").strip().lower()
        if mode not in {"off", "balanced", "strict"}:
            return "balanced"
        return mode

    def _load_min_reputable_sources(self) -> int:
        raw = os.getenv("SEARCH_MIN_REPUTABLE_SOURCES", "2").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 2
        return max(1, min(5, value))

    def _load_time_sensitive_min_reputable_sources(self) -> int:
        raw = os.getenv("SEARCH_TIME_SENSITIVE_MIN_REPUTABLE_SOURCES", "3").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 3
        return max(self.min_reputable_sources, min(6, value))

    def _load_deep_read_top_links(self) -> int:
        raw = os.getenv("SEARCH_DEEP_READ_TOP_LINKS", "3").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 3
        return max(1, min(5, value))

    def _load_deep_read_max_chars(self) -> int:
        raw = os.getenv("SEARCH_DEEP_READ_MAX_CHARS", "1800").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 1800
        return max(600, min(5000, value))

    def _load_exa_autoprompt(self) -> bool:
        return (os.getenv("SEARCH_EXA_AUTOPROMPT", "false") or "false").strip().lower() == "true"

    def _split_csv_domains(self, raw: str) -> List[str]:
        parts = [p.strip().lower() for p in (raw or "").split(",")]
        return [p for p in parts if p]

    def _load_trusted_profiles(self) -> Dict[str, Dict[str, List[str]]]:
        profiles = {
            "gaming": {
                "tier_a": [
                    "hoyolab.com", "genshin.hoyoverse.com", "hsr.hoyoverse.com", "zenless.hoyoverse.com",
                    "wutheringwaves.kurogames.com", "arknights.global", "www.fate-go.us"
                ],
                "tier_b": ["game8.co", "gamewith.net", "ign.com", "gamespot.com"]
            },
            "tech": {
                "tier_a": [
                    "developer.mozilla.org", "docs.python.org", "python.org", "learn.microsoft.com",
                    "cloud.google.com", "developer.apple.com", "android.com"
                ],
                "tier_b": ["arstechnica.com", "anandtech.com", "theverge.com"]
            },
            "law_politics": {
                "tier_a": ["congress.gov", "whitehouse.gov", "gov.uk", "europa.eu", "un.org"],
                "tier_b": ["reuters.com", "apnews.com", "bbc.com"]
            },
            "culture": {
                "tier_a": ["britannica.com", "unesco.org", "smithsonianmag.com"],
                "tier_b": ["nationalgeographic.com", "history.com", "newyorker.com"]
            },
            "health_wellness": {
                "tier_a": ["who.int", "cdc.gov", "nih.gov", "mayoclinic.org"],
                "tier_b": ["healthline.com", "webmd.com"]
            },
            "finance": {
                "tier_a": ["sec.gov", "federalreserve.gov", "imf.org", "worldbank.org"],
                "tier_b": ["reuters.com", "ft.com", "bloomberg.com"]
            },
            "general": {
                "tier_a": ["reuters.com", "apnews.com", "bbc.com", "wikipedia.org"],
                "tier_b": ["npr.org", "dw.com", "theguardian.com"]
            }
        }

        env_mapping = {
            "gaming": "SEARCH_TRUSTED_DOMAINS_GAMING",
            "tech": "SEARCH_TRUSTED_DOMAINS_TECH",
            "law_politics": "SEARCH_TRUSTED_DOMAINS_POLITICS",
            "culture": "SEARCH_TRUSTED_DOMAINS_CULTURE",
            "health_wellness": "SEARCH_TRUSTED_DOMAINS_HEALTH",
            "finance": "SEARCH_TRUSTED_DOMAINS_FINANCE",
            "general": "SEARCH_TRUSTED_DOMAINS_GENERAL",
        }

        for topic, env_name in env_mapping.items():
            extra = self._split_csv_domains(os.getenv(env_name, ""))
            if not extra:
                continue
            tier_a = profiles.get(topic, {}).get("tier_a", [])
            for domain in extra:
                if domain not in tier_a:
                    tier_a.append(domain)
            profiles.setdefault(topic, {})["tier_a"] = tier_a

        return profiles

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

    def _normalize_domain(self, url: str) -> str:
        try:
            host = (urlparse(url).netloc or "").lower().strip()
            if host.startswith("www."):
                host = host[4:]
            return host
        except Exception:
            return ""

    def _normalize_url(self, url: str) -> str:
        try:
            parsed = urlparse(url.strip())
            if parsed.scheme not in {"http", "https"}:
                return ""
            query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
            filtered = []
            for k, v in query_pairs:
                lk = (k or "").lower()
                if lk.startswith("utm_") or lk in {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid"}:
                    continue
                filtered.append((k, v))
            normalized = parsed._replace(
                scheme="https",
                netloc=(parsed.netloc or "").lower(),
                query=urlencode(filtered, doseq=True),
                fragment=""
            )
            clean = urlunparse(normalized)
            return clean[:-1] if clean.endswith("/") else clean
        except Exception:
            return ""

    def _is_blocked_domain(self, url: str) -> bool:
        domain = self._normalize_domain(url)
        if not domain:
            return True
        blocked = {'shopee', 'lazada', 'amazon', 'tiki'}
        return any(token in domain for token in blocked)

    def _topic_profile_name(self, topic: str) -> str:
        if topic in self.trusted_profiles:
            return topic
        if topic in {"movies_tv", "anime_manga", "music", "books_literature", "fashion_beauty", "history"}:
            return "culture"
        if topic in {"mental_health"}:
            return "health_wellness"
        if topic in {"science", "education", "career_development", "business_entrepreneurship", "automotive"}:
            return "tech"
        if topic in {"real_estate", "cryptocurrency_blockchain"}:
            return "finance"
        if topic in {"law_politics"}:
            return "law_politics"
        return "general"

    def _is_trusted_domain(self, topic: str, domain: str) -> int:
        profile = self.trusted_profiles.get(self._topic_profile_name(topic), {})
        tier_a = profile.get("tier_a", [])
        tier_b = profile.get("tier_b", [])
        if any(domain == d or domain.endswith(f".{d}") for d in tier_a):
            return 2
        if any(domain == d or domain.endswith(f".{d}") for d in tier_b):
            return 1
        return 0

    def _is_time_sensitive_query(self, query: str) -> bool:
        q = (query or "").lower()
        markers = ["latest", "new", "current", "today", "now", "update", "mới", "hiện tại", "hôm nay", "vừa", "patch", "version", "banner"]
        return any(m in q for m in markers)

    def _required_reputable_sources(self, query: str) -> int:
        return self.time_sensitive_min_reputable_sources if self._is_time_sensitive_query(query) else self.min_reputable_sources

    def _split_multi_intents(self, query: str) -> List[str]:
        base = (query or "").strip()
        if not base:
            return []
        parts = re.split(r"\s*(?:\n+|;|\?|\.|\band\b|\bvà\b|,)\s*", base, flags=re.IGNORECASE)
        intents = [p.strip() for p in parts if len(p.strip()) > 2]
        if not intents:
            return [base]
        return intents

    def _determine_batch_size(self, intents: List[str]) -> int:
        if not intents:
            return 2
        avg_len = sum(len(x) for x in intents) / len(intents)
        if avg_len < 45 and len(intents) >= 3:
            return self.intent_batch_size
        return 2

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

    def _build_secondary_query(self, q1: str, suffixes: List[str]) -> str:
        q1_clean = q1.strip()
        if not q1_clean:
            return q1_clean

        for suffix in suffixes:
            suffix_clean = (suffix or "").strip()
            if not suffix_clean:
                continue
            if self._query_contains_suffix_intent(q1_clean, suffix_clean):
                continue
            return f"{q1_clean} {suffix_clean}"

        return q1_clean

    def _score_record(self, topic: str, query: str, record: Dict[str, str]) -> float:
        domain = record.get("domain", "")
        title = (record.get("title") or "").lower()
        snippet = (record.get("snippet") or "").lower()
        q = (query or "").lower()

        trust_tier = self._is_trusted_domain(topic, domain)
        score = 0.0
        score += 3.0 if trust_tier == 2 else 1.5 if trust_tier == 1 else 0.0

        if any(token for token in re.findall(r"\w+", q) if len(token) > 3 and token in f"{title} {snippet}"):
            score += 1.25

        provider = (record.get("provider") or "").lower()
        if provider == "duckduckgo":
            score += 0.4

        if len(snippet) > 120:
            score += 0.4

        return score

    def _format_source_line(self, rec: Dict[str, str]) -> str:
        title = rec.get("title") or "Không có tiêu đề"
        snippet = (rec.get("snippet") or "").strip()
        if len(snippet) > 330:
            snippet = snippet[:330] + "..."
        url = rec.get("url") or ""
        domain = rec.get("domain") or ""
        return f"**{title}** [{domain}](<{url}>): {snippet}"

    def _guess_mime_type(self, image_url: str) -> str:
        mime_type, _ = mimetypes.guess_type(image_url)
        if mime_type in {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}:
            return mime_type
        return "image/jpeg"

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

            def _write_cache_sync(payload: Dict[str, Any]) -> None:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)

            if await asyncio.to_thread(os.path.exists, cache_path):
                try:
                    async with aiofiles.open(cache_path, 'r', encoding='utf-8') as f:
                        cache = json.loads(await f.read())
                    cache_time = datetime.fromisoformat(cache['timestamp'])
                    if datetime.now() - cache_time < timedelta(hours=1):
                        return {**cache['data'], "city_vi": city_vi}
                except Exception:
                    pass

            if not WEATHER_API_KEY:
                default_data = {
                    'current': f'Mưa rào sáng, mây chiều ở {city_vi} (23-28°C).',
                    'forecast': [f'Ngày mai: Nắng, 26°C', f'Ngày kia: Mưa, 25°C'] * 3,
                    'timestamp': datetime.now().isoformat(),
                    'city_vi': city_vi
                }
                await asyncio.to_thread(
                    _write_cache_sync,
                    {'data': default_data, 'timestamp': datetime.now().isoformat()}
                )
                return default_data

            try:
                def _fetch_weather_sync() -> Dict[str, Any]:
                    url = f"http://api.weatherapi.com/v1/forecast.json?key={WEATHER_API_KEY}&q={city_en}&days=7&aqi=no&alerts=no"
                    response = requests.get(url, timeout=10)
                    if response.status_code != 200:
                        raise ValueError(f"API status: {response.status_code}")
                    payload = response.json()
                    if 'error' in payload:
                        raise ValueError(f"API error: {payload['error']['message']}")
                    return payload

                data = await asyncio.to_thread(_fetch_weather_sync)

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
                await asyncio.to_thread(_write_cache_sync, cache_entry)

                return weather_data
            except Exception as e:
                self.logger.error(f"Weather API error: {e}")
                fallback_data = {
                    'current': f'Lỗi API, dùng mặc định: Mưa rào ở {city_vi}, 23-28°C.',
                    'forecast': [f'Ngày mai: Nắng, 26°C', f'Ngày kia: Mưa, 25°C'] * 3,
                    'timestamp': datetime.now().isoformat(),
                    'city_vi': city_vi
                }
                await asyncio.to_thread(
                    _write_cache_sync,
                    {'data': fallback_data, 'timestamp': datetime.now().isoformat()}
                )
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
    
    def _dedupe_records(self, records: List[Dict[str, str]]) -> List[Dict[str, str]]:
        unique = []
        seen = set()
        for rec in records:
            key = rec.get("normalized_url") or rec.get("url")
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(rec)
        return unique

    def _count_reputable_sources(self, records: List[Dict[str, str]], topic: str) -> int:
        trusted = set()
        for rec in records:
            domain = rec.get("domain", "")
            if self._is_trusted_domain(topic, domain) > 0:
                trusted.add(domain)
        return len(trusted)

    def _is_search_result_sufficient(self, records: List[Dict[str, str]], topic: str, required_sources: int, min_chars: int = 220) -> bool:
        if not records:
            return False
        trusted_count = self._count_reputable_sources(records, topic)
        total_chars = sum(len((x.get("snippet") or "").strip()) for x in records[:6])
        if self.trusted_mode == "strict":
            return trusted_count >= required_sources
        return trusted_count >= required_sources and total_chars >= min_chars

    def _extract_main_text(self, html_text: str) -> str:
        text = re.sub(r"<script[\s\S]*?</script>", " ", html_text, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _get_deep_read_cache(self, url: str) -> str:
        item = self.deep_read_cache.get(url)
        if not item:
            return ""
        if datetime.now() - item["timestamp"] > timedelta(hours=2):
            del self.deep_read_cache[url]
            return ""
        return item["text"]

    def _set_deep_read_cache(self, url: str, text: str):
        self.deep_read_cache[url] = {"text": text, "timestamp": datetime.now()}

    async def _fetch_page_evidence(self, url: str) -> str:
        cached = self._get_deep_read_cache(url)
        if cached:
            return cached

        def _fetch() -> str:
            headers = {"User-Agent": "Mozilla/5.0 (AzurisBot/1.0)"}
            response = requests.get(url, headers=headers, timeout=8)
            if response.status_code != 200 or not response.text:
                return ""
            parsed = self._extract_main_text(response.text)
            return parsed[:self.deep_read_max_chars].strip()

        try:
            text = await asyncio.to_thread(_fetch)
            if text:
                self._set_deep_read_cache(url, text)
            return text
        except Exception:
            return ""

    async def _search_duckduckgo_records(self, query: str, index: int = 0) -> List[Dict[str, str]]:
        start_ts = datetime.now().timestamp()
        try:
            def _do_search():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=5))

            results = await asyncio.to_thread(_do_search)
            items: List[Dict[str, str]] = []
            for item in results[:5]:
                url_raw = item.get("href") or item.get("url") or ""
                normalized_url = self._normalize_url(url_raw)
                if not normalized_url or self._is_blocked_domain(normalized_url):
                    continue
                domain = self._normalize_domain(normalized_url)
                snippet = (item.get("body") or "").strip()
                items.append({
                    "provider": "duckduckgo",
                    "title": item.get("title") or "Không có tiêu đề",
                    "snippet": snippet,
                    "url": normalized_url,
                    "normalized_url": normalized_url,
                    "domain": domain,
                    "query": query,
                    "query_index": str(index),
                })

            latency_ms = int((datetime.now().timestamp() - start_ts) * 1000)
            self.logger.info(
                f"AB_METRIC search_primary query_idx={index} success={1 if items else 0} "
                f"latency_ms={latency_ms} provider=duckduckgo"
            )
            return items
        except Exception as e:
            latency_ms = int((datetime.now().timestamp() - start_ts) * 1000)
            self.logger.warning(
                f"AB_METRIC search_primary query_idx={index} success=0 latency_ms={latency_ms} "
                f"provider=duckduckgo error={str(e)[:120]}"
            )
            return []

    async def _search_serpapi_records(self, query: str) -> List[Dict[str, str]]:
        if not SERPAPI_API_KEY:
            return []

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
            return []

        items = []
        for item in results['organic_results'][:3]:
            url_raw = item.get('link', '')
            normalized_url = self._normalize_url(url_raw)
            if not normalized_url or self._is_blocked_domain(normalized_url):
                continue
            items.append({
                "provider": "serpapi",
                "title": item.get('title', 'Không có tiêu đề'),
                "snippet": (item.get('snippet', '') or '').strip(),
                "url": normalized_url,
                "normalized_url": normalized_url,
                "domain": self._normalize_domain(normalized_url),
                "query": query,
            })
        return items

    async def _search_tavily_records(self, query: str) -> List[Dict[str, str]]:
        if not TAVILY_API_KEY:
            return []

        tavily = TavilyClient(api_key=TAVILY_API_KEY)
        params = {
            "query": query,
            "search_depth": "basic",
            "max_results": 3,
            "include_answer": False
        }

        results = await asyncio.to_thread(tavily.search, **params)
        if 'results' not in results:
            return []

        items = []
        for item in results['results'][:3]:
            url_raw = item.get('url', '')
            normalized_url = self._normalize_url(url_raw)
            if not normalized_url or self._is_blocked_domain(normalized_url):
                continue
            items.append({
                "provider": "tavily",
                "title": item.get('title', 'Không có tiêu đề'),
                "snippet": (item.get('content', '') or '').strip(),
                "url": normalized_url,
                "normalized_url": normalized_url,
                "domain": self._normalize_domain(normalized_url),
                "query": query,
            })
        return items

    async def _search_exa_records(self, query: str) -> List[Dict[str, str]]:
        if not EXA_API_KEY:
            return []

        exa = exa_py.Exa(api_key=EXA_API_KEY)
        params = {
            "query": query,
            "num_results": 3,
            "type": "neural"
        }

        try:
            if self.exa_use_autoprompt:
                results = await asyncio.to_thread(exa.search, use_autoprompt=True, **params)
            else:
                results = await asyncio.to_thread(exa.search, **params)
        except TypeError:
            results = await asyncio.to_thread(exa.search, **params)

        if not results.results:
            return []

        items = []
        for item in results.results[:3]:
            url_raw = item.url or ''
            normalized_url = self._normalize_url(url_raw)
            if not normalized_url or self._is_blocked_domain(normalized_url):
                continue
            items.append({
                "provider": "exa",
                "title": item.title or 'Không có tiêu đề',
                "snippet": (item.text or '').strip(),
                "url": normalized_url,
                "normalized_url": normalized_url,
                "domain": self._normalize_domain(normalized_url),
                "query": query,
            })
        return items

    async def _run_fallback_search_records(self, query: str) -> List[Dict[str, str]]:
        provider_funcs = []
        if SERPAPI_API_KEY:
            provider_funcs.append(("SerpAPI", self._search_serpapi_records))
        if TAVILY_API_KEY:
            provider_funcs.append(("Tavily", self._search_tavily_records))
        if EXA_API_KEY:
            provider_funcs.append(("Exa", self._search_exa_records))

        if not provider_funcs:
            self.logger.warning("Không có external search API key để fallback.")
            self.logger.warning("AB_METRIC search_fallback providers=0 success=0")
            return []

        selected = provider_funcs[:self.fallback_provider_limit]
        names = [name for name, _ in selected]
        self.logger.info(f"Running fallback providers: {', '.join(names)}")

        tasks = [func(query) for _, func in selected]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        merged: List[Dict[str, str]] = []
        success_count = 0

        for (name, _), result in zip(selected, results):
            if isinstance(result, Exception):
                self.logger.warning(f"Fallback {name} error: {result}")
                continue
            if result:
                success_count += 1
                merged.extend(result)
                self.logger.info(f"Fallback {name} success for query '{query[:60]}'")
            else:
                self.logger.warning(f"Fallback {name} empty.")

        self.logger.info(f"AB_METRIC search_fallback providers={len(selected)} success={1 if success_count else 0} results={success_count}")
        return merged

    def _classify_topic(self, query: str) -> str:
        query_lower = (query or "").lower()
        generic_tokens = {"update", "news", "latest", "new", "information", "tin tức", "thông tin"}

        best_topic = "general"
        best_score = 0
        for topic, data in self.SEARCH_TOPICS.items():
            if topic == "general":
                continue

            score = 0
            for keyword in data["keywords"]:
                kw = (keyword or "").strip().lower()
                if not kw:
                    continue
                if kw in generic_tokens and topic != "general":
                    continue
                if kw in query_lower:
                    score += 1

            if score > best_score:
                best_score = score
                best_topic = topic

        return best_topic

    def _format_final_search_result(self, topic: str, query: str, ranked_records: List[Dict[str, str]], required_sources: int) -> str:
        trusted_lines = []
        additional_lines = []
        trusted_domains = set()

        for rec in ranked_records:
            trust_tier = self._is_trusted_domain(topic, rec.get("domain", ""))
            line = self._format_source_line(rec)
            if trust_tier > 0 and len(trusted_lines) < max(required_sources, 3):
                trusted_lines.append(line)
                trusted_domains.add(rec.get("domain", ""))
            else:
                additional_lines.append(line)

        deep_lines = []
        for rec in ranked_records[:self.deep_read_top_links]:
            evidence = rec.get("evidence", "")
            if not evidence:
                continue
            title = rec.get("title") or "Không có tiêu đề"
            url = rec.get("url") or ""
            snippet = evidence[:360].strip()
            if snippet:
                deep_lines.append(f"- {title} ([đọc sâu](<{url}>)): {snippet}")

        parts = [
            f"### 🔍 [Chủ đề: {topic.upper()}] Kết quả cho '{query}':",
            f"- Required reputable sources: {required_sources}",
            f"- Reputable sources found: {len(trusted_domains)}",
            "",
            "**Top trusted sources:**",
            "\n".join(trusted_lines) if trusted_lines else "(Không đủ nguồn uy tín từ lượt tìm kiếm này)",
            "",
            "**Additional corroborating sources:**",
            "\n".join(additional_lines[:6]) if additional_lines else "(Không có nguồn bổ sung)",
        ]

        if deep_lines:
            parts.extend(["", "**Evidence excerpts (deep-read):**", "\n".join(deep_lines)])

        return "\n".join(parts).strip()

    async def _search_single_intent(self, q_sub: str, force_fallback: bool = False) -> str:
        selected_topic = self._classify_topic(q_sub)
        suffixes = self.SEARCH_TOPICS.get(selected_topic, self.SEARCH_TOPICS["general"])["suffixes"]
        q1 = q_sub.strip()
        q2 = self._build_secondary_query(q1, suffixes)

        self.logger.info(f"Classified: {selected_topic.upper()}. Searching for: '{q_sub}'")
        self.logger.info(f"Queries: Q1='{q1}', Q2='{q2}'")

        primary_queries = [q1]
        if self.google_search_streams > 1 and q2 and q2.lower() != q1.lower():
            primary_queries.append(q2)

        primary_tasks = [
            asyncio.create_task(self._search_duckduckgo_records(p_query, idx))
            for idx, p_query in enumerate(primary_queries)
        ]
        primary_results = await asyncio.gather(*primary_tasks, return_exceptions=True)

        records: List[Dict[str, str]] = []
        for result in primary_results:
            if isinstance(result, Exception):
                continue
            records.extend(result)

        records = self._dedupe_records(records)
        required_sources = self._required_reputable_sources(q_sub)
        has_enough = self._is_search_result_sufficient(records, selected_topic, required_sources)

        fallback_reason = "none"
        should_fallback = force_fallback or not has_enough
        if should_fallback:
            fallback_reason = "forced" if force_fallback else "insufficient_primary"
            fallback_records = await self._run_fallback_search_records(q_sub)
            records.extend(fallback_records)
            records = self._dedupe_records(records)

        scored = []
        for rec in records:
            rec["score"] = str(self._score_record(selected_topic, q_sub, rec))
            scored.append(rec)

        ranked = sorted(scored, key=lambda x: float(x.get("score", "0")), reverse=True)

        for rec in ranked[:self.deep_read_top_links]:
            rec["evidence"] = await self._fetch_page_evidence(rec.get("url", ""))

        self.logger.info(
            f"AB_METRIC search_query topic={selected_topic} primary_success={1 if records else 0} "
            f"fallback_trigger={1 if should_fallback else 0} fallback_reason={fallback_reason}"
        )

        final = self._format_final_search_result(selected_topic, q_sub, ranked, required_sources)
        if self.trusted_mode == "strict" and self._count_reputable_sources(ranked, selected_topic) < required_sources:
            final += "\n\n⚠️ Chưa đủ nguồn uy tín theo ngưỡng strict. Cần thêm vòng truy xuất hoặc người dùng cung cấp link chính xác."
        return final

    async def run_search_apis(self, query: str, mode: str = "general"):
        async with self.cache_lock:
            cached_result = self.get_web_search_cache(query)
        if cached_result:
            self.logger.info(f"Web search result from cache for query: {query[:50]}...")
            return cached_result

        force_fallback = "[FORCE FALLBACK]" in query.upper()
        clean_query = query.replace("[FORCE FALLBACK]", "").strip()
        intents = self._split_multi_intents(clean_query)
        if not intents:
            return ""

        batch_size = self._determine_batch_size(intents)
        if len(intents) > 1:
            self.logger.info(f"Subquery fanout enabled with adaptive batching: intents={len(intents)} batch_size={batch_size}")

        final_sections = []
        for start in range(0, len(intents), batch_size):
            batch = intents[start:start + batch_size]
            tasks = [self._search_single_intent(intent, force_fallback) for intent in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for intent, res in zip(batch, results):
                if isinstance(res, Exception):
                    self.logger.error(f"Search intent error for '{intent[:60]}': {res}")
                    final_sections.append(f"### 🔍 [Chủ đề: GENERAL] Kết quả cho '{intent}':\n(Không thể truy xuất dữ liệu cho intent này.)")
                elif res:
                    final_sections.append(res)

        if final_sections:
            output = "\n\n".join(final_sections)
            async with self.cache_lock:
                self.set_web_search_cache(query, output)
            self.logger.info(f"Completed search for intents={len(intents)} and cached.")
            return output

        self.logger.error("All search providers failed for all intents.")
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
                content = (args.get("note_content") or "").strip()
                source = (args.get("source") or "chat_inference").strip() or "chat_inference"
                if not content:
                    return "Lỗi: 'note_content' không được rỗng."
                if not self.note_mgr:
                    self.logger.error("save_note called but NoteManager is not configured")
                    return "Lỗi hệ thống: memory manager chưa sẵn sàng."
                return await self.note_mgr.save_note_to_db(user_id, content, source)

            elif name == "retrieve_notes":
                query = (args.get("query") or "").strip()
                if not self.note_mgr:
                    self.logger.error("retrieve_notes called but NoteManager is not configured")
                    return "Lỗi hệ thống: memory manager chưa sẵn sàng."
                return await self.note_mgr.retrieve_notes_from_db(user_id, query)
            
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
