"""Tests for the secret scanner."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

_SCAN_PATH = Path(__file__).resolve().parent.parent / "scripts" / "scan_secrets.py"
_spec = importlib.util.spec_from_file_location("scan_secrets", _SCAN_PATH)
assert _spec is not None and _spec.loader is not None, f"cannot load {_SCAN_PATH}"
scan_secrets = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = scan_secrets
_spec.loader.exec_module(scan_secrets)
scan_text = scan_secrets.scan_text


def rules_found(text: str) -> set[str]:
    return {f.rule for f in scan_text(text, "probe")}


class TestDetectsRealSecrets:
    def test_google_api_key(self):
        key = "AIza" + "B" * 33
        assert "google-api-key" in rules_found(f'GOOGLE_KEY = "{key}"')

    def test_github_pat(self):
        assert "github-token" in rules_found('tok = "ghp_' + "a1b2c3d4e5" * 4 + '"')

    def test_github_fine_grained(self):
        pat = "github_pat_" + "A" * 22 + "_" + "B" * 22
        assert "github-fine-grained-token" in rules_found(f'p = "{pat}"')

    def test_aws_key(self):
        assert "aws-access-key" in rules_found('k = "AKIAIOSFODNN7EXAMPLE"')

    def test_slack_token(self):
        assert "slack-token" in rules_found('s = "xoxb-1234567890-abcdefghij"')

    def test_discord_token(self):
        # Dynamically assembled to avoid triggering static regex pre-commit / push-protection
        prefix = "MTA1Mzg1OTM3" + "NjI4MTM2MjQ3Mg"
        mid = "G2X9mK"
        suffix = "4d8E7f6G5h4I3j2K1l0M" + "9n8O7p6Q5r4S3t2U1v"
        tok = f"{prefix}.{mid}.{suffix}"
        assert "discord-token" in rules_found(f'DISCORD_TOKEN = "{tok}"')

    def test_private_key_block(self):
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----"
        assert "private-key-block" in rules_found(pem)

    def test_jwt(self):
        jwt = ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
               ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
        assert "jwt" in rules_found(f'HEADER = "Bearer {jwt}"')

    @pytest.mark.parametrize("dsn", [
        "postgresql://admin:s3cr3t@db.example.com:5432/app",
        "mysql://root:password@localhost/app",
        "mongodb+srv://u:p@cluster0.example.mongodb.net/db",
        "redis://user:password@127.0.0.1:6379/0",
    ])
    def test_connection_strings(self, dsn):
        assert "db-uri-with-password" in rules_found(f'URL = "{dsn}"')

    def test_generic_password_assignment(self):
        assert "credential-assignment" in rules_found(
            'password = "Tr0ub4dor-and-3xyz-long"'
        )


class TestNoFalsePositives:
    @pytest.mark.parametrize("name", [
        "google-api-key", "github-token", "aws-access-key", "slack-token",
        "discord-token", "private-key-block", "jwt", "db-uri-with-password",
        "credential-assignment",
    ])
    def test_clean_source_is_silent(self, name):
        source = "\n".join([
            "import os",
            "def handler(request):",
            "    payload = request.json()",
            "    return {'status': 'ok'}",
        ])
        assert not rules_found(source)

    def test_allowlisted_placeholders(self):
        assert not rules_found('DISCORD_TOKEN = "your_discord_bot_token"')
        assert not rules_found('KEY = "dummy-api-key-here"')
        assert not rules_found('PASSWORD = "replace_me"')
