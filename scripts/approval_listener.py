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


def listen(
    settings: Settings,
    *,
    run_id: str | None = None,
    approval: TelegramApproval | None = None,
    store: RunResultStore | None = None,
) -> dict:
    """Poll only when Telegram confirms polling mode; webhook ownership is a noop."""
    store = store or RunResultStore(ROOT / "output" / "run-results")
    run = store.start("approval-listener", run_id=run_id or f"approval-{uuid.uuid4().hex}")
    approval = approval or TelegramApproval(settings, QueueDB(settings.db_path))
    handled = approval.poll_once()
    reason = approval.last_poll_reason
    outcome = "preflight_blocked" if reason == "telegram_webhook_state_unknown" else "no_action"
    return store.finish(run, outcome=outcome, reason=reason, extra_fields={"handled": handled})


def main(
    settings: Settings | None = None,
    *,
    approval: TelegramApproval | None = None,
    store: RunResultStore | None = None,
) -> int:
    result = listen(settings or Settings.load(), approval=approval, store=store)
    print(f"handled={result['handled']} reason={result['reason']}")
    return int(result["exit_code"])

if __name__ == "__main__":
    raise SystemExit(main())
