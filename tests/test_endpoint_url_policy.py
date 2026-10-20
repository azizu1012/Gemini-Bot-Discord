"""Tests for LLM endpoint URL safety policy."""

import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.llm.endpoint_url import validate_endpoint_url


def test_loopback_is_allowed_for_local_router():
    assert validate_endpoint_url("http://127.0.0.1:58100")[0] is True
    assert validate_endpoint_url("http://localhost:58100")[0] is True
    assert validate_endpoint_url("http://[::1]:58100")[0] is True


def test_cloud_metadata_and_link_local_are_blocked():
    assert validate_endpoint_url("http://169.254.169.254/latest/meta-data")[0] is False
    assert validate_endpoint_url("http://metadata.google.internal")[0] is False
    assert validate_endpoint_url("http://[fe80::1]")[0] is False


def test_private_network_is_blocked_by_default(monkeypatch):
    monkeypatch.delenv("ALLOW_PRIVATE_ENDPOINT_HOSTS", raising=False)
    assert validate_endpoint_url("http://10.0.0.5:8080")[0] is False
    assert validate_endpoint_url("http://192.168.1.10:8080")[0] is False
    assert validate_endpoint_url("http://172.16.0.10:8080")[0] is False


def test_private_network_can_be_allowed_explicitly(monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE_ENDPOINT_HOSTS", "true")
    assert validate_endpoint_url("http://10.0.0.5:8080")[0] is True


def test_invalid_scheme_and_userinfo_are_blocked():
    assert validate_endpoint_url("ftp://127.0.0.1:58100")[0] is False
    assert validate_endpoint_url("http://user:pass@127.0.0.1:58100")[0] is False


def test_unspecified_address_is_blocked():
    assert validate_endpoint_url("http://0.0.0.0:58100")[0] is False


def test_dns_name_resolving_to_private_is_blocked(monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0))]

    monkeypatch.delenv("ALLOW_PRIVATE_ENDPOINT_HOSTS", raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    ok, error = validate_endpoint_url("http://internal.example.com:8080")

    assert ok is False
    assert "private" in error
