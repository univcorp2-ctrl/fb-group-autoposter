import socket

import pytest

from src import ingest
from src.ingest import _validate_url, ingest_manual


def _fake_getaddrinfo(*ips: str):
    """Build a socket.getaddrinfo replacement that resolves any host to ``ips``."""

    def _resolver(host, port, *args, **kwargs):
        infos = []
        for ip in ips:
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            sockaddr = (ip, 0, 0, 0) if family == socket.AF_INET6 else (ip, 0)
            infos.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
        return infos

    return _resolver


def test_validate_url_rejects_file_scheme():
    with pytest.raises(ValueError, match="scheme not allowed"):
        _validate_url("file:///etc/passwd")


def test_validate_url_rejects_ftp_scheme():
    with pytest.raises(ValueError, match="scheme not allowed"):
        _validate_url("ftp://evil.com/payload")


def test_validate_url_rejects_localhost():
    with pytest.raises(ValueError, match="blocked address"):
        _validate_url("http://localhost/admin")


def test_validate_url_rejects_127():
    with pytest.raises(ValueError, match="blocked address"):
        _validate_url("http://127.0.0.1:8080/secret")


def test_validate_url_rejects_metadata_ip():
    with pytest.raises(ValueError, match="blocked address"):
        _validate_url("http://169.254.169.254/latest/meta-data/")


def test_validate_url_rejects_private_192_168():
    with pytest.raises(ValueError, match="blocked address"):
        _validate_url("http://192.168.1.10/admin")


def test_validate_url_rejects_private_172_16():
    with pytest.raises(ValueError, match="blocked address"):
        _validate_url("http://172.16.0.5/internal")


def test_validate_url_rejects_ipv6_loopback():
    with pytest.raises(ValueError, match="blocked address"):
        _validate_url("http://[::1]/admin")


def test_validate_url_allows_https(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    assert _validate_url("https://example.com/property/123")


def test_validate_url_allows_http(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    assert _validate_url("http://example.com/property/123")


def test_validate_url_rejects_hostname_resolving_to_private_ip(monkeypatch):
    # A public-looking hostname whose DNS answer points at an internal address.
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("10.0.0.5"))
    with pytest.raises(ValueError, match="blocked address"):
        _validate_url("http://internal.attacker.example/")


def test_validate_url_rejects_hostname_resolving_to_metadata_ip(monkeypatch):
    # Classic DNS-rebinding target: attacker domain pointing at cloud metadata.
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("169.254.169.254"))
    with pytest.raises(ValueError, match="blocked address"):
        _validate_url("http://rebind.attacker.example/latest/meta-data/")


def test_validate_url_rejects_hostname_with_one_private_among_public(monkeypatch):
    # If ANY resolved address is internal, the URL must be rejected.
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34", "127.0.0.1"))
    with pytest.raises(ValueError, match="blocked address"):
        _validate_url("http://mixed.attacker.example/")


def test_validate_url_rejects_hostname_resolving_to_ipv6_private(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("fd00::1"))
    with pytest.raises(ValueError, match="blocked address"):
        _validate_url("http://ipv6.attacker.example/")


def test_validate_url_rejects_unresolvable_host(monkeypatch):
    def _boom(*args, **kwargs):
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    with pytest.raises(ValueError, match="could not be resolved"):
        _validate_url("http://does-not-exist.attacker.example/")


def test_validate_url_allows_public_resolved_host(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    ips = _validate_url("https://realestate.example/property/1")
    assert str(ips[0]) == "93.184.216.34"


def test_ingest_url_rejects_rebinding_before_fetch(monkeypatch):
    # End-to-end: ingest_url must refuse a host that resolves to an internal IP,
    # without ever issuing an HTTP request.
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("169.254.169.254"))

    def _fail_get(*args, **kwargs):
        raise AssertionError("requests.get must not be called for a blocked host")

    monkeypatch.setattr(ingest.requests.Session, "get", _fail_get, raising=True)
    with pytest.raises(ValueError, match="blocked address"):
        ingest.ingest_url("http://rebind.attacker.example/")


def test_ingest_manual_generates_id_for_empty_property_id():
    prop = ingest_manual({"property_id": "", "title": "A"})
    assert prop["property_id"]
