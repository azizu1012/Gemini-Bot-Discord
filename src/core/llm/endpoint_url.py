"""Safety policy for admin-configured LLM endpoint URLs.

The bot intentionally allows loopback endpoints so it can talk to a local
router_api instance. Link-local/cloud-metadata addresses are always rejected.
Private LAN/ULA endpoints are rejected unless ALLOW_PRIVATE_ENDPOINT_HOSTS=true.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Tuple
from urllib.parse import urlsplit

BLOCKED_HOSTNAMES = {
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
    "instance-data.ec2.internal",
}
BLOCKED_SUFFIXES = (".local", ".internal", ".lan", ".home", ".corp", ".arpa")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _check_ip(ip: ipaddress._BaseAddress, allow_private: bool) -> Tuple[bool, str]:
    if ip.is_loopback:
        return True, ""
    if ip.is_link_local:
        return False, f"địa chỉ link-local/cloud metadata ({ip}) không được phép"
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False, f"địa chỉ không hợp lệ ({ip})"
    if ip.is_private and not allow_private:
        return False, f"địa chỉ mạng private ({ip}) không được phép; đặt ALLOW_PRIVATE_ENDPOINT_HOSTS=true nếu cần"
    return True, ""


def validate_endpoint_url(url: str) -> Tuple[bool, str]:
    """Return (ok, error_message) for an LLM endpoint URL."""
    if not url or not isinstance(url, str):
        return False, "URL trống"

    try:
        parsed = urlsplit(url.strip())
    except Exception:
        return False, "URL không hợp lệ"

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False, "chỉ chấp nhận http/https và phải có host"
    if parsed.username or parsed.password:
        return False, "URL không được chứa username/password"

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False, "URL thiếu hostname"

    allow_private = _env_flag("ALLOW_PRIVATE_ENDPOINT_HOSTS", False)

    if hostname in BLOCKED_HOSTNAMES:
        return False, f"hostname nội bộ ({hostname}) không được phép"
    if hostname.endswith(BLOCKED_SUFFIXES) and not allow_private:
        return False, f"hostname nội bộ ({hostname}) không được phép"

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        return _check_ip(ip, allow_private)

    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False, f"không phân giải được hostname '{hostname}'"
    except Exception:
        return False, "không kiểm tra được hostname"

    if not addr_info:
        return False, f"không phân giải được hostname '{hostname}'"

    for _, _, _, _, sockaddr in addr_info:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        ok, error = _check_ip(ip, allow_private)
        if not ok:
            return False, error

    return True, ""


__all__ = ["validate_endpoint_url"]
