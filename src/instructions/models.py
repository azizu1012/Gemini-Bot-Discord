"""Domain models and value objects for AI prompt instructions."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class PromptTemplate:
    """Represents a loaded prompt template with variable substitution capabilities."""

    name: str
    content: str
    path: Optional[Path] = None

    def render(self, **kwargs: Any) -> str:
        """Safely render template by replacing placeholders.

        Uses explicit placeholder replacement instead of str.format to avoid
        breaking on JSON examples or braces commonly present in prompt texts.
        Supports both {KEY} and [KEY] style placeholders.
        """
        result = self.content
        for key, val in kwargs.items():
            str_val = str(val) if val is not None else ""
            result = result.replace(f"{{{key}}}", str_val)
            result = result.replace(f"[{key}]", str_val)
        return result

    def is_empty(self) -> bool:
        """Return True if template content is empty or only whitespace."""
        return not bool(self.content.strip())

    def __str__(self) -> str:
        return self.content

    def __bool__(self) -> bool:
        return not self.is_empty()


@dataclass
class RetrievalPrompts:
    """Typed prompt collection for multi-stage retrieval and context integration."""

    auto_retrieval_limit: str = ""
    extra_retrieval: str = ""
    final_synthesis: str = ""
    partial_evidence: str = ""
    search_budget: str = ""
    three_block_context: str = ""

    def get(self, key: str, default: str = "") -> str:
        """Dictionary-like accessor for backward compatibility."""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> str:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def as_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class RoleContracts:
    """Typed role contract constraints for admin vs non-admin callers."""

    admin: str = ""
    user: str = ""

    def get(self, key: str, default: str = "") -> str:
        """Dictionary-like accessor for backward compatibility."""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> str:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def as_dict(self) -> Dict[str, str]:
        return asdict(self)
