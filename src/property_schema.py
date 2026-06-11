from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

PROPERTY_FIELDS = [
    "property_id",
    "title",
    "price",
    "yield_pct",
    "location",
    "access",
    "structure",
    "land_area",
    "building_area",
    "year_built",
    "highlights",
    "url",
    "images",
    "raw_text",
    "ingested_at",
]


def property_id_from_payload(data: dict[str, Any]) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:24]
    return digest or str(uuid.uuid4())


def normalize_property(data: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True)
    highlights = data.get("highlights", [])
    if isinstance(highlights, str):
        highlights = [x.strip() for x in highlights.split(",") if x.strip()]
    images = data.get("images", [])
    if isinstance(images, str):
        images = [images]
    return {
        "property_id": data.get("property_id") or property_id_from_payload(data),
        "title": data.get("title", "記載なし"),
        "price": data.get("price", "記載なし"),
        "yield_pct": data.get("yield_pct", "記載なし"),
        "location": data.get("location", "記載なし"),
        "access": data.get("access", "記載なし"),
        "structure": data.get("structure", "記載なし"),
        "land_area": data.get("land_area", "記載なし"),
        "building_area": data.get("building_area", "記載なし"),
        "year_built": data.get("year_built", "記載なし"),
        "highlights": highlights,
        "url": data.get("url", ""),
        "images": images,
        "raw_text": data.get("raw_text", raw),
        "ingested_at": data.get("ingested_at") or datetime.now(UTC).isoformat(),
    }


def validate_property(data: dict[str, Any]) -> None:
    missing = [key for key in PROPERTY_FIELDS if key not in data]
    if missing:
        raise ValueError(f"property data is missing normalized fields: {missing}")
    if not data["property_id"]:
        raise ValueError("property_id must not be empty")
    if not isinstance(data.get("highlights"), list):
        raise ValueError("highlights must be a list")
    if not isinstance(data.get("images"), list):
        raise ValueError("images must be a list")
