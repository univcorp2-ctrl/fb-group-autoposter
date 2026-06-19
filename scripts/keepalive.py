"""Keep the Facebook login session alive and snapshot a healthy profile.

Run a few times a day (and at logon). Each run opens Facebook briefly with the
posting profile, confirms the session is still logged in, does a small human-like
action so the session stays warm, and — when healthy — backs up the profile so a
later expiry can be auto-restored. If the session is gone, it alerts (Telegram if
configured) and records the unhealthy state; it never tries to silently re-login
(that needs the human + possible 2FA via login_once.py).

Exit code is 0 even when unhealthy so the scheduler does not mark the task failed
on a transient network blip; health is recorded in logs/session_status.json and
the 'session' heartbeat.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from src.approval import TelegramApproval  # noqa: E402
from src.logging_setup import setup_logging  # noqa: E402
from src.queue_db import QueueDB  # noqa: E402
from src.session import backup_profile, is_logged_in, login_required_message  # noqa: E402

log = logging.getLogger("keepalive")
STATUS = ROOT / "logs" / "session_status.json"


async def check_and_warm(settings: Settings) -> dict:
    from playwright.async_api import async_playwright

    healthy = False
    detail = ""
    backup = None
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir),
            headless=False,
            viewport={"width": 1366, "height": 900},
            timeout=settings.page_hard_timeout * 1000,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(4000)
            healthy = await is_logged_in(page)
            detail = page.url
            if healthy:
                # small human-like activity keeps the session warm
                try:
                    await page.mouse.wheel(0, 600)
                    await page.wait_for_timeout(1500)
                    await page.mouse.wheel(0, -300)
                    await page.wait_for_timeout(1000)
                except Exception:
                    pass
        finally:
            await ctx.close()

    if healthy:
        backup = backup_profile(settings.profile_dir, keep=settings.profile_backup_keep)
    return {"healthy": healthy, "detail": detail, "backup": str(backup) if backup else None}


def main() -> int:
    setup_logging()
    settings = Settings.load()
    db = QueueDB(settings.db_path)
    notifier = TelegramApproval(settings, db)

    try:
        result = asyncio.run(check_and_warm(settings))
    except Exception as exc:  # noqa: BLE001 - never crash the keepalive task
        log.warning("keepalive check error: %s: %s", type(exc).__name__, exc)
        result = {"healthy": False, "detail": f"{type(exc).__name__}: {exc}", "backup": None}

    status = {"checked_at": datetime.now(UTC).isoformat(), **result}
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    if result["healthy"]:
        db.mark_heartbeat("session")
        log.info("session healthy; backup=%s", result["backup"])
    else:
        log.error("session NOT healthy: %s", result["detail"])
        if notifier.enabled:
            notifier.alert(f"Facebookセッション要再ログイン: {login_required_message()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
