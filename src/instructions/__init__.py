"""Instructions package exposing OOP prompt manager, models, builders, and legacy prompt facades."""

from src.instructions.models import (
    PromptTemplate,
    RetrievalPrompts,
    RoleContracts,
)
from src.instructions.builders import (
    FallbackPromptFormatter,
    IdentityPromptBuilder,
)
from src.instructions.manager import (
    PromptManager,
    prompt_manager,
)
from src.instructions.prompts import (
    AZURIS_SYSTEM_PROMPT,
    LITE_SYSTEM_PROMPT,
    FALLBACK_SYSTEM_PROMPT,
    format_fallback_prompt,
)

__all__ = [
    # OOP Components
    "PromptManager",
    "prompt_manager",
    "PromptTemplate",
    "RetrievalPrompts",
    "RoleContracts",
    "FallbackPromptFormatter",
    "IdentityPromptBuilder",
    # Legacy facades
    "AZURIS_SYSTEM_PROMPT",
    "LITE_SYSTEM_PROMPT",
    "FALLBACK_SYSTEM_PROMPT",
    "format_fallback_prompt",
]
