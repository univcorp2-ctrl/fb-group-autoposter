"""Arm Messenger auto-send for NEW messages only; never sends anything.

Capture the current one-to-one inbox previews as hashes. Messages already
present at activation are never sent later because a delayed premium review
completed. Preserve the existing attempt ledger and no-replay protections.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import Settings
from src.authenticated_chrome import attach_authenticated_context, select_messenger_page
from src.scraper import scrape_inbox
from src.auto_reply import (
    JST, LEDGER, BASELINE_INBOX, safe_save,
)

async def main():
    settings=Settings.load()
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        attachment=await attach_authenticated_context(p,settings)
        page=await select_messenger_page(attachment.context)
        threads=await scrape_inbox(page, max(settings.max_threads_per_run, 50))
    if not threads:
        raise RuntimeError("Inbox empty or unavailable; do not arm auto-send")
    preview_hashes={
        str(row["thread_id"]): hashlib.sha256(str(row.get("preview", "")).encode("utf-8")).hexdigest()
        for row in threads if str(row.get("thread_id", "")).isdigit()
    }
    if len(preview_hashes) < 1:
        raise RuntimeError("No valid inbox thread IDs; do not arm auto-send")
    when=datetime.now(JST).isoformat()
    ledger={"attempts":{}}
    if LEDGER.exists():
        ledger=json.loads(LEDGER.read_text(encoding="utf-8"))
        if not isinstance(ledger.get("attempts"),dict):
            raise RuntimeError("Existing no-replay ledger is invalid")
    # Write baseline before rearming attempts. Never erase prior send attempts.
    safe_save(BASELINE_INBOX,{"captured_at":when,"previews":preview_hashes})
    ledger["armed_after"]=when
    safe_save(LEDGER,ledger)
    print(json.dumps({
        "baseline_at":when,"inbox_threads":len(threads),
        "hashed_previews":len(preview_hashes),
        "existing_attempts_preserved":len(ledger["attempts"]),
        "sent":False,
    },ensure_ascii=False))

if __name__=="__main__":
    asyncio.run(main())
