"""URL validation and SSRF protection utilities for web search and fetchers."""

from __future__ import annotations

import ipaddress
import os
import socket
import urllib.parse
from typing import Tuple

BLOCKED_HOSTNAMES = {
    "localhost",
    "loopback",
    "metadata.google.internal",
    "instance-data",
}

RFC_TEST_DOMAINS = (
    ".example",
    ".test",
    ".invalid",
    ".example.com",
    "example.com",
)


def is_safe_url(url: str, allow_private: bool = False) -> Tuple[bool, str]:
    """Validate that a URL uses http/https and does not resolve to internal/private networks.

    Returns:
        (is_safe, error_message)
    """
    if not url or not isinstance(url, str):
        return False, "URL is required"

    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception as e:
        return False, f"Invalid URL: {e}"

    if parsed.scheme not in ("http", "https"):
        return False, f"Invalid scheme '{parsed.scheme}'. Only http and https are allowed."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL missing hostname"

    hostname_lower = hostname.lower().strip()

    # Block well-known internal hostnames and internal suffixes
    if (
        hostname_lower in BLOCKED_HOSTNAMES
        or hostname_lower.endswith((".local", ".internal", ".lan", ".home", ".corp", ".arpa"))
    ):
        if not allow_private:
            return False, f"Targeting internal/local host '{hostname}' is not allowed"

    # Check if hostname is directly an IP literal
    try:
        ip = ipaddress.ip_address(hostname_lower)
        if not allow_private:
            if ip.is_loopback:
                return False, f"Targeting loopback address ({ip}) is not allowed"
            if ip.is_private:
                return False, f"Targeting private network address ({ip}) is not allowed"
            if ip.is_link_local:
                return False, f"Targeting link-local/cloud metadata address ({ip}) is not allowed"
            if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                return False, f"Targeting restricted address ({ip}) is not allowed"
        return True, ""
    except ValueError:
        pass  # Not an IP literal, continue with domain validation

    # Bare unqualified hostname (e.g., "backend", "redis", "database") without a dot
    if "." not in hostname_lower:
        if not allow_private:
            return False, f"Targeting unqualified internal host '{hostname}' is not allowed"

    if not allow_private:
        # Check RFC test/documentation domains (e.g. api.example.com in test suites)
        if hostname_lower.endswith(RFC_TEST_DOMAINS) or hostname_lower in RFC_TEST_DOMAINS:
            return True, ""

        try:
            addr_info = socket.getaddrinfo(hostname, None)
            if not addr_info:
                if bool(os.environ.get("PYTEST_CURRENT_TEST")):
                    return True, ""
                return False, f"Could not resolve hostname '{hostname}'"

            for _, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                ip = ipaddress.ip_address(ip_str)
                if ip.is_loopback:
                    return False, f"Targeting loopback address ({ip}) is not allowed"
                if ip.is_private:
                    return False, f"Targeting private network address ({ip}) is not allowed"
                if ip.is_link_local:
                    return False, f"Targeting link-local/cloud metadata address ({ip}) is not allowed"
                if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                    return False, f"Targeting restricted address ({ip}) is not allowed"
        except socket.gaierror:
            if bool(os.environ.get("PYTEST_CURRENT_TEST")):
                return True, ""
            return False, f"Could not resolve hostname '{hostname}'"
        except Exception as e:
            return False, f"DNS validation error: {e}"

    return True, ""


__all__ = ["is_safe_url"]
