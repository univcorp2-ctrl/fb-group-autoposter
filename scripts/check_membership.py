"""Detect whether the bot account is a MEMBER of each configured group, and
optionally enable (enabled:true) the ones already joined.

Membership signal: a member sees a post composer ("テキストを入力" / "投稿を作成");
a non-member sees a join CTA ("グループに参加" / "+ 参加") and no composer. We
require the composer to be present to call it a member (conservative — avoids
enabling a group we cannot actually post to).

Usage:
    python scripts/check_membership.py            # report only
    python scripts/check_membership.py --enable    # also flip joined groups to enabled:true
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from config import Settings  # noqa: E402

GROUPS_YAML = ROOT / "groups.yaml"

COMPOSER_HINTS = ["テキストを入力", "投稿を作成", "ディスカッションを書く", "その気持ち", "近況", "Write something", "Create post"]
JOIN_HINTS = ["グループに参加", "+ 参加", "参加をリクエスト", "Join group", "Join Group"]


async def _is_member(page, post_url: str) -> tuple[bool, str]:
    await page.goto(post_url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4500)
    body = ""
    try:
        body = await page.inner_text("body")
    except Exception:
        pass
    has_composer = any(h in body for h in COMPOSER_HINTS)
    has_join = any(h in body for h in JOIN_HINTS)
    if has_composer:
        return True, "composer present"
    if has_join:
        return False, "join CTA present (not a member)"
    return False, "no composer detected"


def _all_group_entries() -> list[dict]:
    data = yaml.safe_load(GROUPS_YAML.read_text(encoding="utf-8")) or {}
    return data.get("groups", [])


def _enable_in_yaml(group_ids: list[str]) -> int:
    """Flip `enabled: false` -> `true` for the given group ids, editing the file
    as TEXT so all comments/formatting are preserved."""
    text = GROUPS_YAML.read_text(encoding="utf-8")
    lines = text.split("\n")
    flipped = 0
    current_id: str | None = None
    id_re = re.compile(r'^\s*-?\s*id:\s*"?(\d+)"?')
    for i, line in enumerate(lines):
        m = id_re.match(line)
        if m:
            current_id = m.group(1)
            continue
        if current_id in group_ids and re.match(r"^\s*enabled:\s*false\s*$", line):
            lines[i] = line.replace("false", "true")
            flipped += 1
            current_id = None
    if flipped:
        GROUPS_YAML.write_text("\n".join(lines), encoding="utf-8")
    return flipped


async def main() -> None:
    do_enable = "--enable" in sys.argv
    settings = Settings.load()
    groups = _all_group_entries()
    from playwright.async_api import async_playwright

    joined_disabled: list[str] = []
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir), headless=True,
            viewport={"width": 1366, "height": 900}, user_agent=settings.browser_user_agent,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        for g in groups:
            gid = str(g["id"])
            enabled = g.get("enabled", True)
            try:
                member, why = await _is_member(page, g["post_url"])
            except Exception as exc:  # noqa: BLE001
                member, why = False, f"check failed: {exc}"
            mark = "✅member" if member else "❌not-member"
            print(f"  {mark:14} {'ON ' if enabled else 'off'} {gid:18} {g.get('name','')[:26]}  ({why})")
            if member and not enabled:
                joined_disabled.append(gid)
        await ctx.close()

    print(f"\njoined-but-disabled groups: {joined_disabled or 'none'}")
    if do_enable and joined_disabled:
        n = _enable_in_yaml(joined_disabled)
        print(f"enabled {n} group(s) in groups.yaml")


if __name__ == "__main__":
    asyncio.run(main())
