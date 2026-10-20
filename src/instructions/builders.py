"""Prompt builders and formatters encapsulating dynamic prompt assembly."""

from __future__ import annotations

from typing import Optional
from src.instructions.models import PromptTemplate, RoleContracts


class FallbackPromptFormatter:
    """Formats 3-block context (User Input, Reasoning Output, Tool Results) into fallback prompt."""

    def __init__(self, template: PromptTemplate):
        self.template = template

    def format(self, user_input: str, reasoning_output: str, tool_results: str = "") -> str:
        """Format 3-block context into fallback system prompt."""
        tool_text = tool_results.strip() if tool_results and tool_results.strip() else "(Không có tool được gọi)"
        return self.template.render(
            USER_INPUT_HERE=(user_input or "").strip(),
            REASONING_OUTPUT_HERE=(reasoning_output or "").strip(),
            TOOL_RESULTS_HERE=tool_text,
        )


class IdentityPromptBuilder:
    """Assembles identity and runtime capability contracts based on caller role and tools."""

    def __init__(self, template: PromptTemplate, contracts: RoleContracts):
        self.template = template
        self.contracts = contracts

    def build(
        self,
        is_admin: bool,
        has_other_users: bool,
        distinct_user_count: int,
        tool_lines: str,
    ) -> str:
        """Build runtime identity & capability prompt with scoped role contract and tools."""
        role_lines = [
            "- This assistant serves many users, but memory loaded per response is scoped to the current user only.",
            f"- Runtime cross-user signal: has_other_users={str(has_other_users).lower()}, distinct_user_count={distinct_user_count}."
        ]

        if is_admin:
            if self.contracts.admin:
                role_lines.append(self.contracts.admin)
        else:
            if self.contracts.user:
                role_lines.append(self.contracts.user)

        role_contract = "\n".join(role_lines)
        return self.template.render(
            ROLE_CONTRACT=role_contract,
            TOOL_LINES=tool_lines or "",
        )
