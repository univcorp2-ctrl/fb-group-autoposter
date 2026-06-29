"""Collect property listings from the FB groups the account belongs to (役割3).

Pipeline (READ-ONLY — never posts/likes/comments):
  1. open each configured group feed (collector/sources.yaml) with the collector
     profile,
  2. if not logged in -> Telegram alert + exit,
  3. scrape posts, extract property fields from each,
  4. UPSERT real listings into the SQLite property DB (+ JSON mirror),
  5. report counts to Telegram.

Usage:
    python collector/scripts/collect.py
    python collector/scripts/collect.py --no-telegram
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from src.notifier import TelegramNotifier  # noqa: E402
from src.property_extractor import extract_property  # noqa: E402
from src.scraper import scrape_group_feed  # noqa: E402
from src.session import is_logged_in, login_required_message  # noqa: E402
from src.store import PropertyStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("collect")

JST = timezone(timedelta(hours=9))


def _now_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")


async def _collect(settings: Settings, use_telegram: bool) -> dict:
    from playwright.async_api import async_playwright

    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    store = PropertyStore(settings.db_path)
    summary = {"groups": 0, "posts": 0, "extracted": 0, "created": 0, "updated": 0, "logged_in": True}

    if not settings.sources:
        log.warning("no sources configured (collector/sources.yaml); nothing to collect")
        summary["logged_in"] = True
        return summary

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir),
            headless=settings.headless,
            viewport={"width": 1366, "height": 900},
            user_agent=settings.browser_user_agent,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            if not await is_logged_in(ctx):
                summary["logged_in"] = False
                if use_telegram and notifier.enabled:
                    notifier.send_message(f"🔴 {login_required_message()}")
                log.warning("collector not logged in; aborting")
                return summary

            now = _now_jst()
            for source in settings.sources:
                feed_url = source.get("feed_url") or source.get("url")
                if not feed_url:
                    continue
                summary["groups"] += 1
                posts = await scrape_group_feed(page, feed_url, settings.max_posts_per_group)
                summary["posts"] += len(posts)
                for post in posts:
                    prop = extract_property(post.get("text", ""))
                    if prop is None:
                        continue
                    summary["extracted"] += 1
                    record = {
                        **prop.as_dict(),
                        "group_id": str(source.get("id", "")),
                        "group_name": source.get("name", ""),
                        "permalink": post.get("permalink", ""),
                        "author": post.get("author", ""),
                        "posted_at": "",
                        "raw_text": post.get("text", ""),
                    }
                    outcome = store.upsert(record, collected_at=now)
                    summary[outcome] += 1
                await page.wait_for_timeout(random.randint(2000, 5000))  # gentle pacing between groups
        finally:
            await ctx.close()

    store.export_json(settings.data_dir / "collected.json")
    if use_telegram and notifier.enabled and summary["extracted"]:
        notifier.send_message(
            f"🏠 物件収集 {now}\n"
            f"対象 {summary['groups']}グループ / 投稿 {summary['posts']}件\n"
            f"物件抽出 {summary['extracted']}件（新規 {summary['created']} / 更新 {summary['updated']}）\n"
            f"DB累計 {store.count()}件"
        )
    return summary


def main() -> None:
    settings = Settings.load()
    use_telegram = "--no-telegram" not in sys.argv
    summary = asyncio.run(_collect(settings, use_telegram))
    log.info("done: %s", summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
