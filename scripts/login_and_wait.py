"""Open a headed browser and wait (polling) until Facebook login is detected.

Unlike login_once.py (which blocks on terminal input), this polls
`is_logged_in()` so it can be launched in the background: a browser window
appears, the operator logs in (password + 2FA) in that window, and the session
is persisted to the profile dir automatically — no terminal interaction needed.

Usage:
    python scripts/login_and_wait.py --timeout 600
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings
from src.session import is_logged_in

POLL_SECONDS = 3


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=600, help="max seconds to wait for login")
    args = parser.parse_args()

    from playwright.async_api import async_playwright

    settings = Settings.load()
    Path(settings.profile_dir).mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir),
            headless=False,
            viewport={"width": 1366, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        print("BROWSER_OPEN: Facebookにログインしてください（2FA/checkpointも画面で完了）。", flush=True)

        async def cookie_logged_in() -> bool:
            try:
                cookies = await context.cookies("https://www.facebook.com")
                return any(c.get("name") == "c_user" and c.get("value") for c in cookies)
            except Exception:
                return False

        deadline = time.monotonic() + args.timeout
        logged_in = False
        while time.monotonic() < deadline:
            try:
                if await cookie_logged_in() or await is_logged_in(page):
                    logged_in = True
                    break
            except Exception:
                pass
            await asyncio.sleep(POLL_SECONDS)

        if logged_in:
            # let cookies flush to disk
            await asyncio.sleep(2)
            print(f"LOGIN_OK: セッション保存 {settings.profile_dir}", flush=True)
        else:
            print("LOGIN_TIMEOUT: ログインを検知できませんでした。", flush=True)
        await context.close()
        return 0 if logged_in else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
