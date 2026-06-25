"""Read Facebook notifications, keep only the ones about OUR posts, summarize.

The FB notifications feed is noisy (friend requests, group suggestions, others'
posts, birthdays...). This scrapes facebook.com/notifications, keeps only items
about the bot's OWN posts/comments — i.e. reactions and comments on what we
published — and reports a concise summary to Telegram. New items since the last
run are highlighted so the operator is not re-notified about the same thing.

Run:
    python scripts/monitor_notifications.py            # scrape + Telegram
    python scripts/monitor_notifications.py --no-telegram
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from src.logging_setup import setup_logging  # noqa: E402
from src.queue_db import QueueDB  # noqa: E402

log = logging.getLogger("monitor_notifications")
SEEN_PATH = ROOT / "data" / "notifications_seen.json"

# A notification is about US when it references our own post/comment.
_OURS_HINTS = ["あなたの投稿", "あなたのコメント", "your post", "your comment"]
_REACTION_HINTS = ["いいね", "超いいね", "リアクション", "うけるね", "大切だね", "reacted", "like"]
_COMMENT_HINTS = ["コメント", "返信", "commented", "replied"]
_OTHER_NOISE = ["友達リクエスト", "誕生日", "の思い出", "おすすめ", "に参加しませんか", "ライブ動画", "が投稿しました"]
_COUNT_RE = re.compile(r"他\s*(\d[\d,]*)\s*人")


def _classify(text: str) -> str | None:
    """Return 'comment' / 'reaction' if the notification is about our post,
    else None (irrelevant noise)."""
    if not any(h in text for h in _OURS_HINTS):
        return None
    if any(h in text for h in _COMMENT_HINTS):
        return "comment"
    if any(h in text for h in _REACTION_HINTS):
        return "reaction"
    return "reaction"  # default: a reaction-type interaction on our post


def _digest(text: str, href: str) -> str:
    return hashlib.sha256(f"{text}|{href}".encode()).hexdigest()[:16]


def _load_seen() -> set[str]:
    if SEEN_PATH.exists():
        try:
            return set(json.loads(SEEN_PATH.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            return set()
    return set()


def _save_seen(seen: set[str]) -> None:
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Keep the file bounded (last 2000 ids).
    SEEN_PATH.write_text(json.dumps(list(seen)[-2000:], ensure_ascii=False), encoding="utf-8")


async def scrape_notifications(settings: Settings) -> list[dict]:
    from playwright.async_api import async_playwright

    items: list[dict] = []
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir), headless=True,
            viewport={"width": 1366, "height": 900}, user_agent=settings.browser_user_agent,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://www.facebook.com/notifications", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        for _ in range(4):
            await page.mouse.wheel(0, 2500)
            await page.wait_for_timeout(1200)
        # Notifications are anchors with the descriptive text. They are NOT under
        # role="main" on this page, so scan all links and filter by content.
        rows = await page.eval_on_selector_all(
            'a[href]',
            """els => els.map(e => ({
                href: e.href,
                text: (e.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 220)
            }))""",
        )
        seen_text: set[str] = set()
        for r in rows:
            text = r.get("text") or ""
            if len(text) < 8 or text in seen_text:
                continue
            if any(n in text for n in _OTHER_NOISE):
                continue
            kind = _classify(text)
            if not kind:
                continue
            seen_text.add(text)
            m = _COUNT_RE.search(text)
            items.append(
                {
                    "kind": kind,
                    "text": text,
                    "href": (r.get("href") or "").split("?")[0],
                    "count": int(m.group(1).replace(",", "")) + 1 if m else 1,
                }
            )
        await ctx.close()
    return items


def _report(settings: Settings, new_items: list[dict], total: int) -> None:
    from src.approval import TelegramApproval

    comments = [it for it in new_items if it["kind"] == "comment"]
    reactions = [it for it in new_items if it["kind"] == "reaction"]
    lines = [
        f"🔔 自分の投稿への反応（FB通知より）{datetime.now(UTC).isoformat()[:16]}",
        f"新着 {len(new_items)}件（💬コメント{len(comments)} / 👍反応{len(reactions)}）｜既知含む関連通知 {total}件",
    ]
    if comments:
        lines.append("\n💬 新着コメント:")
        for it in comments[:8]:
            lines.append(f"・{it['text'][:90]}\n　🔗 {it['href']}")
    if reactions:
        lines.append("\n👍 新着リアクション:")
        for it in reactions[:8]:
            lines.append(f"・{it['text'][:90]}")
    try:
        notifier = TelegramApproval(settings, QueueDB(settings.db_path))
        if getattr(notifier, "enabled", False):
            notifier.send_message("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        log.warning("notification report skipped: %s", exc)


def main() -> None:
    setup_logging()
    settings = Settings.load()
    items = asyncio.run(scrape_notifications(settings))
    seen = _load_seen()
    new_items = [it for it in items if _digest(it["text"], it["href"]) not in seen]
    for it in items:
        seen.add(_digest(it["text"], it["href"]))
    _save_seen(seen)
    log.info("relevant notifications: %d total, %d new", len(items), len(new_items))
    if new_items and "--no-telegram" not in sys.argv:
        _report(settings, new_items, len(items))
    print(json.dumps({"relevant_total": len(items), "new": len(new_items)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
