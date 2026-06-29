"""Read-only scraping of a Facebook group feed (役割3).

Collects post text + author + permalink from a group's feed. NEVER posts, likes,
or comments — purely passive reading. Like the autoposter's feed handling, it
scrapes-before-scroll and accumulates, because the feed is virtualized (scrolling
unloads earlier posts from the DOM).

FB's DOM drifts, so selectors are defensive and post extraction is best-effort.
No dependency on the other roles.
"""

from __future__ import annotations

import logging
import random
from typing import Any

log = logging.getLogger(__name__)

# Each feed post is an article; we pull its visible text and the first permalink
# (the post's timestamp link). Author is the first strong/link name in the header.
_SCRAPE_POSTS_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  for (const art of Array.from(document.querySelectorAll('div[role="article"]'))) {
    const text = (art.innerText || '').replace(/ /g, ' ').trim();
    if (text.length < 30) continue;
    // The post permalink is a link whose href contains /posts/ or /permalink/.
    let permalink = '';
    for (const a of art.querySelectorAll('a[href]')) {
      const h = a.getAttribute('href') || '';
      if (/\/posts\/|\/permalink\/|story_fbid=/.test(h)) { permalink = h; break; }
    }
    const key = permalink || text.slice(0, 60);
    if (seen.has(key)) continue;
    seen.add(key);
    // First link text in the article header is usually the author name.
    const firstLink = art.querySelector('h3 a, h4 a, strong a, a[role="link"]');
    const author = firstLink ? (firstLink.innerText || '').trim() : '';
    out.push({ text: text.slice(0, 4000), permalink, author });
  }
  return out;
}
"""


async def _human_dwell(page: Any) -> None:
    try:
        await page.mouse.move(random.randint(200, 1000), random.randint(150, 700), steps=random.randint(3, 8))
        await page.wait_for_timeout(random.randint(900, 2400))
    except Exception:  # noqa: BLE001 - dwell is cosmetic
        pass


async def scrape_group_feed(page: Any, feed_url: str, max_posts: int) -> list[dict]:
    """Open a group feed (read-only) and accumulate up to `max_posts` posts.

    Scrapes the current DOM, scrolls a little, scrapes again, accumulating unique
    posts — so virtualization (which unloads earlier posts) never hides them.
    """
    await page.goto(feed_url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(random.randint(4000, 6500))
    acc: dict[str, dict] = {}
    idle = 0
    for i in range(max(6, max_posts // 3)):
        try:
            posts = await page.evaluate(_SCRAPE_POSTS_JS)
        except Exception as exc:  # noqa: BLE001 - keep what we have, never crash
            log.warning("feed scrape attempt failed: %s: %s", type(exc).__name__, exc)
            posts = []
        before = len(acc)
        for p in posts:
            key = p.get("permalink") or p.get("text", "")[:60]
            if key and key not in acc:
                acc[key] = p
        if len(acc) >= max_posts:
            break
        idle = idle + 1 if len(acc) == before else 0
        if i >= 4 and idle >= 3:
            break
        await _human_dwell(page)
        try:
            await page.mouse.wheel(0, random.randint(1500, 2600))
        except Exception:  # noqa: BLE001 - scrolling is best-effort
            pass
        await page.wait_for_timeout(random.randint(1200, 2200))
    return list(acc.values())[:max_posts]
