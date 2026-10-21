"""Read-only investigation of ONE previously uncertain Messenger auto-reply.

No clicks, fills, message sends, state writes, or automatic replay.
Uses an independent background CDP tab, then closes that tab only.
Only reports hashes, booleans and counts; never customer text or identities.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.async_api import async_playwright
from config import Settings
from src.authenticated_chrome import attach_authenticated_context, create_background_page
from src.delivery_proof import inspect_outgoing_text

def uncertain_entry(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    rows = [v for v in obj["attempts"].values()
            if v.get("state") == "blocked_or_uncertain_no_replay"]
    if len(rows) != 1:
        raise ValueError("expected exactly one uncertain entry; safe refusal")
    if not str(rows[0].get("thread_id", "")).isdigit():
        raise ValueError("invalid thread identifier")
    return rows[0]

def matching_archive(path: Path, thread_id: str) -> list[dict]:
    if not path.exists():
        return []
    matching = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        if str(row.get("thread_id")) == thread_id and isinstance(row.get("draft"), str):
            matching.append(row)
    return matching

async def inspect() -> dict:
    settings = Settings.load()
    entry = uncertain_entry(settings.data_dir / 'auto_reply_ledger.json')
    thread_id = str(entry["thread_id"])
    archived = matching_archive(settings.data_dir / "drafts_archive.jsonl", thread_id)
    result = {
        "mode": "read_only_no_send",
        "thread_hash_prefix": hashlib.sha256(thread_id.encode()).hexdigest()[:12],
        "ledger_state_unchanged": entry.get("state"),
        "archive_candidate_count": len(archived),
        "verified_delivery": False,
        "no_replay": True,
        "ui_loaded": False,
    }
    async with async_playwright() as playwright:
        attachment = await attach_authenticated_context(playwright, settings)
        page = await create_background_page(attachment.context)
        try:
            await page.goto(f"https://www.messenger.com/t/{thread_id}",
                            wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1100)
            main = page.locator("main").first
            if not await main.count():
                main = page.locator('[role="main"]').first
            result["exact_thread_url"] = f"/t/{thread_id}" in str(page.url)
            if result["exact_thread_url"] and await main.count():
                result["ui_loaded"] = True
                body = await main.inner_text(timeout=12000)
                result["readable_text_length"] = len(body)
                result["outgoing_label_count"] = await main.locator(
                    '[aria-label*="あなたが送信したメッセージ"]').count()
                # Archived drafts alone do not prove message delivery.
                candidates = [row for row in archived
                              if row.get("draft")
                              and (row.get("material") or {}).get("file_name")]
                exact = [
                    inspect_outgoing_text(body, row["draft"], row["material"]["file_name"])
                    for row in candidates
                ]
                result["eligible_exact_proof_candidates"] = len(candidates)
                result["exact_outgoing_text_and_pdf_match"] = any(
                    p["confirmed"] for p in exact
                )
                # Even text/PDF matching without sender, time and direction
                # confirmation is insufficient to clear the historical ledger.
        finally:
            await page.close()
    return result

if __name__ == "__main__":
    print(json.dumps(asyncio.run(inspect()), ensure_ascii=False))
