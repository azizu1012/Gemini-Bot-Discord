"""Tools facade for backward compatibility."""

import requests
from src.tools.manager import ToolsManager

__all__ = ["ToolsManager", "requests"]
