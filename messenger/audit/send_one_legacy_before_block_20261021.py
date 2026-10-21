from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.async_api import Locator, Page, async_playwright

MESSENGER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MESSENGER_ROOT.parent
if str(MESSENGER_ROOT) not in sys.path:
    sys.path.insert(0, str(MESSENGER_ROOT))

from config import Settings  # noqa: E402
from src.authenticated_chrome import (  # noqa: E402
    attach_authenticated_context,
    select_messenger_page,
)
from src.classifier import classify_thread  # noqa: E402
from src.scraper import scrape_inbox  # noqa: E402

DRAFTS_PATH = MESSENGER_ROOT / "data" / "drafts.json"
STATUS_PATH = MESSENGER_ROOT / "data" / "send_one_reply_status.json"


def normalize(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def message_hash(value: str) -> str:
    return hashlib.sha256(normalize(value).encode("utf-8")).hexdigest()


def remove_internal_note(value: str) -> str:
    kept: list[str] = []
    for line in value.splitlines():
        stripped = line.strip()
        if re.match(r"^[（(]\s*※?\s*この返信は下書きです", stripped):
            continue
        if re.match(r"^[（(]\s*※?\s*送信前に内容をご確認", stripped):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def load_target(args: argparse.Namespace) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    if DRAFTS_PATH.exists():
        payload = json.loads(DRAFTS_PATH.read_text(encoding="utf-8-sig"))
        matches = [
            row
            for row in payload.get("drafts", [])
            if str(row.get("thread_id", "")) == args.thread_id
            and str(row.get("name", "")) == args.target_name
        ]
    if len(matches) > 1:
        raise RuntimeError(
            f"Expected at most one draft for {args.target_name!r}/{args.thread_id}; "
            f"found {len(matches)}."
        )
    if len(matches) == 1:
        return matches[0]
    if not args.expected_preview_file:
        raise RuntimeError(
            "Target is absent from the regenerated drafts file. "
            "Provide --expected-preview-file so the live inbox preview can be checked."
        )
    expected_preview = Path(args.expected_preview_file).read_text(
        encoding="utf-8-sig"
    ).strip()
    if not expected_preview:
        raise RuntimeError("Expected-preview file is empty.")
    return {
        "thread_id": args.thread_id,
        "name": args.target_name,
        "url": f"https://www.messenger.com/t/{args.thread_id}",
        "last_message": expected_preview,
        "draft": "",
    }


def load_reply(args: argparse.Namespace, row: dict[str, Any]) -> str:
    if args.reply_file:
        reply = Path(args.reply_file).read_text(encoding="utf-8-sig").strip()
    else:
        reply = remove_internal_note(str(row.get("draft", "")))
    if not reply:
        raise RuntimeError("Reply text is empty.")
    return reply


def write_status(status: dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(status, ensure_ascii=False))


async def first_visible(page: Page, selectors: list[str]) -> Locator | None:
    for selector in selectors:
        locator = page.locator(selector)
        count = await locator.count()
        for index in range(count - 1, -1, -1):
            candidate = locator.nth(index)
            try:
                if await candidate.is_visible():
                    return candidate
            except Exception:
                continue
    return None


async def read_composer(composer: Locator) -> str:
    try:
        return await composer.inner_text()
    except Exception:
        try:
            return await composer.input_value()
        except Exception:
            return ""


async def verify_current_inbox(
    page: Page,
    *,
    thread_id: str,
    target_name: str,
    expected_preview: str,
    max_threads: int,
) -> tuple[dict[str, Any], Any]:
    threads = await scrape_inbox(page, max_threads)
    matches = [row for row in threads if str(row.get("thread_id", "")) == thread_id]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one current inbox row for thread {thread_id}; found {len(matches)}."
        )

    current = matches[0]
    classification = classify_thread(current)
    if str(current.get("name", "")) != target_name:
        raise RuntimeError("Current inbox name does not match the requested target.")
    if normalize(str(current.get("preview", ""))) != normalize(expected_preview):
        raise RuntimeError("Current inbox preview changed; refusing to send a potentially stale reply.")
    if not classification.needs_reply:
        raise RuntimeError(
            f"Current classifier no longer requires a reply: {classification.reason}."
        )
    return current, classification


