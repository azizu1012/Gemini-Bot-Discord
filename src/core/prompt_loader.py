"""Prompt loader facade delegating to the OOP PromptManager."""

from __future__ import annotations

from typing import Any, Dict
from src.instructions.manager import prompt_manager


def get_azuris_system_prompt() -> str:
    """Return the main personality system prompt."""
    return prompt_manager.get_system_prompt()


def get_lite_reasoning_prompt() -> str:
    """Return the lite reasoning engine prompt."""
    return prompt_manager.get_reasoning_prompt()


def get_fallback_system_prompt() -> str:
    """Return the 3-block fallback system prompt."""
    return prompt_manager.get_fallback_prompt()


def get_file_index_reasoning_prompt() -> str:
    """Return the file indexing reasoning prompt."""
    return prompt_manager.get_file_index_reasoning_prompt()


def get_file_index_validation_prompt() -> str:
    """Return the file indexing validation prompt."""
    return prompt_manager.get_file_index_validation_prompt()


def get_retrieval_prompts() -> Dict[str, str]:
    """Return retrieval prompts as a dictionary."""
    return prompt_manager.get_retrieval_prompts().as_dict()


def get_three_block_context_prompt() -> str:
    """Return three block context integration prompt."""
    return prompt_manager.get_three_block_context_prompt()


def get_search_budget_prompt() -> str:
    """Return search budget warning prompt."""
    return prompt_manager.get_search_budget_prompt()


def get_extra_retrieval_prompt() -> str:
    """Return extra retrieval deep search prompt."""
    return prompt_manager.get_extra_retrieval_prompt()


def get_partial_evidence_prompt() -> str:
    """Return partial evidence truncation prompt."""
    return prompt_manager.get_partial_evidence_prompt()


def get_auto_retrieval_limit_prompt() -> str:
    """Return auto retrieval limit summary prompt."""
    return prompt_manager.get_auto_retrieval_limit_prompt()


def get_final_synthesis_prompt() -> str:
    """Return final synthesis prompt."""
    return prompt_manager.get_final_synthesis_prompt()


def get_identity_capability_prompt() -> str:
    """Return raw identity and capability contract template."""
    return prompt_manager.get_identity_capability_prompt()


def get_role_contracts() -> Dict[str, str]:
    """Return admin and user role contracts as a dictionary."""
    return prompt_manager.get_role_contracts().as_dict()


def build_identity_capability_prompt(
    is_admin: bool,
    has_other_users: bool,
    distinct_user_count: int,
    tool_lines: str,
) -> str:
    """Assemble runtime identity contract based on role and active tools."""
    return prompt_manager.build_identity_prompt(
        is_admin=is_admin,
        has_other_users=has_other_users,
        distinct_user_count=distinct_user_count,
        tool_lines=tool_lines,
    )
