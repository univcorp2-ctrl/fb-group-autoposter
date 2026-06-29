"""Discover the Facebook groups the bot account is ALREADY a member of (read-only).

Posting only works in groups we belong to, so this is the ground truth for which
groups we can actually post into. It scrapes facebook.com/groups/joins (the
"groups you've joined" list), records each group (id, name, members text), flags
which ones look real-estate / investor friendly, cross-references groups.yaml,
and writes data/joined_groups.json.

Read-only: it only reads the membership list — it never joins, posts, or leaves.

Usage:
    python scripts/discover_joined_groups.py
    python scripts/discover_joined_groups.py --headful   # watch it run
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings, load_groups  # noqa: E402
from src.session import is_logged_in  # noqa: E402

OUT_JSON = ROOT / "data" / "joined_groups.json"
GROUP_ID_RE = re.compile(r"/groups/(\d+)")

# Keywords that mark a group as a good fit for property distribution. Tiered so we
# can prioritize: "core" = real estate, "adjacent" = investors/affluent/biz.
_CORE_HINTS = (
    "不動産", "物件", "収益", "大家", "一棟", "区分", "アパート", "マンション",
    "戸建", "空き家", "賃貸", "売買", "用地", "土地", "リフォーム", "民泊", "競売",
)
_ADJACENT_HINTS = (
    "投資", "資産", "FIRE", "副業", "経営者", "社長", "起業", "富裕", "ドクター",
    "オーナー", "ビジネス", "PR", "宣伝", "告知", "集客", "相続", "節税", "士業",
)
# Names that are clearly NOT a distribution target (avoid posting property here).
_EXCLUDE_HINTS = (
    "同窓", "卒業", "�クラス会", "家族", "ファンクラブ", "ゲーム", "売ります買います 地域",
)

# Non-group system links that appear on the joins page.
_SKIP_PATHS = ("/groups/joins", "/groups/create", "/groups/discover", "/groups/feed")


def classify(name: str) -> tuple[str, bool]:
    """Return (category, is_property_friendly)."""
    n = name or ""
    if any(h in n for h in _EXCLUDE_HINTS):
        return "対象外", False
    if any(h in n for h in _CORE_HINTS):
        return "不動産コア", True
    if any(h in n for h in _ADJACENT_HINTS):
        return "投資・経営・隣接", True
    return "その他（要判断）", False


async def _scrape_joined(page) -> list[dict]:
    await page.goto("https://www.facebook.com/groups/joins/", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(5000)
    for _ in range(12):  # scroll to load the full membership list
        await page.mouse.wheel(0, 2600)
        await page.wait_for_timeout(1200)
    anchors = await page.eval_on_selector_all(
        '[role="main"] a[href*="/groups/"]',
        """els => els.map(e => ({
            href: e.href,
            text: (e.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120)
        }))""",
    )
    found: dict[str, dict] = {}
    for a in anchors:
        href = a.get("href") or ""
        if any(sp in href for sp in _SKIP_PATHS):
            continue
        m = GROUP_ID_RE.search(href)
        if not m:
            continue
        gid = m.group(1)
        name = (a.get("text") or "").split("\n")[0].strip()
        # The same group may appear as an image link (no text) and a name link;
        # keep the longest name we see.
        if gid not in found or (name and len(name) > len(found[gid]["name"])):
            cat, friendly = classify(name)
            found[gid] = {
                "group_id": gid,
                "url": f"https://www.facebook.com/groups/{gid}",
                "name": name,
                "category": cat,
                "property_friendly": friendly,
            }
    return list(found.values())


async def main() -> None:
    settings = Settings.load()
    headful = "--headful" in sys.argv
    known = {str(g["id"]): g for g in load_groups()}

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir), headless=not headful,
            viewport={"width": 1366, "height": 900}, user_agent=settings.browser_user_agent,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        if not await is_logged_in(page):
            await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)
        logged_in = await is_logged_in(page)
        groups = await _scrape_joined(page) if logged_in else []
        await ctx.close()

    for g in groups:
        g["in_groups_yaml"] = g["group_id"] in known
        g["enabled_in_yaml"] = bool(known.get(g["group_id"], {}).get("enabled")) if g["group_id"] in known else False

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps({"checked_at": datetime.now(UTC).isoformat(), "logged_in": logged_in, "groups": groups},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    friendly = [g for g in groups if g["property_friendly"]]
    new_friendly = [g for g in friendly if not g["in_groups_yaml"]]
    print(json.dumps({
        "logged_in": logged_in,
        "joined_total": len(groups),
        "property_friendly": len(friendly),
        "friendly_not_in_yaml": len(new_friendly),
    }, ensure_ascii=False))
    print("\n--- 物件配信に向く所属グループ ---")
    for g in sorted(friendly, key=lambda x: (x["in_groups_yaml"], x["category"])):
        flag = "✓yaml" if g["in_groups_yaml"] else "＋新規"
        print(f"  [{flag}] {g['category']:10} {g['name'][:40]}  {g['url']}")


if __name__ == "__main__":
    asyncio.run(main())
