"""Scan Messenger once: read 1:1 threads, draft replies, save them.

Pipeline (read-only by default — NEVER sends a message):
  1. open the inbox (dedicated profile)
  2. if not logged in -> Telegram alert + exit (no retries that could trip a block)
  3. scrape threads, classify which need a reply
  4. for each fresh one: read recent messages, build a draft
  5. save the draft to: local JSON + Notion (if configured) + Telegram notify
  6. optionally (WRITE_DRAFT_TO_FB=true) place the draft in the FB composer — no send

Usage:
    python scripts/run_once.py
    python scripts/run_once.py --no-telegram
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
from src.authenticated_chrome import (  # noqa: E402
    attach_authenticated_context,
    select_messenger_page,
)
from src.classifier import classify_thread, select_threads_needing_reply  # noqa: E402
from src.drafter import build_draft  # noqa: E402
from src.notifier import TelegramNotifier  # noqa: E402
from src.scraper import scrape_inbox  # noqa: E402
from src.session import is_logged_in, login_required_message  # noqa: E402
from src.store import ThreadStateStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("run_once")

JST = timezone(timedelta(hours=9))


def _now_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")


def _sync_notion(settings: Settings, row: dict, checked_at: str) -> None:
    if not settings.notion_enabled:
        return
    from src.notion_sync import upsert_draft

    try:
        outcome = upsert_draft(
            settings.notion_token, settings.notion_replies_database_id, row, checked_at
        )
        log.info("notion %s: %s", outcome, row.get("name"))
    except Exception as exc:  # noqa: BLE001 - one bad row must not abort the rest
        log.warning("notion upsert failed for %s: %s: %s", row.get("name"), type(exc).__name__, exc)


def _archive_draft(settings: Settings, row: dict, checked_at: str) -> None:
    """Append every generated draft to a permanent JSONL archive.

    `drafts.json` holds only the latest run and is overwritten each scan, so a
    later empty run erases past drafts. This append-only log keeps the full
    history locally (independent of Telegram/Notion) — one JSON object per line.
    Best-effort: a write failure must never abort a scan."""
    try:
        path = settings.data_dir / "drafts_archive.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"checked_at": checked_at, **row}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 - archiving must not break the run
        log.warning("draft archive append failed for %s: %s", row.get("name"), exc)


def _notify(notifier: TelegramNotifier, row: dict) -> None:
    if not notifier.enabled:
        return
    priority = "🔴高" if row.get("priority") == "high" else "🟡"
    notifier.send_message(
        f"✉️ Messenger 要返信 {priority}\n"
        f"相手: {row.get('name')}\n"
        f"最新: {row.get('last_message', '')[:160]}\n"
        f"🔗 {row.get('url')}\n\n"
        f"— 返信下書き —\n{row.get('draft', '')}"
    )


async def _scan(settings: Settings, use_telegram: bool) -> dict:
    from playwright.async_api import async_playwright

    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    store = ThreadStateStore(settings.data_dir / "threads_state.json")
    drafts_path = settings.data_dir / "drafts.json"
    active_drafts: dict[str, dict] = {}
    if drafts_path.exists():
        try:
            prior = json.loads(drafts_path.read_text(encoding="utf-8"))
            for row in prior.get("drafts", []) if isinstance(prior, dict) else []:
                if isinstance(row, dict) and row.get("thread_id"):
                    active_drafts[str(row["thread_id"])] = row
        except Exception:
            active_drafts = {}
    summary = {"scanned": 0, "need_reply": 0, "drafted": 0, "placed_in_fb": 0, "logged_in": True}

    async with async_playwright() as p:
        attachment = await attach_authenticated_context(p, settings)
        page = await select_messenger_page(attachment.context)
        try:
            threads = await scrape_inbox(page, settings.max_threads_per_run)
            summary["scanned"] = len(threads)
            if not threads and not await is_logged_in(page):
                summary["logged_in"] = False
                if use_telegram and notifier.enabled:
                    notifier.send_message(f"🔴🔁 {login_required_message()}")
                log.warning("not logged in; aborting scan")
                return summary

            # Remove active drafts only when the scanned thread is now clearly
            # replied/closed. Unseen older drafts are retained until the thread
            # reappears, preventing hourly scans from erasing useful drafts.
            for thread in threads:
                classification = classify_thread(thread)
                if classification.reason in {"already_replied", "closing_ack"}:
                    active_drafts.pop(str(thread.get("thread_id", "")), None)

            needing = select_threads_needing_reply(threads)
            summary["need_reply"] = len(needing)

            for thread in needing:
                preview = thread.get("preview", "")
                if not store.is_new_state(thread["thread_id"], preview):
                    # The state DB can outlive drafts.json. Rehydrate the saved
                    # draft from the current inbound preview if necessary, then
                    # idempotently place/verify it in Messenger's composer.
                    saved = active_drafts.get(str(thread["thread_id"]))
                    if not saved:
                        draft = build_draft(
                            thread["name"],
                            preview,
                            line_url=settings.line_url,
                            community_url=settings.community_url,
                            api_key=settings.anthropic_api_key,
                            model=settings.claude_model,
                        )
                        saved = {
                            "thread_id": thread["thread_id"],
                            "url": thread["url"],
                            "name": thread["name"],
                            "last_message": preview,
                            "draft": draft,
                            "priority": thread["classification"]["priority"],
                        }
                        active_drafts[str(thread["thread_id"])] = saved
                        summary["drafted"] += 1
                        _archive_draft(settings, saved, _now_jst())
                    if settings.write_draft_to_fb and not settings.read_only:
                        from src.fb_draft_writer import write_draft_no_send

                        if await write_draft_no_send(
                            page, thread["url"], str(saved["draft"])
                        ):
                            summary["placed_in_fb"] += 1
                    continue  # already drafted for this exact message state
                # Use the inbox preview as the last message. We deliberately do NOT
                # open the thread: opening marks it "seen" and sends a read receipt,
                # which would break the passive, non-intrusive guarantee.
                last_message = preview
                draft = build_draft(
                    thread["name"],
                    last_message,
                    line_url=settings.line_url,
                    community_url=settings.community_url,
                    api_key=settings.anthropic_api_key,
                    model=settings.claude_model,
                )
                row = {
                    "thread_id": thread["thread_id"],
                    "url": thread["url"],
                    "name": thread["name"],
                    "last_message": last_message,
                    "draft": draft,
                    "priority": thread["classification"]["priority"],
                }
                active_drafts[str(thread["thread_id"])] = row
                summary["drafted"] += 1

                if settings.write_draft_to_fb and not settings.read_only:
                    from src.fb_draft_writer import write_draft_no_send

                    if await write_draft_no_send(page, thread["url"], draft):
                        summary["placed_in_fb"] += 1

                _sync_notion(settings, row, _now_jst())
                if use_telegram:
                    _notify(notifier, row)
                _archive_draft(settings, row, _now_jst())
                store.mark_drafted(thread["thread_id"], preview, drafted_at=_now_jst())
                await page.wait_for_timeout(random.randint(2000, 5000))  # gentle pacing
        finally:
            # The Chrome process, context, and page are externally owned by the
            # central Executor. Exiting Playwright disconnects only this client.
            pass

    store.save()
    drafts_out = list(active_drafts.values())
    summary["active_drafts"] = len(drafts_out)
    drafts_path.write_text(
        json.dumps({"checked_at": _now_jst(), "drafts": drafts_out}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    settings = Settings.load()
    use_telegram = "--no-telegram" not in sys.argv
    if settings.write_draft_to_fb and not settings.read_only:
        log.warning("Tier B 有効: 下書きをFB入力欄に配置します（送信はしません）")
    summary = asyncio.run(_scan(settings, use_telegram))
    log.info("done: %s", summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
