"""Fail-closed automatic Messenger replies to NEW 1:1 property inquiries.

An initial run only arms a baseline. Historical drafts are NEVER auto-sent.
Each new incoming message gets at most one send attempt, persisted before click.
Uses the existing exact-recipient one-shot CLI, not a broad UI send loop.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
LEDGER = ROOT / "data" / "auto_reply_ledger.json"
STATUS = ROOT / "data" / "auto_reply_status.json"
DRIVE_STATUS = Path(r"G:\マイドライブ\AI_Agents\Private\FBGroupAutoposter\messenger_auto_reply_status.json")
KEYWORDS = ("物件", "不動産", "内見", "投資", "賃貸", "利回り", "アパート", "マンション", "土地", "収益ビル", "査定", "売却", "融資", "買付")
IGNORED = ("メッセージは復元されていません", "不在着信", "自動送信", "自動応答")
ONLY_INBOUND = re.compile(r"^\d+$")


def safe_save(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def parse_archive_time(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M JST").replace(tzinfo=JST)
    except (ValueError, TypeError, AttributeError):
        return None


def recent_inbox_timestamp(label: str) -> bool:
    """Require a definite relative time under 24h, not ambiguous 'yesterday'."""
    text = str(label).strip().lower()
    if text in {"今", "たった今", "now", "just now"}:
        return True
    if any(x in text for x in ("昨日", "先週", "週間", "日前", "ヶ月", "か月", "月前", "年前")):
        return False
    match = re.fullmatch(r"(\d+)\s*(秒|分|時間|seconds?|minutes?|hours?|m|h)(?:前| ago)?", text)
    if not match:
        return False
    count = int(match.group(1))
    unit = match.group(2)
    return count <= (23 if unit in ("時間", "hour", "hours", "h") else 1439)


def eligible_message(row: dict) -> bool:
    text = str(row.get("last_message") or "").strip()
    return bool(
        row.get("one_to_one_verified") is True
        and row.get("participant_count") == 1
        and row.get("is_group") is False
        and ONLY_INBOUND.fullmatch(str(row.get("thread_id") or ""))
        and text and any(kw in text for kw in KEYWORDS)
        and not any(no in text for no in IGNORED)
        and recent_inbox_timestamp(row.get("time_text", ""))
        and row.get("url") == f"https://www.messenger.com/t/{row.get('thread_id')}"
        and str(row.get("name") or "").strip()
    )


def run_pending(settings) -> dict:
    now = datetime.now(JST)
    if not LEDGER.exists():
        safe_save(LEDGER, {"armed_after": now.isoformat(), "attempts": {}})
        report = {"armed": True, "attempted": 0, "confirmed": 0,
                  "status": "baseline_saved_no_historical_send"}
        safe_save(STATUS, report)
        return report

    if os.getenv("MESSENGER_AUTO_SEND", "").strip().lower() not in {"true", "1"}:
        report = {"armed": True, "attempted": 0, "confirmed": 0, "status": "disabled"}
        safe_save(STATUS, report)
        return report

    data = json.loads(LEDGER.read_text(encoding="utf-8"))
    if not isinstance(data.get("attempts"), dict):
        raise RuntimeError("auto reply ledger corrupt: do not send")
    baseline = datetime.fromisoformat(str(data["armed_after"]))
    drafts_path = settings.data_dir / "drafts.json"
    archive_path = settings.data_dir / "drafts_archive.jsonl"
    if not drafts_path.exists() or not archive_path.exists():
        return {"armed": True, "attempted": 0, "confirmed": 0, "status": "waiting_for_drafts"}
    current = json.loads(drafts_path.read_text(encoding="utf-8")).get("drafts", [])
    by_id = {str(row.get("thread_id")): row for row in current if isinstance(row, dict)}
    attempted = 0
    confirmed = 0
    skipped = 0
    limit = min(3, max(1, int(os.getenv("MESSENGER_AUTO_SEND_MAX_DAILY", "3"))))
    today_count = sum(
        1 for v in data["attempts"].values()
        if str(v.get("created_at", "")).startswith(now.date().isoformat())
    )
    # The append-only archive guarantees a new inbound preview is processed once.
    for line in archive_path.read_text(encoding="utf-8").splitlines():
        if attempted >= limit or today_count >= limit:
            break
        try:
            row = json.loads(line)
            ts = parse_archive_time(row.get("checked_at", ""))
            if ts is None or ts <= baseline:
                continue
            key = hashlib.sha256(
                (str(row.get("thread_id")) + "\0" + str(row.get("last_message"))).encode("utf-8")
            ).hexdigest()
            if key in data["attempts"]:
                continue
            nowrow = by_id.get(str(row.get("thread_id")))
            if not nowrow or nowrow.get("last_message") != row.get("last_message"):
                skipped += 1
                continue
            # Never deliver legacy bot text or any low-cost draft that has not
            # passed the premium model's exact-input review.
            expected_sha = hashlib.sha256(
                (str(nowrow.get("name", "")) + "\0" +
                 str(nowrow.get("last_message", ""))).encode("utf-8")
            ).hexdigest()
            if (nowrow.get("review_status") != "approved"
                    or not any(m in str(nowrow.get("review_model", "")).lower()
                               for m in ("opus", "gpt-5.6-terra"))
                    or nowrow.get("review_message_sha256") != expected_sha
                    or not str(nowrow.get("draft", "")).strip()):
                skipped += 1
                continue
            if not eligible_message(row):
                skipped += 1
                continue
            # Never send two automated replies to one thread within 24 hours.
            if any(
                v.get("thread_id") == row.get("thread_id")
                and (now - datetime.fromisoformat(v["created_at"])).total_seconds() < 86400
                for v in data["attempts"].values()
            ):
                skipped += 1
                continue
            # Pre-commit before invoking any potentially consequential UI action.
            data["attempts"][key] = {
                "thread_id": row["thread_id"], "created_at": now.isoformat(),
                "state": "attempted_unconfirmed",
            }
            safe_save(LEDGER, data)
            attempted += 1
            today_count += 1
            command = [
                sys.executable, str(ROOT / "scripts" / "send_one_playwright_reply.py"),
                "--target-name", str(row["name"]), "--thread-id", str(row["thread_id"]),
                "--scan-limit", "30", "--send",
            ]
            try:
                proc = subprocess.run(
                    command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding="utf-8", text=True, timeout=100, check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                result = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
                if proc.returncode == 0 and result.get("sent") is True:
                    data["attempts"][key]["state"] = "confirmed_sent"
                    confirmed += 1
                else:
                    data["attempts"][key]["state"] = "blocked_or_uncertain_no_replay"
            except (OSError, ValueError, subprocess.TimeoutExpired):
                data["attempts"][key]["state"] = "blocked_or_uncertain_no_replay"
            safe_save(LEDGER, data)
        except (ValueError, TypeError, KeyError):
            skipped += 1
            continue
    report = {
        "checked_at": now.isoformat(), "armed": True, "attempted": attempted,
        "confirmed": confirmed, "skipped": skipped, "total_attempts": len(data["attempts"]),
        "status": "running" if os.getenv("MESSENGER_AUTO_SEND", "").lower() in {"true", "1"} else "dry_run",
    }
    safe_save(STATUS, report)
    try:
        safe_save(DRIVE_STATUS, report)
    except OSError:
        pass
    return report
