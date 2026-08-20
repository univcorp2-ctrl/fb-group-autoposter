"""Place a reply draft into the Messenger composer WITHOUT sending.

This is the only module that writes into Facebook. It deliberately has no send
path: it never presses Enter, never clicks Send, and never calls a messaging API.

The writer is idempotent and preserves human edits:
- empty composer -> type the draft;
- composer already contains the same draft -> success, no changes;
- composer contains different text -> leave it untouched and return False.
"""

from __future__ import annotations

import logging
import random
from typing import Any

log = logging.getLogger(__name__)

_COMPOSER_SELECTORS = (
    'div[aria-label="メッセージを入力"][contenteditable="true"]',
    'div[aria-label="Message"][contenteditable="true"]',
    'div[role="textbox"][contenteditable="true"]',
)

_HUMAN_PREFIX = 16


def _normalize(text: str) -> str:
    return " ".join((text or "").replace("\n", " ").split())


async def _find_composer(page: Any) -> Any | None:
    for selector in _COMPOSER_SELECTORS:
        try:
            loc = page.locator(selector).first
            if await loc.count() < 1:
                continue
            await loc.scroll_into_view_if_needed(timeout=10_000)
            if await loc.is_visible():
                return loc
        except Exception:
            continue
    return None


async def _composer_text(composer: Any) -> str:
    for getter in ("inner_text", "text_content"):
        try:
            value = await getattr(composer, getter)()
            if value:
                return str(value)
        except Exception:
            continue
    return ""


async def write_draft_no_send(page: Any, thread_url: str, draft: str) -> bool:
    """Open a thread and place ``draft`` into its composer. NEVER sends."""
    if not draft.strip():
        return False
    try:
        await page.goto(thread_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(random.randint(2500, 4500))
        composer = await _find_composer(page)
        if composer is None:
            log.warning("composer not found for %s; draft not placed", thread_url)
            return False

        desired = _normalize(draft)
        existing = _normalize(await _composer_text(composer))
        if existing:
            if existing == desired:
                log.info("draft already visible in composer: %s", thread_url)
                return True
            log.warning("composer contains different text; preserving it: %s", thread_url)
            return False

        await composer.click()
        await page.wait_for_timeout(random.randint(500, 1400))
        flat = draft.replace("\n", " ")
        prefix, rest = flat[:_HUMAN_PREFIX], flat[_HUMAN_PREFIX:]
        await composer.type(prefix, delay=random.randint(60, 150), timeout=20000)
        if rest:
            await composer.type(rest, delay=0, timeout=60000)
        await page.wait_for_timeout(random.randint(600, 1500))

        final_text = _normalize(await _composer_text(composer))
        if final_text != desired:
            log.warning("composer text verification failed for %s", thread_url)
            return False
        log.info("draft placed in composer (NOT sent): %s", thread_url)
        return True
    except Exception as exc:  # noqa: BLE001 - never crash the run
        log.warning(
            "write_draft_no_send failed for %s: %s: %s",
            thread_url,
            type(exc).__name__,
            exc,
        )
        return False

