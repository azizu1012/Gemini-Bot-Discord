"""Keep contributor instructions aligned with the actual offline CI and runtime."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_contributor_checks_match_ci_and_document_offline_requirements():
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for command in ("ruff check .", "mypy src/", "python -m compileall -q src run_bot.py main.py", "python -m pytest -v"):
        assert command in ci
        assert command in contributing
    assert "python-version: '3.13'" in ci
    assert "Python 3.13" in contributing
    assert "FROM python:3.12-slim" in (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for expected in ("Python 3.12", "mock-only", "no PostgreSQL, Redis", "--no-index", "requirements-test.txt",
                     "GitHub Security Advisories", "/security/advisories/new", "fix/", "fix: ..."):
        assert expected in contributing


def test_readme_describes_mock_ci_and_links_contributing():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "PostgreSQL/Redis-backed tests" not in readme
    assert "offline, mock-only tests" in readme
    assert "[CONTRIBUTING.md](CONTRIBUTING.md)" in readme
