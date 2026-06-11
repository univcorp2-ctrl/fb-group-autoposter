from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings
from src.session import is_logged_in


async def main() -> None:
    from playwright.async_api import async_playwright

    settings = Settings.load()
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir),
            headless=False,
            viewport={"width": 1366, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        print("ブラウザでFacebookへ手動ログインしてください。2FA/checkpointが出た場合も手動で完了してください。")
        print("ログイン完了後、このターミナルに戻ってEnterを押してください。")
        input()
        if await is_logged_in(page):
            print(f"ログイン状態を確認しました。プロファイル保存先: {settings.profile_dir}")
        else:
            print("ログイン状態を確認できませんでした。Facebook画面を確認してください。")
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
