"""Unit tests for prompt_loader and prompt formats."""

from src.core.prompt_loader import (
    get_azuris_system_prompt,
    get_lite_reasoning_prompt,
    get_fallback_system_prompt,
    get_retrieval_prompts,
)
from src.instructions.prompts import (
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

    def test_load_all_remaining_prompts(self):
        from src.core.prompt_loader import (
            get_file_index_reasoning_prompt,
            get_file_index_validation_prompt,
            get_three_block_context_prompt,
            get_search_budget_prompt,
            get_extra_retrieval_prompt,
            get_partial_evidence_prompt,
            get_auto_retrieval_limit_prompt,
            get_final_synthesis_prompt,
            get_identity_capability_prompt,
            get_role_contracts,
            build_identity_capability_prompt,
        )
        assert isinstance(get_file_index_reasoning_prompt(), str)
        assert isinstance(get_file_index_validation_prompt(), str)
        assert isinstance(get_three_block_context_prompt(), str)
        assert isinstance(get_search_budget_prompt(), str)
        assert isinstance(get_extra_retrieval_prompt(), str)
        assert isinstance(get_partial_evidence_prompt(), str)
        assert isinstance(get_auto_retrieval_limit_prompt(), str)
        assert isinstance(get_final_synthesis_prompt(), str)
        assert isinstance(get_identity_capability_prompt(), str)
        assert isinstance(get_role_contracts(), dict)
        built = build_identity_capability_prompt(
            is_admin=True,
            has_other_users=True,
            distinct_user_count=5,
            tool_lines="- tool_x",
        )
        assert "tool_x" in built
