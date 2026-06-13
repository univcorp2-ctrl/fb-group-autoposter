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


async def verify_post_visible(page: Any, body: str, *, attempts: int = 12, interval_ms: int = 1500) -> bool:
    # Whitespace-squashed compare: the feed renders each line as a separate node,
    # so raw newlines never appear contiguously in the HTML. We also wait for the
    # composer dialog ("投稿中" spinner) to close so a still-open composer is not
    # mistaken for a published post.
    needle = re.sub(r"\s+", "", body)[:30]
    if not needle:
        return False
    try:
        for _ in range(attempts):
            await page.wait_for_timeout(interval_ms)
            dialog_open = await page.locator(_DIALOG_TEXTBOX).count()
            squashed = re.sub(r"\s+", "", await page.content())
            if not dialog_open and needle in squashed:
                return True
        return needle in re.sub(r"\s+", "", await page.content())
    except Exception:
        return False


def dry_run_screenshot_path(job_id: str, group_id: str) -> str:
    Path("screenshots").mkdir(parents=True, exist_ok=True)
    path = Path("screenshots") / f"dry_run_{job_id}_{group_id}.txt"
    path.write_text("DRY_RUN: screenshot not captured\n", encoding="utf-8")
    return str(path)
