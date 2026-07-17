"""Resolve EstateBoard property images from the Google Drive archive.

The archive is read-only. Folder indexing is cached for one process so each
Facebook group does not trigger another full Drive scan.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
SKIP_DIR_NAMES = {"_データ", "data", "logs", "output"}


def _get(item: dict[str, Any], key: str) -> Any:
    if f"property.{key}" in item:
        return item[f"property.{key}"]
    prop = item.get("property")
    return prop.get(key) if isinstance(prop, dict) else None


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^0-9a-zぁ-んァ-ヶ一-龠]+", "", text)


@lru_cache(maxsize=4)
def _folder_index(root_text: str) -> tuple[tuple[str, str, str], ...]:
    root = Path(root_text)
    if not root.exists():
        return ()
    rows: list[tuple[str, str, str]] = []
    try:
        for folder in root.iterdir():
            if not folder.is_dir() or folder.name in SKIP_DIR_NAMES or folder.name.startswith("_"):
                continue
            rows.append((normalize_name(folder.name), folder.name, str(folder)))
    except OSError as exc:
        log.warning("Drive archive scan failed for %s: %s", root, exc)
    return tuple(rows)


def _score_folder(folder_norm: str, folder_raw: str, property_id: str, title_norm: str) -> int:
    score = 0
    digits = re.sub(r"\D", "", property_id)
    if digits and digits in folder_raw:
        score += 100
    if title_norm and title_norm == folder_norm:
        score += 90
    elif title_norm and (title_norm in folder_norm or folder_norm in title_norm):
        score += 60
    return score


def resolve_property_images(
    item: dict[str, Any], drive_root: str | Path | None, *, max_images: int = 5
) -> list[str]:
    if not drive_root:
        return []
    root = Path(drive_root)
    property_id = str(item.get("propertyId") or item.get("id") or "")
    title = _get(item, "label") or item.get("label") or ""
    title_norm = normalize_name(title)
    ranked: list[tuple[int, Path]] = []
    for folder_norm, folder_raw, folder_text in _folder_index(str(root)):
        score = _score_folder(folder_norm, folder_raw, property_id, title_norm)
        if score:
            ranked.append((score, Path(folder_text)))
    ranked.sort(key=lambda row: row[0], reverse=True)
    for _, folder in ranked[:5]:
        candidates: list[Path] = []
        for base in (folder / "images", folder):
            if not base.exists():
                continue
            try:
                candidates.extend(
                    p for p in base.iterdir() if p.is_file() and p.suffix.casefold() in IMAGE_SUFFIXES
                )
            except OSError:
                continue
        unique = sorted({p.resolve() for p in candidates}, key=lambda p: p.name.casefold())
        if unique:
            return [str(p) for p in unique[:max_images]]
    return []


def attach_drive_images(
    properties: list[dict[str, Any]],
    source_items: list[dict[str, Any]],
    drive_root: str | Path | None,
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in source_items:
        raw_id = item.get("propertyId") or item.get("id")
        if raw_id is not None:
            by_id[f"eb-{raw_id}"] = item
    for prop in properties:
        item = by_id.get(str(prop.get("property_id")))
        if item:
            prop["images"] = resolve_property_images(item, drive_root)
    return properties
