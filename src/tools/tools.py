import asyncio
import json
import re
import os
import random
from datetime import datetime, timedelta
import aiofiles
import requests
import sympy as sp
from google.generativeai.types import Tool, FunctionDeclaration
import serpapi
from tavily import TavilyClient
import exa_py
import aiohttp

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.core.config import (
    logger,
    WEATHER_API_KEY,
    CITY,
    WEATHER_CACHE_PATH,
    SERPAPI_API_KEY,
    TAVILY_API_KEY,
    EXA_API_KEY,
    GOOGLE_CSE_ID,
    GOOGLE_CSE_API_KEY,
    GOOGLE_CSE_ID_1,
    GOOGLE_CSE_API_KEY_1,
    GOOGLE_CSE_ID_2,
    GOOGLE_CSE_API_KEY_2,
    HF_TOKEN
)
from dotenv import load_dotenv

load_dotenv()


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
        self.search_api_counter = 0
        self.search_lock = asyncio.Lock()
        self.cache_lock = asyncio.Lock()
        self.search_cache = {}
    
    def get_all_tools(self):
        """Return all tool definitions for Gemini."""
        return [
            Tool(function_declarations=[
                FunctionDeclaration(
                    name="web_search",
                    description=(
                        "Tìm kiếm thông tin cập nhật, sự kiện mới, tin tức, "
                        "dữ liệu thực tế không có trong kiến thức của AI, "
                        "hoặc để xác minh thông tin. KHÔNG DÙNG cho các tác vụ tính toán, "
                        "dịch thuật, tóm tắt, viết lại, hoặc các câu hỏi không cần dữ liệu mới."
                    ),
                )
            ]),
            Tool(function_declarations=[
                FunctionDeclaration(
                    name="get_weather",
                    description="Lấy thông tin thời tiết hiện tại cho một thành phố cụ thể.",
                    parameters={
                        "type": "object",
                        "properties": {"city": {"type": "string", "description": "Tên thành phố, ví dụ: 'Hanoi', 'Tokyo'."}},
                        "required": ["city"]
                    }
                )
            ]),
            Tool(function_declarations=[
                FunctionDeclaration(
                    name="calculate",
                    description="Giải các bài toán số học hoặc biểu thức phức tạp, bao gồm các hàm lượng giác, logarit, và đại số.",
                    parameters={
                        "type": "object",
                        "properties": {"equation": {"type": "string", "description": "Biểu thức toán học dưới dạng string, ví dụ: 'sin(pi/2) + 2*x'."}},
                        "required": ["equation"]
                    }
                )
            ]),
            Tool(function_declarations=[
                FunctionDeclaration(
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
            Tool(function_declarations=[
                FunctionDeclaration(
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
            Tool(function_declarations=[
                FunctionDeclaration(
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
        """Run image recognition using Hugging Face API."""
        cached_result = self.get_image_recognition_cache(image_url, question)
        if cached_result:
            self.logger.info(f"Image recognition result from cache for URL: {image_url}, Question: {question[:30]}...")
            return cached_result
        
        if not HF_TOKEN:
            return "Lỗi: Không tìm thấy Hugging Face API token. Vui lòng cấu hình HF_TOKEN trong config.py."
        
        API_URL = "https://router.huggingface.co/v1/chat/completions"
        headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}
        
        MAX_RETRIES = 5
        INITIAL_BACKOFF_DELAY = 5
        
        for attempt in range(MAX_RETRIES):
            try:
                async with aiohttp.ClientSession() as session:
                    json_payload = {
                        "model": "Qwen/Qwen2.5-VL-7B-Instruct",
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "image_url", "image_url": {"url": image_url}},
                                    {"type": "text", "text": question}
                                ]
                            }
                        ],
                        "max_tokens": 300
                    }
                    
                    async with session.post(API_URL, headers=headers, json=json_payload) as response:
                        response.raise_for_status()
                        result = await response.json()
                        self.logger.info(f"HF Image Recognition raw result: {result}")
                        
                        if "choices" in result and result["choices"]:
                            generated_text = result["choices"][0]["message"]["content"]
                            assistant_tag = "<|im_start|>assistant\n"
                            if assistant_tag in generated_text:
                                final_result = generated_text.split(assistant_tag, 1)[1].strip()
                            else:
                                final_result = generated_text.strip()
                            
                            self.set_image_recognition_cache(image_url, question, final_result)
                            return final_result
                        
                        error_result = json.dumps(result, ensure_ascii=False)
                        self.set_image_recognition_cache(image_url, question, error_result)
                        return error_result
            
            except aiohttp.ClientResponseError as e:
                if e.status == 429:
                    delay = INITIAL_BACKOFF_DELAY * (2 ** attempt)
                    self.logger.warning(f"HF API rate limit (429). Retrying in {delay:.2f}s... (Attempt {attempt + 1}/{MAX_RETRIES})")
                    await asyncio.sleep(delay)
                else:
                    self.logger.error(f"HF API error ({e.status}): {e.message}")
                    return f"Lỗi từ dịch vụ nhận diện hình ảnh (mã {e.status}): {e.message}"
            except aiohttp.ClientError as e:
                self.logger.error(f"Connection error to HF API: {e}")
                return f"Lỗi kết nối đến dịch vụ nhận diện hình ảnh: {e}"
            except Exception as e:
                self.logger.error(f"Unknown error in image recognition: {e}")
                return f"Đã xảy ra lỗi không mong muốn khi xử lý hình ảnh: {e}"
        
        return f"Lỗi: Đã thử lại {MAX_RETRIES} lần nhưng không thể kết nối đến dịch vụ nhận diện hình ảnh do giới hạn rate."
    
    async def _search_cse(self, query: str, cse_id: str, api_key: str, index: int = 0, start_idx: int = 1, force_lang: str = None):
        """Search using Google Custom Search Engine."""
        if not cse_id or not api_key:
            self.logger.warning(f"CSE{index} không được cấu hình ID/API key.")
            return ""
        
        params = {
            "key": api_key,
            "cx": cse_id,
            "q": query,
            "num": 3,
            "start": start_idx,
            "gl": "vn",
            "hl": force_lang or ("en" if re.search(r"[a-zA-Z]{4,}", query) else "vi"),
        }
        
        try:
            response = await asyncio.to_thread(
                requests.get,
                "https://www.googleapis.com/customsearch/v1",
                params=params,
                timeout=10,
            )
            data = response.json()
            
            if "items" not in data:
                self.logger.warning(f"CSE{index} không có kết quả hợp lệ cho query '{query[:60]}'")
                return ""
            
            relevant = []
            for item in data["items"][:3]:
                title = item.get("title", "Không có tiêu đề")
                snippet_raw = item.get("snippet", "")
                snippet = snippet_raw[:330] + "..." if len(snippet_raw) > 130 else snippet_raw
                link = item.get("link", "")
                if any(ad in link.lower() for ad in ["shopee", "lazada", "amazon", "tiki"]):
                    continue
                relevant.append(f"**{title}**: {snippet} (Nguồn: {link})")
            
            if relevant:
                self.logger.info(f"CSE{index} returned {len(relevant)} valid results.")
                return f"**Search CSE{index} (Dynamic):**\n" + "\n".join(relevant) + "\n\n[DÙNG ĐỂ TRẢ LỜI E-GIRL, KHÔNG LEAK NGUỒN]"
            return ""
        
        except Exception as e:
            self.logger.error(f"CSE{index} error calling API: {e}")
            return ""
    
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
        
        return "**Search SerpAPI (Dynamic):**\n" + "\n".join(relevant) + "\n\n[DÙNG ĐỂ TRẢ LỜI E-GIRL, KHÔNG LEAK NGUỒN]" if relevant else ""
    
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
        
        return "**Search Tavily (Dynamic):**\n" + "\n".join(relevant) + "\n\n[DÙNG ĐỂ TRẢ LỜI E-GIRL, KHÔNG LEAK NGUỒN]" if relevant else ""
    
    async def _search_exa(self, query: str):
        """Search using Exa API."""
        if not EXA_API_KEY:
            return ""
        
        exa = exa_py.Exa(api_key=EXA_API_KEY)
        params = {
            "query": query,
            "num_results": 3,
            "use_autoprompt": True,
            "type": "neural"
        }
        
        results = await asyncio.to_thread(exa.search, **params)
        
        if not results.results:
            return ""
        
        relevant = []
        for item in results.results[:3]:
            title = item.title or 'Không có tiêu đề'
            text = item.text or ''
            snippet = text[:330] + "..." if len(text) > 130 else text
            link = item.url
            if any(ad in link.lower() for ad in ['shopee', 'lazada', 'amazon', 'tiki']):
                continue
            relevant.append(f"**{title}**: {snippet} (Nguồn: {link})")
        
        return "**Search Exa.ai (Dynamic):**\n" + "\n".join(relevant) + "\n\n[DÙNG ĐỂ TRẢ LỜI E-GIRL, KHÔNG LEAK NGUỒN]" if relevant else ""
    
    async def _run_fallback_search(self, query: str):
        """Run fallback search using alternative APIs."""
        apis = ["SerpAPI", "Tavily", "Exa"]
        start_idx = self.search_api_counter % 3
        self.search_api_counter += 1
        
        for i in range(3):
            api_name = apis[(start_idx + i) % 3]
            try:
                if api_name == "SerpAPI" and SERPAPI_API_KEY:
                    result = await self._search_serpapi(query)
                elif api_name == "Tavily" and TAVILY_API_KEY:
                    result = await self._search_tavily(query)
                elif api_name == "Exa" and EXA_API_KEY:
                    result = await self._search_exa(query)
                else:
                    continue
                
                if result:
                    self.logger.info(f"Fallback {api_name} success for query '{query[:60]}'")
                    return result
                else:
                    self.logger.warning(f"Fallback {api_name} empty or error.")
            except Exception as e:
                self.logger.warning(f"Fallback {api_name} error: {e}")
        
        self.logger.error("All fallback APIs failed.")
        return ""
    
    async def run_search_apis(self, query: str, mode: str = "general"):
        """Run web search with CSE and fallback APIs."""
        cached_result = self.get_web_search_cache(query)
        if cached_result:
            self.logger.info(f"Web search result from cache for query: {query[:50]}...")
            return cached_result
        
        self.logger.info(f"CALLING 3x CSE SMART SEARCH for '{query}' (mode: {mode})")
        
        FORCE_FALLBACK_REQUEST = "[FORCE FALLBACK]" in query.upper()
        q_base = query.replace("[FORCE FALLBACK]", "").strip()
        
        sub_queries = []
        if " và " in q_base or " and " in q_base.lower() or "," in q_base:
            splitters = re.split(r"\s*(?:và|and|,)\s*", q_base, flags=re.IGNORECASE)
            sub_queries = [q.strip() for q in splitters if q.strip()]
        else:
            sub_queries = [q_base.strip()]
        
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
                random.shuffle(suffixes)
                
                q1 = q_sub.strip()
                q2 = f"{q1} {suffixes[0]} OR {suffixes[1]}" if len(suffixes) > 1 else q1
                q3 = f"{q1} {suffixes[2]} OR {suffixes[3]}" if len(suffixes) > 3 else q1
                
                fallback_q = f"{q_sub.strip()} {self.SEARCH_TOPICS['general']['suffixes'][0]} OR {self.SEARCH_TOPICS['general']['suffixes'][1]}"
                
                self.logger.info(f"Queries: Q1='{q1}', Q2='{q2}', Q3='{q3}'")
                
                cse0_task = asyncio.create_task(self._search_cse(q1, GOOGLE_CSE_ID, GOOGLE_CSE_API_KEY, 0, start_idx=1, force_lang="vi"))
                cse1_task = asyncio.create_task(self._search_cse(q2, GOOGLE_CSE_ID_1, GOOGLE_CSE_API_KEY_1, 1, start_idx=1, force_lang="en"))
                cse2_task = asyncio.create_task(self._search_cse(q3, GOOGLE_CSE_ID_2, GOOGLE_CSE_API_KEY_2, 2, start_idx=1, force_lang="en"))
                
                cse0_result, cse1_result, cse2_result = await asyncio.gather(
                    cse0_task, cse1_task, cse2_task, return_exceptions=True
                )
                
                def safe_result(r, name):
                    if isinstance(r, Exception):
                        self.logger.error(f"{name} error: {r}")
                        return ""
                    return r or ""
                
                cse0_result = safe_result(cse0_result, "CSE0")
                cse1_result = safe_result(cse1_result, "CSE1")
                cse2_result = safe_result(cse2_result, "CSE2")
                
                should_run_fallback = FORCE_FALLBACK_REQUEST or not (cse0_result or cse1_result or cse2_result)
                
                fallback_result = ""
                if should_run_fallback:
                    log_message = "AI requested [FORCE FALLBACK]" if FORCE_FALLBACK_REQUEST else "All CSE empty/error"
                    self.logger.warning(f"{log_message} → Running Fallback API.")
                    
                    fallback_result = await self._run_fallback_search(fallback_q)
                    if fallback_result:
                        self.logger.info(f"Fallback success.")
                    else:
                        self.logger.warning("Fallback failed.")
                
                parts = [str(x) for x in [cse0_result, cse1_result, cse2_result, fallback_result] if x]
                
                if parts:
                    merged = "\n\n".join(parts)
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
                    final_text = "\n".join(unique_lines)
                    final_results.append(f"### 🔍 [Chủ đề: {selected_topic.upper()}] Kết quả cho '{q_sub}':\n{final_text.strip()}")
        
        if final_results:
            combined_final_results = "\n\n".join(final_results)
            self.set_web_search_cache(query, combined_final_results)
            self.logger.info(f"Completed search for {len(final_results)} subqueries and cached.")
            return combined_final_results
        
        self.logger.error("All 3 CSE + fallback FAILED.")
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
