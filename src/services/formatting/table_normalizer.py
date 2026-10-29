"""Generic Markdown pipe-table normalizer for plain-text clients.

Chuyen doi bang Markdown dang ``| a | b |`` sang dang text thu goi
doc duoc tren cac client khong render table (Discord, CLI, SMS...).
Module nay khong hardcode cho bat ky client cu the nao — client chi
can goi :class:`TableNormalizer` hoac ham tien ich ben duoi voi preset
phu hop.

Output mac dinh la bang ASCII monospaced boc trong code fence
(````` ``` `````) de giu can cot tren client co font monospace.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

# Separator row nhu |---|---|, |:---|---:| hoac khong co pipe ngoai.
_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")
# Chi bao ve fenced block ```...``` (xem _protect).
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
_PLACEHOLDER = "\x00TABLE_CODE_{idx}\x00"

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_DECOR_RE = re.compile(r"(\*\*|__|\*|_|`|~~|\|\|)")


def _split_row(line: str) -> List[str]:
    """Split mot dong table theo pipe, ho tro escape \\|."""
    s = line.strip()
    # Bo pipe ngoai neu co de tranh cot rong 2 dau.
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    # Split theo pipe khong bi escape.
    parts = re.split(r"(?<!\\)\|", s)
    return [p.replace("\\|", "|").strip() for p in parts]


def _is_separator(line: str) -> bool:
    stripped = line.strip()
    if "-" not in stripped:
        return False
    if "|" not in stripped and stripped.strip(":- ").count("-") == 0:
        return False
    if not _SEPARATOR_RE.fullmatch(line):
        return False
    # Sau khi bo het ky tu hop le phai rong.
    core = re.sub(r"[\s:\-|]", "", stripped)
    return core == ""


def _clean_cell(cell: str, max_col_width: int) -> str:
    text = (cell or "").strip()
    # [text](url) -> "text" (giu url neu khac text? plain-text nen giu gon).
    text = _LINK_RE.sub(r"\1", text)
    text = _MD_DECOR_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_col_width:
        text = text[: max_col_width - 1].rstrip() + "…"
    return text


class TableNormalizer:
    """Chuyen bang Markdown pipe-table sang text doc duoc cho plain-text client."""

    def __init__(
        self,
        *,
        preserve_code_blocks: bool = True,
        max_col_width: int = 30,
        max_columns: int = 10,
    ):
        self.preserve_code_blocks = preserve_code_blocks
        self.max_col_width = max(5, min(max_col_width, 60))
        self.max_columns = max(1, min(max_columns, 20))

    def normalize(self, text: str) -> str:
        """Chuyen moi pipe-table trong text sang ASCII code-fence block."""
        if not text or not isinstance(text, str):
            return text or ""
        if "|" not in text:
            return text

        code_blocks: List[str] = []
        working = text
        if self.preserve_code_blocks:
            working, code_blocks = self._protect(working)

        lines = working.split("\n")
        out: List[str] = []
        i = 0
        while i < len(lines):
            block = self._collect_candidate(lines, i)
            if block is not None:
                parsed = self._try_parse(block)
                if parsed is not None:
                    header, rows = parsed
                    out.append(self._render(header, rows))
                    i += len(block)
                    continue
            out.append(lines[i])
            i += 1

        result = "\n".join(out)
        if self.preserve_code_blocks:
            result = self._restore(result, code_blocks)
        return result

    def _collect_candidate(self, lines: List[str], start: int) -> Optional[List[str]]:
        """Gom khoi lien tiep cac dong chua '|' (toi da header + sep + body)."""
        if "|" not in lines[start]:
            return None
        # Can it nhat 2 dong: header + separator.
        if start + 1 >= len(lines):
            return None
        if "|" not in lines[start + 1] or not _is_separator(lines[start + 1]):
            return None
        block = [lines[start], lines[start + 1]]
        j = start + 2
        while j < len(lines) and "|" in lines[j] and lines[j].strip() != "":
            # Gap dong separator thu 2 -> dung (tranh gom 2 bang lien nhau sai).
            if _is_separator(lines[j]):
                break
            block.append(lines[j])
            j += 1
            # Chan bang qua dai de tranh nuot ca message.
            if len(block) > 52:
                break
        return block

    def _try_parse(self, block: List[str]) -> Optional[Tuple[List[str], List[List[str]]]]:
        if len(block) < 2:
            return None
        header_cells = _split_row(block[0])
        sep_cells = _split_row(block[1])
        if not header_cells:
            return None
        # Moi cot separator phai chua it nhat 1 dau '-'.
        if any("-" not in c for c in sep_cells):
            return None
        ncols = max(len(header_cells), len(sep_cells))
        if ncols > self.max_columns or ncols == 0:
            return None
        # Header rong toan bo -> khong phai bang du lieu.
        if all(c.strip() == "" for c in header_cells):
            return None

        def norm(cells: List[str]) -> List[str]:
            cells = (cells + [""] * ncols)[:ncols]
            return [_clean_cell(c, self.max_col_width) for c in cells]

        header = norm(header_cells)
        rows = [norm(_split_row(line)) for line in block[2:]]
        return header, rows

    def _render(self, header: List[str], rows: List[List[str]]) -> str:
        ncols = len(header)
        widths = [len(c) for c in header]
        for row in rows:
            for idx in range(ncols):
                widths[idx] = max(widths[idx], len(row[idx]))
        widths = [min(w, self.max_col_width) for w in widths]

        def fmt(cells: List[str]) -> str:
            return " | ".join(c.ljust(widths[idx]) for idx, c in enumerate(cells)).rstrip()

        sep = "-+-".join("-" * w for w in widths)
        body = [fmt(header), sep]
        body.extend(fmt(r) for r in rows)
        return "```\n" + "\n".join(body) + "\n```"

    @staticmethod
    def _protect(text: str) -> Tuple[str, List[str]]:
        blocks: List[str] = []

        def repl(m: re.Match) -> str:
            blocks.append(m.group(0))
            return _PLACEHOLDER.format(idx=len(blocks) - 1)

        # Chi bao ve fenced block ```...```. Inline `...` giu nguyen de
        # _clean_cell boc tach noi dung that (vd: `50k` -> 50k) thay vi
        # nuot placeholder. Inline code hiem khi chua ca bang 2 dong
        # header + separator nen rui ro false-positive khong dang ke.
        text = _CODE_BLOCK_RE.sub(repl, text)
        return text, blocks

    @staticmethod
    def _restore(text: str, blocks: List[str]) -> str:
        for idx, block in enumerate(blocks):
            text = text.replace(_PLACEHOLDER.format(idx=idx), block)
        return text


_DEFAULT_TABLE_NORMALIZER = TableNormalizer()


def table_to_plain_text(text: str) -> str:
    """Chuyen pipe-table sang ASCII block bang cau hinh mac dinh."""
    return _DEFAULT_TABLE_NORMALIZER.normalize(text)


def normalize_table_for_plain_client(text: str) -> str:
    """Alias tuong thich: dung khi client khong render Markdown table."""
    return _DEFAULT_TABLE_NORMALIZER.normalize(text)
