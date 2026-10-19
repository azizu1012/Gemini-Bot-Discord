"""File index service facade for backward compatibility."""

from src.services.indexing.indexer import (
    FileIndexService,
    should_use_last_index,
    build_index_context,
)

__all__ = ["FileIndexService", "should_use_last_index", "build_index_context"]
