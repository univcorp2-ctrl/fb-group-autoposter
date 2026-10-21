"""Fact-only lookup for property-specific Messenger enquiries.

The source is the same canonical EstateBoard JSON used by the posting pipeline.
Only allowlisted property fields reach the model; sender contact and publication
tokens must never leak. A candidate is NOT permission to share documents.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path

DEFAULT_SOURCE = Path(r"C:\AI-Agent\EstateBoard\output\received\properties.json")

@dataclass(frozen=True)
class Evidence:
    matched: bool
    ambiguous: bool
    subject: str
    property_id: str
    label: str
    price_jpy: int | None
    city: str
    detail_url: str
    publication_scope: str
    sharing_cleared: bool
    source: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)

def _request_price_jpy(text: str) -> int | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*億(?:円)?", text)
    return round(float(m.group(1)) * 100_000_000) if m else None

def lookup_property(inbound: str, source: Path | None = None) -> Evidence:
    path = source or Path(os.getenv("MESSENGER_PROPERTY_SOURCE", str(DEFAULT_SOURCE)))
    blank = {
        "matched": False, "ambiguous": False, "subject": inbound[:100],
        "property_id": "", "label": "", "price_jpy": None, "city": "",
        "detail_url": "", "publication_scope": "",
        "sharing_cleared": False, "source": str(path),
    }
    if not path.is_file():
        return Evidence(**blank, reason="property_catalog_unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Evidence(**blank, reason="property_catalog_invalid")
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return Evidence(**blank, reason="property_catalog_invalid")

    def normalized(value: str) -> str:
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()

    text = normalized(inbound)
    wanted = _request_price_jpy(text)
    valid_rows = [row for row in rows if isinstance(row, dict)]
    explicit_ids = set(re.findall(r"(?:物件id|物件番号|propertyid)[:#]?([0-9]+)(?![a-z0-9])", text))
    named_rows = [row for row in valid_rows
                  if len(normalized(str(row.get("property.label") or ""))) >= 4
                  and normalized(str(row.get("property.label") or "")) in text]
    has_identity = bool(explicit_ids or named_rows)
    if explicit_ids:
        identified = [row for row in valid_rows
                      if str(row.get("propertyId") or row.get("property.id") or "") in explicit_ids]
        if len(explicit_ids) != 1 or (named_rows and named_rows != identified):
            return Evidence(**blank, reason="conflicting_property_identity")
    else:
        identified = named_rows
    # Broad geography alone must never auto-select among unrelated properties.
    areas = [word for word in ("海浜幕張", "幕張本郷", "幕張", "横浜", "渋谷", "新宿", "吉祥寺", "藤沢") if word in text]
    area = areas[0] if areas else ""
    if not has_identity and (not area or wanted is None):
        return Evidence(**blank, reason="insufficient_property_identity")
    matched = []
    candidates = identified if has_identity else valid_rows
    if has_identity and len(candidates) != 1:
        return Evidence(**{**blank, "ambiguous": len(candidates) > 1}, reason="no_unique_property_match")
    for row in candidates:
        name = str(row.get("property.label") or "")
        city = str(row.get("property.cityLabel") or "")
        p = row.get("property.price")
        try:
            price = int(float(p))
        except (ValueError, TypeError, OverflowError):
            continue
        if not has_identity and area not in name + city:
            continue
        if wanted is not None and abs(price - wanted) > max(50_000_000, wanted * 0.03):
            continue
        matched.append((row, price))
    if len(matched) != 1:
        return Evidence(**blank, ambiguous=len(matched) > 1, reason="no_unique_property_match")
    row, price = matched[0]
    scope = str(row.get("publicationScope") or "").upper()
    return Evidence(
        matched=True, ambiguous=False, subject=inbound[:100],
        property_id=str(row.get("propertyId") or row.get("property.id") or ""),
        label=str(row.get("property.label") or ""),
        price_jpy=price, city=str(row.get("property.cityLabel") or ""),
        detail_url=str(row.get("detail_url") or ""),
        publication_scope=scope,
        # Sharing must be separately checked per property and document.
        sharing_cleared=False,
        source=str(path), reason="matched_candidate_sharing_unverified",
    )
