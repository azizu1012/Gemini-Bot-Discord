"""LaTeX to friendly Unicode/Markdown normalizer for clients that do not support LaTeX.

Mục đích: Chuyển đổi các công thức và ký hiệu LaTeX sang ký tự Unicode hoặc định dạng
Markdown dễ đọc trên các giao diện chat không hỗ trợ MathJax/KaTeX (ví dụ: Discord).
Các client hỗ trợ LaTeX (Web, KaTeX renderer...) sẽ bỏ qua module này và giữ nguyên payload.
"""

from __future__ import annotations

import re
from typing import List, Tuple

# Bảng ký tự Unicode cho số mũ
SUPERSCRIPT_MAP: dict[str, str] = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
    "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
    "n": "ⁿ", "i": "ⁱ", "x": "ˣ", "y": "ʸ", "a": "ᵃ", "b": "ᵇ",
    "c": "ᶜ", "d": "ᵈ", "e": "ᵉ", "f": "ᶠ", "g": "ᵍ", "h": "ʰ",
    "j": "ʲ", "k": "ᵏ", "l": "ˡ", "m": "ᵐ", "o": "ᵒ", "p": "ᵖ",
    "r": "ʳ", "s": "ˢ", "t": "ᵗ", "u": "ᵘ", "v": "ᵛ", "w": "ʷ",
}

# Bảng ký tự Unicode cho chỉ số dưới
SUBSCRIPT_MAP: dict[str, str] = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
    "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
    "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎",
    "a": "ₐ", "e": "ₑ", "h": "ₕ", "i": "ᵢ", "j": "ⱼ", "k": "ₖ",
    "l": "ₗ", "m": "ₘ", "n": "ₙ", "o": "ₒ", "p": "ₚ", "r": "ᵣ",
    "s": "ₛ", "t": "ₜ", "u": "ᵤ", "v": "ᵥ", "x": "ₓ",
}

# Ký tự Hy Lạp phổ biến
GREEK_MAP: dict[str, str] = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "Delta": "Δ",
    "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ", "eta": "η",
    "theta": "θ", "Theta": "Θ", "vartheta": "θ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "Lambda": "Λ", "mu": "μ", "nu": "ν", "xi": "ξ", "Xi": "Ξ",
    "pi": "π", "Pi": "Π", "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ",
    "sigma": "σ", "Sigma": "Σ", "tau": "τ", "upsilon": "υ", "Upsilon": "Υ",
    "phi": "φ", "Phi": "Φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "Psi": "Ψ",
    "omega": "ω", "Omega": "Ω",
}

# Ký hiệu toán học, toán tử, logic và tập hợp
SYMBOLS_MAP: dict[str, str] = {
    "approx": "≈", "sim": "~", "simeq": "≃", "cong": "≅", "equiv": "≡",
    "neq": "≠", "ne": "≠", "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥",
    "ll": "≪", "gg": "≫", "pm": "±", "mp": "∓", "times": "×", "div": "÷",
    "cdot": "·", "circ": "°", "bullet": "•", "star": "⋆",
    "infty": "∞", "forall": "∀", "exists": "∃", "nexists": "∄",
    "in": "∈", "notin": "∉", "ni": "∋", "subset": "⊂", "subseteq": "⊆",
    "supset": "⊃", "supseteq": "⊇", "cup": "∪", "cap": "∩", "setminus": "∖",
    "to": "→", "rightarrow": "→", "leftarrow": "←", "Rightarrow": "⇒",
    "Leftarrow": "⇐", "Leftrightarrow": "⇔", "iff": "⇔", "mapsto": "↦",
    "int": "∫", "iint": "∬", "iiint": "∭", "oint": "∮",
    "sum": "∑", "prod": "∏", "coprod": "∐",
    "partial": "∂", "nabla": "∇",
    "quad": "  ", "qquad": "    ",
    "dots": "…", "cdots": "…", "ldots": "…", "ddots": "⋱", "vdots": "⋮",
    "degree": "°", "angle": "∠", "perp": "⊥", "parallel": "∥",
    "emptyset": "∅", "varnothing": "∅",
}

MATH_FUNCTIONS: set[str] = {
    "sin", "cos", "tan", "cot", "sec", "csc",
    "arcsin", "arccos", "arctan", "arccot",
    "sinh", "cosh", "tanh", "coth",
    "ln", "log", "exp", "lim", "max", "min",
    "det", "gcd", "deg", "dim", "ker", "hom",
}


