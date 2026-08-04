from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from config import Settings, load_groups
from src.approval import TelegramApproval
from src.estateboard_adapter import select_postable
from src.freshness import build_checker
from src.generator import generate_variants
from src.ingest import scan_inbox
from src.logging_setup import setup_logging
from src.poster import FacebookPoster
from src.queue_db import QueueDB

log = logging.getLogger(__name__)


def _enqueue_pipeline_summary(db: QueueDB, summary: dict[str, Any], *, flow: str, run_id: str) -> None:
    """Record the summary for downstream delivery; this producer never sends it."""
    db.enqueue_outbox_event(
        event_key=f"telegram:{run_id}:summary",
        event_type="pipeline_summary",
        origin_run_id=run_id,
        subject_id=flow,
        payload={"text": f"📊 pipeline summary\n{json.dumps(summary, ensure_ascii=False, indent=2)}"},
    )


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        # os.kill(pid, 0) is unreliable on Windows (raises WinError 87 /
        # SystemError for dead pids), which made a stale lock from a terminated
        # run crash EVERY later run and silently halt posting. Query the process
        # via the Win32 API instead and confirm it has not exited.
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, SystemError, ProcessLookupError):
        return False
    return True


# A lock older than this is considered stale regardless of pid, as a backstop:
# posting runs are capped at ~1h by the scheduler, so a 2h-old lock means the
# owner died without cleaning up (terminated run). Never block forever.
_LOCK_STALE_SECONDS = 2 * 60 * 60


@contextmanager
def pipeline_lock(path: str | Path = "data/pipeline.lock") -> Iterator[None]:
    lock = Path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        try:
            pid = int(lock.read_text(encoding="utf-8").strip() or "0")
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                age = 0.0
            owner_alive = bool(pid) and pid != os.getpid() and _pid_is_running(pid)
            if owner_alive and age < _LOCK_STALE_SECONDS:
                raise RuntimeError(f"pipeline lock exists: {lock} pid={pid}")
            # Stale (owner dead, or lock too old to be real) -> reclaim it.
            if age >= _LOCK_STALE_SECONDS:
                log.warning("reclaiming stale pipeline lock (age=%.0fs, pid=%s)", age, pid)
            lock.unlink(missing_ok=True)
        except ValueError:
            lock.unlink(missing_ok=True)
    lock.write_text(str(os.getpid()), encoding="utf-8")
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def sample_property() -> dict[str, object]:
    return {
        "property_id": "sample-001",
        "title": "イーリス横浜大口Lofos",
        "price": "3,480万円",
        "yield_pct": "8.5%",
        "location": "横浜市神奈川区大口通",
        "access": "JR大口駅 徒歩7分",
        "structure": "鉄筋コンクリート造 4階建",
        "land_area": "120.5㎡",
        "building_area": "210.3㎡",
        "year_built": "2008年",
        "highlights": ["駅近", "RC造", "満室稼働中"],
        "url": "https://example.com/property/sample-001",
        "images": [],
        "raw_text": "dry run sample",
    }


async def run_cycle(settings: Settings, *, selftest: bool = False, run_id: str | None = None) -> dict[str, object]:
    setup_logging()
    settings.validate_runtime(require_external=not selftest and not settings.dry_run)
    groups = load_groups()
    db = QueueDB(settings.db_path)
    run_id = str(run_id or getattr(settings, "run_id", "") or uuid.uuid4())
    notifier = TelegramApproval(settings, db)
    summary: dict[str, object] = {"created": 0, "approved_processed": 0, "statuses": []}
    with pipeline_lock():
        recovered_attempts = db.recover_incomplete_attempts()
        if recovered_attempts:
            log.warning("recovered %s incomplete submission attempts", recovered_attempts)
        db.reset_stale_posting_jobs()
        db.mark_heartbeat("orchestrator")
        properties = [sample_property()] if selftest else scan_inbox(settings.inbox_dir)
        for prop in properties:
            batch = generate_variants(prop, groups, settings)
            job_id = db.create_job(prop, batch.variants, degraded=batch.degraded)
            notifier.auto_or_send_preview(job_id)
            summary["created"] = int(summary["created"]) + 1
        if selftest and settings.dry_run:
            for job in db.pending_jobs():
                db.approve_job(job["job_id"])
        # Freshness gate: re-validate each property against the latest EstateBoard
        # export at post time so deleted/unpublished listings are never posted.
        # Selftest uses a synthetic property with no source -> checker is skipped.
        checker = None if selftest else build_checker(settings.estateboard_source)
        poster = FacebookPoster(settings, db, groups, notifier, freshness_checker=checker)
        for job in db.approved_jobs():
            status = await poster.post_job(job)
            summary["approved_processed"] = int(summary["approved_processed"]) + 1
            summary["statuses"].append({"job_id": job["job_id"], "status": status})
        db.mark_heartbeat("orchestrator")
    if getattr(settings, "telegram_notify_pipeline_summary", False):
        _enqueue_pipeline_summary(db, summary, flow="run_cycle", run_id=run_id)
    return summary


