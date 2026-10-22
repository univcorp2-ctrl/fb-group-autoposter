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
    img_count = int(row.get("imgCount", 0) or 0)
    is_group = _is_group(aria, img_count)
    thread_id = str(row.get("id", ""))
    # A single counterpart avatar, a numeric DM thread ID and a named
    # counterpart are positive 1:1 inbox signals. Ambiguous rows fail closed.
    # Sending requires a separate, exact-recipient in-thread preflight.
    one_to_one_verified = bool(
        not is_group and img_count == 1 and thread_id.isdecimal()
        and name != "(名称不明)" and bool(name.strip())
    )
    return {
        "thread_id": thread_id,
        "url": f"https://www.messenger.com/t/{thread_id}",
        "name": name,
        "preview": preview,
        "is_unread": False,  # inbox does not reliably expose this; left to a future pass
        "last_from_me": None,  # inferred from the preview prefix by the classifier
        "is_group": is_group,
        "participant_count": 2 if is_group else (1 if one_to_one_verified else None),
        "one_to_one_verified": one_to_one_verified,
        "time_text": spans[-1] if len(spans) >= 3 else "",
    }


async def _human_dwell(page: Any) -> None:
    try:
        await page.mouse.move(random.randint(200, 900), random.randint(150, 700), steps=random.randint(3, 8))
        await page.wait_for_timeout(random.randint(900, 2600))
    except Exception:  # noqa: BLE001 - dwell is cosmetic
        pass


async def scrape_inbox(page: Any, max_threads: int, *, quick: bool = False) -> list[dict]:
    """Load the inbox (read-only) and return up to `max_threads` thread dicts.

    Only the conversation LIST is read — no thread is opened, so nothing is marked
    seen and no read receipt is sent.
    """
    # Preserve the live inbox SPA and its WebSocket subscriptions across polls.
    # Unconditionally reloading each minute resets the virtual list to
    # "loading..." and may miss every new message.
    from urllib.parse import urlparse
    current=urlparse(str(page.url))
    inbox_already_open=(
        (current.hostname or "").lower() in {"messenger.com","www.messenger.com"}
        and current.path in {"","/"}
    )
    if not inbox_already_open:
        await page.goto(MESSENGER_INBOX, wait_until="domcontentloaded", timeout=60000)
    # Modern Chrome resets window.name when navigating from about:blank to
    # messenger.com. Tag on the *Messenger origin* so the background tab is
    # found again on the next poll, avoiding a new tab every minute.
    from src.authenticated_chrome import AUTOMATION_PAGE_TAG
    await page.evaluate("(tag) => { window.name = tag; }", AUTOMATION_PAGE_TAG)
    # Wait for the conversation list to actually populate before scraping — the
    # SSO bounce + SPA render can lag several seconds, and scraping too early
    # under-counts (the list looks empty, then fills in).
    try:
        await page.wait_for_selector('a[href*="/t/"]', timeout=12000 if quick else 30000)
    except Exception:  # noqa: BLE001 - fall through; _poll_rows still tries
        pass
    if quick:
        # The virtualized list retains its scroll position between daemon polls.
        # Start every scan at the newest rows, including after a deep lookup.
        await page.mouse.move(220, 400)
        await page.mouse.wheel(0, -100000)
        await page.wait_for_timeout(350)
        # The newest inbound DM is at the top. Never scroll through history
        # on every minute-sized poll; that takes too long and disturbs UI state.
        await page.wait_for_timeout(650)
        raw_rows = await _poll_rows(page, max_scrolls=2, interval_ms=350)
        if not raw_rows:
            # Messenger sometimes renders "loading..." for several seconds
            # *after* domcontentloaded. Never report a false empty inbox.
            await page.wait_for_timeout(2600)
            raw_rows = await _poll_rows(page, max_scrolls=6, interval_ms=800)
        if not raw_rows:
            raise RuntimeError("messenger_inbox_not_rendered_retry")
    else:
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
        if i == max_scrolls - 1:
            break
        try:
            await page.mouse.move(220, 400)
            await page.mouse.wheel(0, 1400)
        except Exception:  # noqa: BLE001 - scrolling is best-effort
            pass
        await page.wait_for_timeout(interval_ms)
    return list(acc.values())
