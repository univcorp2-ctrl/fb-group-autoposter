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


_ARTICLE_JS = """arts => arts.map(a => {
    const link = a.querySelector('a[href*="/posts/"], a[href*="/permalink/"]');
    return { href: link ? link.href : '', text: (a.innerText || '').slice(0, 500) };
})"""


async def _scan_url(page: Any, url: str, *, scrolls: int) -> tuple[list[dict[str, str]], str]:
    """Load `url` and return (article posts, accumulated normalized page text).

    CRITICAL: Facebook's feed is virtualized — scrolling unloads the TOP posts
    from the DOM. A freshly published post lives at the top, so we must scrape
    BEFORE scrolling and ACCUMULATE across scroll steps; scraping only after
    scrolling misses the newest post (the false-negative bug)."""
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3500)

    posts: list[dict[str, str]] = []
    seen: set[str] = set()
    text_parts: list[str] = []
    noperma = 0

    async def _harvest() -> None:
        nonlocal noperma
        try:
            records = await page.eval_on_selector_all('div[role="article"]', _ARTICLE_JS)
        except Exception as exc:  # noqa: BLE001
            log.warning("article scrape failed on %s: %s", url, exc)
            records = []
        for r in records:
            href = (r.get("href") or "").split("?")[0]
            m = POST_HREF_RE.search(href)
            if m:
                key = m.group(0)
                if key in seen:
                    continue
                seen.add(key)
                posts.append({"permalink": f"https://www.facebook.com{m.group(0)}", "text": r.get("text") or ""})
            elif r.get("text"):
                noperma += 1
                posts.append({"permalink": "", "text": r.get("text") or ""})
        try:
            text_parts.append(norm(await page.inner_text("body")))
        except Exception:  # noqa: BLE001
            pass

    await _harvest()  # top first (fresh posts live here)
    for _ in range(scrolls):
        await page.mouse.wheel(0, 2500)
        await page.wait_for_timeout(1300)
        await _harvest()
    return posts, "".join(text_parts)


def _verify_urls(group_id: str, user_id: str, post_url: str | None) -> list[str]:
    """Where to look, most-reliable first: the plain group feed shows the author's
    freshly published post at the top (proven), then the bot's in-group page."""
    urls = [post_url or f"https://www.facebook.com/groups/{group_id}"]
    urls.append(f"https://www.facebook.com/groups/{group_id}/user/{user_id}")
    return urls


async def collect_my_posts(
    page: Any,
    group_id: str,
    user_id: str,
    *,
    post_url: str | None = None,
    scrolls: int = 4,
) -> list[dict[str, str]]:
    """Posts to match against, merged from the group feed + the bot's posts page."""
    merged: dict[str, dict[str, str]] = {}
    idx = 0
    for url in _verify_urls(group_id, user_id, post_url):
        try:
            posts, _ = await _scan_url(page, url, scrolls=scrolls)
            for post in posts:
                key = post["permalink"] or f"noperma:{url}:{idx}"
                idx += 1
                merged.setdefault(key, post)
        except Exception as exc:  # noqa: BLE001
            log.warning("collect from %s failed: %s", url, exc)
    return list(merged.values())


def match_permalink(body: str, posts: list[dict[str, str]]) -> str | None:
    needle = needle_of(body)
    if len(needle) < 4:  # too short to be distinctive
        return None
    for post in posts:
        if needle in norm(post["text"]):
            return post["permalink"] or None
    return None


async def find_my_post(
    page: Any,
    group_id: str,
    user_id: str,
    body: str,
    *,
    post_url: str | None = None,
    attempts: int = 3,
) -> str | None:
    """Return the permalink of the bot's post matching `body`, or None.

    Strategy, retried (a fresh post can take a few seconds to surface):
      1. Scan the plain group feed (author sees their new post at the top), then
         the bot's in-group page.
      2. Match the property-title needle against each article -> return its
         permalink.
      3. Fallback: if no article carried a permalink but the needle IS in the
         page text, the post IS public — return the group URL as a best-effort
         link rather than a false negative.
    None means the post was not found anywhere (genuinely not visible)."""
    needle = needle_of(body)
    if len(needle) < 4:
        return None
    for attempt in range(attempts):
        page_text_hit_url: str | None = None
        for url in _verify_urls(group_id, user_id, post_url):
            try:
                posts, page_text = await _scan_url(page, url, scrolls=4)
            except Exception as exc:  # noqa: BLE001
                log.warning("verify scan failed for %s: %s", url, exc)
                continue
            for post in posts:
                if needle in norm(post["text"]) and post["permalink"]:
                    return post["permalink"]
            if needle in page_text and page_text_hit_url is None:
                page_text_hit_url = post_url or url
        if page_text_hit_url:
            # Confirmed present (page text) but no clean permalink anchor — better
            # a best-effort group link than a false "not posted".
            log.info("post confirmed via page text (no exact permalink) in group %s", group_id)
            return page_text_hit_url
        if attempt < attempts - 1:
            await page.wait_for_timeout(4000)
    return None
