"""Combined formatter for clients without rich Markdown/LaTeX rendering.

Vi du: Discord, CLI, SMS... — noi pipe-table khong can cot va
``$...$`` khong hien cong thuc. Module generic: khong hardcode ten
client, chi dinh nghia "plain client" = client can text don gian.
"""

from __future__ import annotations

from src.services.formatting.latex_normalizer import LatexNormalizer
from src.services.formatting.table_normalizer import TableNormalizer


class PlainClientNormalizer:
    """Gom Latex + Table normalize thanh 1 pipeline duy nhat."""

    def __init__(
        self,
        latex: LatexNormalizer | None = None,
        table: TableNormalizer | None = None,
    ):
        self.latex = latex or LatexNormalizer()
        self.table = table or TableNormalizer()

    def normalize(self, text: str) -> str:
        if not text or not isinstance(text, str):
            return text or ""
        # Table truoc de giu so lieu nguyen truoc khi latex lam sach ky tu.
        text = self.table.normalize(text)
        text = self.latex.normalize(text)
        return text


_DEFAULT_PLAIN_NORMALIZER = PlainClientNormalizer()


def normalize_for_plain_client(text: str) -> str:
    """Pipeline chuan cho moi plain-text client (Discord/CLI/SMS...)."""
    return _DEFAULT_PLAIN_NORMALIZER.normalize(text)


def normalize_for_unsupported_client(text: str) -> str:
    """Alias giu tuong thich voi ten interface cu."""
    return _DEFAULT_PLAIN_NORMALIZER.normalize(text)
