"""Conservative Facebook community growth manager.

Runs before the normal posting window and expands the usable community pool
without weakening any Facebook safety controls.

Daily policy:
- refresh already-joined groups;
- promote at most two already-joined, clearly real-estate groups;
- submit at most one *simple* join request to a high-fit group;
- never answer membership questions or bypass checkpoint/CAPTCHA/2FA;
- never touch Facebook while the posting pipeline owns the profile;
- respect the same durable CircuitManager used by the production poster;
- use the same headed Chrome BrowserContract as production posting.

Auto-promoted groups live in data/auto_groups.json and are merged by
config.load_groups(), so scheduled operation never dirties groups.yaml/Git.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings, load_groups  # noqa: E402
from scripts.discover_groups import CANDIDATES_JSON, _parse_member_count  # noqa: E402
from scripts.discover_joined_groups import OUT_JSON as JOINED_JSON, _scrape_joined  # noqa: E402
from src.browser_runtime import BrowserContract, build_launch_kwargs  # noqa: E402
from src.circuits import CircuitManager, FailureKind  # noqa: E402
from src.orchestrator import _pid_is_running  # noqa: E402
from src.queue_db import QueueDB  # noqa: E402
from src.session import classify_challenge, is_logged_in  # noqa: E402

GROUPS_YAML = ROOT / "groups.yaml"
AUTO_GROUPS_JSON = ROOT / "data" / "auto_groups.json"
STATE_JSON = ROOT / "data" / "community_manager_state.json"
REGISTER_SLO_TASKS = ROOT / "scripts" / "register_slo_tasks.ps1"

DEFAULT_PROMOTIONS_PER_DAY = 2
DEFAULT_JOIN_REQUESTS_PER_DAY = 1

_REAL_ESTATE_TERMS = (
    "不動産",
    "収益物件",
    "物件情報",
    "物件紹介",
    "物件共有",
    "不動産売買",
    "不動産投資",
    "不動産情報",
    "不動産ラウンジ",
    "不動産業者",
    "不動産関連",
)
_NAME_EXCLUDES = (
    "自動車", "トラック", "重機", "ダンプ", "クレーン", "農業機械", "車の部品", "パーツ",
    "暗号", "仮想通貨", "FX", "バイナリー", "競馬", "MLM", "恋人", "友達募集",
    "ファンクラブ", "同窓", "卒業", "ゲーム", "会員限定", "資格", "受験", "セミナー",
    "勉強会", "研修", "学校", "サロン", "部会", "出版", "応援グループ", "DIY",
    "遊ぶ会", "学ぶ会", "月収100万円", "問題山積", "ベトナム", "海外不動産", "沖縄",
    "とちぎ", "入居可能", "Q&A", "協会", "いいね！した友達", "いいね",
)
_PAGE_BLOCKERS = (
    "宣伝禁止", "広告禁止", "営業禁止", "勧誘禁止", "商用禁止", "物件掲載禁止",
    "業者お断り", "営業目的禁止", "外部リンク禁止", "広告・宣伝は禁止",
)
_COMPOSER_HINTS = ("テキストを入力", "投稿を作成", "ディスカッションを書く", "Write something", "Create post")
_JOIN_TEXTS = ("グループに参加", "参加をリクエスト", "Join group", "Join Group")
_PENDING_TEXTS = ("参加リクエストをキャンセル", "参加リクエスト済み", "リクエスト済み", "Cancel request")
_QUESTION_HINTS = ("参加に関する質問", "メンバーシップの質問", "質問に回答", "Membership questions")
_SELECTION_ORDERS = ("newest", "price_asc", "yield_desc", "price_desc")
_CHALLENGE_KINDS = {
    "checkpoint": FailureKind.CHECKPOINT,
    "captcha": FailureKind.CAPTCHA,
    "two_factor": FailureKind.TWO_FACTOR,
    "login": FailureKind.UNCLASSIFIED_LOGIN,
}


def _today_jst() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()


def _load_state() -> dict[str, Any]:
    data: dict[str, Any] = {}
    if STATE_JSON.exists():
        try:
            raw = json.loads(STATE_JSON.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except Exception:
            data = {}
    history = data.get("join_history", []) if isinstance(data.get("join_history", []), list) else []
    if data.get("date") != _today_jst():
        return {"date": _today_jst(), "promoted": [], "join_attempts": [], "join_history": history[-500:]}
    data.setdefault("promoted", [])
    data.setdefault("join_attempts", [])
    data.setdefault("join_history", history[-500:])
    return data


def _save_state(state: dict[str, Any]) -> None:
    STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
    STATE_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _pipeline_busy(lock_path: Path) -> tuple[bool, str]:
    if not lock_path.exists():
        return False, ""
    try:
        pid = int(lock_path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return True, "pipeline lock unreadable"
    if pid and _pid_is_running(pid):
        return True, f"posting pipeline active pid={pid}"
    return False, "dead-owner pipeline lock present"


def _manual_group_ids() -> set[str]:
    try:
        data = yaml.safe_load(GROUPS_YAML.read_text(encoding="utf-8")) or {}
        return {str(group.get("id")) for group in data.get("groups", []) if isinstance(group, dict) and group.get("id")}
    except Exception:
        return set()


def _load_auto_groups() -> list[dict[str, Any]]:
    if not AUTO_GROUPS_JSON.exists():
        return []
    try:
        data = json.loads(AUTO_GROUPS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = data.get("groups", []) if isinstance(data, dict) else data
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _known_group_ids() -> set[str]:
    return _manual_group_ids() | {str(group.get("id")) for group in _load_auto_groups() if group.get("id")}


def _strict_name_fit(name: str) -> bool:
    text = (name or "").strip()
    return bool(text) and any(term in text for term in _REAL_ESTATE_TERMS) and not any(blocked in text for blocked in _NAME_EXCLUDES)


def _promotion_score(name: str) -> int:
    text = name or ""
    score = sum(50 for term in ("物件情報", "物件紹介", "物件共有", "不動産売買", "収益物件") if term in text)
    score += sum(30 for term in ("不動産ラウンジ", "不動産投資情報", "不動産情報", "不動産関連業者") if term in text)
    if "不動産投資" in text:
        score += 10
    return score


def _joined_strict_candidates(joined: list[dict[str, Any]], known: set[str]) -> list[dict[str, Any]]:
    rows = [group for group in joined if str(group.get("group_id", "")) not in known and group.get("property_friendly") and group.get("category") == "不動産コア" and _strict_name_fit(str(group.get("name", "")))]
    return sorted(rows, key=lambda group: (-_promotion_score(str(group.get("name", ""))), str(group.get("name", "")), str(group.get("group_id", ""))))


def _selection_order(group_id: str) -> str:
    try:
        index = int(group_id) % len(_SELECTION_ORDERS)
    except ValueError:
        index = sum(ord(char) for char in group_id) % len(_SELECTION_ORDERS)
    return _SELECTION_ORDERS[index]


def _save_auto_group(group: dict[str, Any]) -> bool:
    gid = str(group["group_id"])
    rows = _load_auto_groups()
    if gid in _known_group_ids():
        return False
    rows.append({"id": gid, "name": str(group.get("name") or f"Facebook Group {gid}"), "post_url": f"https://www.facebook.com/groups/{gid}", "selection_order": _selection_order(gid), "enabled": True})
    AUTO_GROUPS_JSON.parent.mkdir(parents=True, exist_ok=True)
    AUTO_GROUPS_JSON.write_text(json.dumps({"updated_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), "groups": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def _load_search_candidates(known: set[str], joined_ids: set[str], attempted_ids: set[str]) -> list[dict[str, Any]]:
    if not CANDIDATES_JSON.exists():
        return []
    try:
        rows = json.loads(CANDIDATES_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []
    candidates: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        gid = str(row.get("group_id", ""))
        if not gid or gid in known or gid in joined_ids or gid in attempted_ids:
            continue
        if row.get("category") not in {"不動産投資（コア）", "物件・売買情報"} or not _strict_name_fit(str(row.get("name", ""))):
            continue
        candidates.append(row)
    return sorted(candidates, key=lambda row: (-_promotion_score(str(row.get("name", ""))), -_parse_member_count(str(row.get("members", ""))), str(row.get("name", ""))))


def _record_challenge(circuits: CircuitManager, challenge: str | None, environment: str) -> None:
    if challenge:
        circuits.record_failure(_CHALLENGE_KINDS.get(challenge, FailureKind.UNCLASSIFIED_LOGIN), environment=environment, metadata={"source": "community_manager"})


def _ensure_slo_tasks() -> dict[str, Any]:
    if not REGISTER_SLO_TASKS.exists() or sys.platform != "win32":
        return {"configured": False, "reason": "registration script unavailable"}
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    try:
        proc = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File", str(REGISTER_SLO_TASKS)], cwd=str(ROOT), capture_output=True, text=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
        return {"configured": proc.returncode == 0, "returncode": proc.returncode}
    except Exception as exc:
        return {"configured": False, "reason": f"{type(exc).__name__}: {exc}"}


async def _page_text(page: Any) -> str:
    try:
        return await page.inner_text("body")
    except Exception:
        return ""


async def _refresh_joined(page: Any, known: set[str]) -> list[dict[str, Any]]:
    joined = await _scrape_joined(page)
    enabled_ids = {str(group["id"]) for group in load_groups()}
    for group in joined:
        gid = str(group.get("group_id", ""))
        group["in_groups_yaml"] = gid in known
        group["enabled_in_yaml"] = gid in enabled_ids
    JOINED_JSON.parent.mkdir(parents=True, exist_ok=True)
    JOINED_JSON.write_text(json.dumps({"checked_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), "logged_in": True, "groups": joined}, ensure_ascii=False, indent=2), encoding="utf-8")
    return joined


async def _probe_promotable(page: Any, group: dict[str, Any]) -> tuple[bool, str]:
    await page.goto(str(group.get("url") or f"https://www.facebook.com/groups/{group['group_id']}"), wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3500)
    challenge = await classify_challenge(page)
    if challenge:
        return False, f"challenge:{challenge}"
    body = await _page_text(page)
    if any(blocker in body for blocker in _PAGE_BLOCKERS):
        return False, "promotion/rule blocker detected"
    if any(hint in body for hint in _COMPOSER_HINTS):
        return True, "composer present"
    if any(hint in body for hint in _JOIN_TEXTS):
        return False, "not currently joined"
    return False, "composer not confirmed"


async def _submit_one_simple_join(page: Any, candidate: dict[str, Any]) -> tuple[bool, str]:
    await page.goto(str(candidate["url"]), wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3500)
    challenge = await classify_challenge(page)
    if challenge:
        return False, f"challenge:{challenge}"
    body = await _page_text(page)
    if any(blocker in body for blocker in _PAGE_BLOCKERS):
        return False, "promotion/rule blocker detected"
    if any(text in body for text in _PENDING_TEXTS):
        return False, "already pending"
    if any(text in body for text in _COMPOSER_HINTS):
        return False, "already joined"
    button = None
    for label in _JOIN_TEXTS:
        locator = page.get_by_role("button", name=label, exact=True)
        try:
            if await locator.count() and await locator.first.is_visible():
                button = locator.first
                break
        except Exception:
            continue
    if button is None:
        return False, "simple join button not found"
    await button.click(timeout=10000)
    await page.wait_for_timeout(2500)
    challenge = await classify_challenge(page)
    if challenge:
        return False, f"challenge:{challenge}"
    try:
        dialogs = page.locator('[role="dialog"]')
        if await dialogs.count():
            dialog_text = await dialogs.first.inner_text()
            question_fields = await dialogs.first.locator("textarea, input[type='text']").count()
            if question_fields or any(hint in dialog_text for hint in _QUESTION_HINTS):
                await page.keyboard.press("Escape")
                return False, "membership questions require manual review"
    except Exception:
        pass
    body = await _page_text(page)
    if any(text in body for text in _PENDING_TEXTS):
        return True, "join request submitted"
    if any(text in body for text in _COMPOSER_HINTS):
        return True, "joined immediately"
    return False, "join outcome not confirmed"


async def main_async() -> dict[str, Any]:
    settings = Settings.load()
    db = QueueDB(settings.db_path)
    circuits = CircuitManager(db)
    environment = str(getattr(settings, "runtime_environment", "default"))
    result: dict[str, Any] = {"ok": True, "date": _today_jst(), "promoted": [], "join": None, "task_bootstrap": _ensure_slo_tasks()}
    blocking = circuits.blocking_circuit(environment=environment)
    if blocking:
        result.update({"skipped": True, "reason": f"safety circuit: {blocking.get('reason')}"})
        print(json.dumps(result, ensure_ascii=False))
        return result
    busy, reason = _pipeline_busy(Path(settings.db_path).with_name("pipeline.lock"))
    if busy:
        result.update({"skipped": True, "reason": reason})
        print(json.dumps(result, ensure_ascii=False))
        return result
    promotions_per_day = max(0, int(os.getenv("COMMUNITY_PROMOTIONS_PER_DAY", str(DEFAULT_PROMOTIONS_PER_DAY))))
    joins_per_day = max(0, int(os.getenv("COMMUNITY_JOIN_REQUESTS_PER_DAY", str(DEFAULT_JOIN_REQUESTS_PER_DAY))))
    state = _load_state()
    known = _known_group_ids()
    from playwright.async_api import async_playwright
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(**build_launch_kwargs(BrowserContract.from_settings(settings)))
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)
        challenge = await classify_challenge(page)
        if challenge:
            _record_challenge(circuits, challenge, environment)
            result.update({"ok": False, "reason": f"challenge:{challenge}"})
            await context.close(); _save_state(state); print(json.dumps(result, ensure_ascii=False)); return result
        if not await is_logged_in(page):
            circuits.record_failure(FailureKind.SESSION_EXPIRED, environment=environment, metadata={"source": "community_manager"})
            result.update({"ok": False, "reason": "facebook session not logged in"})
            await context.close(); _save_state(state); print(json.dumps(result, ensure_ascii=False)); return result
        joined = await _refresh_joined(page, known)
        strict_pool = _joined_strict_candidates(joined, known)
        remaining_promotions = max(0, promotions_per_day - len(state.get("promoted", [])))
        for group in strict_pool:
            if remaining_promotions <= 0: break
            promotable, why = await _probe_promotable(page, group)
            if why.startswith("challenge:"):
                challenge = why.split(":", 1)[1]; _record_challenge(circuits, challenge, environment); result.update({"ok": False, "reason": why}); break
            if promotable and _save_auto_group(group):
                gid = str(group["group_id"]); item = {"group_id": gid, "name": group.get("name", ""), "reason": why}
                state.setdefault("promoted", []).append(item); result["promoted"].append(item); known.add(gid); remaining_promotions -= 1
        attempts_today = state.get("join_attempts", []); history = state.get("join_history", [])
        if result["ok"] and len(attempts_today) < joins_per_day:
            attempted_ids = {str(item.get("group_id", "")) for item in [*attempts_today, *history] if isinstance(item, dict)}
            joined_ids = {str(group.get("group_id", "")) for group in joined}
            candidates = _load_search_candidates(known, joined_ids, attempted_ids)
            if candidates:
                candidate = candidates[0]; submitted, why = await _submit_one_simple_join(page, candidate)
                entry = {"at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), "group_id": str(candidate.get("group_id", "")), "name": candidate.get("name", ""), "submitted": submitted, "reason": why}
                state.setdefault("join_attempts", []).append(entry); state.setdefault("join_history", []).append(entry); state["join_history"] = state["join_history"][-500:]; result["join"] = entry
                if why.startswith("challenge:"):
                    challenge = why.split(":", 1)[1]; _record_challenge(circuits, challenge, environment); result.update({"ok": False, "reason": why})
                elif submitted and why == "joined immediately":
                    promoted = {"group_id": str(candidate.get("group_id", "")), "name": candidate.get("name", "")}
                    if _save_auto_group(promoted): result["promoted"].append({**promoted, "reason": "joined immediately"})
            else:
                result["join"] = {"submitted": False, "reason": "no unused safe candidate"}
        await context.close()
    _save_state(state)
    if result["promoted"]:
        try:
            from scripts.build_group_registry import build_registry
            from scripts.sync_groups_web import sync_groups_web
            result["registry"] = build_registry()["summary"]; result["web_sync"] = sync_groups_web()
        except Exception as exc:
            result["registry_error"] = f"{type(exc).__name__}: {exc}"
    result["strict_joined_unused"] = len(_joined_strict_candidates(joined, _known_group_ids()))
    print(json.dumps(result, ensure_ascii=False, indent=2)); return result


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
