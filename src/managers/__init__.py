"""
Managers Module
Quản lý các tài nguyên và dịch vụ: cache, cleanup, notes, premium
"""
from .cache_manager import (
    get_web_search_cache,
    set_web_search_cache,
    get_image_recognition_cache,
    set_image_recognition_cache,
    clear_all_caches
)
from .cleanup_manager import (
    get_disk_free_space_mb,
    cleanup_local_files
)
from .note_manager import (
    save_note_to_db,
    save_file_note_to_db,
    retrieve_notes_from_db
)
from .premium_manager import (
    is_premium_user,
    is_admin_user,
    add_premium_user,
    remove_premium_user
)

__all__ = [
    'get_web_search_cache',
    'set_web_search_cache',
    'get_image_recognition_cache',
    'set_image_recognition_cache',
    'clear_all_caches',
    'get_disk_free_space_mb',
    'cleanup_local_files',
    'save_note_to_db',
    'save_file_note_to_db',
    'retrieve_notes_from_db',
    'is_premium_user',
    'is_admin_user',
    'add_premium_user',
    'remove_premium_user',
]

