"""Capture recent exact-thread context for a review draft.

This opens a temporary tab in the already authenticated Messenger Chrome context.
Reading an actual thread may mark messages seen; never send a message here.
The newly created tab is closed, all preexisting tabs are untouched.
"""
from __future__ import annotations

from typing import Any

async def read_recent_thread_text(page: Any, thread_id: str, recipient_name: str) -> str:
    if not thread_id.isdecimal():
        return ""
    temp = await page.context.new_page()
    try:
        await temp.goto(
            f"https://www.messenger.com/t/{thread_id}",
            wait_until="domcontentloaded", timeout=40_000,
        )
        await temp.wait_for_timeout(1200)
        if f"/t/{thread_id}" not in str(temp.url):
            return ""
        name_visible = temp.get_by_text(recipient_name, exact=True)
        if not await name_visible.count():
            return ""
        # Scope to the conversation panel; do not read other sidebar chats.
        for selector in ('main', '[role="main"]'):
            loc = temp.locator(selector)
            if await loc.count():
                raw = (await loc.first.inner_text(timeout=8000)).strip()
                if raw:
                    return raw[-3800:]
        # Unknown layout; do not silently substitute unrelated sidebar content.
        return ""
    except Exception:
        return ""
    finally:
        await temp.close()
