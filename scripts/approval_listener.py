from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings
from src.approval import TelegramApproval
from src.queue_db import QueueDB
from src.run_result import RunResultStore


def main(
    *,
    settings: Settings | None = None,
    approval: TelegramApproval | None = None,
    store: RunResultStore | None = None,
) -> int:
    settings = settings or Settings.load()
    approval = approval or TelegramApproval(settings, QueueDB(settings.db_path))
    store = store or RunResultStore(ROOT / "output" / "run-results" / "approval-listener")
    run = store.start("approval-listener", run_id=f"approval-{uuid.uuid4().hex}")
    handled = approval.poll_once()
    reason = str(getattr(approval, "last_poll_reason", "telegram_poll_failed"))
    outcome = "preflight_blocked" if reason == "telegram_webhook_state_unknown" else "no_action"
    result = store.finish(run, outcome=outcome, reason=reason, handled=handled)
    return int(result["exit_code"])

if __name__ == "__main__":
    raise SystemExit(main())
