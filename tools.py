
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
from serpapi import GoogleSearch
from tavily import TavilyClient
import exa_py
from typing import Any, Dict, Tuple, Optional
from config import (
    logger,
    NOTE_PATH,
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
    GOOGLE_CSE_API_KEY_2
)

# --- ĐỊNH NGHĨA TOOLS CHO GEMINI ---
ALL_TOOLS = [
    Tool(function_declarations=[
        FunctionDeclaration(
            name="web_search",
            description=(
                "Tìm kiếm thông tin cập nhật (tin tức, giá cả, phiên bản game, sự kiện) sau năm 2024. "
                "Chỉ dùng khi kiến thức nội bộ của bạn đã lỗi thời so với ngày hiện tại. "
                "Yêu cầu TỰ DỊCH câu hỏi tiếng Việt của user thành một query tìm kiếm tiếng Anh TỐI ƯU."
            ),
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Câu hỏi bằng tiếng Anh"}},
                "required": ["query"]
            }
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
            description="Lưu một mẩu thông tin, ghi chú hoặc lời nhắc cụ thể theo yêu cầu của người dùng để bạn có thể truy cập lại sau.",
            parameters={
                "type": "object",
                "properties": {"note": {"type": "string", "description": "Nội dung ghi chú cần lưu."}},
                "required": ["note"]
            }
        )
    ]),
]

# === BỘ ĐIỀU PHỐI TOOL ===
async def call_tool(function_call: Any, user_id: str) -> str:
    name = function_call.name
    args = dict(function_call.args)
    logger.info(f"TOOL GỌI: {name} | Args: {args} | User: {user_id}")

    try:
        if name == "web_search":
            query = args.get("query", "")
            return await run_search_apis(query, "general")

        elif name == "get_weather":
            city = args.get("city", "Ho Chi Minh City")
            data = await get_weather(city)
            return json.dumps(data, ensure_ascii=False, indent=2)

        elif name == "calculate":
            eq = args.get("equation", "")
            return await asyncio.to_thread(run_calculator, eq)

        elif name == "save_note":
            note = args.get("note", "")
            return await save_note(note)

        else:
            return "Tool không tồn tại!"

    except Exception as e:
        logger.error(f"Tool {name} lỗi: {e}")
        return f"Lỗi tool: {str(e)}"

# --- BẢN ĐỒ TÊN THÀNH PHỐ ---
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

def normalize_city_name(city_query: str) -> Tuple[str, str]:
    if not city_query:
        return ("Ho Chi Minh City", "Thành phố Hồ Chí Minh")
    city_key = city_query.strip().lower()
    for k, v in CITY_NAME_MAP.items():
        if k in city_key:
            return v
    return (city_query, city_query.title())

weather_lock = asyncio.Lock()

async def get_weather(city_query: Optional[str] = None) -> Dict[str, Any]:
    async with weather_lock:
        if city_query is None:
            city_query = CITY or "Ho Chi Minh City"
        city_en, city_vi = normalize_city_name(city_query)

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
            logger.error(f"Weather API lỗi: {e}")
            fallback_data = {
                'current': f'Lỗi API, dùng mặc định: Mưa rào ở {city_vi}, 23-28°C.',
                'forecast': [f'Ngày mai: Nắng, 26°C', f'Ngày kia: Mưa, 25°C'] * 3,
                'timestamp': datetime.now().isoformat(),
                'city_vi': city_vi
            }
            with open(cache_path, 'w') as f:
                json.dump({'data': fallback_data, 'timestamp': datetime.now().isoformat()}, f)
            return fallback_data

def run_calculator(equation_str: str) -> str:
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

async def save_note(query: str) -> str:
    try:
        note = query.lower().replace("ghi note: ", "").replace("save note: ", "").strip()
        async with aiofiles.open(NOTE_PATH, 'a', encoding='utf-8') as f:
            await f.write(f"[{datetime.now().isoformat()}] {note}\n")
        return f"Đã ghi note: {note}"
    except PermissionError:
        return "Lỗi: Không có quyền ghi file notes.txt!"
    except Exception as e:
        return f"Lỗi ghi note: {str(e)}"

async def read_note() -> str:
    try:
        if not os.path.exists(NOTE_PATH):
            return "Chưa có note nào bro! Ghi note đi nha! 😎"
        async with aiofiles.open(NOTE_PATH, 'r', encoding='utf-8') as f:
            notes = await f.readlines()
        if not notes:
            return "Chưa có note nào bro! Ghi note đi nha! 😎"
        return "Danh sách note:\n" + "".join(notes[-5:])
    except PermissionError:
        return "Lỗi: Không có quyền đọc file notes.txt!"
    except Exception as e:
        return f"Lỗi đọc note: {str(e)}"

SEARCH_API_COUNTER = 0
SEARCH_LOCK = asyncio.Lock()
SEARCH_CACHE = {}
CACHE_LOCK = asyncio.Lock()

