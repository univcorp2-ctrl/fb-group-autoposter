"""Open Facebook login in the central authenticated Chrome Default profile.

The central Executor must already be running its visible Chrome session. Log in
by hand and handle any 2FA/checkpoint. This client never launches or closes the
browser and never falls back to a repository-local or Guest profile.

If you prefer to close it yourself, press Enter in the terminal at any time.

Usage:
    python scripts/login.py
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from src.authenticated_chrome import (  # noqa: E402
    attach_authenticated_context,
    select_messenger_page,
)

# How long to keep the window open waiting for a human to finish logging in.
LOGIN_WAIT_TIMEOUT_S = 600
POLL_INTERVAL_S = 3
# After login, dwell so Chromium flushes cookies to disk and Messenger's
# cross-domain session (messenger.com) gets established from the FB cookies.
FLUSH_DWELL_S = 8


async def _c_user(ctx) -> str | None:
    """Return the value of the c_user cookie (logged-in FB user id) if present.

    This is the GROUND TRUTH for being logged in — far more reliable than DOM
    markers, which can match a transient/anonymous page and give false positives.
    """
    for c in await ctx.cookies():
        if c.get("name") == "c_user" and c.get("value"):
            return c["value"]
    return None


async def _wait_for_login(ctx) -> str | None:
    waited = 0
    while waited < LOGIN_WAIT_TIMEOUT_S:
        uid = await _c_user(ctx)
        if uid:
            return uid
        await asyncio.sleep(POLL_INTERVAL_S)
        waited += POLL_INTERVAL_S
    return None


async def _run() -> None:
    from playwright.async_api import async_playwright

    settings = replace(Settings.load(), browser_display_mode="visible")
    print(f"Messenger プロファイル: {settings.profile_dir.resolve()}")
    async with async_playwright() as p:
        attachment = await attach_authenticated_context(p, settings)
        ctx = attachment.context
        page = await select_messenger_page(ctx)
        # Log in on facebook.com — it issues PERSISTENT c_user/xs cookies (unlike
        # messenger.com's "keep me logged in" which defaulted to a session cookie
        # and was lost on close). Messenger then authenticates from these via SSO.
        await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=60000)
        print("\n▼ ブラウザで Facebook にログインしてください（2FA/本人確認も対応）。")
        print("  ※「ログイン情報を保存」は ON のままにしてください（永続化のため）。")
        print("  ログインを検知したら自動で保存して閉じます（最大10分待機）…")
        uid = await _wait_for_login(ctx)
        if uid:
            print("✅ ログインを検知しました。Messengerセッションを確立中…")
            # Warm messenger.com so its own cookies are set from the FB session.
            try:
                await page.goto("https://www.messenger.com/", wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(FLUSH_DWELL_S * 1000)
            except Exception:  # noqa: BLE001 - warming is best-effort
                await page.wait_for_timeout(FLUSH_DWELL_S * 1000)
            # Confirm c_user persisted as the final ground-truth check.
            persisted = await _c_user(ctx)
        else:
            persisted = None
            print("⌛ タイムアウト（ログイン未検知）。")
    if persisted:
        print("セッションを保存しました。`python scripts/run_once.py` で読み取りを実行できます。")
    else:
        print("⚠️ ログインが永続化されませんでした。もう一度 `python scripts/login.py` を実行し、"
              "「ログイン情報を保存」をONにしてログインしてください。")


if __name__ == "__main__":
    asyncio.run(_run())
