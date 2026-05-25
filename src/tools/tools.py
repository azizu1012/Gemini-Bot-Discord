import asyncio
import json
import re
import os
import mimetypes
import time
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from typing import Dict, List, Any, Optional, Set
import aiofiles
import requests
import sympy as sp
from sympy.parsing.sympy_parser import (
    parse_expr,
    standard_transformations,
    implicit_multiplication_application,
    convert_xor,
)
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
import src.core.config as config
from src.core.api_router import get_api_router
from src.core.api_config import AVAILABLE_MODELS

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

    SEARCH_CACHE_STOPWORDS = {
        "the", "a", "an", "of", "for", "to", "and", "or", "in", "on", "at", "is", "are", "be",
        "toi", "la", "va", "cua", "cho", "ve", "trong", "tai", "duoc", "khong", "nao", "gi", "bao", "khi",
        "news", "information", "thong", "tin", "xem", "hoi", "giup",
    }

    SEARCH_CACHE_PHRASE_ALIASES = [
        ("moi nhat", "latest"),
        ("hien tai", "current"),
        ("cap nhat", "update"),
        ("khi nao", "when"),
        ("bao gio", "when"),
        ("ket thuc", "end"),
        ("thoi gian", "schedule"),
        ("lich", "schedule"),
    ]

    SEARCH_CACHE_TOKEN_ALIASES = {
        "hsr": "honkai_star_rail",
        "starrail": "honkai_star_rail",
        "banner": "banner",
        "latest": "latest",
        "current": "current",
        "update": "update",
        "patch": "patch",
        "schedule": "schedule",
    }


    def __init__(self, note_mgr=None, db_repo=None):
        self.logger = logger
        self.api_router = get_api_router()
        self.note_mgr = note_mgr
        self.db_repo = db_repo
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
        self.min_quality_sources = self._load_min_quality_sources()
        self.time_sensitive_min_quality_sources = self._load_time_sensitive_min_quality_sources()
        self.search_web_mode = self._load_search_web_mode()
        self.search_grounded_top_links = self._load_search_grounded_top_links()
        self.search_top_results_limit = self._load_search_top_results_limit()
        self.deep_read_top_links = self._load_deep_read_top_links()
        self.deep_read_max_chars = self._load_deep_read_max_chars()
        self.exa_use_autoprompt = self._load_exa_autoprompt()
        self.deep_read_cache = {}
        self.inflight_search_tasks: Dict[str, asyncio.Task] = {}
        self.failed_search_cooldowns: Dict[str, float] = {}
        self.search_semantic_cache_enabled = self._load_search_semantic_cache_enabled()
        self.search_general_cache_ttl_seconds = self._load_search_general_cache_ttl_seconds()
        self.search_time_sensitive_cache_ttl_seconds = self._load_search_time_sensitive_cache_ttl_seconds()
        self.search_failed_query_cooldown_seconds = self._load_search_failed_query_cooldown_seconds()
        self.search_empty_evidence_cache_ttl_seconds = self._load_search_empty_evidence_cache_ttl_seconds()

        if GEMINI_API_KEYS:
            self.logger.info(
                f"Search/image tools ready: provider=duckduckgo streams={self.google_search_streams} "
                f"fallback_limit={self.fallback_provider_limit} batch={self.intent_batch_size} "
                f"web_mode={self.search_web_mode} grounded_links={self.search_grounded_top_links} "
                f"top_results_limit={self.search_top_results_limit} quality_sources={self.min_quality_sources}/{self.time_sensitive_min_quality_sources} "
                f"deep_read_top_links={self.deep_read_top_links} semantic_cache={self.search_semantic_cache_enabled} "
                f"general_ttl={self.search_general_cache_ttl_seconds}s "
                f"time_ttl={self.search_time_sensitive_cache_ttl_seconds}s cooldown={self.search_failed_query_cooldown_seconds}s"
            )
        else:
            self.logger.warning("Không có Gemini API key cho tools; web_search/image_recognition sẽ failback.")

    async def _resolve_router_model_alias_for_vision(self) -> str:
        """Map configured vision model_id to router alias for shared key/quota accounting."""
        # Use FINAL_MODEL_ALIAS (default gemini-flash-35) for vision tasks
        # consistent with message_handler where Lite is for reasoning only.
        final_alias = os.getenv("FINAL_MODEL_ALIAS", "gemini-flash-35").strip()

        # If the final_alias is valid, ensure we can route to it or its peer
        if True:
            # We don't want to actually reserve the key here, we just want to verify
            # if final_alias or its priority peer (like flash-30) is available.
            # Using get_next_key_for_model_reservation handles checking priority fallback.
            reservation = await self.api_router.get_next_key_for_model_reservation(final_alias)
            if reservation:
                return reservation["model_alias"]

        return final_alias

    def get_all_tools(self, is_admin: bool = False):
        """Return all tool definitions for Gemini."""
        tools_list = [
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
                    description=(
                        "Giải các bài toán số học hoặc biểu thức phức tạp (đại số, lượng giác, logarit). "
                        "Hỗ trợ đạo hàm/tích phân/rút gọn bằng cú pháp SymPy (vd: diff(x**3*exp(sin(x)), x))."
                    ),
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
                    name="delete_note",
                    description=(
                        "Xóa một ghi chú/thông tin cụ thể đã lưu trữ của người dùng dựa vào note_id. "
                        "Thường sử dụng kết hợp sau khi gọi retrieve_notes để lấy chính xác note_id cần xóa."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "note_id": {"type": "string", "description": "ID của note cần xóa (UUID)."}
                        },
                        "required": ["note_id"]
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

        if is_admin:
            tools_list.append(
                genai_types.Tool(function_declarations=[
                    genai_types.FunctionDeclaration(
                        name="manage_user_role",
                        description=(
                            "Quản lý vai trò (roles) của người dùng: Thăng chức làm Moderator, Premium hoặc Admin, "
                            "hoặc hạ chức người dùng về User thông thường. Lệnh này chỉ thực hiện được khi người gọi lệnh "
                            "(tham số user_id của chat context) là Admin thực tế của bot."
                        ),
                        parameters={
                            "type": "object",
                            "properties": {
                                "target_user_id": {"type": "string", "description": "ID Discord số của người dùng cần thay đổi vai trò."},
                                "action": {"type": "string", "description": "Hành động: 'add' (thăng chức/thêm) hoặc 'remove' (hạ chức/xóa).", "enum": ["add", "remove"]},
                                "role": {"type": "string", "description": "Vai trò cần thiết lập: 'moderator', 'premium', hoặc 'admin'.", "enum": ["moderator", "premium", "admin"]}
                            },
                            "required": ["target_user_id", "action", "role"]
                        }
                    )
                ])
            )

        return tools_list
    
    def _remove_diacritics(self, text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text or "")
        return "".join(ch for ch in normalized if not unicodedata.combining(ch))

    def _canonicalize_search_query(self, query: str) -> str:
        lowered = (query or "").strip().lower()
        lowered = lowered.replace("[force fallback]", " ")
        lowered = self._remove_diacritics(lowered)

        for src, dst in self.SEARCH_CACHE_PHRASE_ALIASES:
            lowered = re.sub(rf"\b{re.escape(src)}\b", dst, lowered)

        lowered = re.sub(r"[^a-z0-9_\s]", " ", lowered)
        lowered = re.sub(r"\s+", " ", lowered).strip()
        if not lowered:
            return ""

        tokens = []
        for token in lowered.split(" "):
            normalized_token = self.SEARCH_CACHE_TOKEN_ALIASES.get(token, token)
            if not normalized_token or normalized_token in self.SEARCH_CACHE_STOPWORDS:
                continue
            if len(normalized_token) <= 1:
                continue
            tokens.append(normalized_token)

        if not tokens:
            return lowered

        canonical_tokens = sorted(set(tokens))
        return " ".join(canonical_tokens[:32])

    def _normalize_search_cache_key(self, query: str) -> str:
        normalized = (query or "").strip().lower()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = re.sub(r"\s*\|\s*", "|", normalized)

        mode = "general"
        payload = normalized
        if "|" in normalized:
            maybe_mode, maybe_payload = normalized.split("|", 1)
            mode = maybe_mode or "general"
            payload = maybe_payload or ""

        if self.search_semantic_cache_enabled:
            canonical_payload = self._canonicalize_search_query(payload)
            if canonical_payload:
                payload = canonical_payload

        return f"{mode}|{payload}"

    def get_web_search_cache(self, query: str):
        """Get cached web search result. (Deprecated - Now uses SQLite DB for persistence but memory cache for fast responses)"""
        key = self._normalize_search_cache_key(query)
        if key in self.web_search_cache:
            cached_item = self.web_search_cache[key]
            expires_at = cached_item.get("expires_at")
            if isinstance(expires_at, datetime):
                if datetime.now() <= expires_at:
                    return cached_item.get("data")
                del self.web_search_cache[key]
                return None

            if datetime.now() - cached_item['timestamp'] < timedelta(hours=6):
                return cached_item['data']
            del self.web_search_cache[key]
        return None

    def set_web_search_cache(self, query: str, data: str, time_sensitive: bool = False):
        """Set web search cache."""
        key = self._normalize_search_cache_key(query)
        if len(self.web_search_cache) >= self.MAX_CACHE_SIZE:
            oldest_key = min(self.web_search_cache, key=lambda k: self.web_search_cache[k]['timestamp'])
            del self.web_search_cache[oldest_key]

        now = datetime.now()
        ttl_seconds = self.search_time_sensitive_cache_ttl_seconds if time_sensitive else self.search_general_cache_ttl_seconds
        self.web_search_cache[key] = {
            'data': data,
            'timestamp': now,
            'expires_at': now + timedelta(seconds=ttl_seconds),
            'ttl_seconds': ttl_seconds,
            'time_sensitive': time_sensitive,
        }
    
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
        raw = os.getenv("GOOGLE_SEARCH_STREAMS", "1").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 1
        return max(1, min(2, value))

    def _load_fallback_provider_limit(self) -> int:
        raw = os.getenv("SEARCH_FALLBACK_PROVIDER_LIMIT", "2").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 2
        return max(1, min(3, value))

    def _load_intent_batch_size(self) -> int:
        raw = os.getenv("SEARCH_INTENT_BATCH_MAX", "3").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 3
        return max(2, min(3, value))

    def _load_search_web_mode(self) -> str:
        mode = (os.getenv("SEARCH_WEB_MODE", "grounded") or "grounded").strip().lower()
        if mode not in {"grounded", "fast"}:
            return "grounded"
        return mode

    def _load_search_grounded_top_links(self) -> int:
        raw = os.getenv("SEARCH_GROUNDED_TOP_LINKS", "3").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 3
        return max(2, min(5, value))

    def _load_search_top_results_limit(self) -> int:
        raw = os.getenv("SEARCH_TOP_RESULTS_LIMIT", "5").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 5
        return max(3, min(5, value))

    def _load_min_quality_sources(self) -> int:
        raw = os.getenv("SEARCH_MIN_QUALITY_SOURCES", os.getenv("SEARCH_MIN_REPUTABLE_SOURCES", "1")).strip()
        try:
            value = int(raw)
        except ValueError:
            value = 1
        return max(1, min(5, value))

    def _load_time_sensitive_min_quality_sources(self) -> int:
        raw = os.getenv(
            "SEARCH_TIME_SENSITIVE_MIN_QUALITY_SOURCES",
            os.getenv("SEARCH_TIME_SENSITIVE_MIN_REPUTABLE_SOURCES", "2"),
        ).strip()
        try:
            value = int(raw)
        except ValueError:
            value = 2
        return max(self.min_quality_sources, min(6, value))

    def _load_deep_read_top_links(self) -> int:
        raw = os.getenv("SEARCH_DEEP_READ_TOP_LINKS", "2").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 2
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

    def _load_search_semantic_cache_enabled(self) -> bool:
        return (os.getenv("SEARCH_SEMANTIC_CACHE_ENABLED", "true") or "true").strip().lower() in {"1", "true", "yes", "on"}

    def _load_search_general_cache_ttl_seconds(self) -> int:
        raw = os.getenv("SEARCH_GENERAL_CACHE_TTL_SEC", "21600").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 21600
        return max(300, min(43200, value))

    def _load_search_time_sensitive_cache_ttl_seconds(self) -> int:
        raw = os.getenv("SEARCH_TIME_SENSITIVE_CACHE_TTL_SEC", "1800").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 1800
        return max(120, min(self.search_general_cache_ttl_seconds, value))

    def _load_search_failed_query_cooldown_seconds(self) -> int:
        raw = os.getenv("SEARCH_FAILED_QUERY_COOLDOWN_SEC", "15").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 15
        return max(0, min(120, value))

    def _load_search_empty_evidence_cache_ttl_seconds(self) -> int:
        raw = os.getenv("SEARCH_EMPTY_EVIDENCE_CACHE_TTL_SEC", "600").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 600
        return max(60, min(7200, value))

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

    def _organization_domain(self, domain: str) -> str:
        d = (domain or "").strip().lower()
        if not d:
            return ""
        labels = [x for x in d.split(".") if x]
        if len(labels) < 2:
            return d

        if len(labels) >= 3 and ".".join(labels[-2:]) in {"com.vn", "gov.vn", "org.vn", "edu.vn", "net.vn"}:
            return ".".join(labels[-3:])

        return ".".join(labels[-2:])

    def _normalize_query_tokens(self, text: str) -> List[str]:
        normalized = unicodedata.normalize("NFKD", (text or "").lower())
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
        tokens = [t for t in normalized.split() if len(t) > 2]
        return tokens

    def _normalize_text_for_match(self, text: str) -> str:
        normalized = unicodedata.normalize("NFKD", (text or "").lower())
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def _query_overlap_count(self, query: str, text: str) -> int:
        q_tokens = set(self._normalize_query_tokens(query))
        if not q_tokens:
            return 0
        t_tokens = set(self._normalize_query_tokens(text))
        return len(q_tokens.intersection(t_tokens))

    def _query_coverage_score(self, query: str, text: str) -> float:
        q_tokens = self._normalize_query_tokens(query)
        if not q_tokens:
            return 0.0

        normalized_text = self._normalize_text_for_match(text)
        text_tokens = set(normalized_text.split())
        unique_query_tokens = list(dict.fromkeys(q_tokens))

        token_hits = sum(1 for token in unique_query_tokens if token in text_tokens)
        token_ratio = token_hits / len(unique_query_tokens)

        score = 0.0
        if token_ratio >= 0.9:
            score += 1.45
        elif token_ratio >= 0.75:
            score += 1.1
        elif token_ratio >= 0.55:
            score += 0.8
        elif token_ratio >= 0.35:
            score += 0.45
        elif token_ratio > 0:
            score += 0.2

        phrase_hits = 0
        phrase_total = 0
        max_n = min(4, len(q_tokens))
        padded_text = f" {normalized_text} "

        for n in range(max_n, 1, -1):
            for i in range(0, len(q_tokens) - n + 1):
                phrase = " ".join(q_tokens[i:i + n]).strip()
                if len(phrase) < 7:
                    continue
                phrase_total += 1
                if f" {phrase} " in padded_text:
                    phrase_hits += 1

        if phrase_total > 0:
            phrase_ratio = phrase_hits / phrase_total
            if phrase_ratio >= 0.5:
                score += 1.25
            elif phrase_ratio >= 0.3:
                score += 0.85
            elif phrase_hits > 0:
                score += 0.45

        if phrase_hits > 0 and token_ratio >= 0.6:
            score += 0.35

        return score

    def _dynamic_reputation_score(self, topic: str, query: str, record: Dict[str, str]) -> float:
        domain = (record.get("domain") or "").strip().lower()
        title = record.get("title") or ""
        snippet = record.get("snippet") or ""
        evidence = record.get("evidence") or ""

        score = 0.0

        score += self._query_coverage_score(query, f"{title} {snippet}")
        if evidence:
            score += 0.75 * self._query_coverage_score(query, f"{title} {evidence}")

        overlap_snippet = self._query_overlap_count(query, f"{title} {snippet}")
        if overlap_snippet >= 4:
            score += 1.0
        elif overlap_snippet == 3:
            score += 0.75
        elif overlap_snippet == 2:
            score += 0.5
        elif overlap_snippet == 1:
            score += 0.2

        if evidence:
            overlap_evidence = self._query_overlap_count(query, f"{title} {evidence}")
            if overlap_evidence >= 3:
                score += 0.75
            elif overlap_evidence == 2:
                score += 0.45
            elif overlap_evidence == 1:
                score += 0.2

        snippet_len = len(snippet.strip())
        if snippet_len >= 80:
            score += 0.3
        if snippet_len >= 140:
            score += 0.25

        evidence_len = len(evidence.strip())
        if evidence_len >= 180:
            score += 0.75

        if any(tag in domain for tag in [".gov", ".edu", ".ac.", ".int", "gov.vn", "edu.vn"]):
            score += 0.35

        title_match = any(token for token in re.findall(r"\w+", query.lower()) if len(token) > 3 and token in title.lower())
        if title_match:
            score += 0.35

        return score

    def _is_quality_record(self, topic: str, query: str, record: Dict[str, str]) -> bool:
        _ = topic
        dynamic_score = self._dynamic_reputation_score(topic, query, record)

        threshold = 2.25
        if self.search_web_mode == "grounded" and len((record.get("evidence") or "").strip()) >= 160:
            threshold -= 0.2
        if len((record.get("snippet") or "").strip()) >= 120:
            threshold -= 0.1

        return dynamic_score >= threshold

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

    def _is_time_sensitive_query(self, query: str) -> bool:
        q = self._normalize_text_for_match(query)
        markers = [
            "latest", "new", "current", "today", "now", "update", "moi", "hien tai", "hom nay", "vua",
            "patch", "version", "banner", "gia xang", "ron95", "diesel", "fuel", "endfield"
        ]
        return any(m in q for m in markers)

    def _required_quality_sources(self, query: str) -> int:
        return self.time_sensitive_min_quality_sources if self._is_time_sensitive_query(query) else self.min_quality_sources

    def _split_multi_intents(self, query: str) -> List[str]:
        base = (query or "").strip()
        if not base:
            return []

        parts = re.split(r"\s*(?:\n+|;|\?|\.)\s*", base, flags=re.IGNORECASE)
        intents = [p.strip() for p in parts if len(p.strip()) > 2]
        if not intents:
            return [base]

        if len(intents) == 1:
            return intents

        if any(len(intent) < 14 for intent in intents):
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
        title = (record.get("title") or "").lower()
        snippet = (record.get("snippet") or "").lower()
        q = (query or "").lower()

        score = self._dynamic_reputation_score(topic, query, record)

        if any(token for token in re.findall(r"\w+", q) if len(token) > 3 and token in f"{title} {snippet}"):
            score += 1.1

        provider = (record.get("provider") or "").lower()
        if provider == "duckduckgo":
            score += 0.4

        if len(snippet) > 120:
            score += 0.35

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
        raw_eq = (equation_str or "").strip()
        if not raw_eq:
            return json.dumps({
                "equation": equation_str,
                "result": "Lỗi biểu thức: Biểu thức rỗng.",
                "success": False
            }, ensure_ascii=False)

        cleaned_eq = raw_eq.strip().lower().replace(',', '.')
        cleaned_eq = cleaned_eq.replace('×', '*').replace('·', '*').replace('÷', '/')
        cleaned_eq = cleaned_eq.replace('−', '-')
        if cleaned_eq.endswith('='):
            cleaned_eq = cleaned_eq[:-1].strip()
        if '=' in cleaned_eq:
            cleaned_eq = cleaned_eq.split('=', 1)[1].strip()

        transformations = standard_transformations + (
            implicit_multiplication_application,
            convert_xor,
        )
        local_dict = {
            "sin": sp.sin,
            "cos": sp.cos,
            "tan": sp.tan,
            "asin": sp.asin,
            "acos": sp.acos,
            "atan": sp.atan,
            "sinh": sp.sinh,
            "cosh": sp.cosh,
            "tanh": sp.tanh,
            "log": sp.log,
            "ln": sp.log,
            "exp": sp.exp,
            "sqrt": sp.sqrt,
            "pi": sp.pi,
            "e": sp.E,
            "diff": sp.diff,
            "integrate": sp.integrate,
            "limit": sp.limit,
            "simplify": sp.simplify,
        }

        try:
            expr = parse_expr(
                cleaned_eq,
                local_dict=local_dict,
                transformations=transformations,
                evaluate=True,
            )

            if hasattr(expr, "doit"):
                expr = expr.doit()

            if getattr(expr, "free_symbols", set()):
                result = sp.simplify(expr)
            else:
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

        start_ts = datetime.now().timestamp()
        vision_alias = await self._resolve_router_model_alias_for_vision()
        vision_model_id = self.api_router.get_model_id(vision_alias)
        attempt_budget = max(1, min(5, len(GEMINI_API_KEYS) if GEMINI_API_KEYS else 1))
        last_error = ""
        try:
            image_bytes = await asyncio.to_thread(lambda: requests.get(image_url, timeout=12).content)
            if not image_bytes:
                return "Lỗi: Không tải được dữ liệu hình ảnh từ URL."

            if len(image_bytes) > self.MAX_FILE_SIZE_BYTES:
                return "Lỗi: Ảnh vượt quá giới hạn 20MB cho inline image understanding."

            mime_type = self._guess_mime_type(image_url)
            image_part = genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

            # Require quota before calling API (using tpm limit)
            quota_ok = await self.api_router.acquire_gemini_quota(question, 2000, model_alias=vision_alias, image_count=1)
            if not quota_ok:
                return "⚠️ Hệ thống đang quá tải (vượt giới hạn truy vấn ảnh), vui lòng thử lại sau vài giây."

            for attempt in range(1, attempt_budget + 1):
                reservation = await self.api_router.get_next_key_for_model_reservation(vision_alias)
                api_key = (reservation or {}).get("key") or self._next_gemini_api_key()
                if not api_key:
                    break

                key_alias = f"...{api_key[-4:]}" if len(api_key) >= 4 else "<short>"
                try:
                    # Count image calls into shared key rotation/quota accounting.
                    if reservation:
                        self.api_router.commit_key_usage(reservation)

                    client = genai.Client(api_key=api_key)
                    response = await asyncio.to_thread(
                        client.models.generate_content,
                        model=vision_model_id,
                        contents=[image_part, question],
                    )

                    final_result = (getattr(response, "text", "") or "").strip()
                    if not final_result:
                        final_result = "Không thể nhận diện nội dung ảnh rõ ràng từ truy vấn này."

                    self._invalid_tool_keys.discard(api_key)
                    self._tool_key_cooldowns.pop(api_key, None)
                    self.set_image_recognition_cache(image_url, question, final_result)
                    latency_ms = int((datetime.now().timestamp() - start_ts) * 1000)
                    self.logger.info(
                        f"AB_METRIC image_tool success=1 latency_ms={latency_ms} bytes={len(image_bytes)} "
                        f"model={vision_model_id} attempt={attempt}/{attempt_budget} key={key_alias} alias={vision_alias}"
                    )
                    return final_result
                except Exception as attempt_error:
                    error_text = str(attempt_error)
                    lowered = error_text.lower()
                    last_error = error_text

                    if any(token in lowered for token in ["api key not found", "api_key_invalid", "invalid api key", "permission denied"]):
                        self._invalid_tool_keys.add(api_key)
                        if reservation:
                            self.api_router.mark_key_exhausted(
                                api_key,
                                reservation.get("model_alias", vision_alias),
                                pool=reservation.get("pool", "main"),
                                counter_key=reservation.get("counter_key"),
                            )
                    elif any(token in lowered for token in ["429", "resource_exhausted", "quota", "rate limit"]):
                        self._tool_key_cooldowns[api_key] = time.time() + 60
                        if reservation:
                            self.api_router.mark_key_cooldown(
                                api_key,
                                reservation.get("model_alias", vision_alias),
                                60,
                                pool=reservation.get("pool", "main"),
                                counter_key=reservation.get("counter_key"),
                            )

                    if attempt >= attempt_budget:
                        raise
                    continue
        except Exception as e:
            error_text = str(e)

            latency_ms = int((datetime.now().timestamp() - start_ts) * 1000)
            self.logger.warning(
                f"AB_METRIC image_tool success=0 latency_ms={latency_ms} "
                f"attempts={attempt_budget} model={vision_model_id} alias={vision_alias} "
                f"error={(last_error or error_text)[:180]}"
            )
            return f"Đã xảy ra lỗi khi xử lý hình ảnh bằng Gemini: {last_error or e}"
    
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

    def _count_quality_sources(self, records: List[Dict[str, str]], topic: str, query: str = "") -> int:
        quality_domains = set()
        for rec in records:
            domain = rec.get("domain", "")
            if self._is_quality_record(topic, query, rec):
                quality_domains.add(self._organization_domain(domain) or domain)
        return len(quality_domains)

    def _is_search_result_sufficient(self, records: List[Dict[str, str]], topic: str, query: str, required_sources: int, min_chars: int = 220) -> bool:
        if not records:
            return False

        quality_count = self._count_quality_sources(records, topic, query)
        top_window = records[:self.search_top_results_limit]
        total_chars = sum(len((x.get("snippet") or "").strip()) for x in top_window)
        return quality_count >= required_sources and total_chars >= min_chars

    def _extract_main_text(self, html_text: str) -> str:
        text = html_text or ""
        text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<noscript[\s\S]*?</noscript>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<(svg|form|button)[\s\S]*?</\1>", " ", text, flags=re.IGNORECASE)

        article_match = re.search(r"<(article|main)[^>]*>([\s\S]*?)</\1>", text, flags=re.IGNORECASE)
        if article_match:
            text = article_match.group(2)

        for block_tag in ("header", "footer", "nav", "aside"):
            text = re.sub(rf"<{block_tag}[^>]*>[\s\S]*?</{block_tag}>", " ", text, flags=re.IGNORECASE)

        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\b(cookie policy|accept cookies|subscribe|advertisement|all rights reserved)\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _get_deep_read_cache(self, url: str) -> Optional[str]:
        item = self.deep_read_cache.get(url)
        if not item:
            return None

        ttl_seconds = int(item.get("ttl_seconds", 7200))
        if datetime.now() - item["timestamp"] > timedelta(seconds=ttl_seconds):
            del self.deep_read_cache[url]
            return None

        return item.get("text", "")

    def _set_deep_read_cache(self, url: str, text: str, ttl_seconds: int = 7200):
        self.deep_read_cache[url] = {
            "text": text,
            "timestamp": datetime.now(),
            "ttl_seconds": max(60, ttl_seconds),
        }

    async def _fetch_page_evidence(self, url: str) -> str:
        cached = self._get_deep_read_cache(url)
        if cached is not None:
            return cached

        def _fetch_once(timeout_sec: int) -> str:
            headers = {
                "User-Agent": "Mozilla/5.0 (ChadGibitiBot/1.0)",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.8,vi;q=0.7",
            }
            response = requests.get(url, headers=headers, timeout=timeout_sec)
            if response.status_code != 200 or not response.text:
                return ""

            if not response.encoding:
                response.encoding = response.apparent_encoding or "utf-8"

            parsed = self._extract_main_text(response.text)
            if len(parsed) < 120:
                return ""
            return parsed[:self.deep_read_max_chars].strip()

        for attempt in range(2):
            timeout_sec = 6 + (attempt * 2)
            try:
                text = await asyncio.to_thread(_fetch_once, timeout_sec)
                if text:
                    self._set_deep_read_cache(url, text, ttl_seconds=7200)
                    return text
            except Exception:
                continue

        self._set_deep_read_cache(url, "", ttl_seconds=self.search_empty_evidence_cache_ttl_seconds)
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

    def _domain_diversify_records(self, records: List[Dict[str, str]], limit: int, enforce_diversity: bool) -> List[Dict[str, str]]:
        if not enforce_diversity:
            return records[:limit]

        diverse: List[Dict[str, str]] = []
        used_domains: Set[str] = set()

        for rec in records:
            domain = (rec.get("domain") or "").strip().lower()
            org_domain = self._organization_domain(domain) or domain
            if not domain or org_domain in used_domains:
                continue
            diverse.append(rec)
            used_domains.add(org_domain)
            if len(diverse) >= limit:
                return diverse

        if len(diverse) < limit:
            for rec in records:
                if rec in diverse:
                    continue
                diverse.append(rec)
                if len(diverse) >= limit:
                    break

        return diverse[:limit]

    def _format_final_search_result(self, topic: str, query: str, ranked_records: List[Dict[str, str]], required_sources: int) -> str:
        top_lines = []
        additional_lines = []
        quality_domains = set()
        display_records = self._domain_diversify_records(ranked_records, self.search_top_results_limit, True)

        top_target = min(self.search_top_results_limit, max(required_sources, 3))
        for idx, rec in enumerate(display_records):
            line = self._format_source_line(rec)
            if idx < top_target:
                top_lines.append(line)
            else:
                additional_lines.append(line)

            if self._is_quality_record(topic, query, rec):
                domain = rec.get("domain", "")
                quality_domains.add(self._organization_domain(domain) or domain)

        deep_lines = []
        if self.search_web_mode == "grounded":
            for rec in display_records[:self.search_grounded_top_links]:
                evidence = rec.get("evidence", "")
                if not evidence:
                    continue
                title = rec.get("title") or "Không có tiêu đề"
                url = rec.get("url") or ""
                snippet = evidence[:360].strip()
                if snippet:
                    deep_lines.append(f"- {title} ([đọc nội dung](<{url}>)): {snippet}")

        parts = [
            f"### 🔍 [Chủ đề: {topic.upper()}] Kết quả cho '{query}':",
            f"- Mode: {self.search_web_mode}",
            f"- Top results: {len(display_records)}",
            f"- Grounded reads: {self.search_grounded_top_links if self.search_web_mode == 'grounded' else 0}",
            f"- Required quality sources: {required_sources}",
            f"- Quality sources found: {len(quality_domains)}",
            "",
            "**Top ranked sources:**",
            "\n".join(top_lines) if top_lines else "(Không có nguồn top phù hợp từ lượt tìm kiếm này)",
            "",
            "**Additional corroborating sources:**",
            "\n".join(additional_lines) if additional_lines else "(Không có nguồn bổ sung)",
        ]

        if self.search_web_mode == "grounded":
            if deep_lines:
                parts.extend(["", "**Evidence excerpts (grounded read):**", "\n".join(deep_lines)])
            else:
                parts.extend([
                    "",
                    "⚠️ Grounded read chưa lấy được đoạn evidence rõ ràng; kết quả đang dựa nhiều vào snippet từ nguồn đã truy xuất.",
                ])

        return "\n".join(parts).strip()

    async def _search_single_intent(self, q_sub: str, force_fallback: bool = False) -> str:
        selected_topic = self._classify_topic(q_sub)
        q1 = q_sub.strip()

        self.logger.info(f"Classified: {selected_topic.upper()}. Searching for: '{q_sub}'")
        self.logger.info(f"Primary query: Q1='{q1}'")

        primary_queries = [q1]

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
        required_sources = self._required_quality_sources(q_sub)
        has_enough = self._is_search_result_sufficient(records, selected_topic, q_sub, required_sources)

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

        if self.search_web_mode == "grounded":
            top_records = ranked[:self.search_grounded_top_links]
            if top_records:
                evidence_results = await asyncio.gather(
                    *(self._fetch_page_evidence(rec.get("url", "")) for rec in top_records),
                    return_exceptions=True,
                )
                for rec, evidence in zip(top_records, evidence_results):
                    rec["evidence"] = evidence if isinstance(evidence, str) else ""

        self.logger.info(
            f"AB_METRIC search_query topic={selected_topic} primary_success={1 if records else 0} "
            f"fallback_trigger={1 if should_fallback else 0} fallback_reason={fallback_reason}"
        )

        final = self._format_final_search_result(selected_topic, q_sub, ranked, required_sources)
        quality_count = self._count_quality_sources(ranked, selected_topic, q_sub)

        if quality_count < required_sources:
            final += "\n\n⚠️ Chưa đủ nguồn chất lượng theo ngưỡng cho truy vấn này; nên xem kết quả như thông tin tham khảo."
        return final

    async def _execute_search_pipeline(self, clean_query: str, force_fallback: bool) -> str:
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

        return "\n\n".join(final_sections).strip() if final_sections else ""

    async def run_search_apis(self, query: str, mode: str = "general"):
        raw_query = query or ""
        force_fallback = "[FORCE FALLBACK]" in raw_query.upper()
        clean_query = raw_query.replace("[FORCE FALLBACK]", "").strip()
        if not clean_query:
            return ""

        cache_key = f"{mode}|{clean_query}"
        normalized_key = self._normalize_search_cache_key(cache_key)
        time_sensitive = self._is_time_sensitive_query(clean_query)
        bypass_cache = time_sensitive and not force_fallback

        inflight_task: Optional[asyncio.Task] = None
        async with self.cache_lock:
            cached_result = None if (force_fallback or bypass_cache) else self.get_web_search_cache(cache_key)
            if not cached_result:
                inflight_task = self.inflight_search_tasks.get(normalized_key)

        if cached_result:
            self.logger.info(f"Web search result from cache for query: {clean_query[:50]}...")
            return cached_result

        if inflight_task:
            self.logger.info(f"Web search joined inflight task for key={normalized_key[:80]}")
            return await inflight_task

        if not force_fallback and not time_sensitive and self.search_failed_query_cooldown_seconds > 0:
            async with self.cache_lock:
                cooldown_until = self.failed_search_cooldowns.get(normalized_key, 0)
            if cooldown_until > time.time():
                self.logger.info(f"Search cooldown active for key={normalized_key[:80]}")
                return "⚠️ Nguồn tìm kiếm đang tạm quá tải, vui lòng thử lại sau ít giây."

        task = asyncio.create_task(self._execute_search_pipeline(clean_query, force_fallback))
        async with self.cache_lock:
            self.inflight_search_tasks[normalized_key] = task

        try:
            output = await task
            if not output and time_sensitive and not force_fallback:
                absolute_date = datetime.now().strftime("%d/%m/%Y")
                forced_query = f"{clean_query} ngay {absolute_date}"
                self.logger.info(
                    f"Time-sensitive query produced empty result. Retrying forced fallback query='{forced_query[:80]}'."
                )
                output = await self._execute_search_pipeline(forced_query, True)

            if output:
                async with self.cache_lock:
                    if not bypass_cache:
                        self.set_web_search_cache(cache_key, output, time_sensitive=time_sensitive)
                    self.failed_search_cooldowns.pop(normalized_key, None)
                if bypass_cache:
                    self.logger.info(f"Completed fresh search for time-sensitive query='{clean_query[:60]}'.")
                else:
                    self.logger.info(f"Completed search for query='{clean_query[:60]}' and cached.")
                return output

            if not time_sensitive and self.search_failed_query_cooldown_seconds > 0:
                async with self.cache_lock:
                    self.failed_search_cooldowns[normalized_key] = time.time() + self.search_failed_query_cooldown_seconds
            self.logger.error("All search providers failed for all intents.")
            return ""
        except Exception as e:
            if not time_sensitive and self.search_failed_query_cooldown_seconds > 0:
                async with self.cache_lock:
                    self.failed_search_cooldowns[normalized_key] = time.time() + self.search_failed_query_cooldown_seconds
            self.logger.error(f"Search pipeline exception: {e}")
            return ""
        finally:
            async with self.cache_lock:
                current = self.inflight_search_tasks.get(normalized_key)
                if current is task:
                    del self.inflight_search_tasks[normalized_key]
    
    async def call_tool(self, function_call, user_id: str):
        """Dispatch tool calls to appropriate handlers."""
        name = function_call.name
        args = dict(function_call.args) if function_call.args else {}
        self.logger.info(f"TOOL CALLED: {name} | Args: {args} | User: {user_id}")
        
        try:
            if name == "web_search":
                query = args.get("query", "")
                result = await self.run_search_apis(query, "general")
                try:
                    if self.db_repo is not None:
                        await self.db_repo.log_web_search(user_id, query, str(result)[:2000])
                except Exception as e:
                    self.logger.error(f"Error logging web search to DB: {e}")
                return result
            
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

            elif name == "delete_note":
                note_id = (args.get("note_id") or "").strip()
                if not note_id:
                    return "Lỗi: 'note_id' không được rỗng."
                if not self.note_mgr:
                    self.logger.error("delete_note called but NoteManager is not configured")
                    return "Lỗi hệ thống: memory manager chưa sẵn sàng."
                return await self.note_mgr.delete_note_from_db(user_id, note_id)

            elif name == "image_recognition":
                image_url = args.get("image_url")
                question = args.get("question")
                if not image_url or not question:
                    return "Lỗi: 'image_url' và 'question' không được rỗng cho image_recognition."
                return await self.run_image_recognition(image_url, question)

            elif name == "manage_user_role":
                target_user_id = (args.get("target_user_id") or "").strip()
                action = (args.get("action") or "").strip()
                role = (args.get("role") or "").strip()

                if not target_user_id or not action or not role:
                    return "Lỗi: Thiếu tham số bắt buộc 'target_user_id', 'action' hoặc 'role'."

                if self.db_repo is None:
                    return "Lỗi hệ thống: Kết nối cơ sở dữ liệu chưa sẵn sàng."

                # 1. Xác thực quyền Admin của người đang chat (user_id)
                is_caller_admin = (user_id in config.ADMIN_USER_IDS) or (await self.db_repo.is_admin_user(user_id))
                if not is_caller_admin:
                    return "❌ Lỗi: Bạn không phải Admin hệ thống, không có quyền thăng chức hay hạ chức người khác!"

                # 2. Thực hiện hành động thăng/hạ chức tương ứng
                if action == "add":
                    if role == "moderator":
                        await self.db_repo.add_moderator_user(target_user_id)
                        return f"🎉 Thăng chức thành công người dùng {target_user_id} làm Moderator!"
                    elif role == "admin":
                        await self.db_repo.add_admin_user(target_user_id)
                        return f"👑 Thăng chức thành công người dùng {target_user_id} làm Admin!"
                    elif role == "premium":
                        await self.db_repo.add_premium_user(target_user_id)
                        return f"✨ Kích hoạt Premium thành công cho người dùng {target_user_id}!"
                elif action == "remove":
                    if role == "moderator":
                        await self.db_repo.remove_moderator_user(target_user_id)
                        return f"✅ Đã hạ chức người dùng {target_user_id} khỏi vai trò Moderator."
                    elif role == "admin":
                        # Không cho phép demote tài khoản static trong .env
                        if target_user_id in config.ADMIN_USER_IDS:
                            return "❌ Lỗi: Không thể hạ chức Admin gốc cấu hình tĩnh trong .env!"
                        await self.db_repo.remove_admin_user(target_user_id)
                        return f"✅ Đã hạ chức người dùng {target_user_id} khỏi vai trò Admin."
                    elif role == "premium":
                        await self.db_repo.remove_premium_user(target_user_id)
                        return f"✅ Đã hủy Premium của người dùng {target_user_id}."
                return "Lỗi: Hành động hoặc vai trò không hợp lệ."

            else:
                return "Tool không tồn tại!"
        
        except Exception as e:
            self.logger.error(f"Tool {name} error: {e}")
            return f"Lỗi tool: {str(e)}"
