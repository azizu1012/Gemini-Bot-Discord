"""Offline tests for validate_endpoint_url."""
import sys
from unittest.mock import MagicMock

sys.path.insert(0, ".")

from src.core.llm.endpoint_url import validate_endpoint_url


def test_empty_url():
    assert validate_endpoint_url("")[0] is False
    assert validate_endpoint_url(None)[0] is False


def test_invalid_scheme():
    ok, err = validate_endpoint_url("ftp://host")
    assert ok is False
    assert "http/https" in err


def test_no_netloc():
    ok, err = validate_endpoint_url("http://")
    assert ok is False


def test_username_password_rejected():
    ok, err = validate_endpoint_url("http://user:pass@host:8000")
    assert ok is False
    assert "username/password" in err


def test_blocked_hostname():
    assert validate_endpoint_url("http://metadata.google.internal")[0] is False


def test_blocked_suffix():
    ok, err = validate_endpoint_url("http://service.internal")
    assert ok is False
    assert "nội bộ" in err


def test_loopback_ip():
    # loopback is intentionally allowed (for local router_api)
    assert validate_endpoint_url("http://127.0.0.1:8000")[0] is True


def test_private_ip():
    assert validate_endpoint_url("http://10.0.0.1")[0] is False


def test_public_hostname_allowed(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", MagicMock(return_value=[(None, None, None, None, ("8.8.8.8", 80))]))
    ok, _ = validate_endpoint_url("http://example.com")
    assert ok is True


def test_hostname_gaierror(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", MagicMock(side_effect=socket.gaierror("no")))
    ok, err = validate_endpoint_url("http://nonexistent.tld")
    assert ok is False
    assert "không phân giải" in err


def test_hostname_no_addr_info(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", MagicMock(return_value=[]))
    ok, err = validate_endpoint_url("http://emptydns.tld")
    assert ok is False
    assert "không phân giải" in err


def test_hostname_resolves_to_private(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", MagicMock(return_value=[(None, None, None, None, ("10.1.1.1", 80))]))
    ok, _ = validate_endpoint_url("http://srv.example.com")
    assert ok is False


def test_allow_private_unlocks_ip(monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE_ENDPOINT_HOSTS", "true")
    ok, _ = validate_endpoint_url("http://192.168.1.5")
    assert ok is True
    monkeypatch.delenv("ALLOW_PRIVATE_ENDPOINT_HOSTS")
