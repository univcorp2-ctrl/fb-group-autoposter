from __future__ import annotations

from datetime import UTC, datetime, timedelta
import sqlite3
import threading
import time

import pytest

from src.outbox import DeliveryOutbox
from src.queue_db import QueueDB


def _outbox(tmp_path):
    return DeliveryOutbox(QueueDB(tmp_path / "jobs.db"))


def test_enqueue_is_idempotent_by_stable_event_key(tmp_path):
    outbox = _outbox(tmp_path)

    first = outbox.enqueue(
        event_key="telegram:attempt-1:verified",
        event_type="verified_post",
        origin_run_id="run-1",
        attempt_id="attempt-1",
        subject_id="property-1",
        payload={"text": "verified", "permalink": "https://www.facebook.com/groups/a/posts/b"},
    )
    repeated = outbox.enqueue(
        event_key="telegram:attempt-1:verified",
        event_type="verified_post",
        origin_run_id="run-1",
        attempt_id="attempt-1",
        subject_id="property-1",
        payload={"text": "verified"},
    )

    assert repeated["event_id"] == first["event_id"]
    assert len(outbox.list_events()) == 1
    assert first["state"] == "pending"


def test_claim_honors_limit_and_reclaims_expired_lease(tmp_path):
    outbox = _outbox(tmp_path)
    for index in range(3):
        outbox.enqueue(
            event_key=f"telegram:run-1:summary:{index}",
            event_type="pipeline_summary",
            origin_run_id="run-1",
            payload={"text": str(index)},
        )

    claimed = outbox.claim("worker-a", limit=2, lease_seconds=30)
    assert [item["lease_owner"] for item in claimed] == ["worker-a", "worker-a"]
    assert len(outbox.claim("worker-b", limit=2, lease_seconds=30)) == 1

    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with outbox.db.connect() as conn:
        conn.execute(
            "UPDATE delivery_outbox SET lease_expires_at=? WHERE event_id=?",
            (expired, claimed[0]["event_id"]),
        )

    reclaimed = outbox.claim("worker-c", limit=2, lease_seconds=30)
    assert reclaimed[0]["event_id"] == claimed[0]["event_id"]
    assert reclaimed[0]["attempt_count"] == 2


def test_delivery_terminal_states_and_explicit_reset(tmp_path):
    outbox = _outbox(tmp_path)
    outbox.enqueue(
        event_key="telegram:attempt-1:uncertain",
        event_type="uncertain_post",
        attempt_id="attempt-1",
        payload={"text": "uncertain"},
    )
    claimed = outbox.claim("worker", limit=1, lease_seconds=30)[0]
    delivered = outbox.mark_delivered(claimed["event_id"], "worker", remote_message_id="77")
    assert (delivered["state"], delivered["remote_message_id"]) == ("delivered", "77")

    failed_event = outbox.enqueue(
        event_key="telegram:run-1:environment:login",
        event_type="challenge",
        origin_run_id="run-1",
        payload={"text": "login"},
    )
    outbox.mark_failed(outbox.claim("worker", limit=1, lease_seconds=30)[0]["event_id"], "worker", "offline")
    assert outbox.get(failed_event["event_id"])["state"] == "failed"

    ambiguous_event = outbox.enqueue(
        event_key="telegram:run-1:summary",
        event_type="pipeline_summary",
        origin_run_id="run-1",
        payload={"text": "summary"},
    )
    outbox.mark_ambiguous(outbox.claim("worker", limit=1, lease_seconds=30)[0]["event_id"], "worker", "timeout")
    assert outbox.get(ambiguous_event["event_id"])["state"] == "delivery_ambiguous"
    with pytest.raises(ValueError, match="resolution"):
        outbox.reset(ambiguous_event["event_id"], operator="operator-1")
    assert outbox.claim("other", limit=1) == []
    assert outbox.reset(
        ambiguous_event["event_id"], operator="operator-1", resolution="confirmed_not_delivered"
    )["state"] == "pending"
    with outbox.db.connect() as conn:
        audit = conn.execute("SELECT resolution, operator FROM delivery_outbox_resolutions").fetchone()
    assert tuple(audit) == ("confirmed_not_delivered", "operator-1")


def test_payload_rejects_delivery_credentials(tmp_path):
    outbox = _outbox(tmp_path)

    with pytest.raises(ValueError, match="payload"):
        outbox.enqueue(
            event_key="telegram:run-1:summary",
            event_type="pipeline_summary",
            origin_run_id="run-1",
            payload={"telegram_token": "secret"},
        )


def test_payload_schema_rejects_unknown_fields_and_redacts_token_shaped_text(tmp_path):
    outbox = _outbox(tmp_path)

    with pytest.raises(ValueError, match="payload fields"):
        outbox.enqueue(
            event_key="telegram:run-1:summary", event_type="pipeline_summary", origin_run_id="run-1",
            payload={"text": "ok", "authorization": "Bearer bad"},
        )

    event = outbox.enqueue(
        event_key="telegram:run-2:summary", event_type="pipeline_summary", origin_run_id="run-2",
        payload={"text": "token 123456:abcdefghijklmnopqrstuvwxyzABCDE"},
    )
    assert "123456:" not in event["payload"]["text"]


def test_schema_migration_adds_outbox_without_replacing_existing_jobs(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE jobs (job_id TEXT PRIMARY KEY, property_id TEXT, status TEXT, created_at TEXT, updated_at TEXT, degraded INTEGER, payload_json TEXT)"
        )
        conn.execute(
            "INSERT INTO jobs VALUES ('legacy-job', 'property-1', 'done', 'old', 'old', 0, '{}')"
        )

    db = QueueDB(path)

    assert db.get_job("legacy-job")["status"] == "done"
    assert db.enqueue_outbox_event(
        event_key="telegram:legacy:summary", event_type="pipeline_summary", payload={"text": "ok"}
    )["state"] == "pending"


def test_enqueue_waits_for_a_short_sqlite_write_lock(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    blocker = sqlite3.connect(db.path, check_same_thread=False)
    blocker.execute("BEGIN IMMEDIATE")
    release = threading.Timer(0.1, blocker.rollback)
    release.start()
    try:
        started = time.monotonic()
        event = db.enqueue_outbox_event(
            event_key="telegram:run-lock:summary", event_type="pipeline_summary", payload={"text": "ok"}
        )
    finally:
        release.join()
        blocker.close()

    assert event["state"] == "pending"
    assert time.monotonic() - started >= 0.08
