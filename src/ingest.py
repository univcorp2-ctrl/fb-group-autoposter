from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from src.property_schema import normalize_property, validate_property

MAX_URL_INGEST_CHARS = 50_000
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"URL scheme not allowed: {parsed.scheme!r}")
    host = (parsed.hostname or "").lower()
    if host in _BLOCKED_HOSTS:
        raise ValueError(f"URL resolves to a blocked address: {host}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip and (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        raise ValueError(f"URL resolves to a blocked address: {host}")


def ingest_manual(data: dict[str, Any]) -> dict[str, Any]:
    prop = normalize_property(data)
    validate_property(prop)
    return prop


def ingest_url(url: str, *, timeout: int = 20) -> dict[str, Any]:
    _validate_url(url)
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 property-ingest"})
    resp.raise_for_status()
    text = resp.text[:MAX_URL_INGEST_CHARS]
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
