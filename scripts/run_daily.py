"""Daily posting entry point: ingest one fresh broker-OK property, then post.

Designed to be scheduled (e.g. twice a day). Each run:
  1. selects the newest broker-OK (仲介回しOK) EstateBoard property that has
     not been posted yet, and writes it to the inbox,
  2. runs the posting pipeline, which posts only when within the group's
     active hours and the group has not already been posted today (JST).

Safe by design: the calendar-day (JST) same-group guard means at most one post
per group per day. The morning run posts; the evening run sees "already posted
today" and skips. Running this more often than needed never over-posts and
never produces a duplicate, while still guaranteeing a post every single day.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings, load_groups
from src.ensure import ensure_posted_today
from src.estateboard_adapter import select_postable
from src.logging_setup import setup_logging
from src.orchestrator import run_cycle_grouped
from src.queue_db import QueueDB
from src.session import restore_profile

log = logging.getLogger("run_daily")

DEFAULT_SOURCE = Path(
    r"G:\マイドライブ\AI_Agents\github\repos\EstateBoard\output\received\properties.json"
)


ALERT_FILE = ROOT / "logs" / "ALERT_SESSION_DEAD.txt"
# A distinct sentinel for an unrecoverable login challenge (checkpoint/captcha/
# 2FA). A restore can never clear these — the operator's action differs from a
# plain cookie expiry, so it gets its own file the monitor can watch separately.
CHECKPOINT_ALERT_FILE = ROOT / "logs" / "ALERT_CHECKPOINT.txt"
_CHALLENGE_KINDS = {"checkpoint", "captcha", "two_factor"}


def _alert_session_dead(result: dict, settings: Settings, db: QueueDB) -> None:
    """Persist a loud, Telegram-independent alert that the FB login is dead."""
    from datetime import datetime, timezone

    from src.session import challenge_message, login_required_message

    kind = result.get("challenge")
    # Use the kind-specific guidance when a real challenge was detected; fall
    # back to the generic message for a plain (kind-less) session expiry.
    msg = challenge_message(kind) if kind in _CHALLENGE_KINDS else login_required_message()
    try:
        ALERT_FILE.parent.mkdir(parents=True, exist_ok=True)
        ALERT_FILE.write_text(
            f"{datetime.now(timezone.utc).isoformat()}  reason={result.get('reason')}\n{msg}\n",
            encoding="utf-8",
        )
        if kind in _CHALLENGE_KINDS:
            CHECKPOINT_ALERT_FILE.write_text(
                f"{datetime.now(timezone.utc).isoformat()}  reason={result.get('reason')}  kind={kind}\n{msg}\n",
                encoding="utf-8",
            )
    except Exception:  # noqa: BLE001 - alerting must never crash the run
        pass
    if kind in _CHALLENGE_KINDS:
        log.critical("FB LOGIN CHALLENGE (%s) — posting halted until manual re-login: %s", kind, msg)
    else:
        log.critical("FB SESSION DEAD — posting halted until manual re-login: %s", msg)
    try:
        from src.approval import TelegramApproval

        notifier = TelegramApproval(settings, db)
        if getattr(notifier, "enabled", False):
            notifier.alert(f"⚠️ {msg}")
    except Exception:  # noqa: BLE001 - best-effort, no-op when Telegram disabled
        pass


def _clear_session_alert() -> None:
    """Remove the session-dead sentinels once a run no longer reports a dead session."""
    for sentinel in (ALERT_FILE, CHECKPOINT_ALERT_FILE):
        try:
            if sentinel.exists():
                sentinel.unlink()
        except Exception:  # noqa: BLE001
            pass


def _load_items(source: Path) -> list[dict]:
    data = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("items", [])
    return data if isinstance(data, list) else []


def refresh_inbox(settings: Settings, *, source: Path, count: int) -> int:
    """Replace inbox with `count` fresh (unposted) broker-OK properties."""
    inbox = Path(settings.inbox_dir)
    inbox.mkdir(parents=True, exist_ok=True)
    for old in inbox.glob("eb-*.json"):
        old.unlink()

    posted = QueueDB(settings.db_path).posted_property_ids()
    try:
        items = _load_items(source)
    except FileNotFoundError:
        log.warning("EstateBoard source not found: %s", source)
        return 0
    properties = select_postable(items, limit=count, exclude_ids=posted)
    for prop in properties:
        (inbox / f"{prop['property_id']}.json").write_text(
            json.dumps(prop, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    log.info("inbox refreshed: %d fresh properties (excluded %d posted)", len(properties), len(posted))
    return len(properties)


def main() -> None:
    setup_logging()
    settings = Settings.load()
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    groups = load_groups()
    db = QueueDB(settings.db_path)

    async def run_once() -> None:
        # One full grouped cycle: each group independently selects its OWN next
        # unposted property (by its configured selection_order), then posts.
        # (Replaces the old refresh_inbox + run_cycle one-property-to-all flow.)
        summary = await run_cycle_grouped(settings, source=source)
        log.info("cycle summary: %s", json.dumps(summary, ensure_ascii=False))

    def restore_session() -> bool:
        # Recovery fallback: an expired login is restored from the latest healthy
        # profile backup, then the loop retries. Returns True if a backup existed.
        used = restore_profile(settings.profile_dir)
        if used:
            log.warning("restored profile from backup: %s", used.name)
        else:
            log.error("session expired and no profile backup to restore; manual login_once.py needed")
        return used is not None

    result = asyncio.run(
        ensure_posted_today(settings, groups, db, run_once=run_once, restore_session=restore_session)
    )
    log.info("run_daily ensure result: %s", json.dumps(result, ensure_ascii=False))

    # A dead/unrecoverable session is the one failure a retry can never fix — it
    # needs a human re-login. Surface it loudly even when Telegram is disabled:
    # write a sentinel file (cleared on the next healthy run) and log CRITICAL so
    # the monitor and the operator both see it instead of silent zero-posting.
    if result.get("reason") in {"session_unrecoverable", "no_backup_to_restore"}:
        _alert_session_dead(result, settings, db)
    else:
        _clear_session_alert()

    # Keep the at-a-glance posting-status DB (Excel + CSV) current after every run.
    try:
        from src.status_report import build_status_files

        status = build_status_files(source, str(settings.db_path), ROOT / "output", root=ROOT)
        log.info("status DB refreshed: %s", json.dumps(status["counts"], ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - status DB is best-effort, never block posting
        log.warning("status DB refresh skipped: %s: %s", type(exc).__name__, exc)

    # Project posting status into EstateBoard (master store + live dashboard) so
    # 投稿済/未投稿 shows there too. Best-effort: never block or crash the run.
    try:
        from scripts.sync_estateboard_status import sync_estateboard_status

        eb = sync_estateboard_status(settings.db_path)
        log.info("EstateBoard status synced: %s", json.dumps(eb, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - EstateBoard sync is best-effort
        log.warning("EstateBoard status sync skipped: %s: %s", type(exc).__name__, exc)


if __name__ == "__main__":
    main()
