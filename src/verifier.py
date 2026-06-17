from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DIALOG_TEXTBOX = 'div[role="dialog"] div[role="textbox"][contenteditable="true"]'


async def save_screenshot(page: Any, *, prefix: str, job_id: str, group_id: str) -> str:
    Path("screenshots").mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = Path("screenshots") / f"{prefix}_{job_id}_{group_id}_{stamp}.png"
    await page.screenshot(path=str(path), full_page=True)
    return str(path)


async def _needle_in_page(page: Any, needle: str) -> bool:
    squashed = re.sub(r"\s+", "", await page.content())
    return needle in squashed


async def verify_post_visible(
    page: Any,
    body: str,
    *,
    attempts: int = 10,
    interval_ms: int = 1500,
    reload_rounds: int = 3,
) -> bool:
    """Confirm a published post is actually visible in the group feed.

    Two phases, because a freshly published post is lazy-loaded:
      1. Wait for the composer dialog to close (submission accepted).
      2. Reload the group feed and scroll so the new post renders, then look
         for the body text. Without the reload+scroll the post often sits below
         the fold and a successful post is wrongly marked "uncertain".

    Whitespace-squashed compare: the feed renders each line as a separate node,
    so raw newlines never appear contiguously in the HTML.
    """
    needle = re.sub(r"\s+", "", body)[:40]
    if not needle:
        return False
    try:
        # Phase 1: wait for the composer dialog to close (submission accepted).
        for _ in range(attempts):
            await page.wait_for_timeout(interval_ms)
            if await page.locator(_DIALOG_TEXTBOX).count() == 0:
                break
        # Phase 2: surface the freshly published post via reload + scroll.
        for round_index in range(reload_rounds):
            if await _needle_in_page(page, needle):
                return True
            if round_index < reload_rounds - 1:
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    pass
                for _ in range(3):
                    await page.mouse.wheel(0, 1600)
                    await page.wait_for_timeout(1200)
        return await _needle_in_page(page, needle)
    except Exception:
        return False


def dry_run_screenshot_path(job_id: str, group_id: str) -> str:
    Path("screenshots").mkdir(parents=True, exist_ok=True)
    path = Path("screenshots") / f"dry_run_{job_id}_{group_id}.txt"
    path.write_text("DRY_RUN: screenshot not captured\n", encoding="utf-8")
    return str(path)