def _to_superscript(s: str) -> str:
    cleaned = s.strip()
    if cleaned and all(c in SUPERSCRIPT_MAP for c in cleaned):
        return "".join(SUPERSCRIPT_MAP[c] for c in cleaned)
    return f"^{s}" if len(s) == 1 else f"^({s})"


def _to_subscript(s: str) -> str:
    cleaned = s.strip()
    if cleaned and all(c in SUBSCRIPT_MAP for c in cleaned):
        return "".join(SUBSCRIPT_MAP[c] for c in cleaned)
    return f"_{s}" if len(s) == 1 else f"_({s})"


def _replace_frac(match: re.Match) -> str:
    num = match.group(1).strip()
    den = match.group(2).strip()
    if any(op in num for op in "+- "):
        num = f"({num})"
    if any(op in den for op in "+- "):
        den = f"({den})"
    return f"{num}/{den}"


def _replace_sqrt(match: re.Match) -> str:
    deg = match.group(1)
    body = match.group(2).strip()
    if deg:
        deg = deg.strip()
        sup_deg = "".join(SUPERSCRIPT_MAP.get(c, c) for c in deg)
        root_symbol = f"{sup_deg}√"
    else:
        root_symbol = "√"

    if len(body) == 1 or body.isdigit():
        return f"{root_symbol}{body}"
    return f"{root_symbol}({body})"


def _clean_math_expression(math_text: str) -> str:
    """Chuyển đổi một biểu thức toán LaTeX đơn lẻ sang chuỗi Unicode thân thiện."""
    text = math_text.strip()
    if not text:
        return ""

    # 1. Bỏ \left, \right
    text = re.sub(r"\\left([(\[{|.])", r"\1", text)
    text = re.sub(r"\\right([)\]}|.])", r"\1", text)

    # 2. Text styling: \text{...}, \mathrm{...}, \mathbf{...}, \mathit{...}
    text = re.sub(r"\\mathbf\{([^{}]+)\}", r"**\1**", text)
    text = re.sub(r"\\mathit\{([^{}]+)\}", r"*\1*", text)
    text = re.sub(r"\\(?:text|mathrm|operatorname)\{([^{}]+)\}", r"\1", text)

    # 3. Phân số \frac{tử}{mẫu} (hỗ trợ tối đa 3 cấp lồng nhau)
    for _ in range(3):
        text = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", _replace_frac, text)

    # 4. Căn thức \sqrt[n]{x} và \sqrt{x}
    for _ in range(3):
        text = re.sub(r"\\sqrt(?:\[([^{}]+)\])?\{([^{}]+)\}", _replace_sqrt, text)

    # 5. Các ký hiệu toán và chữ Hy Lạp
    for cmd, sym in SYMBOLS_MAP.items():
        text = re.sub(rf"\\{cmd}(?![a-zA-Z])", sym, text)
    for cmd, sym in GREEK_MAP.items():
        text = re.sub(rf"\\{cmd}(?![a-zA-Z])", sym, text)
    for fn in MATH_FUNCTIONS:
        text = re.sub(rf"\\{fn}(?![a-zA-Z])", fn, text)

    # 6. Lũy thừa ^{...} hoặc ^x
    text = re.sub(r"\^\{([^{}]+)\}", lambda m: _to_superscript(m.group(1)), text)
    text = re.sub(r"\^([0-9a-zA-Z+\-])", lambda m: _to_superscript(m.group(1)), text)

    # 7. Chỉ số dưới _{...} hoặc _x
    text = re.sub(r"_\{([^{}]+)\}", lambda m: _to_subscript(m.group(1)), text)
    text = re.sub(r"_([0-9a-zA-Z+\-])", lambda m: _to_subscript(m.group(1)), text)

    # 8. Bỏ các dấu gạch chéo thoát ký tự: \{ \} \, \; \: \!
    text = re.sub(r"\\([{}])", r"\1", text)
    text = re.sub(r"\\[,;:!]", " ", text)
    text = re.sub(r"\\(?=\s|$)", "", text)

    # 9. Dọn dẹp khoảng trắng
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text


