"""Discover candidate Facebook groups for real-estate / investor audiences.

Read-only: it searches Facebook Groups for a set of keywords using the
logged-in session, collects candidate groups (name, URL, member text, privacy),
de-duplicates against groups.yaml and previously discovered candidates, and
writes:
  - data/group_candidates.json  (machine-readable, accumulates over time)
  - data/group_candidates.md     (human review list, newest first)

This script itself is read-only. To minimize Facebook account risk it uses the
same headed Chrome identity as production and searches only a small rotating
subset of keywords each day. Scheduled membership growth is handled by
scripts/community_manager.py, which may submit at most one simple no-question
join request per JST day. Neither path answers membership questions nor bypasses
Facebook challenges.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings, load_groups
from src.browser_runtime import BrowserContract, build_launch_kwargs
from src.circuits import CircuitManager, FailureKind
from src.orchestrator import _pid_is_running
from src.queue_db import QueueDB
from src.session import classify_challenge, is_logged_in

# Keywords grouped by AUDIENCE CATEGORY, so each candidate carries a category we
# can reason about when proposing it. Categories cover the core real-estate
# audience PLUS adjacent communities where property posts OR other distribution
# (e.g. the LINE 未公開物件 channel) would be welcome.
KEYWORD_CATEGORIES: dict[str, list[str]] = {
    "不動産投資（コア）": [
        "不動産投資", "収益物件", "一棟 収益", "不動産投資家",
        "不動産オーナー", "大家 交流", "資産運用 不動産", "区分マンション 投資",
    ],
    "投資・資産形成（隣接）": [
        "投資家 交流", "資産形成", "FIRE 投資", "副業 投資", "資産運用",
    ],
    "富裕層・経営者（別件配信もOK）": [
        "富裕層 投資", "経営者 交流", "社長 交流", "起業家 交流", "ドクター 投資",
    ],
    "物件・売買情報": [
        "不動産 売買", "物件情報 共有", "不動産 情報交換",
    ],
}
# Why each category is a fit — shown in the daily proposal so the operator can
# decide quickly.
CATEGORY_RATIONALE: dict[str, str] = {
    "不動産投資（コア）": "本業の収益物件投稿に最適。最優先で参加検討。",
    "投資・資産形成（隣接）": "投資家層が濃く、物件投稿＋LINE配信の導線が刺さりやすい。",
    "富裕層・経営者（別件配信もOK）": "購買力が高く、不動産以外の配信(LINE未公開物件等)も歓迎されやすい。",
    "物件・売買情報": "物件情報の共有が前提の場なので投稿が自然になじむ。",
}
_KEYWORD_TO_CATEGORY = {kw: cat for cat, kws in KEYWORD_CATEGORIES.items() for kw in kws}
KEYWORDS = list(_KEYWORD_TO_CATEGORY.keys())
DISCOVERY_KEYWORDS_PER_DAY = 3


def _today_keywords() -> list[str]:
    """Rotate a bounded subset so discovery grows without search bursts."""
    if not KEYWORDS:
        return []
    ordinal = datetime.now(ZoneInfo("Asia/Tokyo")).date().toordinal()
    count = min(DISCOVERY_KEYWORDS_PER_DAY, len(KEYWORDS))
    start = (ordinal * count) % len(KEYWORDS)
    return [KEYWORDS[(start + offset) % len(KEYWORDS)] for offset in range(count)]


def _pipeline_busy(lock_path: Path) -> bool:
    if not lock_path.exists():
        return False
    try:
        pid = int(lock_path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return True
    return bool(pid and _pid_is_running(pid))

CANDIDATES_JSON = ROOT / "data" / "group_candidates.json"
CANDIDATES_MD = ROOT / "data" / "group_candidates.md"
GROUP_ID_RE = re.compile(r"/groups/(\d+)")


def _parse_member_count(text: str) -> int:
    """Best-effort parse of a members string ('1.2万人のメンバー', '3,456 members')
    into an int for ranking. Returns 0 when unknown."""
    if not text:
        return 0
    import re as _re

    m = _re.search(r"([\d.,]+)\s*万", text)
    if m:
        try:
            return int(float(m.group(1).replace(",", "")) * 10000)
        except ValueError:
            return 0
    m = _re.search(r"([\d,]{2,})", text)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return 0
    return 0


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
    challenge = await classify_challenge(page)
    if challenge:
        raise RuntimeError(f"facebook_challenge:{challenge}")
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
            "category": _KEYWORD_TO_CATEGORY.get(keyword, "その他"),
        }
    return list(found.values())


async def main() -> None:
    from playwright.async_api import async_playwright

    settings = Settings.load()
    db = QueueDB(settings.db_path)
    circuits = CircuitManager(db)
    environment = str(getattr(settings, "runtime_environment", "default"))
    blocking = circuits.blocking_circuit(environment=environment)
    if blocking:
        print(f"[skip] safety circuit open: {blocking.get('reason')}")
        return
    if _pipeline_busy(Path(settings.db_path).with_name("pipeline.lock")):
        print("[skip] posting pipeline is active")
        return

    existing = _load_existing()
    known = _known_group_ids()
    now = datetime.now(UTC).isoformat()
    discovered_new = 0
    new_candidates: list[dict] = []
    keywords = _today_keywords()

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            **build_launch_kwargs(BrowserContract.from_settings(settings))
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)
        challenge = await classify_challenge(page)
        if challenge:
            kind = {
                "checkpoint": FailureKind.CHECKPOINT,
                "captcha": FailureKind.CAPTCHA,
                "two_factor": FailureKind.TWO_FACTOR,
                "login": FailureKind.UNCLASSIFIED_LOGIN,
            }.get(challenge, FailureKind.UNCLASSIFIED_LOGIN)
            circuits.record_failure(kind, environment=environment, metadata={"source": "discover_groups"})
            print(f"[stop] Facebook challenge: {challenge}")
            await ctx.close()
            return
        if not await is_logged_in(page):
            circuits.record_failure(
                FailureKind.SESSION_EXPIRED,
                environment=environment,
                metadata={"source": "discover_groups"},
            )
            print("[stop] Facebook session is not logged in")
            await ctx.close()
            return

        for kw in keywords:
            try:
                results = await _search_keyword(page, kw)
            except Exception as exc:
                text = str(exc)
                if text.startswith("facebook_challenge:"):
                    challenge = text.split(":", 1)[1]
                    kind = {
                        "checkpoint": FailureKind.CHECKPOINT,
                        "captcha": FailureKind.CAPTCHA,
                        "two_factor": FailureKind.TWO_FACTOR,
                        "login": FailureKind.UNCLASSIFIED_LOGIN,
                    }.get(challenge, FailureKind.UNCLASSIFIED_LOGIN)
                    circuits.record_failure(
                        kind,
                        environment=environment,
                        metadata={"source": "discover_groups"},
                    )
                    print(f"[stop] Facebook challenge during discovery: {challenge}")
                    break
                print(f"[warn] keyword '{kw}' failed: {exc}")
                continue
            for row in results:
                gid = row["group_id"]
                if gid in known:
                    continue
                if gid in existing:
                    existing[gid]["last_seen"] = now
                    if row.get("name") and not existing[gid].get("name"):
                        existing[gid]["name"] = row["name"]
                    continue
                row["first_seen"] = now
                row["last_seen"] = now
                existing[gid] = row
                new_candidates.append(row)
                discovered_new += 1
            print(f"keyword '{kw}': {len(results)} groups seen")
        await ctx.close()

    candidates = sorted(
        existing.values(),
        key=lambda candidate: candidate.get("first_seen", ""),
        reverse=True,
    )
    CANDIDATES_JSON.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATES_JSON.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Facebook グループ候補（不動産・投資・富裕層系）",
        "",
        f"更新: {now}　／　新規 {discovered_new} 件　／　総候補 {len(candidates)} 件",
        "",
        "> 参加済みの良質グループを優先利用しつつ、CommunityManager が安全候補へ1日最大1件だけ単純参加申請を行います。参加質問やcheckpoint/CAPTCHA/2FAが出た場合は申請しません。",
        "",
        "| カテゴリ | 名前 | メンバー | 公開/非公開 | URL | 検出キーワード |",
        "|----------|------|----------|-------------|-----|----------------|",
    ]
    ranked = sorted(
        candidates,
        key=lambda candidate: _parse_member_count(candidate.get("members", "")),
        reverse=True,
    )
    for candidate in ranked[:200]:
        lines.append(
            f"| {candidate.get('category','')} | {candidate.get('name','')} | "
            f"{candidate.get('members','')} | {candidate.get('privacy','')} | "
            f"{candidate['url']} | {candidate.get('keyword','')} |"
        )
    CANDIDATES_MD.write_text("\n".join(lines), encoding="utf-8")
    print(
        f"discovered {discovered_new} new candidates from {len(keywords)} bounded searches; "
        f"total {len(candidates)}"
    )

    if new_candidates:
        _notify_new_candidates(settings, new_candidates)


def _notify_new_candidates(settings: Settings, new_candidates: list[dict]) -> None:
    """Send a thoughtful daily PROPOSAL of where to post next.

    Groups candidates by audience category, ranks each by member count, leads
    with the best 3 picks (with reasoning), and explains which kind of content
    fits each category (property posts vs other distribution). Membership
    growth itself is governed by CommunityManager's strict daily limits."""
    try:
        from src.approval import TelegramApproval
        from src.queue_db import QueueDB

        notifier = TelegramApproval(settings, QueueDB(settings.db_path))
        if not getattr(notifier, "enabled", False):
            return

        ranked = sorted(new_candidates, key=lambda c: _parse_member_count(c.get("members", "")), reverse=True)
        lines = [
            f"🔎 今日のコミュニティ提案：投稿できそうな新規グループ {len(new_candidates)}件",
            "（参加済み候補を優先しつつ、安全候補へ1日最大1件だけ単純参加申請。質問・checkpoint等では停止）",
            "",
            "⭐ おすすめ参加先 TOP3:",
        ]
        for c in ranked[:3]:
            mem = f"（{c['members']}）" if c.get("members") else ""
            note = CATEGORY_RATIONALE.get(c.get("category", ""), "")
            lines.append(f"・{c.get('name') or c['group_id']}{mem}\n　{c['url']}\n　▶ {c.get('category','')}：{note}")

        by_cat: dict[str, list[dict]] = {}
        for c in ranked:
            by_cat.setdefault(c.get("category", "その他"), []).append(c)
        for cat, items in by_cat.items():
            lines.append("")
            lines.append(f"■ {cat}（{len(items)}件）— {CATEGORY_RATIONALE.get(cat,'')}")
            for c in items[:5]:
                mem = f"／{c['members']}" if c.get("members") else ""
                lines.append(f"・{c.get('name') or c['group_id']}{mem}\n　{c['url']}")
            if len(items) > 5:
                lines.append(f"　…ほか{len(items)-5}件")
        lines.append("\n全件は data/group_candidates.md を参照。")
        notifier.send_message("\n".join(lines))
    except Exception as exc:  # noqa: BLE001 - discovery notice must never crash the run
        print(f"[warn] candidate notification skipped: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
