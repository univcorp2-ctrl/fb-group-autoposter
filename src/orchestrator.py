from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from config import Settings, load_groups
from src.approval import TelegramApproval
from src.generator import generate_variants
from src.ingest import scan_inbox
from src.logging_setup import setup_logging
from src.poster import FacebookPoster
from src.queue_db import QueueDB

log = logging.getLogger(__name__)


@contextmanager
def pipeline_lock(path: str | Path = "data/pipeline.lock") -> Iterator[None]:
    lock = Path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        try:
            pid = int(lock.read_text(encoding="utf-8").strip() or "0")
            if pid and pid != os.getpid():
                raise RuntimeError(f"pipeline lock exists: {lock} pid={pid}")
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


async def run_cycle(settings: Settings, *, selftest: bool = False) -> dict[str, object]:
    setup_logging()
    settings.validate_runtime(require_external=not selftest and not settings.dry_run)
    groups = load_groups()
    db = QueueDB(settings.db_path)
    notifier = TelegramApproval(settings, db)
    summary: dict[str, object] = {"created": 0, "approved_processed": 0, "statuses": []}
    with pipeline_lock():
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
        poster = FacebookPoster(settings, db, groups, notifier)
        for job in db.approved_jobs():
            status = await poster.post_job(job)
            summary["approved_processed"] = int(summary["approved_processed"]) + 1
            summary["statuses"].append({"job_id": job["job_id"], "status": status})
        db.mark_heartbeat("orchestrator")
    if notifier.enabled:
        notifier.send_message(f"📊 pipeline summary\n{json.dumps(summary, ensure_ascii=False, indent=2)}")
    return summary


def run_approval_poll(settings: Settings) -> int:
    db = QueueDB(settings.db_path)
    approval = TelegramApproval(settings, db)
    return approval.poll_once()


def healthcheck(settings: Settings) -> int:
    db = QueueDB(settings.db_path)
    age = db.heartbeat_age_minutes("orchestrator")
    approval = TelegramApproval(settings, db)
    if age is None or age > settings.heartbeat_timeout_min:
        approval.alert(f"ハートビート停滞: age_min={age}")
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
        print(f"handled={handled}")
        return
    if args.healthcheck:
        raise SystemExit(healthcheck(settings))
    summary = asyncio.run(run_cycle(settings, selftest=args.selftest))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
