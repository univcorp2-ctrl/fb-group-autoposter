from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests


def _property_id_from_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:24]


def normalize_property(data: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True)
    out = {
        "property_id": data.get("property_id") or _property_id_from_text(raw) or str(uuid.uuid4()),
        "title": data.get("title", "記載なし"),
        "price": data.get("price", "記載なし"),
        "yield_pct": data.get("yield_pct", "記載なし"),
        "location": data.get("location", "記載なし"),
        "access": data.get("access", "記載なし"),
        "structure": data.get("structure", "記載なし"),
        "land_area": data.get("land_area", "記載なし"),
        "building_area": data.get("building_area", "記載なし"),
        "year_built": data.get("year_built", "記載なし"),
        "highlights": data.get("highlights", []),
        "url": data.get("url", ""),
        "images": data.get("images", []),
        "raw_text": data.get("raw_text", raw),
        "ingested_at": data.get("ingested_at") or datetime.now(UTC).isoformat(),
    }
    return out


def ingest_manual(data: dict[str, Any]) -> dict[str, Any]:
    return normalize_property(data)


def ingest_url(url: str, *, timeout: int = 20) -> dict[str, Any]:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 property-ingest"})
    resp.raise_for_status()
    text = resp.text[:50_000]
    return normalize_property({"url": url, "raw_text": text, "title": "URL取込物件"})


def ingest_pdf(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    raw_text = ""
    try:
        import fitz

        with fitz.open(path) as doc:
            raw_text = "\n".join(page.get_text("text") for page in doc)
    except Exception as exc:
        raw_text = f"PDF text extraction failed: {exc}"
    title = path.stem
    return normalize_property({"title": title, "raw_text": raw_text, "source_file": str(path)})


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
