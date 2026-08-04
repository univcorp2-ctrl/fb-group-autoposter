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
_SESSION_DEAD_REASONS = {
    "session_unrecoverable",
    "no_backup_to_restore",
    "manual_profile_recovery_required",
    "candidate_probe_healthy_manual_recovery_required",
}


def _requires_session_dead_alert(reason: object) -> bool:
    return reason in _SESSION_DEAD_REASONS


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
    # Record a persistent, acknowledge-until-cleared alert. The scheduled
    # re-notifier (scripts/renotify_alerts.py) keeps re-sending it to Telegram
    # until the operator taps ✅ or a healthy run clears it — so a dead session
    # can never go silently unnoticed (the whole point of this requirement).
    try:
        from src.approval import TelegramApproval

        alert_kind = kind if kind in _CHALLENGE_KINDS else "session_dead"
        TelegramApproval(settings, db).raise_persistent_alert(alert_kind, msg)
    except Exception:  # noqa: BLE001 - best-effort, no-op when Telegram disabled
        pass


def _clear_session_alert(settings: Settings | None = None, db: QueueDB | None = None) -> None:
    """Clear the session-dead sentinels + persistent alerts once a run no longer
    reports a dead session (the login recovered)."""
    for sentinel in (ALERT_FILE, CHECKPOINT_ALERT_FILE):
        try:
            if sentinel.exists():
                sentinel.unlink()
        except Exception:  # noqa: BLE001
            pass
    if settings is None or db is None:
        return
    try:
        from src.approval import TelegramApproval

        notifier = TelegramApproval(settings, db)
        for kind in ("session_dead", *_CHALLENGE_KINDS):
            notifier.clear_persistent_alert(kind)
    except Exception:  # noqa: BLE001 - recovery notice is best-effort
        pass


def _send_completion_report(settings: Settings, db: QueueDB, groups: list[dict]) -> None:
    """Double-checked completion report to Telegram: list today's VERIFIED posts
    (with their direct permalinks) and any unverified/failed ones (with the group
    URL to check). Reads the DB, whose 'posted' rows were each confirmed live by
    permalink at post time — so the report only calls something done when it is
    genuinely verified, and always ships the link to double-check."""
    from datetime import datetime, timedelta, timezone

    jst = timezone(timedelta(hours=9))
    start = datetime.now(jst).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start.astimezone(timezone.utc).isoformat()
    names = {str(g["id"]): g.get("name", g["id"]) for g in groups}
    urls = {str(g["id"]): g.get("post_url", "") for g in groups}

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT t.group_id, t.status, t.permalink, j.property_id
            FROM job_targets t JOIN jobs j ON j.job_id = t.job_id
            WHERE COALESCE(t.posted_at, j.updated_at) >= ?
            ORDER BY t.group_id
            """,
            (start_utc,),
        ).fetchall()

    verified = [r for r in rows if r["status"] == "posted"]
    unverified = [r for r in rows if r["status"] in ("uncertain", "failed")]
    if not verified and not unverified:
        return  # nothing happened today; stay quiet

    lines = [f"📋 本日の投稿完了報告（{start.strftime('%Y-%m-%d')}）", ""]
    lines.append(f"✅ 検証済み投稿 {len(verified)}件:")
    for r in verified:
        lines.append(f"・{names.get(r['group_id'], r['group_id'])}：{r['property_id']}")
        lines.append(f"　🔗 {r['permalink'] or '(リンク未取得)'}")
    if unverified:
        lines.append("")
        lines.append(f"⚠️ 未確認/失敗 {len(unverified)}件（投稿済みにはカウントしません・要確認）:")
        for r in unverified:
            lines.append(f"・{names.get(r['group_id'], r['group_id'])}：{r['property_id']}")
            lines.append(f"　確認: {urls.get(r['group_id'], '')}")

    try:
        report_day = start.strftime("%Y-%m-%d")
        db.enqueue_outbox_event(
            event_key=f"telegram:daily:{report_day}:completion_report",
            event_type="completion_report",
            origin_run_id=f"daily:{report_day}",
            subject_id=report_day,
            payload={"text": "\n".join(lines)},
        )
    except Exception as exc:  # noqa: BLE001 - reporting must never block posting
        log.warning("completion report enqueue skipped: %s: %s", type(exc).__name__, exc)


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
        # Scheduled recovery never writes a backup into the live Chrome profile.
        log.error("manual_profile_recovery_required: run read-only preflight and manual login_once.py")
        return False

    result = asyncio.run(
        ensure_posted_today(settings, groups, db, run_once=run_once, restore_session=restore_session)
    )
    if result.get("reason") == "no_backup_to_restore":
        result["reason"] = "manual_profile_recovery_required"
        result["circuit_open"] = True
    log.info("run_daily ensure result: %s", json.dumps(result, ensure_ascii=False))

    # A dead/unrecoverable session is the one failure a retry can never fix — it
    # needs a human re-login. Surface it loudly even when Telegram is disabled:
    # write a sentinel file (cleared on the next healthy run) and log CRITICAL so
    # the monitor and the operator both see it instead of silent zero-posting.
    if _requires_session_dead_alert(result.get("reason")):
        _alert_session_dead(result, settings, db)
    else:
        _clear_session_alert(settings, db)

    # Keep the at-a-glance posting-status DB (Excel + CSV) current after every run.
    try:
        from src.status_report import build_status_files

        status = build_status_files(source, str(settings.db_path), ROOT / "output", root=ROOT)
        log.info("status DB refreshed: %s", json.dumps(status["counts"], ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - status DB is best-effort, never block posting
        log.warning("status DB refresh skipped: %s: %s", type(exc).__name__, exc)

    # Refresh the GROUP posting registry (which groups, membership, post counts) so
    # the record of WHERE we post stays current every run — including any group
    # added since the last run. Best-effort: never blocks posting.
    try:
        from scripts.build_group_registry import build_registry

        reg = build_registry()
        log.info("group registry refreshed: %s", json.dumps(reg["summary"], ensure_ascii=False))
        # Publish the registry to the EstateBoard dashboard (estateboard.pages.dev/
        # groups) so the record of WHERE we post is visible on the web too.
        from scripts.sync_groups_web import sync_groups_web

        web = sync_groups_web()
        log.info("group registry web sync: %s", json.dumps(web, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - registry/web is best-effort
        log.warning("group registry refresh skipped: %s: %s", type(exc).__name__, exc)

    # Project posting status into EstateBoard (master store + live dashboard) so
    # 投稿済/未投稿 shows there too. Best-effort: never block or crash the run.
    try:
        from scripts.sync_estateboard_status import sync_estateboard_status

        eb = sync_estateboard_status(settings.db_path)
        log.info("EstateBoard status synced: %s", json.dumps(eb, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - EstateBoard sync is best-effort
        log.warning("EstateBoard status sync skipped: %s: %s", type(exc).__name__, exc)

    # Double-checked completion report: only VERIFIED (permalink-confirmed) posts
    # are reported as done, each with its link; unverified ones are flagged.
    _send_completion_report(settings, db, groups)


if __name__ == "__main__":
    main()
