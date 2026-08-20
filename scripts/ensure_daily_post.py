"""Final daily posting safety net.

Runs late in the normal Facebook active window. It does nothing when at least
one permalink-confirmed post already exists for the current JST day. Otherwise
it invokes the normal production pipeline with MAX_POSTS_PER_DAY=1, so every
existing session, active-hours, freshness, duplicate, circuit, challenge and
permalink-verification guard remains authoritative.

The safety net never retries after an uncertain/clicked submission and performs
at most two pre-submit attempts per JST day. A global/environment safety circuit
also blocks the attempt. On success it immediately re-syncs EstateBoard.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from scripts.sync_estateboard_status import sync_estateboard_status  # noqa: E402
from src.circuits import CircuitManager  # noqa: E402
from src.orchestrator import _pid_is_running  # noqa: E402
from src.queue_db import QueueDB  # noqa: E402

STATE_PATH = ROOT / "data" / "daily_guarantee_state.json"
MAX_PRESUBMIT_ATTEMPTS = 2


def _today() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"date": _today(), "attempts": 0}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    if state.get("date") != _today():
        return {"date": _today(), "attempts": 0}
    return state


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _live_pipeline_owner(lock_path: Path) -> int | None:
    if not lock_path.exists():
        return None
    try:
        pid = int(lock_path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return -1
    return pid if pid and _pid_is_running(pid) else None


def _has_uncertain_today(db: QueueDB) -> bool:
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM job_targets t JOIN jobs j ON j.job_id=t.job_id
            WHERE t.status='uncertain'
              AND date(datetime(COALESCE(t.posted_at,j.updated_at), '+9 hours'))=date('now','+9 hours')
            """
        ).fetchone()
        if row and int(row["n"]) > 0:
            return True
        attempt = conn.execute(
            """
            SELECT COUNT(*) AS n FROM submission_attempts
            WHERE click_started_at IS NOT NULL
              AND completed_at IS NULL
              AND date(datetime(click_started_at, '+9 hours'))=date('now','+9 hours')
            """
        ).fetchone()
        return bool(attempt and int(attempt["n"]) > 0)


def main() -> int:
    settings = Settings.load()
    db = QueueDB(settings.db_path)
    state = _load_state()

    if db.count_posts_today() >= 1:
        state.update(
            {
                "status": "already_posted",
                "last_sync": sync_estateboard_status(settings.db_path),
            }
        )
        _save_state(state)
        print(json.dumps(state, ensure_ascii=False))
        return 0

    circuit = CircuitManager(db).blocking_circuit(
        environment=str(getattr(settings, "runtime_environment", "default"))
    )
    if circuit:
        state.update(
            {
                "status": "blocked_by_safety_circuit",
                "reason": circuit.get("reason"),
            }
        )
        _save_state(state)
        print(json.dumps(state, ensure_ascii=False))
        return 0

    if _has_uncertain_today(db):
        state.update({"status": "uncertain_submission_exists_no_retry"})
        _save_state(state)
        print(json.dumps(state, ensure_ascii=False))
        return 0

    owner = _live_pipeline_owner(Path(settings.db_path).with_name("pipeline.lock"))
    if owner is not None:
        state.update({"status": "pipeline_busy", "owner_pid": owner})
        _save_state(state)
        print(json.dumps(state, ensure_ascii=False))
        return 0

    attempts = int(state.get("attempts", 0))
    if attempts >= MAX_PRESUBMIT_ATTEMPTS:
        state.update({"status": "attempt_limit_reached"})
        _save_state(state)
        print(json.dumps(state, ensure_ascii=False))
        return 0

    state["attempts"] = attempts + 1
    state["status"] = "attempting"
    _save_state(state)

    env = os.environ.copy()
    env["MAX_POSTS_PER_DAY"] = "1"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_daily.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=20 * 60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )

    posted = db.count_posts_today()
    state["pipeline_returncode"] = proc.returncode
    if posted >= 1:
        state["status"] = "verified_post_created"
        state["last_sync"] = sync_estateboard_status(settings.db_path)
        _save_state(state)
        print(json.dumps(state, ensure_ascii=False))
        return 0

    state["status"] = "no_verified_post"
    state["stderr_tail"] = (proc.stderr or "")[-1000:]
    _save_state(state)
    print(json.dumps(state, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
