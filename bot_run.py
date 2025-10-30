from keep_alive import keep_alive
from discord.ext import commands
from dotenv import load_dotenv
import os
import logging
import asyncio
import sqlite3
import json
import re
import requests
import sympy as sp
from datetime import datetime, timedelta
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from duckduckgo_search import DDGS
from discord import app_commands
import discord

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

def normalize_city_name(city_query):
    if not city_query:
        return ("Ho Chi Minh City", "Thành phố Hồ Chí Minh")
    city_key = city_query.strip().lower()
    for k, v in CITY_NAME_MAP.items():
        if k in city_key:
            return v
    return (city_query, city_query.title())

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('bot_gemini')
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
file_handler = logging.FileHandler('bot.log', encoding='utf-8')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
stream_handler.setLevel(logging.INFO)
logger.addHandler(stream_handler)

# --- TẢI BIẾN MÔI TRƯỜNG ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GEMINI_API_KEY_PROD = os.getenv('GEMINI_API_KEY_PROD')
GEMINI_API_KEY_TEST = os.getenv('GEMINI_API_KEY_TEST')
GEMINI_API_KEY_BACKUP = os.getenv('GEMINI_API_KEY_BACKUP')
GEMINI_API_KEY_EXTRA1 = os.getenv('GEMINI_API_KEY_EXTRA1')
GEMINI_API_KEY_EXTRA2 = os.getenv('GEMINI_API_KEY_EXTRA2')
MODEL_NAME = os.getenv('MODEL_NAME')
ADMIN_ID = os.getenv('ADMIN_ID', '')
HABE_USER_ID = os.getenv('HABE_USER_ID', '')
MIRA_USER_ID = os.getenv('MIRA_USER_ID', '')
ADO_FAT_USER_ID = os.getenv('ADO_FAT_USER_ID', '')
MUC_RIM_USER_ID = os.getenv('MUC_RIM_USER_ID', '')
SUC_VIEN_USER_ID = os.getenv('SUC_VIEN_USER_ID', '')
CHUI_USER_ID = os.getenv('CHUI_USER_ID', '')
WEATHER_CACHE_PATH = os.path.join(os.path.dirname(__file__), 'weather_cache.json')
weather_lock = asyncio.Lock()
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')
CITY = os.getenv('CITY')
DB_PATH = os.path.join(os.path.dirname(__file__), 'chat_history.db')
DB_BACKUP_PATH = os.path.join(os.path.dirname(__file__), 'chat_history_backup.db')
NOTE_PATH = os.path.join(os.path.dirname(__file__), 'notes.txt')
MEMORY_PATH = os.path.join(os.path.dirname(__file__), 'short_term_memory.json')
memory_lock = asyncio.Lock()
GEMINI_API_KEYS = []
if GEMINI_API_KEY_PROD:
    GEMINI_API_KEYS.append(GEMINI_API_KEY_PROD)
if GEMINI_API_KEY_TEST:
    GEMINI_API_KEYS.append(GEMINI_API_KEY_TEST)
if GEMINI_API_KEY_BACKUP:
    GEMINI_API_KEYS.append(GEMINI_API_KEY_BACKUP)
if GEMINI_API_KEY_EXTRA1:
    GEMINI_API_KEYS.append(GEMINI_API_KEY_EXTRA1)
if GEMINI_API_KEY_EXTRA2:
    GEMINI_API_KEYS.append(GEMINI_API_KEY_EXTRA2)
if not GEMINI_API_KEYS:
    logger.error("Không tìm thấy Gemini API keys! Bot sẽ không thể hoạt động.")
else:
    logger.info(f"Đã thiết lập {len(GEMINI_API_KEYS)} Gemini API keys cho Failover.")
LAST_WORKING_KEY_INDEX = 0
# ...existing code for run_gemini_api, DB, memory, weather, tools, enrich, commands, on_message, etc...
# Để ngắn gọn, bạn copy phần còn lại từ bot_run.py của bạn vào đây

if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
