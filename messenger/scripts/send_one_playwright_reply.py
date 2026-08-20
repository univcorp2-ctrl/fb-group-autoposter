"""Send one explicitly targeted Messenger reply through the dedicated profile.

The default mode is a live preflight: it verifies the exact recipient, thread,
current inbox preview, reply-needed classification, visible recipient name, and
composer without changing the composer or sending anything.

Actual sending requires ``--send``.  There is no inbox-wide send mode.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from src.authenticated_chrome import (  # noqa: E402
    attach_authenticated_context,
    select_messenger_page,
)
from src.classifier import classify_thread  # noqa: E402
from src.scraper import scrape_inbox  # noqa: E402
from src.targeted_reply import (  # noqa: E402
    message_fingerprint,
    normalize_text,
    sanitize_draft,
    select_exact_draft,
)

JST = timezone(timedelta(hours=9))
COMPOSER_SELECTORS = (
    'div[aria-label="メッセージを入力"][contenteditable="true"]',
    'div[aria-label="Message"][contenteditable="true"]',
    'div[role="textbox"][contenteditable="true"]',
    "textarea",
)
SEND_SELECTORS = (
    '[aria-label="送信"]',
    '[aria-label="Enterを押して送信"]',
    '[aria-label="Send"]',
    '[aria-label="Press Enter to send"]',
    '[data-testid="send"]',
)


def _now_jst() -> str:
    return datetime.now(JST).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _reply_text(args: argparse.Namespace, row: dict[str, Any]) -> str:
    supplied = sum(
        bool(value)
        for value in (args.reply_text, args.reply_base64, args.reply_file)
    )
    if supplied > 1:
        raise ValueError("use only one of --reply-text, --reply-base64, or --reply-file")
    if args.reply_base64:
        try:
            value = base64.b64decode(args.reply_base64, validate=True).decode("utf-8")
        except Exception as exc:  # noqa: BLE001 - convert to a clear CLI error
            raise ValueError("--reply-base64 must be valid UTF-8 base64") from exc
    elif args.reply_file:
        value = Path(args.reply_file).read_text(encoding="utf-8-sig")
    elif args.reply_text:
        value = args.reply_text
    else:
        value = sanitize_draft(str(row.get("draft", "")))
    value = value.strip()
    if not value:
        raise ValueError("reply text is empty")
    return value


def _base_status(args: argparse.Namespace, fingerprint: str, message_length: int) -> dict[str, Any]:
    return {
        "ok": False,
        "sent": False,
        "send_requested": bool(args.send),
        "checked_at": _now_jst(),
        "target_name": args.target_name,
        "thread_id": args.thread_id,
        "message_sha256": fingerprint,
        "message_length": message_length,
        "reason": "not_started",
    }


def _block_duplicate(status_path: Path, args: argparse.Namespace) -> None:
    if not args.send or args.force or not status_path.exists():
        return
    try:
        prior = _read_json(status_path)
    except Exception:
        return
    if prior.get("sent") is True and str(prior.get("thread_id", "")) == args.thread_id:
        raise RuntimeError(
            "this thread is already recorded as sent; use --force only after an "
            "independent check confirms a new reply is required"
        )


async def _first_visible(page: Any, selectors: tuple[str, ...]) -> Any | None:
    for selector in selectors:
        locator = page.locator(selector)
        count = await locator.count()
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if await candidate.is_visible():
                    return candidate
            except Exception:
                continue
    return None


async def _any_exact_text_visible(page: Any, text: str) -> bool:
    locator = page.get_by_text(text, exact=True)
    count = await locator.count()
    for index in range(count):
        try:
            if await locator.nth(index).is_visible():
                return True
        except Exception:
            continue
    return False


async def _editor_text(editor: Any) -> str:
    try:
        return await editor.inner_text()
    except Exception:
        try:
            return await editor.input_value()
        except Exception:
            return ""


async def _set_editor_text(page: Any, editor: Any, value: str) -> None:
    try:
        await editor.fill(value, timeout=20_000)
    except Exception:
        await editor.click(timeout=10_000)
        await page.keyboard.press("Control+A")
        await page.keyboard.insert_text(value)


async def _restore_editor(page: Any, editor: Any, value: str) -> None:
    try:
        await _set_editor_text(page, editor, value)
    except Exception:
        pass


async def _scan_exact_thread(
    page: Any,
    *,
    thread_id: str,
    scan_limit: int,
) -> tuple[dict[str, Any], Any, int]:
    threads = await scrape_inbox(page, scan_limit)
    matches = [row for row in threads if str(row.get("thread_id", "")) == thread_id]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one current inbox thread for {thread_id!r}; found {len(matches)}"
        )
    thread = matches[0]
    return thread, classify_thread(thread), len(threads)


async def _run_browser(
    settings: Settings,
    args: argparse.Namespace,
    row: dict[str, Any],
    reply: str,
    status: dict[str, Any],
) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    expected_preview = normalize_text(str(row.get("last_message", "")))
    if not expected_preview:
        raise RuntimeError("saved draft has no last_message to verify")

    clicked = False
    original_editor_text = ""
    editor: Any | None = None

    async with async_playwright() as playwright:
        attachment = await attach_authenticated_context(playwright, settings)
        page = await select_messenger_page(attachment.context)
        try:
            current, classification, scanned = await _scan_exact_thread(
                page,
                thread_id=args.thread_id,
                scan_limit=args.scan_limit,
            )
            current_preview = normalize_text(str(current.get("preview", "")))
            status.update(
                {
                    "scanned": scanned,
                    "current_preview_matches_saved": current_preview == expected_preview,
                    "pre_send_classification": classification.reason,
                    "pre_send_needs_reply": classification.needs_reply,
                }
            )
            if str(current.get("name", "")) != args.target_name:
                raise RuntimeError("current inbox recipient name does not match exact target")
            if current_preview != expected_preview:
                raise RuntimeError("current inbox preview changed since the saved draft")
            if not classification.needs_reply:
                raise RuntimeError(
                    f"current thread is not reply-needed: {classification.reason}"
                )

            target_url = str(row.get("url", ""))
            expected_url = f"https://www.messenger.com/t/{args.thread_id}"
            if target_url != expected_url:
                raise RuntimeError("saved target URL is not the exact expected thread URL")

            await page.goto(
                expected_url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            await page.wait_for_timeout(5_000)
            if "login.php" in page.url or f"/t/{args.thread_id}" not in page.url:
                raise RuntimeError("authenticated Chrome profile is not on the exact target thread")
            if not await _any_exact_text_visible(page, args.target_name):
                raise RuntimeError("target recipient name is not visible in the opened thread")

            body_before = normalize_text(await page.locator("body").inner_text(timeout=10_000))
            if expected_preview not in body_before:
                raise RuntimeError("saved inbound message is not visible in the opened thread")

            editor = await _first_visible(page, COMPOSER_SELECTORS)
            if editor is None:
                raise RuntimeError("Messenger composer was not found")
            original_editor_text = await _editor_text(editor)
            status.update(
                {
                    "recipient_verified": True,
                    "thread_verified": True,
                    "inbound_message_verified": True,
                    "composer_found": True,
                    "composer_had_existing_text": bool(normalize_text(original_editor_text)),
                }
            )

            if not args.send:
                status.update(
                    {
                        "ok": True,
                        "sent": False,
                        "reason": "preflight_ready_exact_target",
                    }
                )
                return status

            await _set_editor_text(page, editor, reply)
            editor_after_fill = normalize_text(await _editor_text(editor))
            if editor_after_fill != normalize_text(reply):
                raise RuntimeError("composer text did not exactly match the intended reply")

            send_button = await _first_visible(page, SEND_SELECTORS)
            if send_button is None:
                raise RuntimeError("exact Messenger send button was not found")

            await send_button.click(timeout=10_000)
            clicked = True

            dom_confirmed = False
            for _ in range(30):
                await page.wait_for_timeout(500)
                remaining = normalize_text(await _editor_text(editor))
                body_after = normalize_text(await page.locator("body").inner_text())
                if not remaining and normalize_text(reply) in body_after:
                    dom_confirmed = True
                    break

            post_inbox_confirmed = False
            post_reason = "not_checked"
            post_preview = ""
            try:
                await page.wait_for_timeout(1_500)
                post_thread, post_classification, _ = await _scan_exact_thread(
                    page,
                    thread_id=args.thread_id,
                    scan_limit=args.scan_limit,
                )
                post_reason = post_classification.reason
                post_preview = normalize_text(str(post_thread.get("preview", "")))
                post_inbox_confirmed = (
                    not post_classification.needs_reply
                    and (
                        post_classification.reason == "already_replied"
                        or post_preview.startswith("あなた:")
                        or normalize_text(reply)[:32] in post_preview
                    )
                )
            except Exception as exc:  # noqa: BLE001 - DOM proof remains available
                post_reason = f"post_check_error:{type(exc).__name__}"

            sent = dom_confirmed or post_inbox_confirmed
            status.update(
                {
                    "dom_confirmed": dom_confirmed,
                    "post_inbox_confirmed": post_inbox_confirmed,
                    "post_send_classification": post_reason,
                    "post_preview_starts_with_you": post_preview.startswith("あなた:"),
                    "sent": sent,
                    "ok": sent,
                    "reason": (
                        "sent_confirmed"
                        if sent
                        else "send_clicked_but_delivery_unconfirmed"
                    ),
                }
            )
            return status
        except Exception:
            if editor is not None and not clicked:
                await _restore_editor(page, editor, original_editor_text)
            raise
        finally:
            # External Chrome ownership stays with the central Executor.
            pass


def _remove_exact_draft(path: Path, *, target_name: str, thread_id: str) -> bool:
    if not path.exists():
        return False
    payload = _read_json(path)
    rows = payload.get("drafts", [])
    if not isinstance(rows, list):
        return False
    kept = [
        row
        for row in rows
        if not (
            isinstance(row, dict)
            and str(row.get("name", "")) == target_name
            and str(row.get("thread_id", "")) == thread_id
        )
    ]
    if len(kept) == len(rows):
        return False
    payload["drafts"] = kept
    payload["checked_at"] = _now_jst()
    _write_json_atomic(path, payload)
    return True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-name", required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--reply-text", default="")
    parser.add_argument("--reply-base64", default="")
    parser.add_argument("--reply-file", default="")
    parser.add_argument("--scan-limit", type=int, default=50)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--headful", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.scan_limit < 1 or args.scan_limit > 100:
        raise SystemExit("--scan-limit must be between 1 and 100")

    settings = replace(
        Settings.load(),
        headless=not args.headful,
        browser_display_mode="visible" if args.headful else "headless",
    )
    drafts_path = settings.data_dir / "drafts.json"
    status_path = settings.data_dir / "send_one_reply_status.json"

    try:
        payload = _read_json(drafts_path)
        row = select_exact_draft(
            payload,
            target_name=args.target_name,
            thread_id=args.thread_id,
        )
        reply = _reply_text(args, row)
        fingerprint = message_fingerprint(reply)
        status = _base_status(args, fingerprint, len(reply))
        _block_duplicate(status_path, args)
        status = asyncio.run(_run_browser(settings, args, row, reply, status))
        if status.get("sent") is True:
            status["draft_removed_from_repo"] = _remove_exact_draft(
                drafts_path,
                target_name=args.target_name,
                thread_id=args.thread_id,
            )
        _write_json_atomic(status_path, status)
        print(json.dumps(status, ensure_ascii=False))
        return 0 if status.get("ok") else 2
    except Exception as exc:  # noqa: BLE001 - produce a durable one-shot status
        fingerprint = locals().get("fingerprint", "")
        reply = locals().get("reply", "")
        status = _base_status(args, fingerprint, len(reply))
        status.update(
            {
                "reason": "exception",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        _write_json_atomic(status_path, status)
        print(json.dumps(status, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