async def run(args: argparse.Namespace) -> int:
    row = load_target(args)
    reply = load_reply(args, row)
    reply_digest = message_hash(reply)

    base_status: dict[str, Any] = {
        "ok": False,
        "sent": False,
        "send_requested": bool(args.send),
        "checked_at": datetime.now(UTC).astimezone().isoformat(),
        "target_name": args.target_name,
        "thread_id": args.thread_id,
        "message_sha256": reply_digest,
        "message_length": len(reply),
        "reason": "not_started",
    }

    if args.send and STATUS_PATH.exists() and not args.force:
        try:
            prior = json.loads(STATUS_PATH.read_text(encoding="utf-8-sig"))
        except Exception:
            prior = {}
        if (
            prior.get("sent") is True
            and str(prior.get("thread_id", "")) == args.thread_id
            and str(prior.get("message_sha256", "")) == reply_digest
        ):
            raise RuntimeError(
                "This exact reply is already recorded as sent. Use --force only after independent verification."
            )

    os.chdir(MESSENGER_ROOT)
    settings = replace(
        Settings.load(),
        headless=True,
        browser_display_mode="auto",
        max_threads_per_run=max(args.max_threads, 50),
    )

    async with async_playwright() as playwright:
        attachment = await attach_authenticated_context(playwright, settings)
        page = await select_messenger_page(attachment.context)
        try:
            current, classification = await verify_current_inbox(
                page,
                thread_id=args.thread_id,
                target_name=args.target_name,
                expected_preview=str(row.get("last_message", "")),
                max_threads=settings.max_threads_per_run,
            )
            base_status["pre_send"] = {
                "name_match": True,
                "preview_match": True,
                "needs_reply": bool(classification.needs_reply),
                "reason": classification.reason,
                "is_unread": bool(current.get("is_unread")),
            }

            url = str(row.get("url") or f"https://www.messenger.com/t/{args.thread_id}")
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(5_000)

            if f"/t/{args.thread_id}" not in page.url or "login.php" in page.url:
                raise RuntimeError("Messenger target thread did not open in the authenticated profile.")
            if await page.get_by_text(args.target_name, exact=True).count() < 1:
                raise RuntimeError("Target name is not present in the opened thread.")

            body_before = normalize(await page.locator("body").inner_text(timeout=10_000))
            expected_preview = normalize(str(row.get("last_message", "")))
            if expected_preview not in body_before:
                raise RuntimeError("Expected inbound message is not present in the opened thread.")
            if normalize(reply) in body_before:
                base_status.update(
                    {
                        "ok": True,
                        "sent": False,
                        "reason": "reply_already_visible_before_send",
                    }
                )
                write_status(base_status)
                return 3

            composer = await first_visible(
                page,
                [
                    'div[aria-label="メッセージを入力"][contenteditable="true"]',
                    'div[aria-label="Message"][contenteditable="true"]',
                    'div[role="textbox"][contenteditable="true"]',
                    "textarea",
                ],
            )
            if composer is None:
                raise RuntimeError("Messenger composer was not found.")

            if not args.send:
                base_status.update(
                    {
                        "ok": True,
                        "sent": False,
                        "reason": "preflight_ready_exact_target",
                    }
                )
                write_status(base_status)
                return 0

            await composer.fill(reply)
            await page.wait_for_timeout(700)
            if normalize(await read_composer(composer)) != normalize(reply):
                raise RuntimeError("Filled reply text could not be verified in the composer.")

            send_button = await first_visible(
                page,
                [
                    '[aria-label="送信"]',
                    '[aria-label="Send"]',
                    '[data-testid="send"]',
                ],
            )
            if send_button is None:
                raise RuntimeError("Messenger send button was not found after filling the reply.")

            await send_button.click(timeout=10_000)
            await page.wait_for_timeout(4_000)

            composer_after = normalize(await read_composer(composer))
            body_after = normalize(await page.locator("body").inner_text(timeout=10_000))
            if composer_after:
                raise RuntimeError("Composer still contains text after clicking Send.")
            if normalize(reply) not in body_after:
                raise RuntimeError("Sent reply is not visible in the thread after clicking Send.")

            await page.reload(wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(4_000)
            body_reloaded = normalize(await page.locator("body").inner_text(timeout=10_000))
            if normalize(reply) not in body_reloaded:
                raise RuntimeError("Sent reply was not visible after reloading the target thread.")

            post_threads = await scrape_inbox(page, settings.max_threads_per_run)
            post_matches = [
                item
                for item in post_threads
                if str(item.get("thread_id", "")) == args.thread_id
            ]
            post_result: dict[str, Any] = {"match_count": len(post_matches)}
            if len(post_matches) == 1:
                post_classification = classify_thread(post_matches[0])
                post_result.update(
                    {
                        "needs_reply": bool(post_classification.needs_reply),
                        "reason": post_classification.reason,
                        "preview_contains_reply_prefix": normalize(reply)[:32]
                        in normalize(str(post_matches[0].get("preview", ""))),
                    }
                )

            base_status.update(
                {
                    "ok": True,
                    "sent": True,
                    "reason": "sent_and_verified_after_reload",
                    "post_send": post_result,
                }
            )
            write_status(base_status)
            return 0
        finally:
            # External Chrome ownership stays with the central Executor.
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send one Messenger reply only after exact target and stale-preview checks."
    )
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--target-name", required=True)
    parser.add_argument("--reply-file")
    parser.add_argument("--expected-preview-file")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-threads", type=int, default=50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(run(args))
    except Exception as exc:
        status = {
            "ok": False,
            "sent": False,
            "send_requested": bool(args.send),
            "checked_at": datetime.now(UTC).astimezone().isoformat(),
            "target_name": args.target_name,
            "thread_id": args.thread_id,
            "reason": "exception",
            "error": str(exc),
        }
        write_status(status)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
