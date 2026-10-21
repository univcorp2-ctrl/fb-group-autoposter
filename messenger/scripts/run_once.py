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
import hashlib
import logging
import os
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
            threads = await scrape_inbox(page, settings.max_threads_per_run, quick=True)
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
            # Review only *new*, recent, one-to-one document requests.
            # Existing inbox previews are hashed at activation; no old
            # conversation can become a new send merely due to re-review.
            from src.auto_reply import BASELINE_INBOX, recent_inbox_timestamp
            if not BASELINE_INBOX.is_file():
                summary["needs_baseline"] = True
                needing = []
            else:
                baseline = json.loads(BASELINE_INBOX.read_text(encoding="utf-8"))
                hashes = baseline.get("previews")
                if not isinstance(hashes, dict):
                    raise RuntimeError("inbox_baseline_invalid")
                doc_terms = ("資料", "図面", "レントロール", "概要書", "パンフ", "PDF", "pdf", "物件概要")
                needing = [
                    t for t in needing
                    if recent_inbox_timestamp(t.get("time_text", ""))
                    and any(term in str(t.get("preview","")) for term in doc_terms)
                    and hashes.get(str(t.get("thread_id"))) != hashlib.sha256(
                        str(t.get("preview","")).encode("utf-8")
                    ).hexdigest()
                ]
            summary["new_document_requests"] = len(needing)

            from src.review_pipeline import review_draft
            from src.thread_context import read_recent_thread_text

            review_limit = max(1, min(10, int(os.getenv("MESSENGER_MAX_REVIEWS_PER_SCAN", "5"))))
            reviewed_now = 0
            for thread in needing:
                preview = str(thread.get("preview") or "")
                tid = str(thread["thread_id"])
                prior = active_drafts.get(tid)
                # Reject all legacy drafts: these predate mandatory senior review.
                # Do not preserve bot text with "first-time" greetings and ads.
                # Cache accepted and human-escalated high-end reviews for
                # unchanged messages. Do not re-bill the premium model every
                # 30 minutes for the same unresolved document request.
                review_cached = bool(
                    prior and prior.get("last_message") == preview
                    and prior.get("review_status") in {"approved", "needs_human"}
                    and prior.get("review_policy_version") == "2026-10-20-v3"
                    and any(m in str(prior.get("review_model", "")).lower()
                            for m in ("opus", "gpt-5.6-terra"))
                )
                if review_cached:
                    continue
                if reviewed_now >= review_limit:
                    # Pending requests remain in the inbox for the next cycle.
                    # Do not delete an unrelated user's existing draft.
                    continue
                reviewed_now += 1
                history = await read_recent_thread_text(page, tid, str(thread["name"]))
                decision = await asyncio.to_thread(
                    review_draft, str(thread["name"]), preview,
                    history=history, api_key=settings.anthropic_api_key,
                )
                row = {
                    "thread_id": tid, "url": str(thread["url"]),
                    "name": str(thread["name"]), "last_message": preview,
                    "priority": thread["classification"]["priority"],
                    "one_to_one_verified": thread.get("one_to_one_verified") is True,
                    "participant_count": thread.get("participant_count"),
                    "is_group": thread.get("is_group") is True,
                    "time_text": thread.get("time_text", ""),
                    "review_policy_version": "2026-10-20-v3",
                    **decision,
                }
                active_drafts[tid] = row
                summary["drafted"] += int(bool(row.get("draft")))
                summary["reviewed_approved"] = summary.get("reviewed_approved", 0) + (
                    1 if decision["review_status"] == "approved" else 0
                )
                summary["review_blocked"] = summary.get("review_blocked", 0) + (
                    1 if decision["review_status"] != "approved" else 0
                )
                # Only a high-end approved text can reach the composer. By default
                # composer writes are switched OFF until a human clears old text.
                if (decision["review_status"] == "approved"
                        and decision["draft"]
                        and settings.write_draft_to_fb and not settings.read_only):
                    from src.fb_draft_writer import write_draft_no_send
                    if await write_draft_no_send(page, str(thread["url"]), decision["draft"]):
                        summary["placed_in_fb"] += 1
                _sync_notion(settings, row, _now_jst())
                if use_telegram:
                    _notify(notifier, row)
                _archive_draft(settings, row, _now_jst())
                store.mark_drafted(tid, preview, drafted_at=_now_jst())
                await page.wait_for_timeout(random.randint(400, 900))
            # Scrub cached pre-review legacy drafts, including threads omitted
            # from today's virtualized inbox scan, so they cannot be auto-sent.
            for tid in list(active_drafts):
                if active_drafts[tid].get("review_status") != "approved":
                    if active_drafts[tid].get("review_status") is None:
                        active_drafts[tid]["draft"] = ""
                        active_drafts[tid]["review_status"] = "legacy_unreviewed"
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
