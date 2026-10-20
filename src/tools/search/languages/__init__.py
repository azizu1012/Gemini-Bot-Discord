"""Language-specific search classification hints.

Each language lives in its own small module so adding vocabulary does not
require editing the core search data table.
"""

from .registry import build_search_topics, detect_query_languages, language_topic_keywords

__all__ = ["build_search_topics", "detect_query_languages", "language_topic_keywords"]

