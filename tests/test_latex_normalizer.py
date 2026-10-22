"""Tests for LatexNormalizer OOP service."""

from src.services.formatting import LatexNormalizer, latex_to_markdown, normalize_latex_for_unsupported_client


class TestLatexNormalizerOOP:
    def test_basic_powers_and_subscripts(self):
        normalizer = LatexNormalizer()
        text = "Phương trình $x^2 + 2x + 1 = 0$ và nghiệm $x_1, x_2$."
        res = normalizer.normalize(text)
        assert res == "Phương trình x² + 2x + 1 = 0 và nghiệm x₁, x₂."

    def test_polynomial_and_roots(self):
        normalizer = LatexNormalizer()
        text = (
            "Nghiệm của phương trình $x^6 - 3x^4 + 2x^2 = 0$ là:\n"
            "$x = 0$\n"
            "$x = 1$\n"
            "$x = -1$\n"
            "$x = \\sqrt{2} \\approx 1.414$\n"
            "$x = -\\sqrt{2} \\approx -1.414$"
        )
        res = normalizer.normalize(text)
        assert "x⁶ - 3x⁴ + 2x² = 0" in res
        assert "x = 0" in res
        assert "x = 1" in res
        assert "x = -1" in res
        assert "x = √2 ≈ 1.414" in res
        assert "x = -√2 ≈ -1.414" in res
        assert "$" not in res

    def test_integral_and_fractions(self):
        text = "Tích phân hàm số $x^2$ từ $0$ đến $1$ là: $\\frac{1}{3}$"
        res = latex_to_markdown(text)
        assert res == "Tích phân hàm số x² từ 0 đến 1 là: 1/3"

    def test_greek_letters_and_constants(self):
        text = "Góc $\\theta = \\frac{\\pi}{2}$ có $\\sin(\\theta) = 1$."
        res = latex_to_markdown(text)
        assert res == "Góc θ = π/2 có sin(θ) = 1."

    def test_naked_latex_commands(self):
        text = "Giá trị là \\sqrt{2} \\approx 1.414 và \\pi."
        res = latex_to_markdown(text)
        assert res == "Giá trị là √2 ≈ 1.414 và π."

    def test_preserves_currency(self):
        text = "Sản phẩm A giá $50, còn sản phẩm B giá $100."
        res = latex_to_markdown(text)
        assert "$50" in res
        assert "$100" in res

    def test_preserves_code_blocks(self):
        text = "Trong code: `var $x = 10;` và ngoài code: $x^2$."
        res = latex_to_markdown(text)
        assert "`var $x = 10;`" in res
        assert "x²" in res

    def test_multiline_code_block_preserved(self):
        text = (
            "```python\n"
            "# $x = 10$\n"
            "def foo():\n"
            "    return $y\n"
            "```\n"
            "Ngoài code: $x = \\sqrt{4} = 2$"
        )
        res = latex_to_markdown(text)
        assert "```python\n# $x = 10$\ndef foo():\n    return $y\n```" in res
        assert "x = √4 = 2" in res

    def test_parenthesis_math_delimiters(self):
        text = "Biểu thức \\(x^3 + 1\\) và \\[E = mc^2\\]"
        res = normalize_latex_for_unsupported_client(text)
        assert "x³ + 1" in res
        assert "E = mc²" in res
        assert "\\(" not in res
        assert "\\[" not in res

    def test_custom_normalizer_configuration(self):
        custom_symbols = {"custom_op": "⚡"}
        normalizer = LatexNormalizer(symbols_map=custom_symbols)
        res = normalizer.normalize("Kết quả: $\\custom_op$")
        assert res == "Kết quả: ⚡"