async def run_cycle_grouped(
    settings: Settings,
    *,
    source: str | Path,
    sleeper: Any = asyncio.sleep,
    run_id: str | None = None,
) -> dict[str, object]:
    """Daily flow where EACH group picks its OWN next property by its OWN order.

    Unlike `run_cycle` (one property to all groups), this independently selects
    the next unposted property per group (by that group's `selection_order`),
    generates a single-group variant, queues + auto-approves it, then posts the
    approved jobs with a randomized sleep between posts (block avoidance).

    The JST calendar-day one-post-per-group guard is preserved: a group already
    posted today is skipped before selection, and the poster's preflight is the
    final backstop.
    """
    from scripts.run_daily import _load_items

    setup_logging()
    settings.validate_runtime(require_external=not settings.dry_run)
    groups = load_groups()
    db = QueueDB(settings.db_path)
    run_id = str(run_id or getattr(settings, "run_id", "") or uuid.uuid4())
    notifier = TelegramApproval(settings, db)
    summary: dict[str, Any] = {"created": 0, "approved_processed": 0, "skipped_groups": 0, "statuses": []}

    try:
        items = _load_items(Path(source))
    except FileNotFoundError:
        log.warning("EstateBoard source not found: %s", source)
        items = []

    with pipeline_lock():
        recovered_attempts = db.recover_incomplete_attempts()
        if recovered_attempts:
            log.warning("recovered %s incomplete submission attempts", recovered_attempts)
        db.reset_stale_posting_jobs()
        db.mark_heartbeat("orchestrator")

        # Properties chosen for an earlier group THIS run, so no two groups ever
        # post the SAME listing on the same day — even when their selection_order
        # overlaps (which happens once there are more groups than distinct orders).
        selected_this_run: set[str] = set()
        for group in groups:
            if db.posted_same_group_today(group["id"]):
                summary["skipped_groups"] = int(summary["skipped_groups"]) + 1
                continue
            order = group.get("selection_order", "newest")
            exclude = db.posted_property_ids_for_group(group["id"]) | selected_this_run
            picks = select_postable(
                items,
                limit=1,
                exclude_ids=exclude,
                order=order,
            )
            if not picks:
                log.warning("no fresh property for group %s (order=%s)", group["id"], order)
                continue
            prop = picks[0]
            selected_this_run.add(prop["property_id"])
            batch = generate_variants(prop, [group], settings)
            job_id = db.create_job(prop, batch.variants, degraded=batch.degraded)
            notifier.auto_or_send_preview(job_id)
            summary["created"] = int(summary["created"]) + 1

        # Freshness gate built from the SAME source these groups selected from, so
        # a property deleted between selection and posting is skipped, not posted.
        checker = build_checker(source)
        poster = FacebookPoster(settings, db, groups, notifier, freshness_checker=checker)
        approved = db.approved_jobs()
        for index, job in enumerate(approved):
            status = await poster.post_job(job)
            summary["approved_processed"] = int(summary["approved_processed"]) + 1
            summary["statuses"].append({"job_id": job["job_id"], "status": status})
            # Randomized spacing BETWEEN posts (not after the last) to avoid
            # robotic cadence that trips block detection.
            if index < len(approved) - 1:
                await sleeper(random.randint(settings.min_interval_min * 60, settings.max_interval_min * 60))
        db.mark_heartbeat("orchestrator")

    if getattr(settings, "telegram_notify_pipeline_summary", False):
        _enqueue_pipeline_summary(db, summary, flow="run_cycle_grouped", run_id=run_id)
    return summary


def run_approval_poll(settings: Settings) -> int:
    db = QueueDB(settings.db_path)
    approval = TelegramApproval(settings, db)
    return approval.poll_once()


def healthcheck(settings: Settings) -> int:
    db = QueueDB(settings.db_path)
    age = db.heartbeat_age_minutes("orchestrator")
    if age is None or age > settings.heartbeat_timeout_min:
        db.enqueue_outbox_event(
            event_key="telegram:healthcheck:environment:heartbeat_stalled",
            event_type="environment",
            origin_run_id="healthcheck",
            subject_id="orchestrator",
            payload={"text": f"🔴 ハートビート停滞: age_min={age}"},
        )
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--approval-poll", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    settings = Settings.load()
    if args.approval_poll:
        handled = run_approval_poll(settings)
        log.info("handled=%d", handled)
        return
    if args.healthcheck:
        raise SystemExit(healthcheck(settings))
    summary = asyncio.run(run_cycle(settings, selftest=args.selftest))
    log.info("pipeline summary: %s", json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
