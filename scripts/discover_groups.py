"""Discover candidate Facebook groups for real-estate / investor audiences.

Read-only: it searches Facebook Groups for a set of keywords using the
logged-in session, collects candidate groups (name, URL, member text, privacy),
de-duplicates against groups.yaml and previously discovered candidates, and
writes:
  - data/group_candidates.json  (machine-readable, accumulates over time)
  - data/group_candidates.md     (human review list, newest first)

It does NOT auto-join groups. Joining is left to the operator on purpose:
auto-joining is a strong ban signal and most quality groups gate membership
behind approval questions. Review the list and join the good ones manually;
then add their URLs to groups.yaml to post into them.
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

from config import Settings, load_groups

KEYWORDS = [
    "不動産投資",
    "収益物件",
    "一棟 収益",
    "不動産投資家",
    "投資家 交流",
    "富裕層 投資",
    "資産運用 不動産",
    "不動産オーナー",
    "大家 交流",
    "経営者 投資 交流",
]

CANDIDATES_JSON = ROOT / "data" / "group_candidates.json"
CANDIDATES_MD = ROOT / "data" / "group_candidates.md"
GROUP_ID_RE = re.compile(r"/groups/(\d+)")


def _load_existing() -> dict[str, dict]:
    if CANDIDATES_JSON.exists():
        try:
            return {c["group_id"]: c for c in json.loads(CANDIDATES_JSON.read_text(encoding="utf-8"))}
        except Exception:
            return {}
    return {}


def _known_group_ids() -> set[str]:
    ids: set[str] = set()
    try:
        for g in load_groups():
            ids.add(str(g["id"]))
    except Exception:
        pass
    return ids


async def _search_keyword(page, keyword: str) -> list[dict]:
    url = f"https://www.facebook.com/search/groups/?q={keyword}"
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(4000)
    for _ in range(4):  # scroll to load more results
        await page.mouse.wheel(0, 2500)
        await page.wait_for_timeout(1500)
    # Scope to the search-results main region so the notification flyout (which
    # also contains /groups/ links) does not leak in.
    anchors = await page.eval_on_selector_all(
        '[role="main"] a[href*="/groups/"]',
        """els => els.map(e => ({
            href: e.href,
            text: (e.closest('[role=\"article\"]')?.innerText || e.innerText || '').trim().slice(0, 300)
        }))""",
    )
    found: dict[str, dict] = {}
    for a in anchors:
        m = GROUP_ID_RE.search(a["href"] or "")
        if not m:
            continue
        gid = m.group(1)
        if gid in found:
            continue
        text = a["text"] or ""
        name = text.split("\n")[0][:80] if text else ""
        # Drop notification-style leakage (e.g. "未読…さんが…に投稿しました").
        if name.startswith("未読") or any(p in name for p in ("さんが", "のコメント", "に投稿しました", "メンションしました")):
            continue
        members = ""
        mm = re.search(r"(メンバー[\s\S]{0,15}?[\d,，.万]+\s*人?|[\d,，.万]+\s*人のメンバー|[\d.,]+[KM]?\s*members)", text)
        if mm:
            members = mm.group(0).replace("\n", " ").strip()
        privacy = "非公開" if "非公開" in text or "Private" in text else ("公開" if "公開" in text or "Public" in text else "")
        found[gid] = {
            "group_id": gid,
            "url": f"https://www.facebook.com/groups/{gid}",
            "name": name,
            "members": members,
            "privacy": privacy,
            "keyword": keyword,
        }
    return list(found.values())


async def main() -> None:
    from playwright.async_api import async_playwright

    settings = Settings.load()
    existing = _load_existing()
    known = _known_group_ids()
    now = datetime.now(UTC).isoformat()
    discovered_new = 0

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.profile_dir), headless=True, viewport={"width": 1366, "height": 900}
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        for kw in KEYWORDS:
            try:
                results = await _search_keyword(page, kw)
            except Exception as exc:  # keep going on a bad keyword
                print(f"[warn] keyword '{kw}' failed: {exc}")
                continue
            for r in results:
                gid = r["group_id"]
                if gid in known:
                    continue  # already posting there
                if gid in existing:
                    existing[gid]["last_seen"] = now
                    if r.get("name") and not existing[gid].get("name"):
                        existing[gid]["name"] = r["name"]
                    continue
                r["first_seen"] = now
                r["last_seen"] = now
                existing[gid] = r
                discovered_new += 1
            print(f"keyword '{kw}': {len(results)} groups seen")
        await ctx.close()

    candidates = sorted(existing.values(), key=lambda c: c.get("first_seen", ""), reverse=True)
    CANDIDATES_JSON.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATES_JSON.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Facebook グループ候補（不動産・投資・富裕層系）",
        "",
        f"更新: {now}　／　新規 {discovered_new} 件　／　総候補 {len(candidates)} 件",
        "",
        "> 自動参加はしません（ban回避）。良いグループに手動で参加し、URLを groups.yaml に追加してください。",
        "",
        "| 名前 | メンバー | 公開/非公開 | URL | 検出キーワード |",
        "|------|----------|-------------|-----|----------------|",
    ]
    for c in candidates[:200]:
        lines.append(
            f"| {c.get('name','')} | {c.get('members','')} | {c.get('privacy','')} | {c['url']} | {c.get('keyword','')} |"
        )
    CANDIDATES_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"discovered {discovered_new} new candidates; total {len(candidates)}")
    print(f"written: {CANDIDATES_JSON}  and  {CANDIDATES_MD}")


if __name__ == "__main__":
    asyncio.run(main())
