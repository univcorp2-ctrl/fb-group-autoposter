"""Read-only Messenger scraping — INBOX LIST ONLY.

We deliberately read ONLY the conversation list, never opening individual
threads. Opening a thread marks it "seen" and sends the other person a read
receipt — a visible side effect we must avoid for a passive assistant. The inbox
row already exposes everything we need: name, last-message preview, group-vs-1:1,
and recency. Reading the list marks nothing as seen.

messenger.com inbox structure (verified live):
  each conversation is a [role="row"] containing an <a href=".../t/<id>"> and
  span[dir="auto"] nodes = [name, last-message-preview, "·", timestamp].
  Group chats carry aria-label "グループチャット: …" and 2 stacked avatars;
  1:1 chats have an empty aria-label and a single avatar.

Selectors are defensive (FB DOM drifts); extraction is best-effort and missing
fields are returned conservatively for the classifier.
"""

from __future__ import annotations

import logging
import random
from typing import Any

log = logging.getLogger(__name__)

MESSENGER_INBOX = "https://www.messenger.com/"

# Pull conversation rows out of the inbox. For each row we capture the thread id,
# the link aria-label (group chats announce themselves there), the avatar image
# count (groups stack 2+), and the span[dir=auto] texts (name + preview + time).
_SCRAPE_ROWS_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  for (const r of Array.from(document.querySelectorAll('[role="row"]'))) {
    const a = r.querySelector('a[href*="/t/"]');
    if (!a) continue;
    const m = (a.getAttribute('href') || '').match(/\/t\/([^/?#]+)/);
    if (!m) continue;
    const id = m[1];
    if (seen.has(id)) continue;
    seen.add(id);
    const aria = (a.getAttribute('aria-label') || '').trim();
    const imgCount = r.querySelectorAll('img').length + r.querySelectorAll('svg image').length;
    const spans = Array.from(r.querySelectorAll('span[dir="auto"]'))
      .map(s => (s.innerText || '').trim())
      .filter(Boolean);
    out.push({ id, aria, imgCount, spans });
  }
  return out;
}
"""

_GROUP_ARIA_PREFIXES = ("グループチャット", "group chat")


def _is_group(aria: str, img_count: int) -> bool:
    a = aria.lower()
    if any(a.startswith(p) for p in _GROUP_ARIA_PREFIXES):
        return True
    # Group conversations stack 2+ avatars; 1:1 shows a single avatar.
    return img_count >= 2


def _parse_row(row: dict) -> dict:
    spans = [s for s in (row.get("spans") or []) if s and s != "·"]
    aria = row.get("aria", "") or ""
    name = spans[0] if spans else (aria or "(名称不明)")
    # spans = [name, preview, timestamp]; the preview is the second meaningful node.
    # The last node is the relative timestamp ("2時間") — exclude it from preview.
    preview = ""
    if len(spans) >= 3:
        preview = spans[1]
    elif len(spans) == 2:
        preview = spans[1]  # could be preview or time; classifier tolerates either
    is_group = _is_group(aria, int(row.get("imgCount", 0) or 0))
    thread_id = row.get("id", "")
    return {
        "thread_id": thread_id,
        "url": f"https://www.messenger.com/t/{thread_id}",
        "name": name,
        "preview": preview,
        "is_unread": False,  # inbox does not reliably expose this; left to a future pass
        "last_from_me": None,  # inferred from the preview prefix by the classifier
        "is_group": is_group,
        "participant_count": 2 if is_group else 1,
    }


async def _human_dwell(page: Any) -> None:
    try:
        await page.mouse.move(random.randint(200, 900), random.randint(150, 700), steps=random.randint(3, 8))
        await page.wait_for_timeout(random.randint(900, 2600))
    except Exception:  # noqa: BLE001 - dwell is cosmetic
        pass


async def scrape_inbox(page: Any, max_threads: int) -> list[dict]:
    """Load the inbox (read-only) and return up to `max_threads` thread dicts.

    Only the conversation LIST is read — no thread is opened, so nothing is marked
    seen and no read receipt is sent.
    """
    await page.goto(MESSENGER_INBOX, wait_until="domcontentloaded", timeout=60000)
    # Wait for the conversation list to actually populate before scraping — the
    # SSO bounce + SPA render can lag several seconds, and scraping too early
    # under-counts (the list looks empty, then fills in).
    try:
        await page.wait_for_selector('a[href*="/t/"]', timeout=30000)
    except Exception:  # noqa: BLE001 - fall through; _poll_rows still tries
        pass
    await page.wait_for_timeout(random.randint(2500, 4000))
    await _human_dwell(page)
    raw_rows = await _poll_rows(page)
    threads = [_parse_row(r) for r in raw_rows]
    return threads[:max_threads]


async def _poll_rows(page: Any, *, max_scrolls: int = 14, interval_ms: int = 1200) -> list[dict]:
    """Accumulate inbox rows across gentle scrolls.

    The conversation list is virtualized — only the rows near the viewport exist
    in the DOM at any moment. We scrape, scroll the list down a little, scrape
    again, and accumulate unique rows by thread id (newest stay at the top, so a
    half-render never hides the important recent ones).

    Early-exit only after the list has been steadily idle for several scrolls AND
    we have already traversed a few screens — a slow-to-populate inbox must not be
    mistaken for a short one (that bug made a real reply candidate get missed).
    """
    acc: dict[str, dict] = {}
    idle = 0
    for i in range(max_scrolls):
        try:
            rows = await page.evaluate(_SCRAPE_ROWS_JS)
        except Exception as exc:  # noqa: BLE001 - keep what we have, never crash
            log.warning("inbox scrape attempt failed: %s: %s", type(exc).__name__, exc)
            rows = []
        before = len(acc)
        for r in rows:
            rid = r.get("id")
            if rid and rid not in acc:
                acc[rid] = r
        idle = idle + 1 if len(acc) == before else 0
        # Only stop once we have scrolled a few screens and seen no new rows for
        # several consecutive reads — otherwise a lagging render ends it too soon.
        if i >= 5 and idle >= 4:
            break
        try:
            await page.mouse.move(220, 400)
            await page.mouse.wheel(0, 1400)
        except Exception:  # noqa: BLE001 - scrolling is best-effort
            pass
        await page.wait_for_timeout(interval_ms)
    return list(acc.values())
