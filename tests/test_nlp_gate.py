"""Unit test cho NLP gate (src/core/nlp_gate.py) — chay offline, pure stdlib.

Golden set: cau xa giao that tu log + cau kho tra hinh (fail-open COMPLEX).
Ghi cau "um" (qua ngan, mo ho) bi loai khoi golden: fail-open ve COMPLEX
theo thiet ke an toan, khong phai loi gate.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core import nlp_gate
from src.core.nlp_gate import (
    EASY_GENERATION_CONFIG,
    EASY_THRESHOLD,
    _best_match,
    build_easy_system_instruction,
    classify,
    easy_score,
    is_easy,
)

GOLDEN_EASY = [
    "Chào buổi sáng nhé!",
    "chào bạn",
    "hé lô cả nhà iu",
    "chao ban",
    "chaobuoi sang",
    "bạn khỏe hông",
    "khoẻ không bn",
    "cảm ơn bạn nhiều nhé",
    "tks bn",
    "ok",
    "bye bạn, hẹn gặp lại",
    "ngủ ngon nhé",
    "haha hay quá",
    "bạn tên gì vậy",
    "hi",
    # Chao tieng Anh (di qua map/normalize giong TV).
    "good morning!",
    "thank you so much",
    "bye bye",
    "see you tomorrow",
    "how are you today",
    # Moi ngon ngu 2 mau EASY (ngan + co ten/dau cau).
    "konnichiwa!",
    "ohayou gozaimasu",
    "annyeong!",
    "gamsahamnida",
    "ni hao!",
    "xie xie ni",
    "hola!",
    "buenos días",
    "bonjour!",
    "merci beaucoup",
    "hallo!",
    "guten morgen",
    "olá!",
    "bom dia",
    "privet!",
    "spasibo bolshoe",
    "sawatdee krap!",
    "khop khun kha",
    "halo!",
    "terima kasih banyak",
    "namaste!",
    "dhanyavaad",
    "ciao!",
    "grazie mille",
    "salam!",
    "shukran jazilan",
    "merhaba!",
    "günaydın",
]

GOLDEN_HARD = [
    "chào, tính giúp mình (15*37+8)/4",
    "chào bạn, cho hỏi thời tiết Hà Nội hôm nay?",
    "hello, bạn có nhớ mình thích màu gì không?",
    "cảm ơn, còn kết quả có chia hết cho 7 không?",
    "ok vậy còn vé máy bay thì sao, tìm giúp mình",
    "Tính (15 * 37 + 8) / 4 rồi cho biết có chia hết cho 7 không?",
    "Tra cứu giúp mình thông tin về...",
    "Ghi nhớ giúp mình là mình thích cà phê đen",
    "So sánh giúp mình 2 phương án A và B",
    "vâng, tiếp tục đi",
    "yes",
    "tại sao lại như vậy, giải thích kỹ hơn đi",
    "vẽ giúp mình sơ đồ...",
    "tìm giúp mình 3 quán ăn ngon gần đây",
    # Guard: cau kho co chua tu greeting (map khong duoc kich hoat qua muc).
    "thank you, but what about the result, is it divisible by 7?",
    "good morning, calculate (15*37+8)/4 for me",
    "pizza ngon quá, tìm giúp mình quán gần đây",
    # Guard moi ngon ngu: chao + yeu cau kho -> bat buoc COMPLEX.
    "konnichiwa, (15*37+8)/4 wo keisan shite kudasai",
    "annyeonghaseyo, oneul nalssi eottaeyo?",
    "ni hao, jintian Hanoi de tianqi zenmeyang?",
    "hola, calcula (15*37+8)/4 por favor",
    "bonjour, quelle est la météo à Hanoï aujourd'hui?",
    "hallo, wie ist das Wetter heute in Hanoi?",
    "olá, qual é a previsão do tempo para hoje?",
    "privet, soschitai (15*37+8)/4 pozhaluysta",
    "sawatdee, chuai khit lek (15*37+8)/4 hai noi",
    "halo, tolong hitung (15*37+8)/4 untuk saya",
    "namaste, aaj Hanoi mein mausam kaisa hai?",
    "ciao, quanto fa (15*37+8)/4?",
    "merhaba, (15*37+8)/4 kaç eder?",
    "sabah al-khair, kam natijat (15*37+8)/4?",
]


def test_easy_greetings_routed_easy():
    for text in GOLDEN_EASY:
        decision, score = classify(text)
        assert decision == "EASY", f"{text!r}: got {decision} ({score:.2f})"
        assert is_easy(text)


def test_hard_questions_fail_open_complex():
    for text in GOLDEN_HARD:
        decision, score = classify(text)
        assert decision == "COMPLEX", f"{text!r}: got {decision} ({score:.2f})"
        assert not is_easy(text)


def test_precision_over_recall_no_false_easy():
    fps = [t for t in GOLDEN_HARD if is_easy(t)]
    assert fps == [], f"cau KHO lot sang EASY (nguy hiem): {fps}"


def test_empty_and_long_fail_open():
    assert not is_easy("")
    assert not is_easy("   ")
    assert not is_easy("chào " + "bạn " * 20)  # dai -> auto COMPLEX


def test_length_slack_rule_greeting_plus_question_is_complex():
    # Chao + cau hoi ngan cung ngon ngu: trigram chong lan lon nhung dai hon
    # mau khop nhat qua slack -> bat buoc COMPLEX.
    hard = "annyeonghaseyo, oneul nalssi eottaeyo?"
    score, _ = _best_match(hard)
    assert score >= EASY_THRESHOLD, f"can bang test yeu: score={score:.2f}"
    assert not is_easy(hard)
    # Loi chao don thuan ngan hon slack -> EASY.
    assert is_easy("annyeonghaseyo")
    assert is_easy("xie xie ni")
    assert is_easy("khop khun kha")


def test_deterministic():
    for text in GOLDEN_EASY + GOLDEN_HARD:
        assert easy_score(text) == easy_score(text)


def test_fast_enough_for_hot_path():
    corpus = GOLDEN_EASY + GOLDEN_HARD
    t0 = time.perf_counter()
    for text in corpus:
        is_easy(text)
    avg_ms = (time.perf_counter() - t0) / len(corpus) * 1000
    assert avg_ms < 50, f"gate qua cham cho hot path: {avg_ms:.1f}ms/call"


def test_easy_config_bounds_output():
    assert EASY_GENERATION_CONFIG["max_output_tokens"] <= 1024
    assert "tools" not in EASY_GENERATION_CONFIG  # duong tat khong gan tools
    assert EASY_GENERATION_CONFIG["temperature"] == 0.7


def test_build_easy_system_instruction():
    pctx = {
        "is_admin": False,
        "discord_display_name": "Spike",
        "distinct_user_count": 1,
        "has_other_users": False,
        "admin_cross_user_evidence": "",
        "user_identity": "",
        "bot_name": "Azuris",
    }
    identity = "IDENTITY-CONTRACT"
    system = build_easy_system_instruction(
        user_input="Chào buổi sáng nhé!",
        privacy_context=pctx,
        identity_instruction=identity,
        bot_name="Azuris",
    )
    assert "[USER_CONTEXT_BLOCK]" not in system
    assert "[REASONING_RESULT]" not in system
    assert "[TOOL_RESULTS]" not in system
    assert nlp_gate.EASY_NO_REASONING_MARKER in system
    assert nlp_gate.EASY_NO_TOOLS_MARKER in system
    assert "IDENTITY-CONTRACT" in system
    assert "Spike" in system  # user block giu display name
    assert "Chad Gibiti" not in system  # bot name da replace
    assert "Azuris" in system


if __name__ == "__main__":
    test_easy_greetings_routed_easy()
    test_hard_questions_fail_open_complex()
    test_precision_over_recall_no_false_easy()
    test_empty_and_long_fail_open()
    test_length_slack_rule_greeting_plus_question_is_complex()
    test_deterministic()
    test_fast_enough_for_hot_path()
    test_easy_config_bounds_output()
    test_build_easy_system_instruction()
    print("ALL PASS")
