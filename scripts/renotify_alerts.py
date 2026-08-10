"""Re-notify unacknowledged alerts until the operator confirms them.

Some failures (dead FB login, checkpoint/captcha/2FA) cannot be fixed by a
retry — they need a human re-login. A single Telegram ping is easy to miss, so
those are recorded as persistent alerts (see src/alerts.py). This script, run
frequently by the scheduler, keeps the operator informed until they act.

A marker-controlled production recovery hook is intentionally kept here because
this task already runs every 30 minutes in the interactive user session.  It is
a no-op unless data/recovery_once.flag exists; the recovery script atomically
consumes that marker before doing anything, so it can never run twice.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from src.approval import TelegramApproval  # noqa: E402
from src.logging_setup import setup_logging  # noqa: E402
from src.queue_db import QueueDB  # noqa: E402

log = logging.getLogger("renotify_alerts")


def renotify(settings: Settings) -> dict[str, int]:
    db = QueueDB(settings.db_path)
    notifier = TelegramApproval(settings, db)
    acked = notifier.poll_once() if notifier.has_pending_alerts() else 0
    resent = notifier.renotify_pending()
    return {"acks_processed": acked, "alerts_resent": resent}


def run_marker_controlled_recovery() -> dict[str, object] | None:
    flag = ROOT / "data" / "recovery_once.flag"
    if not flag.exists():
        return None
    script = ROOT / "scripts" / "recovery_once.py"
    if not script.exists():
        log.error("recovery marker exists but script is missing: %s", script)
        return {"started": False, "error": "recovery_script_missing"}
    python = Path(sys.executable)
    try:
        proc = subprocess.run(
            [str(python), str(script)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=9 * 60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.error("recovery_once timed out; marker is consumed by child to prevent automatic re-post")
        return {"started": True, "returncode": None, "error": "timeout"}
    if proc.stdout:
        log.info("recovery_once stdout: %s", proc.stdout[-4000:])
    if proc.stderr:
        log.warning("recovery_once stderr: %s", proc.stderr[-4000:])
    return {"started": True, "returncode": proc.returncode}


def main() -> None:
    setup_logging()
    settings = Settings.load()
    summary = renotify(settings)
    recovery = run_marker_controlled_recovery()
    if recovery is not None:
        summary["recovery"] = recovery  # type: ignore[assignment]
    log.info("renotify summary: %s", json.dumps(summary, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
