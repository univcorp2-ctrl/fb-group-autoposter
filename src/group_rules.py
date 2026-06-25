from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

# Some sources carry a well-known supplier brand (e.g. Daiwa House) that must
# NEVER appear in a public post — we promote the property as coming from a
# "超大手有名企業ブランド" without naming the company. Replace every alias.
BRAND_MASK = "超大手有名企業ブランド"
_BRAND_ALIASES = (
    "大和ハウス工業株式会社",
    "大和ハウス工業",
    "大和ハウス",
    "ダイワハウス工業",
    "ダイワハウス",
    "Daiwa House Industry",
    "Daiwa House",
    "DaiwaHouse",
)


def mask_brands(text: str) -> str:
    """Replace any supplier brand alias with the generic 超大手有名企業ブランド label."""
    out = text or ""
    for alias in _BRAND_ALIASES:
        out = out.replace(alias, BRAND_MASK)
    return out


@dataclass(frozen=True)
class RuleResult:
    body: str
    removed_links: bool = False
    removed_forbidden: tuple[str, ...] = ()
    truncated: bool = False


def strip_links(body: str) -> tuple[str, bool]:
    new_body = URL_RE.sub("", body).strip()
    return new_body, new_body != body.strip()


def remove_forbidden_words(body: str, forbidden: list[str] | tuple[str, ...] | None) -> tuple[str, tuple[str, ...]]:
    removed: list[str] = []
    out = body
    for word in forbidden or []:
        if word and word in out:
            out = out.replace(word, "")
            removed.append(word)
    return out, tuple(removed)


def append_signature_once(body: str, signature: str | None) -> str:
    signature = signature or ""
    if not signature.strip():
        return body.strip()
    if signature.strip() in body:
        return body.strip()
    return f"{body.rstrip()}\n{signature}".strip()


def enforce_max_chars(body: str, max_chars: int, signature: str | None = None) -> tuple[str, bool]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if len(body) <= max_chars:
        return body, False
    signature = signature or ""
    if signature.strip() and signature.strip() in body:
        base = body.replace(signature, "").rstrip()
        reserve = len(signature) + 1
        return f"{base[: max_chars - reserve].rstrip()}\n{signature}"[:max_chars].strip(), True
    return body[:max_chars].rstrip(), True


def apply_group_rules(body: str, group: dict[str, Any]) -> RuleResult:
    # Mask supplier brand names first so they can never leak into a public post,
    # regardless of which source the property came from.
    body = mask_brands(body)
    signature = group.get("signature", "") or ""
    # Idempotency: if a previous apply already appended the signature, remove it
    # BEFORE link-stripping. Otherwise strip_links (allow_links=false) would
    # delete the signature's own URLs (e.g. the LINE / community-invite links),
    # and append_signature_once would then add a second, intact copy — producing
    # a duplicated signature whose first copy has empty 👉 lines. Removing it
    # first makes apply_group_rules safe to call any number of times.
    if signature.strip() and signature in body:
        body = body.replace(signature, "").rstrip()
    removed_links = False
    if not group.get("allow_links", True):
        body, removed_links = strip_links(body)
    body, removed_forbidden = remove_forbidden_words(body, group.get("forbidden", []))
    body = append_signature_once(body, signature)
    body, truncated = enforce_max_chars(body, int(group.get("max_chars", 1500)), signature)
    return RuleResult(
        body=body.strip(),
        removed_links=removed_links,
        removed_forbidden=removed_forbidden,
        truncated=truncated,
    )


def validate_group(group: dict[str, Any]) -> None:
    required = ["id", "name", "post_url", "tone", "max_chars", "active_hours"]
    for key in required:
        if key not in group:
            raise ValueError(f"group {group!r} is missing {key}")
    if not str(group["id"]).strip():
        raise ValueError("group id must not be empty")
    if not str(group["post_url"]).startswith("https://www.facebook.com/groups/"):
        raise ValueError(f"group {group['id']} post_url must be a Facebook group URL")
    max_chars = int(group["max_chars"])
    if max_chars < 100:
        raise ValueError(f"group {group['id']} max_chars must be >= 100")
    active_hours = group["active_hours"]
    if not isinstance(active_hours, list | tuple) or len(active_hours) != 2:
        raise ValueError(f"group {group['id']} active_hours must be [start, end]")
    start, end = int(active_hours[0]), int(active_hours[1])
    if not (0 <= start <= 24 and 0 <= end <= 24):
        raise ValueError(f"group {group['id']} active_hours must be within 0..24")
    if group.get("forbidden") is not None and not isinstance(group.get("forbidden"), list):
        raise ValueError(f"group {group['id']} forbidden must be a list")
