"""Pytest cấu hình chung cho tests.

Toàn bộ test chạy offline (mock), không cần PostgreSQL/Redis/mạng thật.
Chỉ chốt `sys.path` để import `src.*` nhất quán bất kể nơi chạy.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
