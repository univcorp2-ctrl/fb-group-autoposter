"""Keep Messenger reply drafts refreshed and the latest reply screen open.

Safety properties:
- NEVER sends a Facebook/Messenger message.
- Reuses the dedicated Messenger Playwright profile only.
- Generates drafts through the existing run_once scan pipeline.
- Uses fb_draft_writer, which preserves non-matching human composer text.
- Keeps only one daemon instance active using a local lock file.

Default interval: 30 minutes. Override with MESSENGER_DRAFT_INTERVAL_MINUTES.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from scripts.run_once import _scan  # noqa: E402
from src.fb_draft_writer import write_draft_no_send  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("draft_daemon")
JST = timezone(timedelta(hours=9))
DEFAULT_INTERVAL_MINUTES = 30
MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 240


def _now_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")


def _interval_minutes() -> int:
    raw = os.getenv("MESSENGER_DRAFT_INTERVAL_MINUTES", str(DEFAULT_INTERVAL_MINUTES)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_INTERVAL_MINUTES
    return max(MIN_INTERVAL_MINUTES, min(MAX_INTERVAL_MINUTES, value))


def _load_active_drafts(data_dir: Path) -> list[dict[str, Any]]:
    path = data_dir / "drafts.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = payload.get("drafts", []) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict) and row.get("url") and row.get("draft")]


def _select_focus_draft(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    # drafts.json preserves scan/inbox order. High-priority rows win; otherwise
    # keep the first active row so the visible browser opens the most actionable thread.
    for row in rows:
        if row.get("priority") == "high":
            return row
    return rows[0]


class _SingleInstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: Any | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a+", encoding="utf-8")
        try:
            import msvcrt

            msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self._fh.close()
            self._fh = None
            return False
        self._fh.seek(0)
        self._fh.truncate()
        self._fh.write(str(os.getpid()))
        self._fh.flush()
        return True

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            import msvcrt

            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self._fh.close()
        self._fh = None


async def _hold_reply_screen(settings: Settings, row: dict[str, Any], seconds: int) -> dict[str, Any]:
    """Open one target thread visibly, verify/place its draft, then keep it open."""
    from playwright.async_api import async_playwright

    result: dict[str, Any] = {
        "opened": False,
        "draft_visible": False,
        "thread_id": str(row.get("thread_id", "")),
        "name": str(row.get("name", "")),
        "url": str(row.get("url", "")),
    }
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir),
            headless=False,
            viewport={"width": 1366, "height": 900},
            user_agent=settings.browser_user_agent,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            result["draft_visible"] = await write_draft_no_send(page, str(row["url"]), str(row["draft"]))
            result["opened"] = True
            # Keep the actual Messenger reply screen visible until the next scan.
            # The task never presses Enter or clicks Send.
            remaining = max(1, seconds)
            while remaining > 0:
                step = min(30, remaining)
                await page.wait_for_timeout(step * 1000)
                remaining -= step
        finally:
            await ctx.close()
    return result


def _write_status(settings: Settings, payload: dict[str, Any]) -> None:
    path = settings.data_dir / "draft_daemon_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def main_async() -> int:
    settings = Settings.load()
    interval_minutes = _interval_minutes()
    interval_seconds = interval_minutes * 60
    lock = _SingleInstanceLock(settings.data_dir / "draft_daemon.lock")
    if not lock.acquire():
        log.info("another Messenger draft daemon is already running")
        return 0

    try:
        while True:
            started = _now_jst()
            status: dict[str, Any] = {
                "running": True,
                "started_at": started,
                "interval_minutes": interval_minutes,
                "send_enabled": False,
                "profile_dir": str(settings.profile_dir),
            }
            try:
                # The existing scan pipeline owns its browser briefly, classifies
                # inbox rows, builds drafts, persists state, and may write drafts.
                scan = await _scan(settings, use_telegram=True)
                status["scan"] = scan
                rows = _load_active_drafts(settings.data_dir)
                focus = _select_focus_draft(rows)
                status["active_drafts"] = len(rows)
                status["focus"] = {
                    "thread_id": str(focus.get("thread_id", "")),
                    "name": str(focus.get("name", "")),
                    "url": str(focus.get("url", "")),
                } if focus else None
                status["last_success_at"] = _now_jst()
                _write_status(settings, status)

                if focus:
                    hold = await _hold_reply_screen(settings, focus, interval_seconds)
                    status["hold"] = hold
                    _write_status(settings, status)
                else:
                    # No active reply needed: avoid opening a meaningless thread,
                    # but keep periodic scans alive.
                    await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # one failed cycle must not kill the daemon
                log.exception("Messenger draft cycle failed")
                status["last_error_at"] = _now_jst()
                status["error"] = f"{type(exc).__name__}: {exc}"
                _write_status(settings, status)
                await asyncio.sleep(min(interval_seconds, 5 * 60))
    finally:
        lock.release()


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
