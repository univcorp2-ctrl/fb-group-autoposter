"""One-shot production recovery for the Facebook property autoposter.

The script is marker-controlled and intentionally conservative:
1) atomically consumes data/recovery_once.flag (no automatic rerun),
2) runs focused regression tests,
3) re-registers Task Scheduler with the repaired long posting limit,
4) verifies the Facebook session without bypassing any challenge,
5) submits at most ONE already-approved property through FacebookPoster,
6) syncs EstateBoard only when a real permalink-confirmed post is recorded.

It never weakens rate limits, CAPTCHA/checkpoint handling, freshness, duplicate,
or permalink verification safeguards.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings, load_groups  # noqa: E402
from scripts.keepalive import check_and_warm  # noqa: E402
from src.approval import TelegramApproval  # noqa: E402
from src.freshness import build_checker  # noqa: E402
from src.logging_setup import setup_logging  # noqa: E402
from src.orchestrator import pipeline_lock  # noqa: E402
from src.poster import FacebookPoster  # noqa: E402
from src.queue_db import QueueDB  # noqa: E402

FLAG = ROOT / "data" / "recovery_once.flag"
RUNNING = ROOT / "data" / "recovery_once.running"
RESULT = ROOT / "logs" / "recovery_once_result.json"
PREFERRED_PROPERTY_ID = "eb-24801"


def write_result(payload: dict[str, Any]) -> None:
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated_at": datetime.now(UTC).isoformat(), **payload}
    RESULT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def consume_marker() -> bool:
    FLAG.parent.mkdir(parents=True, exist_ok=True)
    if not FLAG.exists():
        return False
    try:
        os.replace(FLAG, RUNNING)
    except FileNotFoundError:
        return False
    return True


def run_checked(argv: list[str], *, timeout: int) -> dict[str, Any]:
    proc = subprocess.run(
        argv,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout[-6000:],
        "stderr": proc.stderr[-6000:],
    }


def register_tasks() -> dict[str, Any]:
    ps = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    script = ROOT / "scripts" / "install_windows_tasks.ps1"
    result = run_checked(
        [
            ps,
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        timeout=180,
    )
    if result["returncode"] != 0:
        raise RuntimeError(f"scheduled task registration failed: {result['stderr'][-1000:]}")
    return result


def run_focused_tests() -> dict[str, Any]:
    result = run_checked(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_orchestrator_lock.py",
            "tests/test_protection_compatibility.py",
            "tests/test_recovery_acceptance_contract.py",
        ],
        timeout=180,
    )
    if result["returncode"] != 0:
        raise RuntimeError(f"focused tests failed: {result['stdout'][-1500:]} {result['stderr'][-1500:]}")
    return result


def choose_job(db: QueueDB, poster: FacebookPoster, groups: list[dict[str, Any]]) -> dict[str, Any] | None:
    groups_by_id = {str(g["id"]): g for g in groups}
    jobs = list(db.approved_jobs())
    preferred = [j for j in jobs if j.get("property_id") == PREFERRED_PROPERTY_ID]
    ordered = list(reversed(preferred)) + [j for j in reversed(jobs) if j.get("property_id") != PREFERRED_PROPERTY_ID]
    for job in ordered:
        targets = db.unposted_targets(job["job_id"])
        if len(targets) != 1:
            continue
        target = targets[0]
        group = groups_by_id.get(str(target["group_id"]))
        if not group:
            continue
        if poster._preflight_target(job, target, group) is None:  # existing production guard, read-only check
            return job
    return None


async def post_one_verified_candidate(settings: Settings) -> dict[str, Any]:
    groups = load_groups()
    db = QueueDB(settings.db_path)
    notifier = TelegramApproval(settings, db)
    poster = FacebookPoster(
        settings,
        db,
        groups,
        notifier,
        freshness_checker=build_checker(settings.estateboard_source),
    )

    with pipeline_lock():
        if hasattr(db, "recover_incomplete_attempts"):
            db.recover_incomplete_attempts()
        db.reset_stale_posting_jobs()
        before = db.count_posts_today()
        if before >= settings.max_posts_per_day:
            return {"posted": False, "reason": "daily_limit_already_reached", "count_before": before}
        job = choose_job(db, poster, groups)
        if job is None:
            return {"posted": False, "reason": "no_preflight_eligible_approved_job", "count_before": before}
        job_id = job["job_id"]
        property_id = job["property_id"]
        status = await poster.post_job(job)
        targets = db.get_targets(job_id)
        after = db.count_posts_today()
        verified = [t for t in targets if t.get("status") == "posted" and t.get("permalink")]
        uncertain = [t for t in targets if t.get("status") == "uncertain"]
        return {
            "posted": bool(verified),
            "job_status": status,
            "job_id": job_id,
            "property_id": property_id,
            "count_before": before,
            "count_after": after,
            "verified": [
                {"group_id": t.get("group_id"), "permalink": t.get("permalink")}
                for t in verified
            ],
            "uncertain": [
                {"group_id": t.get("group_id"), "last_error": t.get("last_error")}
                for t in uncertain
            ],
            "targets": [
                {"group_id": t.get("group_id"), "status": t.get("status"), "last_error": t.get("last_error"), "permalink": t.get("permalink")}
                for t in targets
            ],
        }


async def main_async() -> int:
    setup_logging()
    if not consume_marker():
        return 0
    result: dict[str, Any] = {"phase": "starting"}
    write_result(result)
    try:
        tests = run_focused_tests()
        result["tests"] = {"returncode": tests["returncode"], "stdout": tests["stdout"][-2000:]}
        result["phase"] = "tests_passed"
        write_result(result)

        registration = register_tasks()
        result["task_registration"] = {"returncode": registration["returncode"], "stdout": registration["stdout"][-2500:]}
        result["phase"] = "tasks_registered"
        write_result(result)

        settings = Settings.load()
        settings.validate_runtime(require_external=True)
        session = await check_and_warm(settings)
        result["session"] = {
            "healthy": bool(session.get("healthy")),
            "challenge": session.get("challenge"),
            "detail": session.get("detail"),
        }
        if not session.get("healthy"):
            result["phase"] = "session_unhealthy_stop"
            write_result(result)
            return 2

        result["phase"] = "session_healthy"
        write_result(result)
        post = await post_one_verified_candidate(settings)
        result["post"] = post
        result["phase"] = "post_attempt_finished"
        write_result(result)

        if post.get("posted"):
            from scripts.sync_estateboard_status import sync_estateboard_status

            sync = sync_estateboard_status(settings.db_path)
            result["estateboard_sync"] = sync
            result["phase"] = "success_verified_and_synced"
            write_result(result)
            return 0
        if post.get("uncertain"):
            result["phase"] = "submitted_but_unverified_stop_no_retry"
            write_result(result)
            return 3
        result["phase"] = "no_verified_post_stop"
        write_result(result)
        return 4
    except Exception as exc:  # noqa: BLE001 - one-shot must persist diagnostics and never auto-retry
        result["phase"] = "failed_stop_no_retry"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()[-6000:]
        write_result(result)
        return 1
    finally:
        RUNNING.unlink(missing_ok=True)


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
