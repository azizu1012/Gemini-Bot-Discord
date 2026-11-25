from typing import Dict, List, Set, Tuple


CACHE_TTL_SECONDS = 3600
MAX_CACHE_SIZE = 1000
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024
MAX_TEXT_LENGTH = 10000
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json'



CITY_NAME_MAP: Dict[str, Tuple[str, str]] = {
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

SEARCH_CACHE_STOPWORDS: Set[str] = {
    "the", "a", "an", "of", "for", "to", "and", "or", "in", "on", "at", "is", "are", "be",
    "toi", "la", "va", "cua", "cho", "ve", "trong", "tai", "duoc", "khong", "nao", "gi", "bao", "khi",
    "news", "information", "thong", "tin", "xem", "hoi", "giup",
}

SEARCH_CACHE_PHRASE_ALIASES: List[Tuple[str, str]] = [
    ("moi nhat", "latest"),
    ("hien tai", "current"),
    ("cap nhat", "update"),
    ("khi nao", "when"),
    ("bao gio", "when"),
    ("ket thuc", "end"),
    ("thoi gian", "schedule"),
    ("lich", "schedule"),
]

SEARCH_CACHE_TOKEN_ALIASES: Dict[str, str] = {
    "hsr": "honkai_star_rail",
    "starrail": "honkai_star_rail",
    "banner": "banner",
    "latest": "latest",
    "current": "current",
    "update": "update",
    "patch": "patch",
    "schedule": "schedule",
}
