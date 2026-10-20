"""Consolidated system prompts and prompt formatters for Azuris AI (backward-compatible facade)."""

from __future__ import annotations

from src.instructions.manager import prompt_manager

AZURIS_SYSTEM_PROMPT: str = prompt_manager.get_system_prompt()
LITE_SYSTEM_PROMPT: str = prompt_manager.get_reasoning_prompt()
FALLBACK_SYSTEM_PROMPT: str = prompt_manager.get_fallback_prompt()


def format_fallback_prompt(user_input: str, reasoning_output: str, tool_results: str = "") -> str:
    """Format fallback system prompt with 3-block context."""
    return prompt_manager.format_fallback_prompt(user_input, reasoning_output, tool_results)


__all__ = [
    "AZURIS_SYSTEM_PROMPT",
    "LITE_SYSTEM_PROMPT",
    "FALLBACK_SYSTEM_PROMPT",
    "format_fallback_prompt",
]
