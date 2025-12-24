import json
import os
from typing import List
from core.config import config

PREMIUM_USERS_FILE = 'premium_users.json'

def _load_premium_users() -> List[str]:
    """Loads the list of premium user IDs from the JSON file."""
    if os.path.exists(PREMIUM_USERS_FILE):
        with open(PREMIUM_USERS_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

def _save_premium_users(users: List[str]):
    """Saves the list of premium user IDs to the JSON file."""
    with open(PREMIUM_USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=4)

def is_premium_user(user_id: str) -> bool:
    """Checks if a given user ID is in the premium list."""
    premium_users = _load_premium_users()
    return user_id in premium_users

def is_admin_user(user_id: str) -> bool:
    """Checks if a given user ID is in the admin list."""
    return user_id in config.ADMIN_USER_IDS

def add_premium_user(user_id: str) -> bool:
    """Adds a user ID to the premium list. Returns True if added, False if already present."""
    premium_users = _load_premium_users()
    if user_id not in premium_users:
        premium_users.append(user_id)
        _save_premium_users(premium_users)
        return True
    return False

def remove_premium_user(user_id: str) -> bool:
    """Removes a user ID from the premium list. Returns True if removed, False if not found."""
    premium_users = _load_premium_users()
    if user_id in premium_users:
        premium_users.remove(user_id)
        _save_premium_users(premium_users)
        return True
    return False
