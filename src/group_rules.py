from __future__ import annotations

import re
from typing import Any

URL_RE = re.compile(r"https?://\S+")


def strip_links(body: str) -> str:
    return URL_RE.sub("", body).strip()


def normalize_forbidden_words(group: dict[str, Any]) -> list[str]:
    values = group.get("forbidden", []) or []
    return [str(v) for v in values if str(v)]


def apply_group_rules(body: str, group: dict[str, Any]) -> str:
    normalized = body or ""
    if not group.get("allow_links", True):
        normalized = strip_links(normalized)
    for word in normalize_forbidden_words(group):
        normalized = normalized.replace(word, "")
    signature = group.get("signature", "") or ""
    if signature and signature.strip() not in normalized:
        normalized = f"{normalized.rstrip()}\n{signature}"
    max_chars = int(group.get("max_chars", 1500))
    if len(normalized) > max_chars:
        reserve = len(signature) + 8 if signature else 0
        limit = max(0, max_chars - reserve)
        normalized = normalized[:limit].rstrip()
        if signature:
            normalized = f"{normalized}\n{signature}"
    return normalized.strip()


def validate_group_policy(group: dict[str, Any]) -> None:
    required = ["id", "name", "post_url", "tone", "max_chars", "active_hours"]
    for key in required:
        if key not in group:
            raise ValueError(f"group {group!r} is missing {key}")
    active_hours = group.get("active_hours")
    if not isinstance(active_hours, list) or len(active_hours) != 2:
        raise ValueError(f"group {group.get('id')} active_hours must be [start, end]")
    start, end = int(active_hours[0]), int(active_hours[1])
    if not (0 <= start <= 24 and 0 <= end <= 24):
        raise ValueError(f"group {group.get('id')} active_hours must be between 0 and 24")
    if int(group.get("max_chars", 0)) <= 0:
        raise ValueError(f"group {group.get('id')} max_chars must be positive")
