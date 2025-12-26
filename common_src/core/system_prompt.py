#!/usr/bin/env python3
"""
Dynamic System Prompt Loader for Tier 2 (Flash personality)
Loads bot personality from instance-specific instructions.py
Falls back to Chad Gibiti if no custom personality found.

Usage in message_handler.py:
    from core.system_prompt import get_system_prompt
    PERSONALITY_PROMPT = get_system_prompt()
"""

import sys
from pathlib import Path

def get_system_prompt():
    """Load bot personality from instance's instructions.py or use default."""
    instance_instructions = Path.cwd() / 'instructions'
    
    if instance_instructions.exists():
        instructions_file = instance_instructions / 'instructions.py'
        if instructions_file.exists():
            try:
                sys.path.insert(0, str(instance_instructions))
                from instructions import PERSONALITY_PROMPT
                return PERSONALITY_PROMPT
            except ImportError:
                pass
    
    # Fallback to Chad Gibiti
    return AZURIS_DEFAULT

# Default Chad Gibiti personality
AZURIS_DEFAULT = r"""IDENTITY:
You are "Chad Gibiti" — A high-tier Tech-Lord and the ultimate Bro.
Your vibe is: Alpha-Intelligence, Direct, Bro-tier, Chill but Sharp, and Ultra-Confident.
You speak like a seasoned Developer/Gamer friend.

STANCE:
- You are an equal, a mentor, or a rival in knowledge.
- You have the "Main Character" energy.
- You despise cringe, laziness, and beating around the bush.
- Walking encyclopedia of Tech, Programming, Gacha, Anime, Internet Subcultures.

TONE:
- Witty, sarcastic, sharp
- Direct and efficient
- Tech-savvy bro language
- Conversational and friendly
- Cut through BS - give the real answer

LANGUAGE ADAPTATION:
- Respond in the SAME language as user
- Vietnamese user → Vietnamese response
- English user → English response
"""


# Legacy export for compatibility
AZURIS_SYSTEM_PROMPT = get_system_prompt()
