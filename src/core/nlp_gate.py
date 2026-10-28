"""Bo loc NLP co dien (khong AI model) cho duong tat EASY.

Thay the gate LLM dat do (13-16s/call) bang chuan hoa tieng Viet + char 3-gram
cosine: ~1ms/call, offline, deterministic, khong phu thuoc router.

Luat:
- EASY: chao hoi/xa giao don gian, tra loi truc tiep 1-2 cau, khong can tool
  hay suy luan. Duong tat: 1 call lite + sandwich rut gon (khong khoi reasoning).
- Moi thu khac -> COMPLEX (fail-open ve full 2-tier pipeline).

Nguong chon tu spike do precision (khong cau KHO nao lot sang EASY):
EASY_THRESHOLD = 0.50 — HARD max 0.35, EASY min 0.65 (do tren golden set).
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from datetime import datetime
from typing import Any, Dict, Tuple

from src.core.prompt_loader import (
    get_azuris_system_prompt,
    get_three_block_context_prompt,
)

# Map teencode/chat-viet tat pho bien ve dang chuan. SUBSTRING: thay theo cum
# (giu nguyen hanh vi cu). WORD: key 1 ky tu chi thay khi dung doc lap
# (ranh gioi tu) de khong pha vo tu tieng Anh ("pizza" != "pivayva").
_TEENCODE_SUBSTRING = {
    "hé lô": "chào", "helo": "chào", "hello": "chào", "hi": "chào", "hí": "chào",
    "yo": "chào", "hey": "chào", "ê": "chào",
    "ko": "không", "kô": "không", "khum": "không", "hông": "không", "hong": "không",
    "iu": "yêu", "bn": "bạn", "mik": "mình", "mk": "mình", "mih": "mình",
    "tao": "tôi",
    "zậy": "vậy", "zay": "vậy",
    "ok": "được", "oke": "được", "okey": "được",
    "thanks": "cảm ơn", "thank": "cảm ơn", "tks": "cảm ơn",
    "mơn": "cảm ơn",
    "nhé": "nhé", "nha": "nhé", "nhe": "nhé",
    " lun": " luôn", " z": " vậy",
}
_TEENCODE_WORD = {
    "t": "tôi",
    "z": "vậy",
    "ạ": "",
}

# Cau xa giao don gian (EASY). Gi them cau moi vao day + golden set trong
# tests/test_nlp_gate.py khi mo rong coverage (khong phinh taxonomy tuy tien).
EASY_PROTOS = [
    "chào bạn",
    "chào buổi sáng",
    "chào buổi tối",
    "chào cả nhà",
    "chào mọi người",
    "bạn khỏe không",
    "khỏe không bạn",
    "dạo này sao rồi",
    "có khỏe không",
    "cảm ơn bạn",
    "cảm ơn nhiều",
    "thanks bạn",
    "ok cảm ơn",
    "tạm biệt",
    "bye bạn",
    "hẹn gặp lại",
    "ngủ ngon",
    "ok",
    "ừ",
    "vâng",
    "được rồi",
    "haha hay quá",
    "bạn tên gì vậy",
    "hi",
    # Chao tieng Anh (chuan hoa giong TV: vd "hello" -> "chao" nen van khop).
    "good morning",
    "good evening",
    "good night",
    "thank you",
    "bye bye",
    "see you",
    "how are you",
    # Nhat (native + romaji).
    "おはようございます",
    "こんにちは",
    "こんばんは",
    "ありがとうございます",
    "お疲れ様です",
    "ohayou gozaimasu",
    "konnichiwa",
    "arigatou gozaimasu",
    # Han (native + romanized).
    "안녕하세요",
    "감사합니다",
    "좋은 아침입니다",
    "annyeonghaseyo",
    "gamsahamnida",
    # Trung (giản thể + pinyin).
    "你好",
    "早上好",
    "晚上好",
    "谢谢",
    "再见",
    "ni hao",
    "xie xie",
    "xie xie ni",
    "zai jian",
    # Tay Ban Nha.
    "hola",
    "buenos días",
    "buenas noches",
    "gracias",
    "hasta luego",
    "cómo estás",
    # Phap.
    "bonjour",
    "bonsoir",
    "merci",
    "bonne nuit",
    "comment ça va",
    # Duc.
    "hallo",
    "guten morgen",
    "guten tag",
    "danke",
    "tschüss",
    "wie geht es dir",
    # Bo Dao Nha.
    "olá",
    "bom dia",
    "boa noite",
    "obrigado",
    "tchau",
    "como vai você",
    # Nga (native + romanized).
    "привет",
    "доброе утро",
    "добрый вечер",
    "спасибо",
    "до свидания",
    "как дела",
    "privet",
    "spasibo",
    # Thai (native + romanized).
    "สวัสดี",
    "สวัสดีตอนเช้า",
    "ขอบคุณ",
    "ลาก่อน",
    "สบายดีไหม",
    "sawatdee",
    "khop khun",
    "khop khun khap",
    # Indonesia.
    "halo",
    "selamat pagi",
    "selamat malam",
    "terima kasih",
    "dadah",
    "apa kabar",
    # Hindi (native + romanized).
    "नमस्ते",
    "सुप्रभात",
    "धन्यवाद",
    "अलविदा",
    "आप कैसे हैं",
    "namaste",
    "dhanyavaad",
    # Y.
    "ciao",
    "buongiorno",
    "buonasera",
    "grazie",
    "arrivederci",
    "come stai",
    # A Rap (native + romanized).
    "مرحبا",
    "صباح الخير",
    "مساء الخير",
    "شكرا",
    "مع السلامة",
    "كيف حالك",
    "salam",
    "shukran",
    # Tho Nhi Ky.
    "merhaba",
    "günaydın",
    "iyi akşamlar",
    "teşekkürler",
    "güle güle",
    "nasılsın",
]

EASY_THRESHOLD = 0.50
MAX_WORDS_EASY = 12  # dai hon -> auto COMPLEX (ngon ngu co khoang trang)
MAX_CHARS_EASY_NORM = 60  # dai hon -> auto COMPLEX (bat ca chu Han/Nhat/Thai khong khoang trang)
# Text EASY phai xap xi la loi chao: dai hon mau khop nhat khong qua slack nay.
# Chao + cau hoi ("annyeonghaseyo, oneul nalssi...?") -> COMPLEX du trigram chong lan lon.
EASY_LEN_SLACK_CHARS = 12
MAX_CHARS_EASY = 300  # guard them truoc khi goi gate tu message_handler

EASY_GENERATION_CONFIG: Dict[str, Any] = {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "max_output_tokens": 1024,
}

EASY_TIMEOUT_SECONDS = 60.0

# Marker cho slot reasoning khi duong tat khong qua vong suy luan.
# Template 3-block la noi chuoi thuan — marker noi ro cho model biet dung
# di tim reasoning khong ton tai.
EASY_NO_REASONING_MARKER = "(Trả lời trực tiếp — không qua vòng suy luận.)"
EASY_NO_TOOLS_MARKER = "(No tools were called)"  # production dung san khi tools rong


def fold_diacritics(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def normalize(text: str) -> str:
    import re as _re

    t = (text or "").lower().strip()
    t = " ".join(t.split())
    for k, v in _TEENCODE_SUBSTRING.items():
        t = t.replace(k, v)
    for k, v in _TEENCODE_WORD.items():
        t = _re.sub(r"\b" + _re.escape(k) + r"\b", v, t)
    t = " ".join(t.split())
    return fold_diacritics(t)


def trigrams(s: str) -> Counter:
    s = f"  {s}  "
    return Counter(s[i:i + 3] for i in range(len(s) - 2))


def cosine(a: Counter, b: Counter) -> float:
    inter = sum((a & b).values())
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return inter / (na * nb)


def easy_score(text: str) -> float:
    """Diem tuong dong cao nhat voi tap cau EASY (0.0-1.0)."""
    score, _ = _best_match(text)
    return score


def _best_match(text: str) -> Tuple[float, int]:
    """Tra ve (diem cao nhat, do dai mau khop nhat da chuan hoa)."""
    norm = normalize(text)
    if not norm:
        return 0.0, 0
    if len(norm) > MAX_CHARS_EASY_NORM:
        return 0.0, 0
    if len(norm.split()) > MAX_WORDS_EASY:
        return 0.0, 0
    tri = trigrams(norm)
    best = 0.0
    best_len = 0
    for p in EASY_PROTOS:
        pn = normalize(p)
        if pn == norm:
            return 1.0, len(pn)
        s = cosine(tri, trigrams(pn))
        if s > best:
            best, best_len = s, len(pn)
    return best, best_len


def classify(text: str) -> Tuple[str, float]:
    """Tra ve (decision, score). Quy tac an toan: mo ho -> COMPLEX."""
    score, proto_len = _best_match(text)
    if score >= EASY_THRESHOLD and len(normalize(text)) <= proto_len + EASY_LEN_SLACK_CHARS:
        return "EASY", score
    return "COMPLEX", score


def is_easy(text: str) -> bool:
    decision, _ = classify(text)
    return decision == "EASY"


def build_easy_system_instruction(
    *,
    user_input: str,
    privacy_context: Dict[str, Any],
    identity_instruction: str,
    bot_name: str,
) -> str:
    """Sandwich rut gon cho duong tat EASY: giu identity + persona + user block,
    khoi reasoning, khong tool. Giong _call_gemini_final nhung thay slot
    reasoning bang marker, khong gan tools."""
    # Import tai day de tranh circular import luc load module (cung tang core).
    from src.core.gemini_pipeline import _prepare_user_context_block

    user_block = _prepare_user_context_block(user_input, privacy_context)
    three = get_three_block_context_prompt()
    three = three.replace("[USER_CONTEXT_BLOCK]", user_block)
    three = three.replace("[REASONING_RESULT]", EASY_NO_REASONING_MARKER)
    three = three.replace("[TOOL_RESULTS]", EASY_NO_TOOLS_MARKER)
    time_ctx = (
        "SYSTEM ALERT: Current Date/Time is "
        f"{datetime.now().strftime('%A, %d %B %Y %H:%M')}.\n\n"
    )
    system = time_ctx + identity_instruction + get_azuris_system_prompt() + "\n\n" + three
    return system.replace("Chad Gibiti", bot_name)
