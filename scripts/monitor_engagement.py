"""Monitor engagement (reactions / comments) on the bot's published posts.

For every VERIFIED posted target that has a permalink, open the post and read its
comment count (reliable) and reaction count (best-effort), snapshot the numbers
to data/engagement.json, and send a Telegram report ranked by engagement so the
operator can see which listings / groups are getting traction.

Run:
    python scripts/monitor_engagement.py            # scrape + report
    python scripts/monitor_engagement.py --no-telegram
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings, load_groups  # noqa: E402
from src.logging_setup import setup_logging  # noqa: E402
from src.queue_db import QueueDB  # noqa: E402

log = logging.getLogger("monitor_engagement")
SNAPSHOT = ROOT / "data" / "engagement.json"

_COMMENTS_RE = re.compile(r"(\d[\d,]*)\s*件のコメント")
_SHARES_RE = re.compile(r"(\d[\d,]*)\s*件のシェア")
# Reaction count comes from the post's aria-labels ("いいね！: 4人" /
# "リアクション…: 4人") — the reliable source. Text fallbacks for older layouts.
_REACT_RES = [
    re.compile(r"(?:いいね！|リアクション)[^0-9]{0,8}[:：]\s*(\d[\d,]*)\s*人"),
    re.compile(r"他\s*(\d[\d,]*)\s*人"),
    re.compile(r"(\d[\d,]*)\s*人が「?いいね"),
]
_COMMENT_LABEL_RE = re.compile(r"コメント[^0-9]{0,6}[:：]\s*(\d[\d,]*)")


def _to_int(s: str | None) -> int:
    if not s:
        return 0
    try:
        return int(s.replace(",", ""))
    except ValueError:
        return 0


def _parse_counts(text: str) -> dict[str, int]:
    cm = _COMMENTS_RE.search(text) or _COMMENT_LABEL_RE.search(text)
    comments = _to_int(cm.group(1)) if cm else 0
    shares = _to_int(_SHARES_RE.search(text).group(1)) if _SHARES_RE.search(text) else 0
    reactions = 0
    for rx in _REACT_RES:
        m = rx.search(text)
        if m:
            reactions = max(reactions, _to_int(m.group(1)))
    return {"reactions": reactions, "comments": comments, "shares": shares}


def _posted_targets(db: QueueDB) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT t.group_id, t.permalink, j.property_id
            FROM job_targets t JOIN jobs j ON j.job_id = t.job_id
            WHERE t.status = 'posted' AND t.permalink IS NOT NULL AND t.permalink != ''
            ORDER BY t.posted_at DESC
            """
        ).fetchall()
    # De-dup by permalink (keep newest).
    seen: dict[str, dict] = {}
    for r in rows:
        seen.setdefault(r["permalink"], dict(r))
    return list(seen.values())


async def scrape(now_iso: str, *, headed: bool = False) -> dict:
    settings = Settings.load()
    names = {str(g["id"]): g.get("name", g["id"]) for g in load_groups()}
    db = QueueDB(settings.db_path)
    targets = _posted_targets(db)
    results: list[dict] = []
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir), headless=not headed,
            viewport={"width": 1366, "height": 900}, user_agent=settings.browser_user_agent,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        for t in targets:
            counts = {"reactions": 0, "comments": 0, "shares": 0}
            try:
                await page.goto(t["permalink"], wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3500)
                # Parse the POST article only — the whole-page text pulls in
                # sidebars/suggestions ("他4人" etc.) and yields a constant wrong
                # number for every post.
                # innerText + the article's aria-labels (the reaction count lives
                # in a label like "いいね！: 4人", not in visible text).
                payload = await page.evaluate(
                    """() => {
                        const art = document.querySelector('div[role="article"]');
                        if (!art) return {text: '', labels: []};
                        const labels = Array.from(art.querySelectorAll('[aria-label]'))
                            .map(e => e.getAttribute('aria-label')).filter(Boolean);
                        return {text: art.innerText || '', labels};
                    }"""
                )
                text = (payload.get("text") or "") + "\n" + "\n".join(payload.get("labels") or [])
                if not text.strip():
                    text = await page.inner_text("body")
                counts = _parse_counts(text)
            except Exception as exc:  # noqa: BLE001
                log.warning("engagement scrape failed for %s: %s", t["permalink"], exc)
            results.append(
                {
                    "property_id": t["property_id"],
                    "group_id": t["group_id"],
                    "group": names.get(str(t["group_id"]), t["group_id"]),
                    "permalink": t["permalink"],
                    **counts,
                    "score": counts["reactions"] + counts["comments"] * 2 + counts["shares"] * 3,
                }
            )
        await ctx.close()
    results.sort(key=lambda r: r["score"], reverse=True)
    return {"checked_at": now_iso, "posts": results}


def _save(snapshot: dict) -> None:
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def _report(settings: Settings, snapshot: dict) -> None:
    from src.approval import TelegramApproval

    posts = snapshot["posts"]
    if not posts:
        return
    tot_r = sum(p["reactions"] for p in posts)
    tot_c = sum(p["comments"] for p in posts)
    lines = [
        f"📊 投稿の反応モニタリング（{snapshot['checked_at'][:16]}）",
        f"投稿{len(posts)}件　合計：👍{tot_r}　💬{tot_c}",
        "",
        "反応の多い順:",
    ]
    for p in posts[:10]:
        lines.append(f"・{p['group'][:14]}｜{p['property_id']}　👍{p['reactions']} 💬{p['comments']}")
        lines.append(f"　🔗 {p['permalink']}")
    try:
        notifier = TelegramApproval(settings, QueueDB(settings.db_path))
        if getattr(notifier, "enabled", False):
            notifier.send_message("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        log.warning("engagement report skipped: %s", exc)


def main() -> None:
    setup_logging()
    settings = Settings.load()
    now_iso = datetime.now(UTC).isoformat()
    snapshot = asyncio.run(scrape(now_iso))
    _save(snapshot)
    log.info("engagement snapshot: %d posts", len(snapshot["posts"]))
    if "--no-telegram" not in sys.argv:
        _report(settings, snapshot)
    print(json.dumps({"posts": len(snapshot["posts"]), "snapshot": str(SNAPSHOT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
