import src.core.config as config
from src.database.repository import DatabaseRepository

class PremiumManager:
    """Manager for premium user status (using Database)."""

    def __init__(self):
        self.db = DatabaseRepository()

    async def is_premium_user(self, user_id: str) -> bool:
        """Check if user is premium."""
        return await self.db.is_premium_user(user_id)

    async def is_admin_user(self, user_id: str) -> bool:
        """Check if user is admin."""
        if user_id in config.ADMIN_USER_IDS:
            return True
        return await self.db.is_admin_user(user_id)

    async def is_moderator_user(self, user_id: str) -> bool:
        """Check if user is moderator."""
        if user_id in config.MODERATOR_USER_IDS:
            return True
        return await self.db.is_moderator_user(user_id)

    async def add_premium_user(self, user_id: str) -> bool:
        """Add user to premium list."""
        return await self.db.add_premium_user(user_id)

    async def remove_premium_user(self, user_id: str) -> bool:
        """Remove user from premium list."""
        return await self.db.remove_premium_user(user_id)
