"""Resolve a Messenger material request to a verified Drive PDF (fail closed).

Only proof-backed entries in the private Drive registry may be attached. Never
guess a PDF from a near-name search. PDF bytes remain in the user's Drive,
and downloads are validated against allowed property + file metadata.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from src.property_evidence import lookup_property, Evidence

SOURCE = Path(os.environ.get("MESSENGER_PROPERTY_SOURCE",r"C:\AI-Agent\EstateBoard\output\received\properties.json"))
REGISTRY = Path(os.environ.get("MESSENGER_DRIVE_MATERIAL_REGISTRY",r"G:\マイドライブ\AI_Agents\Private\FBGroupAutoposter\material_registry.json"))
CACHE = Path(os.environ.get("MESSENGER_MATERIAL_CACHE",r"G:\マイドライブ\AI_Agents\Private\FBGroupAutoposter\material_cache"))
MAX_BYTES = 15_000_000
DRIVE_ID = re.compile(r"^[A-Za-z0-9_-]{20,90}$")

@dataclass(frozen=True)
class Material:
    approved: bool
    reason: str
    property_id: str = ""
    property_label: str = ""
    drive_file_id: str = ""
    file_name: str = ""
    file_path: str = ""
    sha256: str = ""
    updated_at: str = ""
    source_url: str = ""

    def dict(self) -> dict[str, Any]:
        return asdict(self)


def _rows(source: Path) -> list[dict]:
    doc = json.loads(source.read_text(encoding="utf-8"))
    return doc.get("items", []) if isinstance(doc, dict) else doc


def _latest_row(evidence: Evidence, source: Path) -> dict | None:
    if not evidence.matched or evidence.ambiguous or not evidence.property_id:
        return None
    matching = [r for r in _rows(source) if str(r.get("propertyId")) == evidence.property_id]
    return matching[0] if len(matching) == 1 else None


def _registered(item: dict, entry: dict) -> bool:
    file_id = str(entry.get("drive_file_id", ""))
    if not DRIVE_ID.fullmatch(file_id):
        return False
    if entry.get("mime_type") != "application/pdf" or not str(entry.get("file_name", "")).lower().endswith(".pdf"):
        return False
    if entry.get("google_drive_permission") != "anyone_reader":
        return False
    if not entry.get("broker_sharing_verified"):
        return False
    if not entry.get("manual_document_sharing_approval"):
        # Broadly shared Drive links and broker permissions do not automatically
        # override a USER-only publication scope. Require explicit clearance.
        return False
    if not item.get("property.propertyAttachments"):
        return False
    attachments = item["property.propertyAttachments"]
    try:
        attachments = json.loads(attachments) if isinstance(attachments, str) else attachments
    except (ValueError, TypeError):
        return False
    if not isinstance(attachments, list):
        return False
    expected_name = str(entry.get("source_attachment_name") or "")
    return bool(expected_name and any(
        str(a.get("path", "")).endswith(expected_name) for a in attachments
        if isinstance(a, dict)
    ))


def plan_material(inbound: str, source: Path | None=None, registry: Path | None=None) -> Material:
    source = source or SOURCE
    registry = registry or REGISTRY
    evidence = lookup_property(inbound,source)
    if not evidence.matched or evidence.ambiguous:
        return Material(False, "property_not_uniquely_identified")
    row = _latest_row(evidence,source)
    if not row:
        return Material(False, "property_catalog_row_missing")
    if str(row.get("publicationStatus")) != "PUBLISHED":
        return Material(False, "property_not_published")
    if str(row.get("property.allowBrokerSharing")).lower() not in {"true","1"}:
        return Material(False, "broker_sharing_not_permitted")
    if str(row.get("property.disclosureStatus")) != "ABLE_TO_SHOW":
        return Material(False, "document_disclosure_not_verified")
    if not registry.is_file():
        return Material(False, "drive_material_registry_missing")
    try:
        entries = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Material(False, "drive_material_registry_invalid")
    matches = [v for v in entries.get("materials", []) if str(v.get("property_id"))==evidence.property_id]
    if len(matches)!=1:
        return Material(False,"not_one_verified_pdf")
    entry=matches[0]
    if not _registered(row,entry):
        return Material(False,"document_sharing_approval_or_attachment_match_missing")
    try:
        updated=datetime.fromisoformat(str(row.get("updatedAt","")).replace("Z","+00:00"))
    except (ValueError,TypeError):
        return Material(False,"property_update_unverified")
    max_days = min(365,max(1,int(os.getenv("MESSENGER_MATERIAL_MAX_AGE_DAYS","120"))))
    age=(datetime.now(timezone.utc)-updated).total_seconds()/86400
    if age<0 or age>max_days:
        return Material(False,"property_status_stale")
    return Material(
        approved=True,reason="verified_registry",
        property_id=evidence.property_id,property_label=evidence.label,
        drive_file_id=entry["drive_file_id"],file_name=entry["file_name"],
        updated_at=str(row.get("updatedAt","")),source_url=entry.get("drive_url",""),
    )


def download_material(plan: Material, cache: Path | None=None) -> Material:
    if not plan.approved or not DRIVE_ID.fullmatch(plan.drive_file_id):
        raise RuntimeError("material_not_preapproved")
    cache=cache or CACHE
    cache.mkdir(parents=True,exist_ok=True)
    if (not plan.file_name or Path(plan.file_name).name != plan.file_name
            or any(c in plan.file_name for c in '\\/:*?"<>|')):
        raise RuntimeError("unsafe_pdf_filename")
    dest=cache/plan.property_id/plan.file_name
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():
        data=dest.read_bytes()
    else:
        uri=f"https://drive.google.com/uc?export=download&id={plan.drive_file_id}"
        response=requests.get(uri,timeout=30,stream=True,allow_redirects=True)
        response.raise_for_status()
        if not response.url.startswith("https://drive.usercontent.google.com/") and not response.url.startswith("https://drive.google.com/"):
            raise RuntimeError("document_download_redirect_not_google")
        chunks=[]
        n=0
        for chunk in response.iter_content(65536):
            n+=len(chunk)
            if n>MAX_BYTES:
                raise RuntimeError("material_oversized")
            chunks.append(chunk)
        data=b"".join(chunks)
        if data[:5]!=b"%PDF-" or len(data)<1000:
            raise RuntimeError("drive_material_not_a_pdf")
        temp=dest.with_suffix(".partial")
        temp.write_bytes(data)
        temp.replace(dest)
    if data[:5]!=b"%PDF-" or len(data)>MAX_BYTES:
        raise RuntimeError("invalid_cached_pdf")
    checksum=hashlib.sha256(data).hexdigest()
    return Material(**{**plan.dict(),"file_path":str(dest),"sha256":checksum})
