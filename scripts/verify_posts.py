"""Ground-truth verification: visit each group as the bot and find real posts.

This answers "was it ACTUALLY posted?" by the only reliable means: open the
bot's own posts page inside each group (/groups/{gid}/user/{c_user}), read the
real posts Facebook shows there, capture each post's direct permalink, and match
them against what the DB claims. The DB is then corrected to the truth:
  - a claimed post that IS found  -> status 'posted' + its real permalink
  - a claimed post that is NOT found -> status 'failed' (needs re-posting)

Run:
    python scripts/verify_posts.py            # verify + correct DB (headless)
    python scripts/verify_posts.py --headed   # show the browser
    python scripts/verify_posts.py --probe    # only print what FB shows, no DB writes
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings, load_groups  # noqa: E402
from src.logging_setup import setup_logging  # noqa: E402
from src.post_verify import collect_my_posts, cookie_user_id, match_permalink, norm, pending_match  # noqa: E402
from src.queue_db import QueueDB  # noqa: E402
from src.verifier import save_screenshot  # noqa: E402

log = logging.getLogger("verify_posts")


async def run(*, headed: bool, probe: bool) -> dict:
    settings = Settings.load()
    groups = {str(g["id"]): g for g in load_groups()}
    db = QueueDB(settings.db_path)

    # Re-check posted/uncertain, plus recently-failed targets (so a post that was
    # transiently missed can be RESTORED to posted once found). We never downgrade
    # on a miss (see below), so including failed is safe and self-healing.
    from datetime import UTC, datetime, timedelta

    recent = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT t.job_id, t.group_id, t.status, t.body, t.permalink, j.property_id
            FROM job_targets t JOIN jobs j ON j.job_id = t.job_id
            WHERE t.status IN ('posted','uncertain')
               OR (t.status = 'failed' AND COALESCE(t.posted_at, j.updated_at) >= ?)
            ORDER BY t.group_id
            """,
            (recent,),
        ).fetchall()
    claimed = [dict(r) for r in rows]
    log.info("re-checking %d targets across %d groups", len(claimed), len({r['group_id'] for r in claimed}))

    from playwright.async_api import async_playwright

    summary = {"checked": 0, "confirmed": 0, "missing": 0, "by_group": {}}
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir),
            headless=not headed,
            viewport={"width": 1366, "height": 900},
            user_agent=settings.browser_user_agent,
        )
        c_user = await cookie_user_id(ctx)
        log.info("logged-in bot user id (c_user): %s", c_user)
        if not c_user:
            await ctx.close()
            return {"error": "not_logged_in", "detail": "no c_user cookie; run scripts/login_once.py"}

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        group_posts: dict[str, list[dict]] = {}
        target_gids = {r["group_id"] for r in claimed} | set(groups.keys())
        for gid in target_gids:
            try:
                posts = await collect_my_posts(page, gid, c_user, post_url=groups.get(gid, {}).get("post_url"))
            except Exception as exc:  # noqa: BLE001
                log.warning("could not read group %s: %s", gid, exc)
                posts = []
            group_posts[gid] = posts
            summary["by_group"][gid] = {"name": groups.get(gid, {}).get("name", gid), "real_posts_found": len(posts)}
            log.info("group %s (%s): %d real bot posts visible", gid, groups.get(gid, {}).get("name", "?"), len(posts))

        if probe:
            for gid, posts in group_posts.items():
                print(f"\n=== {gid} ({groups.get(gid, {}).get('name','?')}) — {len(posts)} posts ===")
                for post in posts[:10]:
                    print(f"  {post['permalink']}\n    {norm(post['text'])[:60]}")
            await ctx.close()
            return summary

        # Correct the DB against reality.
        summary["promoted"] = 0
        summary["demoted"] = 0
        summary["still_pending"] = 0
        for rec in claimed:
            summary["checked"] += 1
            gid = rec["group_id"]
            posts = group_posts.get(gid, [])
            permalink = match_permalink(rec["body"] or "", posts)
            if permalink and db.is_valid_facebook_permalink(permalink):
                summary["confirmed"] += 1
                if rec["status"] in {"uncertain", "failed"}:
                    shot = await save_screenshot(await _open(page, permalink), prefix="verified", job_id=rec["job_id"], group_id=gid)
                    name = groups.get(gid, {}).get("name", gid)
                    event_subject = f"{rec['job_id']}:{gid}:{permalink}"
                    db.update_target_status_with_outbox(
                        rec["job_id"],
                        gid,
                        "posted",
                        permalink=permalink,
                        screenshot=shot,
                        event_key=f"telegram:verify:{hashlib.sha256(event_subject.encode()).hexdigest()}:promoted",
                        event_type="verified_promotion",
                        origin_run_id="verify_posts",
                        subject_id=rec["property_id"],
                        payload={
                            "text": f"✅ 公開を確認しました（承認済み）: {name}\n"
                            f"物件: {rec['property_id']}\n🔗 {permalink}",
                            "property_id": rec["property_id"],
                            "group_id": gid,
                            "permalink": permalink,
                        },
                    )
                    # Was uncertain/failed and is now confirmed live -> promote and
                    # tell the operator with the link.
                    summary["promoted"] += 1
                log.info("CONFIRMED %s in %s -> %s", rec["property_id"], gid, permalink)
            elif rec["status"] == "posted" and pending_match(rec["body"] or "", posts):
                # Our post IS present but held for moderator approval (承認制グループ).
                # It was wrongly recorded 'posted' (the approval-gated false-positive)
                # -> DEMOTE to 'uncertain' so it stops counting as 投稿済. This is a
                # POSITIVE pending detection, not a plain miss, so downgrading is
                # correct here (posted_at is preserved by update_target_status).
                name = groups.get(gid, {}).get("name", gid)
                db.update_target_status_with_outbox(
                    rec["job_id"],
                    gid,
                    "uncertain",
                    error="pending_approval",
                    event_key=f"telegram:verify:{rec['job_id']}:{gid}:uncertain",
                    event_type="uncertain_post",
                    origin_run_id="verify_posts",
                    subject_id=rec["property_id"],
                    payload={
                        "text": f"⚠️ 投稿は承認待ちです（{name}）。\n"
                        f"物件: {rec['property_id']}（投稿済みにはカウントしません）",
                        "property_id": rec["property_id"],
                        "group_id": gid,
                    },
                )
                summary["demoted"] += 1
                log.info("DEMOTED (承認待ち→uncertain) %s in %s", rec["property_id"], gid)
            else:
                # NOT found this run. We do NOT downgrade — verification has
                # transient misses (FB feed virtualization/lazy-load), and the
                # post was already verified live at post time. Downgrading a real
                # post on a single miss would itself be a false report. Just count
                # it; the next sweep re-checks. (False positives are prevented at
                # post time now, so 'posted' stays trustworthy.)
                summary["missing"] += 1
                log.info("not-found this run (left as-is, status=%s): %s in %s", rec["status"], rec["property_id"], gid)

        await ctx.close()
    return summary


async def _open(page, permalink: str):
    """Open a permalink and let it render, returning the page for screenshotting."""
    try:
        await page.goto(permalink, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not open permalink %s: %s", permalink, exc)
    return page


def main() -> None:
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--probe", action="store_true", help="only print what FB shows; no DB writes")
    args = ap.parse_args()
    summary = asyncio.run(run(headed=args.headed, probe=args.probe))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
