from functools import lru_cache
from pathlib import Path

from .config import logger
from .system_prompt import AZURIS_SYSTEM_PROMPT
from .lite_sys_prompt import LITE_SYSTEM_PROMPT
from .fallback_sys_prompt import FALLBACK_SYSTEM_PROMPT


INSTRUCTIONS_DIR = Path(__file__).resolve().parent.parent / "instructions"


def _load_prompt(filename: str, fallback_text: str) -> str:
    path = INSTRUCTIONS_DIR / filename
    try:
        content = path.read_text(encoding="utf-8")
        if content.strip():
            return content
        logger.warning(f"Prompt file is empty, using fallback: {path}")
    except Exception as exc:
        logger.warning(f"Cannot load prompt file, using fallback {path}: {exc}")
    return fallback_text


@lru_cache(maxsize=1)
def get_azuris_system_prompt() -> str:
    return _load_prompt("azuris_system_prompt.txt", AZURIS_SYSTEM_PROMPT)


@lru_cache(maxsize=1)
def get_lite_reasoning_prompt() -> str:
    return _load_prompt("lite_reasoning_prompt.txt", LITE_SYSTEM_PROMPT)


@lru_cache(maxsize=1)
def get_fallback_system_prompt() -> str:
    return _load_prompt("fallback_system_prompt.txt", FALLBACK_SYSTEM_PROMPT)
