"""One-time manual login into the collector's own Facebook profile.

Logs in on facebook.com (issues PERSISTENT c_user/xs cookies) and auto-detects
success via the c_user cookie — no terminal interaction needed. Separate profile
from the posting + messenger roles, so the collector never interferes with them.

Usage:
    python collector/scripts/login.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from src.session import c_user  # noqa: E402

LOGIN_WAIT_TIMEOUT_S = 600
POLL_INTERVAL_S = 3
FLUSH_DWELL_S = 6


async def _wait_for_login(ctx) -> str | None:
    waited = 0
    while waited < LOGIN_WAIT_TIMEOUT_S:
        uid = await c_user(ctx)
        if uid:
            return uid
        await asyncio.sleep(POLL_INTERVAL_S)
        waited += POLL_INTERVAL_S
    return None


async def _run() -> None:
    from playwright.async_api import async_playwright

    settings = Settings.load()
    print(f"Collector プロファイル: {settings.profile_dir}")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir),
            headless=False,
            viewport={"width": 1366, "height": 900},
            user_agent=settings.browser_user_agent,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=60000)
        print("\n▼ Facebook にログインしてください（2FA/本人確認も対応）。")
        print("  ※「ログイン情報を保存」は ON のままにしてください。")
        print("  検知したら自動で保存して閉じます（最大10分待機）…")
        uid = await _wait_for_login(ctx)
        if uid:
            print(f"✅ ログインを検知しました（user_id={uid}）。保存中…")
            await page.wait_for_timeout(FLUSH_DWELL_S * 1000)
        else:
            print("⌛ タイムアウト（ログイン未検知）。")
        await ctx.close()
    print("完了。`python collector/scripts/collect.py` で収集を実行できます。" if uid else
          "ログインが完了していません。もう一度実行してください。")


if __name__ == "__main__":
    asyncio.run(_run())
