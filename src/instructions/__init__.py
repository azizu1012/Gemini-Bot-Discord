"""Instructions package exposing system prompts and formatters."""

from src.instructions.prompts import (
    AZURIS_SYSTEM_PROMPT,
    LITE_SYSTEM_PROMPT,
    FALLBACK_SYSTEM_PROMPT,
    format_fallback_prompt,
)

__all__ = [
    "AZURIS_SYSTEM_PROMPT",
    "LITE_SYSTEM_PROMPT",
    "FALLBACK_SYSTEM_PROMPT",
    "format_fallback_prompt",
]
