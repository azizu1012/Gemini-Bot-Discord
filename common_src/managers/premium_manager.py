import json
import os
from typing import List
from core.config import ADMIN_USER_IDS


class PremiumManager:
    """Manager for premium user status."""
    
    PREMIUM_USERS_FILE = 'premium_users.json'
    
    def __init__(self, premium_file: str = PREMIUM_USERS_FILE):
        self.premium_file = premium_file
    
    def _load_premium_users(self) -> List[str]:
        """Load premium users from JSON file."""
        if os.path.exists(self.premium_file):
            with open(self.premium_file, 'r', encoding='utf-8') as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return []
        return []
    
    def _save_premium_users(self, users: List[str]) -> None:
        """Save premium users to JSON file."""
        with open(self.premium_file, 'w', encoding='utf-8') as f:
            json.dump(users, f, indent=4)
    
    def is_premium_user(self, user_id: str) -> bool:
        """Check if user is premium."""
        premium_users = self._load_premium_users()
        return user_id in premium_users
    
    def is_admin_user(self, user_id: str) -> bool:
        """Check if user is admin."""
        return user_id in ADMIN_USER_IDS
    
    def add_premium_user(self, user_id: str) -> bool:
        """Add user to premium list. Returns True if added, False if already exists."""
        premium_users = self._load_premium_users()
        if user_id not in premium_users:
            premium_users.append(user_id)
            self._save_premium_users(premium_users)
            return True
        return False
    
    def remove_premium_user(self, user_id: str) -> bool:
        """Remove user from premium list. Returns True if removed, False if not found."""
        premium_users = self._load_premium_users()
        if user_id in premium_users:
            premium_users.remove(user_id)
            self._save_premium_users(premium_users)
            return True
        return False
