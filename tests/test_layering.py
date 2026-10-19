"""Layering test: enforces that lower architectural layers do not import upward.

Layer hierarchy:
  1. src.core (foundational — cannot import handlers, tools, managers, services)
  2. src.database (persistence — cannot import handlers, tools, managers, services)
  3. src.services, src.managers, src.tools (business & domain logic — cannot import handlers)
  4. src.handlers (top-level presentation / discord / worker)
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _tracked_python_files():
    out = subprocess.run(
        ["git", "ls-files", "-c", "-o", "--exclude-standard", "*.py"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return [REPO_ROOT / p for p in out.stdout.split() if (REPO_ROOT / p).is_file()]


def _module_level_imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src."):
            found.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("src."):
                    found.append(alias.name)
    return found


RULES = [
    (
        "src/core/",
        ("src.handlers", "src.tools", "src.managers", "src.services"),
        "core is foundational and cannot depend on higher-level layers.",
    ),
    (
        "src/database/",
        ("src.handlers", "src.tools", "src.managers", "src.services"),
        "database is persistence layer and cannot depend on higher-level layers.",
    ),
    (
        "src/tools/",
        ("src.handlers",),
        "tools are execution utilities and cannot depend on handlers.",
    ),
    (
        "src/services/",
        ("src.handlers",),
        "services cannot depend on handlers.",
    ),
    (
        "src/managers/",
        ("src.handlers",),
        "managers cannot depend on handlers.",
    ),
    (
        "src/voice/",
        ("src.handlers",),
        "voice cannot depend on handlers.",
    ),
]

KNOWN_EXCEPTIONS = []


def _is_exception(rel_path: str, module: str) -> bool:
    return any(
        rel_path.replace("\\", "/") == file and module.startswith(prefix)
        for file, prefix, _ in KNOWN_EXCEPTIONS
    )


def test_layering_has_no_forbidden_upward_imports():
    violations = []
    for path in _tracked_python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for prefix, forbidden, reason in RULES:
            if not rel.startswith(prefix):
                continue
            for module in _module_level_imports(path):
                bad = [f for f in forbidden if module == f or module.startswith(f + ".")]
                if not bad:
                    continue
                if _is_exception(rel, module):
                    continue
                violations.append(f"{rel} imports {module}: {reason}")

    assert not violations, "\n".join(violations)
