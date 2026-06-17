from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.selectors import SELECTORS

_DIALOG_TEXTBOX = 'div[role="dialog"] div[role="textbox"][contenteditable="true"]'


async def save_screenshot(page: Any, *, prefix: str, job_id: str, group_id: str) -> str:
    Path("screenshots").mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = Path("screenshots") / f"{prefix}_{job_id}_{group_id}_{stamp}.png"
    await page.screenshot(path=str(path), full_page=True)
    return str(path)


async def _posting_block_present(page: Any) -> bool:
    for selector in SELECTORS["posting_block_markers"]:
        try:
            if await page.query_selector(selector):
                return True
        except Exception:
            continue
    return False


async def verify_post_visible(page: Any, body: str, *, attempts: int = 12, interval_ms: int = 1500) -> bool:
    """Return True when the post was accepted by Facebook.

    The reliable success signal is the composer dialog closing after the Post
    click, with no posting-block marker present. The group feed is
    relevance-sorted and lazy-loaded, so scraping its HTML for the body text is
    unreliable — it misses even posts that demonstrably exist — which previously
    marked genuine successes as "uncertain". The body content itself is already
    confirmed before the click by FacebookPoster._verify_composer_contains, so a
    cleanly-closed composer means the (correct) post was submitted and, for a
    group without post approval, published.
    """
    if not body.strip():
        return False
    try:
        composer_closed = False
        for _ in range(attempts):
            await page.wait_for_timeout(interval_ms)
            if await page.locator(_DIALOG_TEXTBOX).count() == 0:
                composer_closed = True
                break
        if not composer_closed:
            return False
        return not await _posting_block_present(page)
    except Exception:
        return False


def dry_run_screenshot_path(job_id: str, group_id: str) -> str:
    Path("screenshots").mkdir(parents=True, exist_ok=True)
    path = Path("screenshots") / f"dry_run_{job_id}_{group_id}.txt"
    path.write_text("DRY_RUN: screenshot not captured\n", encoding="utf-8")
    return str(path)
