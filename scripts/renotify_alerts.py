"""Re-notify unacknowledged alerts until the operator confirms them.

Some failures (dead FB login, checkpoint/captcha/2FA) cannot be fixed by a
retry — they need a human re-login. A single Telegram ping is easy to miss, so
those are recorded as persistent alerts (see src/alerts.py). This script, run
frequently by the scheduler, keeps the operator informed until they act:

  1. Poll Telegram once, so any ✅ the operator just tapped is processed and the
     corresponding alert is acknowledged BEFORE we would re-send it.
  2. Re-send every alert that is still unacknowledged, each with its own ✅
     button.

It is intentionally cheap and side-effect-light: when there are no pending
alerts it polls and exits. Safe to run every few minutes.
"""

from __future__ import annotations

import json
import logging
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
    # Process acknowledgements FIRST so a just-tapped ✅ stops the re-send below.
    acked = notifier.poll_once()
    resent = notifier.renotify_pending()
    return {"acks_processed": acked, "alerts_resent": resent}


def main() -> None:
    setup_logging()
    settings = Settings.load()
    summary = renotify(settings)
    log.info("renotify summary: %s", json.dumps(summary, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
