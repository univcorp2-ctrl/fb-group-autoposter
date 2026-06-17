from __future__ import annotations

import ipaddress
import json
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter

from src.property_schema import normalize_property, validate_property

MAX_URL_INGEST_CHARS = 50_000
MAX_REDIRECTS = 5
_ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _ip_is_blocked(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _parse_ip(value: str) -> ipaddress._BaseAddress | None:
    # Resolved IPv6 addresses may carry a scope id (e.g. ``fe80::1%eth0``);
    # strip it so ``ip_address`` does not choke and silently fall through.
    candidate = value.split("%", 1)[0]
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _resolve_host_ips(host: str) -> list[ipaddress._BaseAddress]:
    """Resolve ``host`` to every IP it maps to, failing closed on errors."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"URL host could not be resolved: {host}") from exc
    ips: list[ipaddress._BaseAddress] = []
    seen: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        raw = sockaddr[0]
        if raw in seen:
            continue
        seen.add(raw)
        ip = _parse_ip(raw)
        if ip is None:
            raise ValueError(f"URL host resolved to an unparseable address: {raw!r}")
        ips.append(ip)
    if not ips:
        raise ValueError(f"URL host could not be resolved: {host}")
    return ips


def _validate_url(url: str) -> list[ipaddress._BaseAddress]:
    """Validate ``url`` against SSRF, returning the validated resolved IP(s).

    Beyond scheme and literal-IP checks, the hostname is resolved via DNS and
    *every* resulting address is checked against the private/loopback/link-local/
    reserved/multicast/unspecified ranges. This closes the gap where a hostname
    resolves to an internal address (e.g. cloud metadata at 169.254.169.254).
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"URL scheme not allowed: {parsed.scheme!r}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL has no host")
    if host in _BLOCKED_HOSTS:
        raise ValueError(f"URL resolves to a blocked address: {host}")

    literal = _parse_ip(host)
    if literal is not None:
        if _ip_is_blocked(literal):
            raise ValueError(f"URL resolves to a blocked address: {host}")
        return [literal]

    resolved = _resolve_host_ips(host)
    for ip in resolved:
        if _ip_is_blocked(ip):
            raise ValueError(f"URL host {host} resolves to a blocked address: {ip}")
    return resolved


def _format_host(ip: ipaddress._BaseAddress) -> str:
    return f"[{ip}]" if isinstance(ip, ipaddress.IPv6Address) else str(ip)


class _PinnedIPAdapter(HTTPAdapter):
    """Pin connections to a pre-validated IP to defeat DNS rebinding (TOCTOU).

    The hostname is resolved and validated once; this adapter then forces the
    actual socket to that exact IP, so a racing DNS answer pointing at an
    internal address cannot be used for the fetch. The original ``Host`` header
    and TLS SNI/cert hostname are preserved so routing and certificate
    validation still target the real host.
    """

    def __init__(self, hostname: str, ip: ipaddress._BaseAddress, **kwargs: Any) -> None:
        self._hostname = hostname
        self._pinned_host = _format_host(ip)
        super().__init__(**kwargs)

    def send(self, request: Any, **kwargs: Any) -> Any:
        parsed = urlparse(request.url)
        original_netloc = parsed.netloc
        netloc = self._pinned_host if parsed.port is None else f"{self._pinned_host}:{parsed.port}"
        request.url = urlunparse(parsed._replace(netloc=netloc))
        request.headers["Host"] = original_netloc

        pool_kw = self.poolmanager.connection_pool_kw
        if parsed.scheme == "https":
            # Connect to the IP literal but present and verify the real hostname.
            pool_kw["server_hostname"] = self._hostname
            pool_kw["assert_hostname"] = self._hostname
        else:
            pool_kw.pop("server_hostname", None)
            pool_kw.pop("assert_hostname", None)
        return super().send(request, **kwargs)


def ingest_manual(data: dict[str, Any]) -> dict[str, Any]:
    prop = normalize_property(data)
    validate_property(prop)
    return prop


def _fetch_url(url: str, *, timeout: int) -> str:
    """Fetch ``url`` with SSRF validation, IP pinning, and per-hop redirect checks."""
    headers = {"User-Agent": "Mozilla/5.0 property-ingest"}
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        resolved = _validate_url(current)
        host = (urlparse(current).hostname or "").lower()
        session = requests.Session()
        adapter = _PinnedIPAdapter(host, resolved[0])
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        try:
            resp = session.get(
                current,
                timeout=timeout,
                headers=headers,
                allow_redirects=False,  # follow manually so each hop is re-validated
            )
            if resp.is_redirect or resp.is_permanent_redirect:
                location = resp.headers.get("Location")
                if not location:
                    resp.raise_for_status()
                    return resp.text[:MAX_URL_INGEST_CHARS]
                current = urljoin(current, location)
                continue
            resp.raise_for_status()
            return resp.text[:MAX_URL_INGEST_CHARS]
        finally:
            session.close()
    raise ValueError(f"Too many redirects while fetching URL: {url}")


def ingest_url(url: str, *, timeout: int = 20) -> dict[str, Any]:
    text = _fetch_url(url, timeout=timeout)
    return ingest_manual({"url": url, "raw_text": text, "title": "URL取込物件"})


def ingest_pdf(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    raw_text = ""
    try:
        import fitz

        with fitz.open(path) as doc:
            raw_text = "\n".join(page.get_text("text") for page in doc)
    except Exception as exc:
        raw_text = f"PDF text extraction failed: {exc}"
    return ingest_manual({"title": path.stem, "raw_text": raw_text, "source_file": str(path)})


def scan_inbox(inbox_dir: str | Path) -> list[dict[str, Any]]:
    inbox = Path(inbox_dir)
    inbox.mkdir(parents=True, exist_ok=True)
    properties: list[dict[str, Any]] = []
    for path in sorted(inbox.glob("*.pdf")):
        properties.append(ingest_pdf(path))
    for path in sorted(inbox.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        properties.append(ingest_manual(data))
    return properties
