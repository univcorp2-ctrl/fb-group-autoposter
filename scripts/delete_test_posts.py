"""Delete the bot's OWN test posts from a group (cleanup after diagnostics).

Only targets posts whose text contains an explicit test marker, so it can never
delete a real listing. Finds them in the group feed, then for each: open the
post's "..." menu -> move to trash -> confirm. Screenshots each step.

Usage:
    python scripts/delete_test_posts.py 1281008662437696
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402

TEST_MARKERS = ["テスト投稿", "動作確認用ダミー", "リンク無し検証用", "動作確認"]
OUT = ROOT / "screenshots" / "delete"

MENU_BUTTON_SELECTORS = [
    'div[role="dialog"] div[aria-haspopup="menu"][role="button"]',
    'div[aria-haspopup="menu"][role="button"]',
    'div[role="dialog"] [aria-label*="アクション"][role="button"]',
    'div[role="dialog"] [aria-label*="オプション"][role="button"]',
    'div[role="dialog"] [aria-label*="その他"][role="button"]',
    '[aria-label*="アクション"][role="button"]',
    '[aria-label*="More"][role="button"]',
]
DELETE_MENUITEM_TEXTS = ["ごみ箱に移動", "投稿を削除", "削除", "Move to trash", "Delete post", "Delete"]
CONFIRM_TEXTS = ["削除する", "移動する", "削除", "移動", "Delete", "Move"]


async def _shot(page, name):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{name}_{datetime.now(UTC).strftime('%H%M%S')}.png"
    await page.screenshot(path=str(p))
    print(f"  shot: {p}")


async def _click_text(page, texts, *, timeout=4000):
    # Prefer real clickable controls (button/menuitem) with EXACT names so a
    # body paragraph that merely contains the word isn't clicked by mistake.
    for role in ("button", "menuitem"):
        for t in texts:
            try:
                loc = page.get_by_role(role, name=t, exact=True).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=timeout)
                    return t
            except Exception:
                continue
    # Fall back to exact visible text.
    for t in texts:
        try:
            loc = page.get_by_text(t, exact=True).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click(timeout=timeout)
                return t
        except Exception:
            continue
    return None


async def _find_test_permalinks(page, gid):
    url = f"https://www.facebook.com/groups/{gid}"
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)
    found: dict[str, str] = {}
    for _ in range(6):
        records = await page.eval_on_selector_all(
            'div[role="article"]',
            """arts => arts.map(a => {
                const link = a.querySelector('a[href*="/posts/"], a[href*="/permalink/"]');
                return { href: link ? link.href.split('?')[0] : '', text: (a.innerText||'').slice(0,160) };
            })""",
        )
        for r in records:
            text = r.get("text") or ""
            href = r.get("href") or ""
            if href and any(mk in text for mk in TEST_MARKERS):
                found.setdefault(href, text.replace("\n", " ")[:60])
        await page.mouse.wheel(0, 2500)
        await page.wait_for_timeout(1200)
    return found


async def _delete_one(page, permalink, label):
    print(f"deleting: {label}\n  {permalink}")
    await page.goto(permalink, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3500)
    await _shot(page, "before")
    # open the post's "..." menu
    opened = False
    for sel in MENU_BUTTON_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                await loc.click(timeout=5000)
                opened = True
                break
        except Exception:
            continue
    await page.wait_for_timeout(1500)
    await _shot(page, "menu")
    if not opened:
        print("  !! could not open post menu")
        return False
    item = await _click_text(page, DELETE_MENUITEM_TEXTS)
    print(f"  menu item: {item}")
    await page.wait_for_timeout(1500)
    await _shot(page, "confirm")
    confirmed = await _click_text(page, CONFIRM_TEXTS)
    print(f"  confirm: {confirmed}")
    await page.wait_for_timeout(2500)
    await _shot(page, "after")
    return bool(item)


async def main():
    gid = sys.argv[1] if len(sys.argv) > 1 else "1281008662437696"
    settings = Settings.load()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir), headless=False,
            viewport={"width": 1366, "height": 900}, user_agent=settings.browser_user_agent,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        targets = await _find_test_permalinks(page, gid)
        print(f"found {len(targets)} test post(s) to delete:")
        for href, label in targets.items():
            print(f"  - {label} :: {href}")
        deleted = 0
        for href, label in targets.items():
            try:
                if await _delete_one(page, href, label):
                    deleted += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  error deleting {href}: {exc}")
        await ctx.close()
    print(f"done: attempted delete on {deleted}/{len(targets)} test posts")


if __name__ == "__main__":
    asyncio.run(main())
