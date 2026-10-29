"""Tests for generic TableNormalizer + plain-client pipeline."""

from src.services.formatting import (
    TableNormalizer,
    normalize_for_plain_client,
    normalize_table_for_plain_client,
    table_to_plain_text,
)


class TestTableNormalizer:
    def test_basic_pipe_table(self):
        text = "| Tên | Tuổi |\n|---|---|\n| An | 30 |\n| Bình | 25 |"
        res = table_to_plain_text(text)
        assert "```" in res
        assert "Tên" in res and "Tuổi" in res
        assert "An" in res and "Bình" in res
        assert "|" not in res.replace("```", "").split("\n")[1] or " | " in res

    def test_no_outer_pipes(self):
        text = "Name | Age\n--- | ---\nAlice | 30"
        res = normalize_table_for_plain_client(text)
        assert "```" in res
        assert "Alice" in res

    def test_preserves_code_blocks(self):
        text = "```\n| a | b |\n|---|---|\n| 1 | 2 |\n```\nSau bảng."
        res = table_to_plain_text(text)
        # Table trong code giu nguyen, khong boc fence long nhau.
        assert res.count("```") == 2
        assert "| a | b |" in res

    def test_ignores_non_table_pipes(self):
        text = "Dùng lệnh a | b trong shell nhé."
        res = table_to_plain_text(text)
        assert res == text

    def test_strips_markdown_in_cells(self):
        text = "| **Sản phẩm** | Giá |\n|---|---|\n| **Bánh** | `50k` |"
        res = table_to_plain_text(text)
        assert "**" not in res
        assert "`50k`" not in res
        assert "Sản phẩm" in res and "50k" in res

    def test_truncates_long_cells(self):
        normalizer = TableNormalizer(max_col_width=10)
        long_cell = "x" * 50
        text = f"| Col |\n|---|\n| {long_cell} |"
        res = normalizer.normalize(text)
        assert "…" in res
        assert long_cell not in res

    def test_link_cell(self):
        text = "| Tài liệu | Mô tả |\n|---|---|\n| [Docs](https://example.com) | Hay |"
        res = table_to_plain_text(text)
        assert "Docs" in res
        assert "https://example.com" not in res

    def test_combined_latex_and_table(self):
        text = "Giá trị $x^2$:\n\n| x | x² |\n|---|---|\n| 2 | 4 |"
        res = normalize_for_plain_client(text)
        assert "x²" in res
        assert "```" in res
        assert "$" not in res


class TestSplitTextCodeFence:
    def test_split_avoids_cutting_table(self):
        from src.handlers.message_handler import MessageHandler

        handler = MessageHandler.__new__(MessageHandler)
        table = "| A | B |\n|---|---|\n" + "\n".join(f"| {i} | {i} |" for i in range(100))
        text = "Mở đầu\n" + table_to_plain_text(table) + "\nKết thúc."
        chunks = MessageHandler._split_text(handler, text, limit=500)
        assert len(chunks) > 1
        # Moi chunk phai co so fence chan (khong cat giua code block).
        for c in chunks:
            assert c.count("```") % 2 == 0
        joined = "\n".join(chunks)
        assert "Mở đầu" in joined and "Kết thúc." in joined