def _is_math_content(content: str) -> bool:
    """Kiểm tra nội dung trong cặp $...$ có phải là toán học hay chỉ là giá tiền/văn bản."""
    # Có lệnh LaTeX (\sqrt, \approx...)
    if "\\" in content:
        return True
    # Có ký hiệu đặc trưng toán học
    if any(ch in content for ch in "^_{}="):
        return True
    # Là biến hoặc biểu thức ngắn (vd: x, y, 0, 1, -1, 2x, x+1)
    cleaned = content.strip()
    if re.fullmatch(r"[+-]?(?:\d+|[a-zA-Z]|\d*[a-zA-Z](?:[0-9a-zA-Z+\-*/()= ])*)", cleaned):
        return True
    return False


def _protect_code_blocks(text: str) -> Tuple[str, List[str]]:
    """Tạm thời trích xuất các khối code markdown để không can thiệp vào code gốc."""
    code_blocks: List[str] = []

    def repl_block(m: re.Match) -> str:
        code_blocks.append(m.group(0))
        return f"\x00CODE_BLOCK_{len(code_blocks) - 1}\x00"

    # Multi-line code block ```...```
    text = re.sub(r"```[\s\S]*?```", repl_block, text)
    # Inline code `...`
    text = re.sub(r"`[^`\n]+?`", repl_block, text)
    return text, code_blocks


def _restore_code_blocks(text: str, code_blocks: List[str]) -> str:
    """Khôi phục lại các khối code markdown nguyên vẹn."""
    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODE_BLOCK_{i}\x00", block)
    return text


def normalize_latex_for_unsupported_client(text: str) -> str:
    """Chuẩn hóa toàn bộ chuỗi LaTeX sang Unicode/Markdown cho client không hỗ trợ LaTeX.

    Dùng riêng cho các client như Discord. Giữ nguyên code blocks và các biểu tượng tiền tệ.
    """
    if not text or not isinstance(text, str):
        return text or ""

    # Nếu văn bản hoàn toàn không chứa bất kỳ dấu vết LaTeX hay toán nào thì trả về luôn
    if "$" not in text and "\\" not in text and "\\[" not in text:
        return text

    # 1. Bảo vệ các khối code markdown
    working_text, code_blocks = _protect_code_blocks(text)

    # 2. Xử lý Display Math dạng block: $$...$$ hoặc \[...\]
    def _display_math_repl(m: re.Match) -> str:
        body = m.group(1).strip()
        cleaned = _clean_math_expression(body)
        return f"\n{cleaned}\n" if cleaned else ""

    working_text = re.sub(r"\$\$([\s\S]+?)\$\$", _display_math_repl, working_text)
    working_text = re.sub(r"\\\[([\s\S]+?)\\\]", _display_math_repl, working_text)

    # 3. Xử lý Inline Math dạng: \( ... \)
    def _paren_math_repl(m: re.Match) -> str:
        body = m.group(1).strip()
        return _clean_math_expression(body)

    working_text = re.sub(r"\\\(([\s\S]+?)\\\)", _paren_math_repl, working_text)

    # 4. Xử lý Inline Math dạng: $ ... $
    def _dollar_math_repl(m: re.Match) -> str:
        body = m.group(1)
        if _is_math_content(body):
            return _clean_math_expression(body)
        # Nếu không phải toán học (ví dụ cụm từ giữa 2 mốc giá tiền), giữ nguyên
        return m.group(0)

    # Match $...$ nhưng không match $$...$$
    working_text = re.sub(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", _dollar_math_repl, working_text)

    # 5. Dọn dẹp các lệnh LaTeX còn sót lại đứng trần ngoài dấu $ (ví dụ \sqrt{2}, \approx)
    if "\\" in working_text:
        # Frac
        working_text = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", _replace_frac, working_text)
        # Sqrt
        working_text = re.sub(r"\\sqrt(?:\[([^{}]+)\])?\{([^{}]+)\}", _replace_sqrt, working_text)
        # Symbols & Greek
        for cmd, sym in SYMBOLS_MAP.items():
            working_text = re.sub(rf"\\{cmd}(?![a-zA-Z])", sym, working_text)
        for cmd, sym in GREEK_MAP.items():
            working_text = re.sub(rf"\\{cmd}(?![a-zA-Z])", sym, working_text)
        for fn in MATH_FUNCTIONS:
            working_text = re.sub(rf"\\{fn}(?![a-zA-Z])", fn, working_text)

    # 6. Khôi phục code blocks
    return _restore_code_blocks(working_text, code_blocks)
