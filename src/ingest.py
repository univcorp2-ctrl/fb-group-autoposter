from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from src.property_schema import normalize_property, validate_property


def ingest_manual(data: dict[str, Any]) -> dict[str, Any]:
    prop = normalize_property(data)
    validate_property(prop)
    return prop


def ingest_url(url: str, *, timeout: int = 20) -> dict[str, Any]:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 property-ingest"})
    resp.raise_for_status()
    text = resp.text[:50_000]
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
