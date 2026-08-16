"""Scan Messenger, save reply drafts, and keep them visibly open for review.

This runner NEVER sends a message. It first executes the normal draft scan, then
opens each active saved draft (max 5) in a dedicated visible Messenger tab,
places the draft into the composer, and keeps the browser open for a bounded
review window. Messenger Web currently discards composer drafts across a hard
reload/browser restart, so keeping the dedicated browser open is the reliable
way to make unsent drafts visibly reviewable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from scripts.run_once import _scan  # noqa: E402
from src.fb_draft_writer import write_draft_no_send  # noqa: E402

log = logging.getLogger("run_visible_drafts")
STATUS_PATH = ROOT / "data" / "visible_drafts_status.json"
DEFAULT_HOLD_MINUTES = 50
MAX_VISIBLE_TABS = 5


def _arg_hold_minutes() -> int:
    if "--hold-minutes" not in sys.argv:
        return DEFAULT_HOLD_MINUTES
    try:
        index = sys.argv.index("--hold-minutes")
        return max(0, min(55, int(sys.argv[index + 1])))
    except (ValueError, IndexError):
        return DEFAULT_HOLD_MINUTES


def _write_status(payload: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_active_drafts(settings: Settings) -> list[dict]:
    path = settings.data_dir / "drafts.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = data.get("drafts", []) if isinstance(data, dict) else []
    return [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("url")
        and str(row.get("draft", "")).strip()
    ][:MAX_VISIBLE_TABS]


async def _show_saved_drafts(settings: Settings, hold_minutes: int) -> dict:
    from playwright.async_api import async_playwright

    rows = _load_active_drafts(settings)
    result = {
        "active_drafts": len(rows),
        "visible_tabs": 0,
        "hold_minutes": hold_minutes,
        "threads": [],
    }
    if not rows:
        _write_status({**result, "status": "no_active_drafts"})
        return result

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir),
            headless=False,
            viewport={"width": 1366, "height": 900},
            user_agent=settings.browser_user_agent,
        )
        closed = asyncio.Event()
        context.on("close", lambda: closed.set())

        pages = list(context.pages)
        try:
            for index, row in enumerate(rows):
                if index < len(pages):
                    page = pages[index]
                else:
                    page = await context.new_page()
                    pages.append(page)
                placed = await write_draft_no_send(
                    page,
                    str(row["url"]),
                    str(row["draft"]),
                )
                result["threads"].append(
                    {
                        "thread_id": row.get("thread_id"),
                        "name": row.get("name"),
                        "visible": placed,
                    }
                )
                if placed:
                    result["visible_tabs"] += 1

            status = "visible" if result["visible_tabs"] else "not_visible"
            _write_status(
                {
                    **result,
                    "status": status,
                    "opened_at": datetime.now(UTC).isoformat(),
                }
            )

            if result["visible_tabs"] and hold_minutes > 0:
                try:
                    await asyncio.wait_for(
                        closed.wait(),
                        timeout=hold_minutes * 60,
                    )
                except TimeoutError:
                    pass
        finally:
            if not closed.is_set():
                await context.close()

    _write_status(
        {
            **result,
            "status": "closed",
            "closed_at": datetime.now(UTC).isoformat(),
        }
    )
    return result


async def main_async() -> dict:
    settings = Settings.load()
    if settings.read_only or not settings.write_draft_to_fb:
        raise RuntimeError(
            "visible draft runner requires READ_ONLY=false and WRITE_DRAFT_TO_FB=true"
        )

    show_only = "--show-only" in sys.argv
    scan_summary = None if show_only else await _scan(settings, use_telegram=True)
    visible_summary = await _show_saved_drafts(settings, _arg_hold_minutes())
    result = {"scan": scan_summary, "visible": visible_summary}
    print(json.dumps(result, ensure_ascii=False))
    return result


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
