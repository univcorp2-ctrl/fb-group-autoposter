"""Read-only Facebook group composer diagnostics.

This module deliberately exposes no click, type, upload, submit, or browser
launch API.  The caller may navigate a configured joined group, then supply
the resulting page for a DOM/accessibility-only decision.
"""

from __future__ import annotations

from typing import Any

from src.selectors import SelectorAmbiguous, SelectorMissing, exactly_one_visible


STABLE_REASONS = frozenset(
    {
        "composer_ready",
        "selector_missing",
        "selector_ambiguous",
        "login_required",
        "checkpoint_required",
        "account_trust_blocked",
    }
)


async def diagnose_composer(page: Any) -> dict[str, Any]:
    """Return a sanitized, read-only composer diagnosis for an already-open page."""

    url = str(getattr(page, "url", "")).lower()
    if "/messages" in url or "/messenger" in url:
        return _result("selector_missing")
    if "checkpoint" in url:
        return _result("checkpoint_required")
    if "login" in url:
        return _result("login_required")
    content = await page.content()
    normalized = content.casefold()
    if "id=\"messenger\"" in normalized or "data-pagelet=\"mw" in normalized:
        return _result("selector_missing")
    if any(marker in normalized for marker in ("you can’t post", "you can't post", "投稿できません", "temporarily blocked", "一時的にブロック")):
        return _result("account_trust_blocked")
    try:
        await exactly_one_visible(page, "open_composer")
    except SelectorMissing:
        return _result("selector_missing")
    except SelectorAmbiguous:
        return _result("selector_ambiguous")
    return _result("composer_ready")


def _result(reason: str) -> dict[str, Any]:
    if reason not in STABLE_REASONS:
        raise ValueError("unknown diagnostic reason")
    return {"reason": reason, "read_only": True, "write_performed": False}
