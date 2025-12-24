import logging
from typing import Optional


class LoggerService:
    """Service for application logging."""
    
    def __init__(self, logger_instance: logging.Logger):
        self.logger = logger_instance
    
    async def log_message(self, user_id: str, role: str, content: str) -> None:
        """Log a message to both database and JSON memory.
        
        This method coordinates logging across multiple backends.
        """
        if role == "user":
            self.logger.info(f"User {user_id} sent a message")
        elif role == "assistant" and "DM reply" in content:
            self.logger.info(f"Bot sent DM to user mentioned in message")
    
    def info(self, message: str) -> None:
        """Log info level message."""
        self.logger.info(message)
    
    def error(self, message: str) -> None:
        """Log error level message."""
        self.logger.error(message)
    
    def warning(self, message: str) -> None:
        """Log warning level message."""
        self.logger.warning(message)
    
    def debug(self, message: str) -> None:
        """Log debug level message."""
        self.logger.debug(message)


def get_logger_service(logger_instance: logging.Logger) -> LoggerService:
    """Factory function to create logger service."""
    return LoggerService(logger_instance)
