"""Registry for language-specific classifier hints."""

from importlib import import_module
from typing import Dict, Iterable, Tuple

_LANGUAGE_MODULES = {
    "vi": "vi",
    "en": "en",
    "ja": "ja",
    "korea": "korea",
    "spanish": "spanish",
    "chinese": "chinese",
}


def language_topic_keywords(language: str) -> Dict[str, Tuple[str, ...]]:
    """Load one language's hints lazily and return an empty map if absent."""
    module_name = _LANGUAGE_MODULES.get(language)
    if not module_name:
        return {}
    module = import_module(f"{__package__}.{module_name}")
    catalog = module.TOPIC_KEYWORDS
    return {
        topic: tuple(value.get("keywords", ())) if isinstance(value, dict) else tuple(value)
        for topic, value in catalog.items()
    }


def build_search_topics() -> Dict[str, Dict[str, list[str]]]:
    """Merge language catalogs into the legacy topic shape consumed by ranking."""
    merged: Dict[str, Dict[str, list[str]]] = {}
    for language in _LANGUAGE_MODULES:
        module_name = _LANGUAGE_MODULES[language]
        module = import_module(f"{__package__}.{module_name}")
        for topic, value in module.TOPIC_KEYWORDS.items():
            keywords = value.get("keywords", ()) if isinstance(value, dict) else value
            suffixes = value.get("suffixes", ()) if isinstance(value, dict) else ()
            entry = merged.setdefault(topic, {"keywords": [], "suffixes": []})
            for keyword in keywords:
                if keyword not in entry["keywords"]:
                    entry["keywords"].append(keyword)
            for suffix in suffixes:
                if suffix not in entry["suffixes"]:
                    entry["suffixes"].append(suffix)
    merged.setdefault("general", {"keywords": [], "suffixes": ["news", "latest", "update", "information"]})
    return merged


def detect_query_languages(query: str) -> tuple[str, ...]:
    """Return script-specific catalogs needed to classify a query."""
    import re

    languages = []
    if re.search(r"[\u3040-\u30ff]", query):
        languages.append("ja")
    if re.search(r"[\uac00-\ud7af]", query):
        languages.append("korea")
    if re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", query) and "ja" not in languages:
        languages.append("chinese")
    return tuple(languages)


def iter_language_topic_keywords(languages: Iterable[str]):
    """Yield topic/keyword pairs without importing every language at startup."""
    for language in languages:
        for topic, keywords in language_topic_keywords(language).items():
            yield topic, keywords

