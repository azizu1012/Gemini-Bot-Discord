"""LaTeX to friendly Unicode/Markdown normalizer for clients without native LaTeX support.

Cung cấp lớp LatexNormalizer chuyển đổi các công thức LaTeX sang ký tự Unicode
và cú pháp Markdown dễ đọc cho các client như Discord, CLI, SMS...
Các client có hỗ trợ LaTeX (Web, KaTeX renderer...) sẽ không dùng module này.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from src.services.formatting.symbols import (
    GREEK_MAP,
    MATH_FUNCTIONS,
    MATH_WORDS,
    SUBSCRIPT_MAP,
    SUPERSCRIPT_MAP,
    SYMBOLS_MAP,
)


class LatexNormalizer:
    """Bộ chuyển đổi công thức LaTeX sang ký tự Unicode và Markdown thân thiện."""

    def __init__(
        self,
        *,
        preserve_code_blocks: bool = True,
        max_nested_levels: int = 3,
        superscript_map: Optional[dict[str, str]] = None,
        subscript_map: Optional[dict[str, str]] = None,
        greek_map: Optional[dict[str, str]] = None,
        symbols_map: Optional[dict[str, str]] = None,
        math_functions: Optional[set[str]] = None,
    ):
        self.preserve_code_blocks = preserve_code_blocks
        self.max_nested_levels = max(1, min(max_nested_levels, 10))
        self.superscript_map = superscript_map or SUPERSCRIPT_MAP
        self.subscript_map = subscript_map or SUBSCRIPT_MAP
        self.greek_map = greek_map or GREEK_MAP
        self.symbols_map = symbols_map or SYMBOLS_MAP
        self.math_functions = math_functions or MATH_FUNCTIONS

    def normalize(self, text: str) -> str:
        """Chuẩn hóa chuỗi văn bản chứa LaTeX sang định dạng Markdown/Unicode thân thiện."""
        if not text or not isinstance(text, str):
            return text or ""

        # Kiểm tra nhanh: nếu không có bất kỳ dấu hiệu toán LaTeX nào thì trả về nguyên bản
        if "$" not in text and "\\" not in text and "\\[" not in text:
            return text

        code_blocks: List[str] = []
        working_text = text
        if self.preserve_code_blocks:
            working_text, code_blocks = self._protect_code_blocks(text)

        # 1. Xử lý Display Math dạng block: $$...$$ hoặc \[...\]
        working_text = re.sub(
            r"\$\$([\s\S]+?)\$\$",
            lambda m: self._format_display_math(m.group(1)),
            working_text,
        )
        working_text = re.sub(
            r"\\\[([\s\S]+?)\\\]",
            lambda m: self._format_display_math(m.group(1)),
            working_text,
        )

        # 2. Xử lý Inline Math dạng: \( ... \)
        working_text = re.sub(
            r"\\\(([\s\S]+?)\\\)",
            lambda m: self._clean_math_expression(m.group(1).strip()),
            working_text,
        )

        # 3. Xử lý Inline Math dạng: $ ... $
        working_text = re.sub(
            r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)",
            self._replace_dollar_math,
            working_text,
        )

        # 4. Xử lý các lệnh LaTeX còn sót lại đứng trần ngoài dấu $
        if "\\" in working_text:
            working_text = self._replace_naked_latex(working_text)

        if self.preserve_code_blocks:
            working_text = self._restore_code_blocks(working_text, code_blocks)

        return working_text

    def _format_display_math(self, raw_body: str) -> str:
        cleaned = self._clean_math_expression(raw_body.strip())
        return f"\n{cleaned}\n" if cleaned else ""

    def _replace_dollar_math(self, match: re.Match) -> str:
        body = match.group(1)
        if self._is_math_content(body):
            return self._clean_math_expression(body)
        # Giữ nguyên nếu là ngữ cảnh tiền tệ (ví dụ khoảng cách giữa 2 mốc giá $50 và $100)
        return match.group(0)

    def _replace_naked_latex(self, text: str) -> str:
        text = self._replace_fractions(text)
        text = self._replace_roots(text)
        for cmd, sym in self.symbols_map.items():
            text = re.sub(rf"\\{cmd}(?![a-zA-Z])", sym, text)
        for cmd, sym in self.greek_map.items():
            text = re.sub(rf"\\{cmd}(?![a-zA-Z])", sym, text)
        for fn in self.math_functions:
            text = re.sub(rf"\\{fn}(?![a-zA-Z])", fn, text)
        return text

    def _clean_math_expression(self, math_text: str) -> str:
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

        # 3. Phân số và căn thức lồng nhau
        text = self._replace_fractions(text)
        text = self._replace_roots(text)

        # 4. Ký hiệu toán học, chữ Hy Lạp và hàm lượng giác
        for cmd, sym in self.symbols_map.items():
            text = re.sub(rf"\\{cmd}(?![a-zA-Z])", sym, text)
        for cmd, sym in self.greek_map.items():
            text = re.sub(rf"\\{cmd}(?![a-zA-Z])", sym, text)
        for fn in self.math_functions:
            text = re.sub(rf"\\{fn}(?![a-zA-Z])", fn, text)

        # 5. Mũ và chỉ số dưới
        text = self._replace_scripts(text)

        # 6. Thoát các ký tự phân cách vô hại: \{ \} \, \; \: \!
        text = re.sub(r"\\([{}])", r"\1", text)
        text = re.sub(r"\\[,;:!]", " ", text)
        text = re.sub(r"\\(?=\s|$)", "", text)

        # 7. Dọn khoảng trắng thừa
        return re.sub(r"[ \t]+", " ", text).strip()

    def _replace_fractions(self, text: str) -> str:
        for _ in range(self.max_nested_levels):
            text = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", self._format_fraction_match, text)
        return text

    def _replace_roots(self, text: str) -> str:
        for _ in range(self.max_nested_levels):
            text = re.sub(r"\\sqrt(?:\[([^{}]+)\])?\{([^{}]+)\}", self._format_root_match, text)
        return text

    def _replace_scripts(self, text: str) -> str:
        # Lũy thừa ^{...} hoặc ^x
        text = re.sub(r"\^\{([^{}]+)\}", lambda m: self._to_superscript(m.group(1)), text)
        text = re.sub(r"\^([0-9a-zA-Z+\-])", lambda m: self._to_superscript(m.group(1)), text)
        # Chỉ số dưới _{...} hoặc _x
        text = re.sub(r"_\{([^{}]+)\}", lambda m: self._to_subscript(m.group(1)), text)
        text = re.sub(r"_([0-9a-zA-Z+\-])", lambda m: self._to_subscript(m.group(1)), text)
        return text

    def _to_superscript(self, s: str) -> str:
        cleaned = s.strip()
        if cleaned and all(c in self.superscript_map for c in cleaned):
            return "".join(self.superscript_map[c] for c in cleaned)
        return f"^{s}" if len(s) == 1 else f"^({s})"

    def _to_subscript(self, s: str) -> str:
        cleaned = s.strip()
        if cleaned and all(c in self.subscript_map for c in cleaned):
            return "".join(self.subscript_map[c] for c in cleaned)
        return f"_{s}" if len(s) == 1 else f"_({s})"

    @staticmethod
    def _format_fraction_match(match: re.Match) -> str:
        num = match.group(1).strip()
        den = match.group(2).strip()
        if any(op in num for op in "+- "):
            num = f"({num})"
        if any(op in den for op in "+- "):
            den = f"({den})"
        return f"{num}/{den}"

    def _format_root_match(self, match: re.Match) -> str:
        deg = match.group(1)
        body = match.group(2).strip()
        if deg:
            deg = deg.strip()
            sup_deg = "".join(self.superscript_map.get(c, c) for c in deg)
            root_symbol = f"{sup_deg}√"
        else:
            root_symbol = "√"

        if len(body) == 1 or body.isdigit():
            return f"{root_symbol}{body}"
        return f"{root_symbol}({body})"

    @staticmethod
    def _is_math_content(content: str) -> bool:
        """Kiểm tra nội dung trong cặp $...$ có phải là toán học hay chỉ là giá tiền/văn bản."""
        if "\\" in content:
            return True
        if any(ch in content for ch in "^_{}="):
            return True
        cleaned = content.strip()
        if not cleaned:
            return False

        # 1. Số nguyên hoặc số thực/thập phân (có thể kèm dấu âm/dương, dấu chấm lửng ... hoặc …)
        if re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?(?:\.{2,3}|…)?|\.\d+(?:\.{2,3}|…)?)", cleaned):
            return True

        # 2. Biểu thức đại số / toán học tổng quát
        if re.fullmatch(r"[0-9a-zA-Z+\-*/()=.,\s^_{}±∓≤≥≠≈~<>\u00B2\u00B3\u2070-\u209F\u2200-\u22FF]+", cleaned):
            words = re.findall(r"[a-zA-Z\u00C0-\u024F\u1EA0-\u1EF9]+", cleaned)
            # Nếu chứa từ tiếng Việt (có dấu) -> câu văn tự nhiên giữa 2 dấu $ (vd: $50 và $100)
            for w in words:
                if re.search(r"[\u00C0-\u024F\u1EA0-\u1EF9]", w):
                    return False
            # Nếu chứa từ dài (>2 ký tự) không nằm trong danh mục hàm/thuật ngữ toán học (vd: and, apple, price)
            long_words = [w.lower() for w in words if len(w) > 2 and w.lower() not in MATH_WORDS]
            if long_words:
                return False
            return True

        return False

    @staticmethod
    def _protect_code_blocks(text: str) -> Tuple[str, List[str]]:
        code_blocks: List[str] = []

        def repl_block(m: re.Match) -> str:
            code_blocks.append(m.group(0))
            return f"\x00CODE_BLOCK_{len(code_blocks) - 1}\x00"

        # Multi-line code block ```...```
        text = re.sub(r"```[\s\S]*?```", repl_block, text)
        # Inline code `...`
        text = re.sub(r"`[^`\n]+?`", repl_block, text)
        return text, code_blocks

    @staticmethod
    def _restore_code_blocks(text: str, code_blocks: List[str]) -> str:
        for i, block in enumerate(code_blocks):
            text = text.replace(f"\x00CODE_BLOCK_{i}\x00", block)
        return text


# Default Singleton Instance for direct module calls
_DEFAULT_NORMALIZER = LatexNormalizer()


def latex_to_markdown(text: str) -> str:
    """Chuyển đổi chuỗi LaTeX sang Markdown/Unicode bằng cấu hình chuẩn."""
    return _DEFAULT_NORMALIZER.normalize(text)


def normalize_latex_for_unsupported_client(text: str) -> str:
    """Tương thích ngược với interface cũ của Discord Gateway."""
    return _DEFAULT_NORMALIZER.normalize(text)
