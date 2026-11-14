"""Sanitize untrusted provider diagnostics before raising or logging them."""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import quote, quote_plus, urlsplit, urlunsplit

_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
# Authorization can contain quoted Digest parameters or be embedded in a
# serialized headers dict. Redact the remainder of that diagnostic line so
# delimiters inside a credential cannot terminate redaction early.
_AUTH = re.compile(
    r"(\bauthorization[\"']?\s*[:=]\s*[\"']?)[^\r\n]+", re.IGNORECASE
)
_BEARER = re.compile(r"\bbearer\s+[^\s\"',;}]+", re.IGNORECASE)


def redact_diagnostic(value: object, secrets: Iterable[str] = ()) -> str:
    text = str(value)
    variants = {variant for secret in secrets if isinstance(secret, str) and secret
                for variant in (secret, quote(secret, safe=""), quote_plus(secret))}
    for secret in sorted(variants, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")

    def clean_url(match: re.Match[str]) -> str:
        try:
            parsed = urlsplit(match.group())
            host = parsed.netloc.rsplit("@", 1)[-1]
            return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
        except ValueError:
            return "[REDACTED URL]"

    text = _URL.sub(clean_url, text)
    text = _AUTH.sub(r"\1[REDACTED]", text)
    return _BEARER.sub("Bearer [REDACTED]", text)
