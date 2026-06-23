"""Reliable post verification by finding the real post + its permalink.

The only trustworthy "did it post?" signal is the post actually appearing as the
bot's own post inside the group. Facebook shows that at
/groups/{group_id}/user/{c_user}. We read the posts there, match our body's
distinctive opening (greeting + property title) against each, and return the
direct permalink of the match. A closed composer is NOT proof (approval-gated
groups close the composer but never publish) — only a found permalink is.

Both the live poster and the re-verification script use this module so the
"posted" definition is identical everywhere.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

POST_HREF_RE = re.compile(r"/groups/\d+/(?:posts|permalink)/\d+")
TITLE_MARK = "🏢"  # the property-title line marker in generated bodies
# Short enough to survive Facebook's TRUNCATED post preview in the listing
# (which often cuts the title mid-word), long enough that two different property
# titles don't collide. The title is the most distinctive part of the body.
NEEDLE_LEN = 8


def norm(text: str) -> str:
    """Keep only CJK/kana/latin/digits so emoji & whitespace differences don't
    break matching between our body and Facebook's rendered innerText."""
    return re.sub(r"[^0-9A-Za-z぀-ヿ一-鿿]", "", text or "")


def needle_of(body: str) -> str:
    """A short, distinctive needle taken from the property-title line (🏢 …),
    since the generic greeting repeats across posts and FB truncates previews.
    Falls back to the body's normalized opening when no title marker exists."""
    for line in body.splitlines():
        if TITLE_MARK in line:
            title = norm(line)
            if len(title) >= 4:
                return title[:NEEDLE_LEN]
    return norm(body)[:NEEDLE_LEN]


async def cookie_user_id(context: Any) -> str | None:
    """The logged-in bot's user id (c_user cookie) — used to build the
    /groups/{gid}/user/{uid} URL that lists only the bot's own posts."""
    try:
        for c in await context.cookies():
            if c.get("name") == "c_user" and c.get("value"):
                return str(c["value"])
    except Exception as exc:  # noqa: BLE001
        log.warning("could not read c_user cookie: %s", exc)
    return None


async def collect_my_posts(page: Any, group_id: str, user_id: str, *, scrolls: int = 4) -> list[dict[str, str]]:
    """[{permalink, text}] for the bot's posts shown in this group (newest first)."""
    url = f"https://www.facebook.com/groups/{group_id}/user/{user_id}"
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3500)
    for _ in range(scrolls):
        await page.mouse.wheel(0, 2500)
        await page.wait_for_timeout(1300)
    records = await page.eval_on_selector_all(
        'a[href*="/posts/"], a[href*="/permalink/"]',
        """els => els.map(e => {
            const art = e.closest('[role="article"]');
            return { href: e.href, text: (art?.innerText || '').slice(0, 400) };
        })""",
    )
    seen: dict[str, dict[str, str]] = {}
    for r in records:
        href = (r.get("href") or "").split("?")[0]
        m = POST_HREF_RE.search(href)
        if not m:
            continue
        key = m.group(0)
        seen.setdefault(key, {"permalink": f"https://www.facebook.com{key}", "text": r.get("text") or ""})
    return list(seen.values())


def match_permalink(body: str, posts: list[dict[str, str]]) -> str | None:
    needle = needle_of(body)
    if len(needle) < 4:  # too short to be distinctive
        return None
    for post in posts:
        if needle in norm(post["text"]):
            return post["permalink"]
    return None


async def find_my_post(
    page: Any,
    group_id: str,
    user_id: str,
    body: str,
    *,
    attempts: int = 3,
) -> str | None:
    """Return the permalink of the bot's post matching `body`, or None.

    Retries because a fresh post can take a few seconds to appear in the
    user-in-group listing. None means the post is NOT visible — treat as NOT
    published (e.g. an approval-gated group holding it for moderation)."""
    for attempt in range(attempts):
        try:
            posts = await collect_my_posts(page, group_id, user_id)
            permalink = match_permalink(body, posts)
            if permalink:
                return permalink
        except Exception as exc:  # noqa: BLE001
            log.warning("verify attempt %d failed for group %s: %s", attempt + 1, group_id, exc)
        if attempt < attempts - 1:
            await page.wait_for_timeout(4000)
    return None
