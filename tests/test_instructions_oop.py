"""Unit tests for OOP instructions package (PromptManager, models, builders)."""

import pytest
from pathlib import Path
from src.instructions.models import PromptTemplate, RetrievalPrompts, RoleContracts
from src.instructions.builders import FallbackPromptFormatter, IdentityPromptBuilder
from src.instructions.manager import PromptManager, prompt_manager
from src.instructions.prompts import (
    AZURIS_SYSTEM_PROMPT,
    LITE_SYSTEM_PROMPT,
    FALLBACK_SYSTEM_PROMPT,
    format_fallback_prompt,
)
from src.instructions.system_prompt import AZURIS_SYSTEM_PROMPT as RE_EXPORT_AZURIS
from src.instructions.lite_sys_prompt import LITE_SYSTEM_PROMPT as RE_EXPORT_LITE
from src.instructions.fallback_sys_prompt import (
    FALLBACK_SYSTEM_PROMPT as RE_EXPORT_FALLBACK,
    format_fallback_prompt as re_export_format_fallback,
)


class TestPromptModels:
    def test_prompt_template_render_curly_and_bracket(self):
        template = PromptTemplate(
            name="test",
            content="Hello {NAME}, you are in [MODE] mode. Raw JSON: {\"key\": 123}",
        )
        rendered = template.render(NAME="Alice", MODE="DEBUG")
        assert "Hello Alice, you are in DEBUG mode." in rendered
        assert '{"key": 123}' in rendered

    def test_prompt_template_empty_check(self):
        empty = PromptTemplate(name="empty", content="   \n\t  ")
        assert empty.is_empty()
        assert not bool(empty)

        valid = PromptTemplate(name="valid", content="System instruction")
        assert not valid.is_empty()
        assert bool(valid)
        assert str(valid) == "System instruction"

    def test_retrieval_prompts_model(self):
        prompts = RetrievalPrompts(
            auto_retrieval_limit="limit_txt",
            extra_retrieval="extra_txt",
            final_synthesis="synth_txt",
            partial_evidence="part_txt",
            search_budget="budget_txt",
            three_block_context="block_txt",
        )
        assert prompts.get("final_synthesis") == "synth_txt"
        assert prompts["search_budget"] == "budget_txt"
        assert "extra_retrieval" in prompts
        as_d = prompts.as_dict()
        assert isinstance(as_d, dict)
        assert as_d["auto_retrieval_limit"] == "limit_txt"

    def test_role_contracts_model(self):
        contracts = RoleContracts(admin="admin rules", user="user rules")
        assert contracts.get("admin") == "admin rules"
        assert contracts["user"] == "user rules"
        assert "admin" in contracts
        assert contracts.as_dict() == {"admin": "admin rules", "user": "user rules"}


class TestPromptBuilders:
    def test_identity_builder_admin(self):
        template = PromptTemplate(name="id", content="ID:{ROLE_CONTRACT}|TOOLS:{TOOL_LINES}")
        contracts = RoleContracts(admin="- ADMIN_SPECIFIC", user="- USER_SPECIFIC")
        builder = IdentityPromptBuilder(template, contracts)

        result = builder.build(
            is_admin=True,
            has_other_users=True,
            distinct_user_count=5,
            tool_lines="- search: search web",
        )
        assert "ADMIN_SPECIFIC" in result
        assert "USER_SPECIFIC" not in result
        assert "has_other_users=true" in result
        assert "distinct_user_count=5" in result
        assert "TOOLS:- search: search web" in result

    def test_identity_builder_user(self):
        template = PromptTemplate(name="id", content="ID:{ROLE_CONTRACT}|TOOLS:{TOOL_LINES}")
        contracts = RoleContracts(admin="- ADMIN_SPECIFIC", user="- USER_SPECIFIC")
        builder = IdentityPromptBuilder(template, contracts)

        result = builder.build(
            is_admin=False,
            has_other_users=False,
            distinct_user_count=1,
            tool_lines="",
        )
        assert "USER_SPECIFIC" in result
        assert "ADMIN_SPECIFIC" not in result
        assert "has_other_users=false" in result

    def test_fallback_prompt_formatter(self):
        template = PromptTemplate(
            name="fallback",
            content="INPUT:[USER_INPUT_HERE]\nREASON:[REASONING_OUTPUT_HERE]\nTOOLS:[TOOL_RESULTS_HERE]",
        )
        formatter = FallbackPromptFormatter(template)

        # Case 1: with tools
        res1 = formatter.format("User Q", "Reasoning steps", "Tool snippet")
        assert "INPUT:User Q" in res1
        assert "REASON:Reasoning steps" in res1
        assert "TOOLS:Tool snippet" in res1

        # Case 2: without tools
        res2 = formatter.format("User Q", "Reasoning steps", "")
        assert "TOOLS:(Không có tool được gọi)" in res2


class TestPromptManager:
    def test_manager_loads_real_templates(self):
        manager = PromptManager()
        sys_prompt = manager.get_system_prompt()
        assert "Chad Gibiti" in sys_prompt
        assert "2026" in sys_prompt

        reasoning = manager.get_reasoning_prompt()
        assert "CONCLUDE:" in reasoning

        fallback = manager.get_fallback_prompt()
        assert "Chad Gibiti" in fallback

        retrieval = manager.get_retrieval_prompts()
        assert bool(retrieval.final_synthesis)
        assert bool(retrieval.three_block_context)

        contracts = manager.get_role_contracts()
        assert bool(contracts.admin)
        assert bool(contracts.user)

    def test_manager_caching_and_reload(self):
        manager = PromptManager()
        t1 = manager.load_template("azuris_system_prompt.txt")
        t2 = manager.load_template("azuris_system_prompt.txt")
        assert t1 is t2

        manager.reload()
        t3 = manager.load_template("azuris_system_prompt.txt")
        assert t3 is not t1
        assert t3.content == t1.content

    def test_manager_missing_template_fallback(self):
        manager = PromptManager(templates_dir=Path("/non/existent/path"))
        fallback = "Custom fallback content"
        tpl = manager.load_template("unknown.txt", fallback_content=fallback)
        assert tpl.content == fallback


class TestBackwardCompatibility:
    def test_prompts_facade_values(self):
        assert isinstance(AZURIS_SYSTEM_PROMPT, str)
        assert len(AZURIS_SYSTEM_PROMPT) > 100
        assert isinstance(LITE_SYSTEM_PROMPT, str)
        assert len(LITE_SYSTEM_PROMPT) > 100
        assert isinstance(FALLBACK_SYSTEM_PROMPT, str)
        assert len(FALLBACK_SYSTEM_PROMPT) > 100

        formatted = format_fallback_prompt("User query", "Reasoning here", "Evidence")
        assert "User query" in formatted
        assert "Reasoning here" in formatted

    def test_re_exports_match(self):
        assert RE_EXPORT_AZURIS == AZURIS_SYSTEM_PROMPT
        assert RE_EXPORT_LITE == LITE_SYSTEM_PROMPT
        assert RE_EXPORT_FALLBACK == FALLBACK_SYSTEM_PROMPT
        assert re_export_format_fallback == format_fallback_prompt
