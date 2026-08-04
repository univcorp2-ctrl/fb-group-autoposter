from __future__ import annotations

from types import SimpleNamespace

import asyncio

import pytest

from src.approval import TelegramApproval
from src.alerts import AlertStore
from src.queue_db import QueueDB


def _settings():
    return SimpleNamespace(
        telegram_bot_token="token",
        telegram_chat_id="chat",
        auto_approve=False,
        auto_approve_skip_degraded=True,
    )


def test_preview_producer_enqueues_without_calling_telegram_transport(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "property-1"}, [{"group_id": "group-1", "body": "body"}])
    approval = TelegramApproval(_settings(), db)
    approval.send_preview = lambda _job_id: (_ for _ in ()).throw(AssertionError("network send"))

    approval.auto_or_send_preview(job_id)

    event = db.list_outbox_events()[0]
    assert (event["event_type"], event["state"]) == ("approval_preview", "pending")
    assert event["event_key"] == f"telegram:job:{job_id}:preview"
    assert event["payload"]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"approve:{job_id}"


def test_atomic_target_finalization_keeps_delivery_obligation_with_posted_truth(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "property-1"}, [{"group_id": "group-1", "body": "body"}])

    db.update_target_status_with_outbox(
        job_id,
        "group-1",
        "posted",
        permalink="https://www.facebook.com/groups/group-1/posts/1",
        event_key="telegram:job-1:group-1:verified",
        event_type="verified_post",
        payload={"text": "verified"},
        subject_id="property-1",
    )

    assert db.get_targets(job_id)[0]["status"] == "posted"
    assert db.list_outbox_events()[0]["state"] == "pending"


def test_atomic_finalization_rolls_back_target_when_outbox_payload_is_invalid(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "property-1"}, [{"group_id": "group-1", "body": "body"}])

    with pytest.raises(ValueError, match="payload"):
        db.update_target_status_with_outbox(
            job_id,
            "group-1",
            "posted",
            event_key="telegram:attempt-1:verified",
            event_type="verified_post",
            payload={"token": "must not persist"},
        )

    assert db.get_targets(job_id)[0]["status"] == "pending"
    assert db.list_outbox_events() == []


def test_atomic_finalization_rolls_back_target_when_outbox_insert_crashes(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "property-1"}, [{"group_id": "group-1", "body": "body"}])
    with db.connect() as conn:
        conn.execute(
            """CREATE TRIGGER fail_outbox_insert BEFORE INSERT ON delivery_outbox
               BEGIN SELECT RAISE(ABORT, 'simulated crash'); END"""
        )

    with pytest.raises(Exception, match="simulated crash"):
        db.update_target_status_with_outbox(
            job_id,
            "group-1",
            "posted",
            event_key="telegram:attempt-1:verified",
            event_type="verified_post",
            payload={"text": "verified"},
        )

    assert db.get_targets(job_id)[0]["status"] == "pending"
    assert db.list_outbox_events() == []


def test_atomic_finalization_rejects_missing_target_without_event(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")

    with pytest.raises(ValueError, match="target not found"):
        db.update_target_status_with_outbox(
            "missing", "missing", "posted", event_key="telegram:x:verified", event_type="verified_post",
            payload={"text": "verified", "property_id": "p", "group_id": "g", "permalink": "https://www.facebook.com/groups/g/posts/1"},
        )

    assert db.list_outbox_events() == []


def test_pipeline_summary_is_enqueued_without_direct_transport(tmp_path, monkeypatch):
    from src import orchestrator

    source = tmp_path / "items.json"
    source.write_text("[]", encoding="utf-8")
    settings = SimpleNamespace(
        db_path=tmp_path / "jobs.db",
        dry_run=True,
        telegram_notify_pipeline_summary=True,
        validate_runtime=lambda **_kwargs: None,
    )

    class Approval:
        enabled = True

        def __init__(self, *_args, **_kwargs):
            pass

        def auto_or_send_preview(self, _job_id):
            return None

        def send_message(self, _text):
            raise AssertionError("summary must not send on the producer path")

    monkeypatch.setattr(orchestrator, "setup_logging", lambda: None)
    monkeypatch.setattr(orchestrator, "load_groups", lambda: [])
    monkeypatch.setattr(orchestrator, "TelegramApproval", Approval)

    asyncio.run(orchestrator.run_cycle_grouped(settings, source=source))

    event = QueueDB(settings.db_path).list_outbox_events()[0]
    assert event["event_type"] == "pipeline_summary"
    assert event["event_key"].startswith("telegram:")
    assert event["event_key"].endswith(":summary")
    assert event["origin_run_id"] not in {"", "run_cycle_grouped"}


def test_pipeline_summary_uses_unique_or_explicit_per_invocation_run_id(tmp_path):
    from src.orchestrator import _enqueue_pipeline_summary

    db = QueueDB(tmp_path / "jobs.db")
    summary = {"created": 0}
    _enqueue_pipeline_summary(db, summary, flow="run_cycle_grouped", run_id="run-a")
    _enqueue_pipeline_summary(db, summary, flow="run_cycle_grouped", run_id="run-b")
    _enqueue_pipeline_summary(db, summary, flow="run_cycle_grouped", run_id="run-a")

    events = db.list_outbox_events()
    assert {event["origin_run_id"] for event in events} == {"run-a", "run-b"}
    assert len(events) == 2


def test_persistent_alert_is_acknowledged_independently_of_queued_delivery(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    store = AlertStore(tmp_path / "alerts.json")
    approval = TelegramApproval(_settings(), db, alert_store=store)
    approval.send_message = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network send"))

    approval.raise_persistent_alert("session_dead", "re-login required")

    assert store.get("session_dead")["acknowledged"] is False
    event = db.list_outbox_events()[0]
    assert (event["event_type"], event["state"]) == ("persistent_alert", "pending")
    assert store.acknowledge("session_dead") is True
    assert store.get("session_dead")["acknowledged"] is True
