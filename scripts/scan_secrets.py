"""Secret scanner for CI — finds credentials in tracked files.

Why not auto-rewrite: a CI job that silently edits your source hides the finding
instead of surfacing it, and a rewrite in CI is a commit you did not review. This
reports and fails loudly; the fix is a human decision.

What it looks for:
  - provider keys (Google, GitHub, AWS, Slack, Discord)
  - private key blocks
  - connection strings with inline credentials
  - JWTs and anything that looks like a base64 blob with a signature
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Iterator


# ── patterns ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern
    severity: str  # "critical" | "high" | "medium"
    note: str


RULES: tuple[Rule, ...] = (
    Rule(
        "google-api-key",
        re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
        "critical",
        "Google API key",
    ),
    Rule(
        "github-token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}"),
        "critical",
        "GitHub personal access / app token",
    ),
    Rule(
        "github-fine-grained-token",
        re.compile(r"github_pat_[A-Za-z0-9_]{40,}"),
        "critical",
        "GitHub fine-grained token",
    ),
    Rule(
        "aws-access-key",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        "critical",
        "AWS access key id",
    ),
    Rule(
        "slack-token",
        re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
        "critical",
        "Slack token",
    ),
    Rule(
        "discord-token",
        re.compile(r"\b[MN][A-Za-z\d]{23,26}\.[A-Za-z\d\-_]{6}\.[A-Za-z\d\-_]{27,38}\b"),
        "critical",
        "Discord bot token",
    ),
    Rule(
        "private-key-block",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
        "critical",
        "Private key material",
    ),
    Rule(
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
        "high",
        "JSON Web Token",
    ),
    Rule(
        # The userinfo segment may be empty (redis://:pw@host) or contain a colon.
        # Variable interpolation like $var or ${var} is excluded.
        "db-uri-with-password",
        re.compile(
            r"\b(?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis|rediss|amqp|amqps)"
            r"://[^\s:/@$()]+:[^\s:/@$()]+@"
        ),
        "critical",
        "Connection string with inline password",
    ),
)

# Assignments that make a bare value look like a credential even if short.
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|secret|password|passwd|token|auth[_-]?key|"
    r"private[_-]?key|client[_-]?secret|access[_-]?key)\b"
    r"\s*[:=]\s*"
    r"([\"'])([^\s\"']{16,})\1"
)

# Values that are obviously not credentials.
_ALLOWLIST = re.compile(
    r"(?i)^(?:dummy|placeholder|example|changeme|your[_-]?|xxx+|todo|"
    r"fake|redacted|redact|masked|none|null|true|false|"
    r"sample|mock|fixture|abc123|foo|bar|baz|"
    r"replace_me|your_discord_bot_token|your_primary_key|"
    r"\*+|[0-9]+)$"
)
_ALLOW_EXACT = {
    "REDACTED-LEAKED-KEY",
    "REDACTED",
    "replace_me",
    "your_discord_bot_token",
    "your_fernet_encryption_key",
    "your_fernet_key",
}


@dataclass
class Finding:
    rule: str
    severity: str
    path: str
    line: int
    preview: str
    note: str


# ── scanning ────────────────────────────────────────────────────────────────

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", ".codegraph",
    ".runtime", "graphify-out", "_old_bots_no_git",
}
SKIP_SUFFIX = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz",
    ".whl", ".pyc", ".so", ".dll", ".exe", ".db", ".sqlite",
    ".key", ".pem", ".pfx", ".p12", ".crt", ".enc",
}
SKIP_NAMES = {
    ".env", ".env.local", ".env.example", ".env.backup",
    "bot.log", "voice_lock.log",
}


def _redact(value: str, keep: int = 4) -> str:
    """Show enough to locate the value, never enough to use it."""
    v = value.strip()
    if len(v) <= keep * 2:
        return "*" * len(v)
    return f"{v[:keep]}...{v[-keep:]}(len={len(v)})"


def _is_allowlisted(value: str) -> bool:
    v = value.strip().strip("\"'")
    if not v:
        return True
    if v in _ALLOW_EXACT:
        return True
    if _ALLOWLIST.match(v):
        return True
    # A value that is mostly punctuation/format chars is not a secret.
    alnum = sum(ch.isalnum() for ch in v)
    if alnum < len(v) * 0.5:
        return True
    # Code-shaped values: anything with brackets, dots, parens or calls is
    # an expression, not a stored literal.
    if re.search(r"[(){}\[\]]|\b(?:get|set|int|str|bool|list|dict)\s*\(", v):
        return True
    return False


def iter_files(roots: Iterable[str]) -> Iterator[Path]:
    """Walk `roots`, yielding only files a scanner should judge."""
    explicit = {str(Path(r).name) for r in roots}
    for root in roots:
        p = Path(root)
        try:
            if p.is_file():
                yield p
                continue
        except OSError:
            continue
        for dirpath, dirnames, filenames in os.walk(p, onerror=lambda _e: None):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                if name in SKIP_NAMES and name not in explicit:
                    continue
                fp = Path(dirpath) / name
                if fp.suffix.lower() in SKIP_SUFFIX:
                    continue
                try:
                    if not fp.is_file():
                        continue
                except OSError:
                    continue
                yield fp


def scan_text(text: str, path: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, int]] = set()

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            if rule.name == "db-uri-with-password":
                val = m.group(0)
                try:
                    user_pass = val.split("://", 1)[1].split("@", 1)[0]
                    if ":" in user_pass:
                        pw = user_pass.split(":", 1)[1]
                        if _is_allowlisted(pw) or pw.lower() in ("replace_me", "dummy", "example"):
                            continue
                except Exception:
                    pass

            line_no = text.count("\n", 0, m.start()) + 1
            if (rule.name, line_no) in seen:
                continue
            seen.add((rule.name, line_no))
            findings.append(Finding(
                rule=rule.name,
                severity=rule.severity,
                path=path,
                line=line_no,
                preview=_redact(m.group(0)),
                note=rule.note,
            ))

    for m in _SECRET_ASSIGNMENT.finditer(text):
        value = m.group(2)
        if _is_allowlisted(value):
            continue
        line_no = text.count("\n", 0, m.start()) + 1
        if ("assignment", line_no) in seen:
            continue
        seen.add(("assignment", line_no))
        findings.append(Finding(
            rule="credential-assignment",
            severity="medium",
            path=path,
            line=line_no,
            preview=_redact(value),
            note="literal assigned to a credential-looking name",
        ))

    return findings


SELF_EXEMPT = {"scripts/scan_secrets.py", "tests/test_secret_scanner.py"}


def _exempt(path: str) -> bool:
    norm = path.replace("\\", "/")
    return any(norm == e or norm.endswith("/" + e) for e in SELF_EXEMPT)


def scan(roots: Iterable[str], use_git: bool = False,
         git_diff_range: str | None = None) -> list[Finding]:
    if git_diff_range:
        import subprocess
        out = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", "-z", git_diff_range],
            capture_output=True, text=True, check=True,
        ).stdout
        paths = [Path(p) for p in out.split("\0") if p]
    elif use_git:
        import subprocess
        out = subprocess.run(
            ["git", "ls-files", "-z", *roots],
            capture_output=True, text=True, check=True,
        ).stdout
        paths = [Path(p) for p in out.split("\0") if p]
    else:
        paths = list(iter_files(roots))

    findings: list[Finding] = []
    for path in paths:
        rel = str(path).replace("\\", "/")
        if _exempt(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        findings.extend(scan_text(text, rel))
    return findings


# ── reporting ───────────────────────────────────────────────────────────────

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2}


def report(findings: list[Finding]) -> str:
    if not findings:
        return "no secrets found"
    findings = sorted(findings, key=lambda f: (SEVERITY_ORDER[f.severity], f.path, f.line))
    lines = []
    for f in findings:
        lines.append(
            f"[{f.severity.upper():8}] {f.path}:{f.line}  {f.rule}  {f.note}\n"
            f"           {f.preview}"
        )
    crit = sum(1 for f in findings if f.severity == "critical")
    high = sum(1 for f in findings if f.severity == "high")
    med = sum(1 for f in findings if f.severity == "medium")
    lines.append(f"\n{len(findings)} finding(s): {crit} critical, {high} high, {med} medium")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scan tracked files for credentials")
    ap.add_argument("paths", nargs="*", default=["."],
                    help="files or directories to scan (default: whole tree)")
    ap.add_argument("--git", action="store_true",
                    help="scan only files tracked by git")
    ap.add_argument("--git-diff", metavar="RANGE",
                    help="scan only files changed in a git diff range")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--warn-only", action="store_true",
                    help="exit 0 even when critical findings exist")
    args = ap.parse_args(argv)

    roots = args.paths or ["."]
    findings = scan(roots, use_git=args.git, git_diff_range=args.git_diff)

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        print(report(findings))

    if args.warn_only:
        return 0
    return 1 if any(f.severity in ("critical", "high") for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
