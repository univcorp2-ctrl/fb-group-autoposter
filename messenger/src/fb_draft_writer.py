"""Tier B (opt-in): type a reply draft into the Messenger composer WITHOUT sending.

⚠️ This is the only module that writes into Facebook. It is disabled by default
(WRITE_DRAFT_TO_FB=false). Even when enabled it:
  - types the draft into the message box and STOPS — it never presses Enter / Send
  - Messenger keeps unsent composer text as a per-thread draft, so the operator
    finds the text ready to review-and-send by hand

The actual send is ALWAYS a human action. There is deliberately no send path here.
"""

from __future__ import annotations

import logging
import random
from typing import Any

log = logging.getLogger(__name__)

# Composer textbox in an open Messenger thread (defensive selector list).
_COMPOSER_SELECTORS = (
    'div[aria-label="メッセージを入力"][contenteditable="true"]',
    'div[aria-label="Message"][contenteditable="true"]',
    'div[role="textbox"][contenteditable="true"]',
)

# Human-typed prefix length; the rest is inserted fast to stay under timeouts.
_HUMAN_PREFIX = 16


async def _find_composer(page: Any) -> Any | None:
    for selector in _COMPOSER_SELECTORS:
        try:
            loc = page.locator(selector).first
            if await loc.count() > 0:
                return loc
        except Exception:
            continue
    return None


async def write_draft_no_send(page: Any, thread_url: str, draft: str) -> bool:
    """Open the thread and type the draft into the composer. NEVER sends.

    Returns True if the text was placed in the composer, False otherwise. Any
    error degrades to False — the Notion/Telegram copy is always the fallback.
    """
    if not draft.strip():
        return False
    try:
        await page.goto(thread_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(random.randint(2500, 4500))
        composer = await _find_composer(page)
        if composer is None:
            log.warning("composer not found for %s; draft not placed", thread_url)
            return False
        await composer.click()
        await page.wait_for_timeout(random.randint(500, 1400))
        prefix, rest = draft[:_HUMAN_PREFIX], draft[_HUMAN_PREFIX:]
        await composer.type(prefix, delay=random.randint(60, 150), timeout=20000)
        if rest:
            # Messenger's Lexical editor turns Enter into Send, so we must NOT
            # type raw newlines. Replace them with spaces in the placed text;
            # the full multi-line draft still lives in Notion/Telegram for the
            # human to paste verbatim if they prefer.
            await composer.type(rest.replace("\n", " "), delay=0, timeout=60000)
        await page.wait_for_timeout(random.randint(600, 1500))
        log.info("draft placed in composer (NOT sent): %s", thread_url)
        return True
    except Exception as exc:  # noqa: BLE001 - never crash the run
        log.warning("write_draft_no_send failed for %s: %s: %s", thread_url, type(exc).__name__, exc)
        return False
