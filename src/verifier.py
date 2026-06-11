from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any


async def save_screenshot(page: Any, *, prefix: str, job_id: str, group_id: str) -> str:
    Path("screenshots").mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = Path("screenshots") / f"{prefix}_{job_id}_{group_id}_{stamp}.png"
    await page.screenshot(path=str(path), full_page=True)
    return str(path)


async def verify_post_visible(page: Any, body: str) -> bool:
    needle = body.strip()[:40]
    if not needle:
        return False
    try:
        await page.wait_for_timeout(3000)
        content = await page.content()
        return needle in content
    except Exception:
        return False


def dry_run_screenshot_path(job_id: str, group_id: str) -> str:
    Path("screenshots").mkdir(parents=True, exist_ok=True)
    path = Path("screenshots") / f"dry_run_{job_id}_{group_id}.txt"
    path.write_text("DRY_RUN: screenshot not captured\n", encoding="utf-8")
    return str(path)
