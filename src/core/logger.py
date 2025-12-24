"""
Logger Manager - Singleton Pattern
Quản lý logging cho toàn bộ ứng dụng
"""
import logging
import os
from typing import Optional


class Logger:
    """
    Singleton Pattern cho Logger
    Đảm bảo chỉ có một logger instance duy nhất
    """
    _instance = None
    _logger: Optional[logging.Logger] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if Logger._logger is not None:
            return
        
        Logger._logger = logging.getLogger('bot_gemini')
        Logger._logger.setLevel(logging.INFO)
        
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        
        # File handler
        log_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'bot.log')
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        
        # Stream handler
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        
        Logger._logger.handlers = [file_handler, stream_handler]
        Logger._logger.propagate = False

    @property
    def logger(self) -> logging.Logger:
        """Get logger instance"""
        if Logger._logger is None:
            self.__init__()
        return Logger._logger

    def info(self, message: str) -> None:
        """Log info message"""
        self.logger.info(message)

    def warning(self, message: str) -> None:
        """Log warning message"""
        self.logger.warning(message)

    def error(self, message: str) -> None:
        """Log error message"""
        self.logger.error(message)

    def debug(self, message: str) -> None:
        """Log debug message"""
        self.logger.debug(message)


# Global instance
logger_manager = Logger()
logger = logger_manager.logger


# Compatibility function for log_message
async def log_message(user_id: str, role: str, content: str) -> None:
    """
    Log a message to database (compatibility function)
    This should be moved to a proper service later
    """
    from database.repository import db_repository
    await db_repository.log_message(user_id, role, content)

