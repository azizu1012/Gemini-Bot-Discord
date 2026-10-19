"""Unit tests for prompt_loader and prompt formats."""

import pytest
from src.core.prompt_loader import (
    get_azuris_system_prompt,
    get_lite_reasoning_prompt,
    get_fallback_system_prompt,
    get_file_index_reasoning_prompt,
    get_file_index_validation_prompt,
    get_retrieval_prompts,
)
from src.instructions.prompts import (
    AZURIS_SYSTEM_PROMPT,
    LITE_SYSTEM_PROMPT,
    FALLBACK_SYSTEM_PROMPT,
    format_fallback_prompt,
)


class TestPromptLoader:
    def test_load_azuris_system_prompt(self):
        prompt = get_azuris_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 100
        assert "Chad Gibiti" in prompt or "Azuris" in prompt or "Current Date/Time" in prompt

    def test_load_lite_reasoning_prompt(self):
        prompt = get_lite_reasoning_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 50
        assert "REASONING FRAMEWORK" in prompt or "ROLE:" in prompt

    def test_load_fallback_system_prompt(self):
        prompt = get_fallback_system_prompt()
        assert isinstance(prompt, str)
        assert "fallback" in prompt.lower()

    def test_load_retrieval_prompts(self):
        retrieval = get_retrieval_prompts()
        assert isinstance(retrieval, dict)
        assert "final_synthesis" in retrieval

    def test_format_fallback_prompt(self):
        user_input = "Giải thích thuyết lượng tử"
        reasoning = "Cần phân tích các khái niệm cơ bản"
        formatted = format_fallback_prompt(user_input, reasoning, "evidence 123")
        assert user_input in formatted
        assert reasoning in formatted
        assert "evidence 123" in formatted
