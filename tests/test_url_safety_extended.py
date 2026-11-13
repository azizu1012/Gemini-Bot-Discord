"""Offline tests for URL SSRF safety."""
import sys
from unittest.mock import MagicMock

sys.path.insert(0, ".")

from src.tools.search.url_safety import is_safe_url


def test_url_required():
    assert is_safe_url("") == (False, "URL is required")
    assert is_safe_url(None) == (False, "URL is required")


def test_invalid_scheme():
    safe, err = is_safe_url("ftp://example.com/file")
    assert safe is False
    assert "scheme" in err


def test_missing_hostname():
    safe, err = is_safe_url("http://")
    assert safe is False
    assert "hostname" in err


def test_blocked_hostname_localhost():
    safe, _ = is_safe_url("http://localhost:5432")
    assert safe is False


def test_blocked_hostname_internal_suffix():
    safe, _ = is_safe_url("http://db.internal")
    assert safe is False


def test_loopback_ip():
    safe, err = is_safe_url("http://127.0.0.1:8080")
    assert safe is False
    assert "loopback" in err


def test_private_ip():
    safe, _ = is_safe_url("http://192.168.1.1")
    assert safe is False


def test_link_local_ip():
    safe, _ = is_safe_url("http://169.254.169.254")  # cloud metadata
    assert safe is False


def test_restricted_ip_multicast():
    safe, _ = is_safe_url("http://224.0.0.1")
    assert safe is False


def test_unqualified_hostname():
    safe, err = is_safe_url("http://backend")
    assert safe is False
    assert "unqualified" in err


def test_rfc_test_domain_allowed():
    safe, _ = is_safe_url("http://api.example.com")
    assert safe is True


def test_allow_private_unlocks_ip():
    safe, _ = is_safe_url("http://127.0.0.1", allow_private=True)
    assert safe is True


def test_public_url_allowed(monkeypatch):
    # mock socket.getaddrinfo to return a public IP
    fake = MagicMock(return_value=[(None, None, None, None, ("8.8.8.8", 80))])
    monkeypatch.setattr("socket.getaddrinfo", fake)
    safe, _ = is_safe_url("http://example.org/path")
    assert safe is True


def test_dns_private_ips_rejected(monkeypatch):
    fake = MagicMock(return_value=[(None, None, None, None, ("10.0.0.1", 80))])
    monkeypatch.setattr("socket.getaddrinfo", fake)
    safe, _ = is_safe_url("http://srv.local")
    assert safe is False


def test_dns_gaierror_in_pytest(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", MagicMock(side_effect=socket.gaierror("no")))
    # PYTEST_CURRENT_TEST is set while running under pytest -> allowed
    safe, _ = is_safe_url("http://nonexistent.tld")
    assert safe is True


def test_dns_resolves_to_loopback(monkeypatch):
    fake = MagicMock(return_value=[(None, None, None, None, ("127.0.0.1", 80))])
    monkeypatch.setattr("socket.getaddrinfo", fake)
    safe, err = is_safe_url("http://dns-loopback.org")
    assert safe is False
    assert "loopback" in err


def test_dns_resolves_to_link_local(monkeypatch):
    fake = MagicMock(return_value=[(None, None, None, None, ("169.254.1.1", 80))])
    monkeypatch.setattr("socket.getaddrinfo", fake)
    safe, err = is_safe_url("http://dns-metadata.org")
    assert safe is False
    assert "not allowed" in err


def test_dns_resolves_to_multicast(monkeypatch):
    fake = MagicMock(return_value=[(None, None, None, None, ("224.0.0.1", 80))])
    monkeypatch.setattr("socket.getaddrinfo", fake)
    safe, err = is_safe_url("http://dns-multicast.org")
    assert safe is False
    assert "restricted" in err


def test_unqualified_hostname_allow_private():
    safe, _ = is_safe_url("http://backend", allow_private=True)
    assert safe is True


def test_urlparse_exception(monkeypatch):
    import urllib.parse
    monkeypatch.setattr(urllib.parse, "urlparse", MagicMock(side_effect=ValueError("bad url")))
    safe, err = is_safe_url("http://bad.org")
    assert safe is False
    assert "Invalid URL" in err


def test_dns_no_addr_info_non_test_env(monkeypatch):
    import socket
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", MagicMock(return_value=[]))
    safe, err = is_safe_url("http://nonexistent-empty.org")
    assert safe is False
    assert "Could not resolve" in err


def test_dns_generic_exception(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", MagicMock(side_effect=RuntimeError("dns boom")))
    safe, err = is_safe_url("http://errordns.org")
    assert safe is False
    assert "DNS validation error" in err
