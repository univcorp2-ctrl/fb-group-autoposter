from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings
from src.session import classify_challenge, is_logged_in


async def main() -> None:
    from playwright.async_api import async_playwright

    settings = Settings.load(ROOT / ".env")
    profile = settings.profile_dir
    if not profile.is_absolute():
        profile = ROOT / profile

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            channel="chrome",
            headless=False,
            viewport={"width": 1366, "height": 900},
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)
            result = {
                "url": page.url,
                "logged_in": await is_logged_in(page),
                "challenge": await classify_challenge(page),
                "email_input": await page.locator('input[name="email"]').count(),
                "password_input": await page.locator('input[name="pass"]').count(),
                "continue_buttons": (
                    await page.get_by_role("button", name="Continue").count()
                    + await page.get_by_role("button", name="続行").count()
                ),
                "login_buttons": (
                    await page.get_by_role("button", name="Log in").count()
                    + await page.get_by_role("button", name="ログイン").count()
                ),
            }
            print(result)
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
