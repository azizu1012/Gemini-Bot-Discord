"""Unicode symbol mapping tables for mathematical expressions.

Tách biệt hoàn toàn phần dữ liệu tra cứu ký tự (Data layer)
khỏi logic phân tích ngữ pháp (Transformation logic).
"""

from __future__ import annotations

# Bảng ký tự Unicode cho số mũ (Superscript)
SUPERSCRIPT_MAP: dict[str, str] = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
    "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
    "n": "ⁿ", "i": "ⁱ", "x": "ˣ", "y": "ʸ", "a": "ᵃ", "b": "ᵇ",
    "c": "ᶜ", "d": "ᵈ", "e": "ᵉ", "f": "ᶠ", "g": "ᵍ", "h": "ʰ",
    "j": "ʲ", "k": "ᵏ", "l": "ˡ", "m": "ᵐ", "o": "ᵒ", "p": "ᵖ",
    "r": "ʳ", "s": "ˢ", "t": "ᵗ", "u": "ᵘ", "v": "ᵛ", "w": "ʷ",
}

# Bảng ký tự Unicode cho chỉ số dưới (Subscript)
SUBSCRIPT_MAP: dict[str, str] = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
    "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
    "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎",
    "a": "ₐ", "e": "ₑ", "h": "ₕ", "i": "ᵢ", "j": "ⱼ", "k": "ₖ",
    "l": "ₗ", "m": "ₘ", "n": "ₙ", "o": "ₒ", "p": "ₚ", "r": "ᵣ",
    "s": "ₛ", "t": "ₜ", "u": "ᵤ", "v": "ᵥ", "x": "ₓ",
}

# Ký tự Hy Lạp thường & hoa phổ biến
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

# Ký hiệu toán học, toán tử, quan hệ, logic và tập hợp
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
    "implies": "⇒", "impliedby": "⇐",
    "Longrightarrow": "⇒", "Longleftarrow": "⇐", "Longleftrightarrow": "⇔",
    "longrightarrow": "→", "longleftarrow": "←",
    "therefore": "∴", "because": "∵",
    "land": "∧", "lor": "∨", "neg": "¬",
    "int": "∫", "iint": "∬", "iiint": "∭", "oint": "∮",
    "sum": "∑", "prod": "∏", "coprod": "∐",
    "partial": "∂", "nabla": "∇",
    "quad": "  ", "qquad": "    ",
    "dots": "…", "cdots": "…", "ldots": "…", "ddots": "⋱", "vdots": "⋮",
    "degree": "°", "angle": "∠", "perp": "⊥", "parallel": "∥",
    "emptyset": "∅", "varnothing": "∅",
}

# Các hàm toán học chuẩn được phép loại bỏ dấu gạch chéo
MATH_FUNCTIONS: set[str] = {
    "sin", "cos", "tan", "cot", "sec", "csc",
    "arcsin", "arccos", "arctan", "arccot",
    "sinh", "cosh", "tanh", "coth",
    "ln", "log", "exp", "lim", "max", "min",
    "det", "gcd", "deg", "dim", "ker", "hom",
}