SEARCH_TOPICS = {
    # --- Core Topics (1-6) ---
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
    # --- Entertainment & Hobbies (7-13) ---
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
    # --- Lifestyle & Wellness (14-20) ---
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
    # --- Practical & Professional (21-27) ---
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
        "keywords": ['real estate', 'bất động sản', 'nhà đất', 'housing market', 'apartment', 'căn hộ', 'chung cư', 'giá nhà'],
        "suffixes": ["market trends", "how to buy", "investment tips", "apartment tour", "xu hướng thị trường", "kinh nghiệm mua nhà"]
    },
    "cryptocurrency_blockchain": {
        "keywords": ['crypto', 'bitcoin', 'ethereum', 'blockchain', 'nft', 'defi', 'web3', 'tiền ảo', 'tiền điện tử'],
        "suffixes": ["price prediction", "news", "how to buy", "wallet", "dự đoán giá", "tin tức crypto"]
    },
    # --- Local & Shopping (28-31) ---
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
    # --- Default ---
    "general": {
        "keywords": [],  # Default
        "suffixes": ["news", "latest", "update", "information", "tin tức", "thông tin", "mới nhất"]
    }
}

async def cached_search(key: str, func: Any, *args: Any) -> Any:
    async with CACHE_LOCK:
        if key in SEARCH_CACHE and datetime.now() - SEARCH_CACHE[key]['time'] < timedelta(hours=6):
            return SEARCH_CACHE[key]['result']
        result = await func(*args)
        SEARCH_CACHE[key] = {'result': result, 'time': datetime.now()}
        return result

async def run_search_apis(query: str, mode: str = "general") -> str:
    logger.info(f"CALLING 3x CSE SMART SEARCH for '{query}' (mode: {mode})")
    global SEARCH_API_COUNTER

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
        async with SEARCH_LOCK:
            # 1. Phân loại chủ đề
            query_lower = q_sub.lower()
            selected_topic = "general"
            for topic, data in SEARCH_TOPICS.items():
                if topic == "general":
                    continue
                if any(keyword in query_lower for keyword in data["keywords"]):
                    selected_topic = topic
                    break
            
            logger.info(f"Phân loại: {selected_topic.upper()}. Chạy search cho: '{q_sub}'")

            # 2. Tạo các truy vấn đa dạng dựa trên chủ đề
            suffixes = SEARCH_TOPICS[selected_topic]["suffixes"]
            random.shuffle(suffixes)
            
            q1 = q_sub.strip()
            q2 = f"{q1} {suffixes[0]} OR {suffixes[1]}" if len(suffixes) > 1 else q1
            q3 = f"{q1} {suffixes[2]} OR {suffixes[3]}" if len(suffixes) > 3 else q1
            
            # Fallback query in case the specialized ones fail
            fallback_q = f"{q_sub.strip()} {SEARCH_TOPICS['general']['suffixes'][0]} OR {SEARCH_TOPICS['general']['suffixes'][1]}"

            logger.info(f"Queries: Q1='{q1}', Q2='{q2}', Q3='{q3}'")

            # --- BẮT ĐẦU CHẠY SEARCH ---
            cse0_task = asyncio.create_task(_search_cse(q1, GOOGLE_CSE_ID, GOOGLE_CSE_API_KEY, 0, start_idx=1, force_lang="vi"))
            cse1_task = asyncio.create_task(_search_cse(q2, GOOGLE_CSE_ID_1, GOOGLE_CSE_API_KEY_1, 1, start_idx=1, force_lang="en"))
            cse2_task = asyncio.create_task(_search_cse(q3, GOOGLE_CSE_ID_2, GOOGLE_CSE_API_KEY_2, 2, start_idx=1, force_lang="en"))

            cse0_result, cse1_result, cse2_result = await asyncio.gather(
                cse0_task, cse1_task, cse2_task, return_exceptions=True
            )

            def safe_result(r, name):
                if isinstance(r, Exception):
                    logger.error(f"{name} lỗi: {r}")
                    return ""
                return r or ""

            cse0_result = safe_result(cse0_result, "CSE0")
            cse1_result = safe_result(cse1_result, "CSE1")
            cse2_result = safe_result(cse2_result, "CSE2")

            # --- LOGIC FALLBACK ---
            # If all CSE results are empty, or forced, run fallback
            should_run_fallback = FORCE_FALLBACK_REQUEST or not (cse0_result or cse1_result or cse2_result)
            
            fallback_result = ""
            if should_run_fallback:
                log_message = "AI yêu cầu [FORCE FALLBACK]" if FORCE_FALLBACK_REQUEST else "Tất cả CSE đều rỗng/lỗi"
                logger.warning(f"{log_message} → Chạy Fallback API.")
                
                # Use a more general query for fallback
                fallback_result = await _run_fallback_search(fallback_q)
                if fallback_result:
                    logger.info(f"Fallback thành công.")
                else:
                    logger.warning("Fallback thất bại.")

            # Combine results
            # Prioritize CSE results, but add fallback if it exists
            parts: list[str] = [str(x) for x in [cse0_result, cse1_result, cse2_result, fallback_result] if x]

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
        logger.info(f"Hoàn tất tìm kiếm {len(final_results)} subquery.")
        return "\n\n".join(final_results)

    logger.error("TẤT CẢ 3 CSE + fallback FAIL.")
    return ""

