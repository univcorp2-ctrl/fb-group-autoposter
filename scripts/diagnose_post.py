"""Step-by-step posting diagnostic for ONE group, with screenshots at each stage.

Purpose: figure out WHY a submit "succeeds" (composer closes) but the post never
appears publicly in some groups. Captures the screen + key page signals right
after the Post click (approval banner? error? topic picker? pending notice?).

Usage:
    python scripts/diagnose_post.py 1281008662437696
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings, load_groups  # noqa: E402
from src.post_verify import cookie_user_id  # noqa: E402
from src.selectors import SELECTORS  # noqa: E402

OUT = ROOT / "screenshots" / "diag"


async def _shot(page, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%H%M%S")
    path = OUT / f"{name}_{stamp}.png"
    await page.screenshot(path=str(path), full_page=False)
    print(f"  shot: {path}")


async def _signals(page, label: str) -> None:
    """Print any approval/pending/error/topic-picker signals on the page."""
    text = ""
    try:
        text = await page.inner_text("body")
    except Exception:
        pass
    markers = {
        "承認": "承認" in text,
        "保留/pending": ("保留" in text or "承認待ち" in text or "pending" in text.lower()),
        "管理者の承認": "管理者" in text and "承認" in text,
        "トピック/topic必須": ("トピックを選択" in text or "トピックを追加" in text),
        "エラー/問題": ("問題が発生" in text or "エラー" in text or "something went wrong" in text.lower()),
        "ブロック/制限": ("ブロック" in text or "制限" in text or "コミュニティ規定" in text),
    }
    hits = [k for k, v in markers.items() if v]
    print(f"  [{label}] signals: {hits or 'none'}")


async def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python scripts/diagnose_post.py <group_id>")
        raise SystemExit(2)
    gid = sys.argv[1]
    settings = Settings.load()
    group = next((g for g in load_groups() if str(g["id"]) == gid), None)
    if not group:
        print(f"group {gid} not in groups.yaml")
        raise SystemExit(1)

    body = (
        "【テスト投稿｜動作確認】収益物件のご紹介です。\n"
        "🏢 動作確認用ダミー物件\n"
        "💰 価格：テスト\n"
        "本投稿は自動投稿の動作確認用です。問題があれば削除します。"
    )

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir),
            headless=False,
            viewport={"width": 1366, "height": 900},
            user_agent=settings.browser_user_agent,
        )
        uid = await cookie_user_id(ctx)
        print(f"c_user={uid}")
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        print(f"1) goto {group['post_url']}")
        await page.goto(group["post_url"], wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4000)
        await _shot(page, "1_group")
        await _signals(page, "group")

        print("2) open composer")
        opened = False
        for sel in SELECTORS["open_composer"]:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.click(timeout=8000)
                    opened = True
                    print(f"   clicked composer via: {sel}")
                    break
            except Exception:
                continue
        await page.wait_for_timeout(3000)
        await _shot(page, "2_composer")
        await _signals(page, "composer")
        if not opened:
            print("   !! could not open composer with CSS selectors")

        print("3) type body")
        typed = False
        for sel in SELECTORS["composer_textbox"]:
            try:
                tb = page.locator(sel).first
                if await tb.count() > 0:
                    await tb.click()
                    await page.wait_for_timeout(800)
                    await tb.type(body, delay=10, timeout=30000)
                    typed = True
                    print(f"   typed via: {sel}")
                    break
            except Exception:
                continue
        await page.wait_for_timeout(1500)
        await _shot(page, "3_typed")
        await _signals(page, "after-type")
        if not typed:
            print("   !! could not type into composer textbox")

        print("4) click Post and watch")
        clicked = False
        for sel in SELECTORS["post_button"]:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.click(timeout=8000)
                    clicked = True
                    print(f"   clicked post via: {sel}")
                    break
            except Exception:
                continue
        if not clicked:
            print("   !! could not find/click post button")
        for secs in (2, 5, 10):
            await page.wait_for_timeout((secs if secs == 2 else secs - (2 if secs == 5 else 5)) * 1000)
            await _shot(page, f"4_after_post_{secs}s")
            await _signals(page, f"after-post-{secs}s")
            still_open = await page.locator('div[role="dialog"] div[role="textbox"][contenteditable="true"]').count()
            print(f"   composer still open at {secs}s: {bool(still_open)}")

        print("5) reload group feed and look for the post")
        await page.goto(group["post_url"], wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        await _shot(page, "5_feed_after")
        feed = ""
        try:
            feed = await page.inner_text("body")
        except Exception:
            pass
        print(f"   '動作確認用ダミー物件' visible in feed: {'動作確認用ダミー物件' in feed}")

        await ctx.close()
    print("done. screenshots in screenshots/diag/")


if __name__ == "__main__":
    asyncio.run(main())
