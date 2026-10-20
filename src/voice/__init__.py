"""Voice package exposing voice lock, tools, stores, and role rank services."""

from src.voice.models import (
    LockRecord,
    LockOutcome,
    PurgeReport,
    RoleMovePlan,
)
from src.voice.store import (
    JsonStore,
    LockStore,
    WhitelistStore,
    LockStoreProtocol,
    WhitelistStoreProtocol,
)
from src.voice.purge import (
    VoicePurgeService,
    voice_purge_service,
    purge_foreign_messages,
    resolve_text_channel,
)
from src.voice.lock_service import RoomLockService
from src.voice.tools_service import RoomToolsService
from src.voice.voice_lock import VoiceLockManager
from src.voice.role_hierarchy import (
    RoleHierarchyService,
    role_hierarchy_service,
    shorten,
    role_order,
    role_is_movable,
    movable_roles,
    role_rank,
    top_movable_slot,
    plan_role_move,
    role_lines,
)
from src.voice.ui import RolePickerView, RolePositionView, RoleDoneView

__all__ = [
    # Models & Value Objects
    "LockRecord",
    "LockOutcome",
    "PurgeReport",
    "RoleMovePlan",
    # Stores & Protocols
    "JsonStore",
    "LockStore",
    "WhitelistStore",
    "LockStoreProtocol",
    "WhitelistStoreProtocol",
    # Domain Services
    "VoicePurgeService",
    "voice_purge_service",
    "RoomLockService",
    "RoomToolsService",
    "RoleHierarchyService",
    "role_hierarchy_service",
    "VoiceLockManager",
    # Backward-compatible facades & functions
    "purge_foreign_messages",
    "resolve_text_channel",
    "shorten",
    "role_order",
    "role_is_movable",
    "movable_roles",
    "role_rank",
    "top_movable_slot",
    "plan_role_move",
    "role_lines",
    # UI Views
    "RolePickerView",
    "RolePositionView",
    "RoleDoneView",
]