async def _search_cse(query: str, cse_id: str | None, api_key: str | None, index: int = 0, start_idx: int = 1, force_lang: str | None = None) -> str:
    if not cse_id or not api_key:
        logger.warning(f"CSE{index} chưa cấu hình ID/API key.")
        return ""

    params = {
        "key": api_key,
        "cx": cse_id,
        "q": query,
        "num": 3,
        "start": start_idx,
        "gl": "vn",
        # SỬA ĐỔI: Dùng force_lang nếu có, nếu không thì dùng logic cũ.
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
            logger.warning(f"CSE{index} không có kết quả hợp lệ cho query '{query[:60]}'")
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
            logger.info(f"CSE{index} trả về {len(relevant)} kết quả hợp lệ.")
            return f"**Search CSE{index} (Dynamic):**\n" + "\n".join(relevant) + "\n\n[DÙNG ĐỂ TRẢ LỜI E-GIRL, KHÔNG LEAK NGUỒN]"
        return ""

    except Exception as e:
        logger.error(f"CSE{index} lỗi khi gọi API: {e}")
        return ""

async def _run_fallback_search(query: str) -> str:
    apis = ["SerpAPI", "Tavily", "Exa"]
    global SEARCH_API_COUNTER
    start_idx = SEARCH_API_COUNTER % 3
    SEARCH_API_COUNTER += 1

    for i in range(3):
        api_name = apis[(start_idx + i) % 3]
        try:
            if api_name == "SerpAPI" and SERPAPI_API_KEY:
                result = await _search_serpapi(query)
            elif api_name == "Tavily" and TAVILY_API_KEY:
                result = await _search_tavily(query)
            elif api_name == "Exa" and EXA_API_KEY:
                result = await _search_exa(query)
            else:
                continue

            if result:
                logger.info(f"Fallback {api_name} thành công cho query '{query[:60]}'")
                return result
            else:
                logger.warning(f"Fallback {api_name} rỗng hoặc lỗi.")
        except Exception as e:
            logger.warning(f"Fallback {api_name} lỗi: {e}")

    logger.error("TẤT CẢ fallback APIs đều thất bại.")
    return ""

async def _search_serpapi(query: str) -> str:
    if not SERPAPI_API_KEY: return ""
    
    params = {
        "q": query,
        "api_key": SERPAPI_API_KEY,
        "engine": "google",
        "num": 3,
        "gl": "vn",
        "hl": "en" if re.search(r'[a-zA-Z]{4,}', query) else "vi"
    }
    
    search = GoogleSearch(params)
    results = await asyncio.to_thread(search.get_dict)
    
    if 'organic_results' not in results:
        return ""
    
    relevant = []
    for item in results['organic_results'][:3]:
        title = item.get('title', 'Không có tiêu đề')
        snippet = item.get('snippet', '')[:330] + "..." if len(item.get('snippet', '')) > 130 else item.get('snippet', '')
        link = item.get('link', '')
        if any(ad in link.lower() for ad in ['shopee', 'lazada', 'amazon', 'tiki']): continue
        relevant.append(f"**{title}**: {snippet} (Nguồn: {link})")
    
    return "**Search SerpAPI (Dynamic):**\n" + "\n".join(relevant) + "\n\n[DÙNG ĐỂ TRẢ LỜI E-GIRL, KHÔNG LEAK NGUỒN]" if relevant else ""

async def _search_tavily(query: str) -> str:
    if not TAVILY_API_KEY: return ""
    
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
        if any(ad in link.lower() for ad in ['shopee', 'lazada', 'amazon', 'tiki']): continue
        relevant.append(f"**{title}**: {snippet} (Nguồn: {link})")
    
    return "**Search Tavily (Dynamic):**\n" + "\n".join(relevant) + "\n\n[DÙNG ĐỂ TRẢ LỜI E-GIRL, KHÔNG LEAK NGUỒN]" if relevant else ""

async def _search_exa(query: str) -> str:
    if not EXA_API_KEY: return ""
    
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
        if any(ad in link.lower() for ad in ['shopee', 'lazada', 'amazon', 'tiki']): continue
        relevant.append(f"**{title}**: {snippet} (Nguồn: {link})")
    
    return "**Search Exa.ai (Dynamic):**\n" + "\n".join(relevant) + "\n\n[DÙNG ĐỂ TRẢ LỜI E-GIRL, KHÔNG LEAK NGUỒN]" if relevant else ""

