from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from src.poster import FacebookPoster
from src.queue_db import QueueDB


ROOT = Path(__file__).resolve().parents[1]


def test_outbox_has_no_telegram_transport_or_facebook_poster_dependency():
    tree = ast.parse((ROOT / "src" / "outbox.py").read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "src.telegram_transport" not in imported
    assert "src.poster" not in imported


def test_delivery_failure_cannot_mutate_facebook_target_truth(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "property-1"}, [{"group_id": "group-1", "body": "body"}])
    db.update_target_status_with_outbox(
        job_id,
        "group-1",
        "posted",
        event_key="telegram:attempt-1:verified",
        event_type="verified_post",
        attempt_id="attempt-1",
        payload={"text": "verified"},
    )
    event = db.claim_outbox_events("worker", limit=1)[0]
    db.mark_outbox_failed(event["event_id"], "worker", "transport down")

    target = db.get_targets(job_id)[0]
    assert (target["status"], target["attempts"]) == ("posted", 0)
    assert db.get_outbox_event(event["event_id"])["state"] == "failed"


def test_two_groups_in_one_job_get_distinct_target_delivery_keys(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job(
        {"property_id": "property-1"},
        [{"group_id": "group-1", "body": "one"}, {"group_id": "group-2", "body": "two"}],
    )
    poster = FacebookPoster(SimpleNamespace(), db, [])
    job = db.get_job(job_id)

    for target in db.get_targets(job_id):
        poster._enqueue_delivery(
            job, target, event_type="posting_failed", suffix="posting_failed", text="failed"
        )

    events = db.list_outbox_events()
    assert len(events) == 2
    assert len({event["event_key"] for event in events}) == 2


def test_verification_promotions_and_demotions_use_atomic_outbox_finalization():
    source = (ROOT / "scripts" / "verify_posts.py").read_text(encoding="utf-8")

    assert source.count("db.update_target_status_with_outbox(") >= 2
    assert "db.update_target_status(rec[" not in source
