import os
from src.core.config import ADMIN_USER_IDS
from src.database.repository import DatabaseRepository

class PremiumManager:
    """Manager for premium user status (using Database)."""
    
    def __init__(self):
        self.db = DatabaseRepository()
    
    def is_premium_user(self, user_id: str) -> bool:
        """Check if user is premium."""
        return self.db.is_premium_user_sync(user_id)
    
    def is_admin_user(self, user_id: str) -> bool:
        """Check if user is admin."""
        return user_id in ADMIN_USER_IDS
    
    def add_premium_user(self, user_id: str) -> bool:
        """Add user to premium list."""
        return self.db.add_premium_user_sync(user_id)
    
    def remove_premium_user(self, user_id: str) -> bool:
        """Remove user from premium list."""
        return self.db.remove_premium_user_sync(user_id)
