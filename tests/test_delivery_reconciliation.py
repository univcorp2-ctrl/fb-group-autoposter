from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from src.outbox import DeliveryOutbox
from src.queue_db import QueueDB
from src.run_result import RunResultStore


ROOT = Path(__file__).resolve().parents[1]


class FakeTelegramTransport:
    def __init__(self, results):
        self.results = list(results)
        self.calls: list[tuple[str, dict | None]] = []

    def send_message(self, text, *, reply_markup=None, disable_web_page_preview=False):
        self.calls.append((text, reply_markup))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _outbox(tmp_path):
    return DeliveryOutbox(QueueDB(tmp_path / "jobs.db"))


def _enqueue(outbox, *, event_key="telegram:run-1:summary", **payload):
    return outbox.enqueue(
        event_key=event_key,
        event_type="pipeline_summary",
        origin_run_id="posting-run-1",
        payload={"text": "safe summary", **payload},
    )


def test_reconciliation_delivers_current_outbox_payload_and_keeps_origin_linkage(tmp_path):
    from scripts.reconcile_delivery import reconcile_delivery

    outbox = _outbox(tmp_path)
    event = outbox.enqueue(
        event_key="telegram:run-1:approval-preview",
        event_type="approval_preview",
        origin_run_id="posting-run-1",
        payload={"text": "safe summary", "reply_markup": {"inline_keyboard": []}},
    )
    transport = FakeTelegramTransport([{"ok": True, "code": "sent", "message_id": 42}])

    summary = reconcile_delivery(outbox, transport, owner="test-worker")

    stored = outbox.get(event["event_id"])
    assert summary == {
        "claimed": 1,
        "delivered": 1,
        "failed": 0,
        "delivery_ambiguous": 0,
        "skipped": 0,
        "retry_pending": 0,
        "origin_run_id": "posting-run-1",
    }
    assert (stored["state"], stored["remote_message_id"], stored["origin_run_id"]) == (
        "delivered",
        "42",
        "posting-run-1",
    )
    assert transport.calls == [("safe summary", {"inline_keyboard": []})]


def test_reconciliation_marks_proven_pre_submit_failure_pending_without_same_pass_resend(tmp_path):
    from scripts.reconcile_delivery import reconcile_delivery

    outbox = _outbox(tmp_path)
    event = _enqueue(outbox)
    transport = FakeTelegramTransport([{"ok": False, "code": "retryable_pre_submit"}])

    reconcile_delivery(outbox, transport, owner="test-worker")

    assert outbox.get(event["event_id"])["state"] == "pending"
    assert len(transport.calls) == 1


def test_retryable_pre_submit_requeues_for_the_next_worker_until_bounded_limit(tmp_path):
    from scripts.reconcile_delivery import MAX_RETRYABLE_ATTEMPTS, reconcile_delivery

    outbox = _outbox(tmp_path)
    event = _enqueue(outbox)
    retryable = FakeTelegramTransport([{"ok": False, "code": "retryable_pre_submit"}])

    first = reconcile_delivery(outbox, retryable, owner="worker-one")

    assert first["retry_pending"] == 1
    assert outbox.get(event["event_id"])["state"] == "pending"
    assert len(retryable.calls) == 1  # never retries during the same worker pass

    for index in range(2, MAX_RETRYABLE_ATTEMPTS + 1):
        reconcile_delivery(
            outbox,
            FakeTelegramTransport([{"ok": False, "code": "retryable_pre_submit"}]),
            owner=f"worker-{index}",
        )

    stored = outbox.get(event["event_id"])
    assert (stored["state"], stored["attempt_count"]) == ("failed", MAX_RETRYABLE_ATTEMPTS)


def test_reconciliation_quarantines_timeout_and_never_auto_resends(tmp_path):
    from scripts.reconcile_delivery import reconcile_delivery

    outbox = _outbox(tmp_path)
    event = _enqueue(outbox)
    transport = FakeTelegramTransport([{"ok": False, "code": "delivery_ambiguous"}])

    reconcile_delivery(outbox, transport, owner="test-worker")
    second = reconcile_delivery(outbox, transport, owner="test-worker")

    assert outbox.get(event["event_id"])["state"] == "delivery_ambiguous"
    assert second["claimed"] == 0
    assert len(transport.calls) == 1


def test_reconciliation_claims_at_most_twenty_and_has_no_facebook_dependency(tmp_path):
    from scripts.reconcile_delivery import reconcile_delivery

    outbox = _outbox(tmp_path)
    for index in range(21):
        _enqueue(outbox, event_key=f"telegram:run-1:{index}")
    transport = FakeTelegramTransport([{"ok": True, "code": "sent", "message_id": index} for index in range(20)])

    summary = reconcile_delivery(outbox, transport, owner="test-worker")
    tree = ast.parse((ROOT / "scripts" / "reconcile_delivery.py").read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert summary["claimed"] == 20
    assert len(outbox.list_events()) == 21
    assert not any("facebook" in name.lower() or "poster" in name.lower() for name in imported)


def test_reconciliation_claims_only_the_oldest_origin_run_and_result_links_that_origin(tmp_path):
    from scripts.reconcile_delivery import reconcile_delivery

    outbox = _outbox(tmp_path)
    first = _enqueue(outbox, event_key="telegram:origin-a:1")
    outbox.enqueue(
        event_key="telegram:origin-b:1",
        event_type="pipeline_summary",
        origin_run_id="posting-run-b",
        payload={"text": "later origin"},
    )
    transport = FakeTelegramTransport([{"ok": True, "code": "sent", "message_id": 1}])

    summary = reconcile_delivery(outbox, transport, owner="worker")

    assert summary["origin_run_id"] == "posting-run-1"
    assert outbox.get(first["event_id"])["state"] == "delivered"
    later = next(event for event in outbox.list_events() if event["origin_run_id"] == "posting-run-b")
    assert later["state"] == "pending"


def test_missing_origin_is_quarantined_without_claiming_another_origin(tmp_path):
    from scripts.reconcile_delivery import reconcile_delivery

    outbox = _outbox(tmp_path)
    missing = outbox.enqueue(
        event_key="telegram:missing-origin:1", event_type="pipeline_summary", payload={"text": "missing"}
    )
    valid = _enqueue(outbox, event_key="telegram:origin-valid:1")

    summary = reconcile_delivery(outbox, FakeTelegramTransport([]), owner="worker")

    assert summary["origin_run_id"] is None
    assert outbox.get(missing["event_id"])["state"] == "failed"
    assert outbox.get(valid["event_id"])["state"] == "pending"


def test_canonical_reconciliation_result_has_one_claimed_origin_only(tmp_path):
    from scripts.reconcile_delivery import run_reconciliation

    db_path = tmp_path / "jobs.db"
    outbox = DeliveryOutbox(QueueDB(db_path))
    _enqueue(outbox)
    outbox.enqueue(
        event_key="telegram:unrelated:1",
        event_type="pipeline_summary",
        origin_run_id="unrelated-run",
        payload={"text": "unrelated"},
    )
    settings = SimpleNamespace(db_path=db_path, telegram_bot_token="", telegram_chat_id="")
    store = RunResultStore(tmp_path / "results")

    result = run_reconciliation(
        settings,
        run_id="delivery-result-1",
        store=store,
        transport=FakeTelegramTransport([{"ok": True, "code": "sent", "message_id": 1}]),
    )

    assert result["schema"] == "fb-autoposter-run/v1"
    assert result["origin_run_id"] == "posting-run-1"
    assert "origin_run_ids" not in result
    assert result["delivery"]["origin_run_id"] == "posting-run-1"


def test_renewed_remaining_batch_lease_blocks_a_competing_worker_during_slow_send(tmp_path):
    from scripts.reconcile_delivery import reconcile_delivery

    inner_outbox = _outbox(tmp_path)
    first = _enqueue(inner_outbox, event_key="telegram:origin:one")
    second = _enqueue(inner_outbox, event_key="telegram:origin:two")

    class FakeClock:
        renewal_batches: list[list[str]] = []

    class LeaseTrackingOutbox:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        def renew_leases(self, event_ids, owner, *, lease_seconds):
            FakeClock.renewal_batches.append(list(event_ids))
            return self.wrapped.renew_leases(event_ids, owner, lease_seconds=lease_seconds)

    outbox = LeaseTrackingOutbox(inner_outbox)

    class SlowTransport(FakeTelegramTransport):
        def send_message(self, text, *, reply_markup=None, disable_web_page_preview=False):
            # This models a competing worker checking while the first delivery
            # is still in progress. Both leases must already be freshly renewed.
            assert inner_outbox.claim("competing-worker", limit=20, lease_seconds=60) == []
            return super().send_message(
                text, reply_markup=reply_markup, disable_web_page_preview=disable_web_page_preview
            )

    result = reconcile_delivery(
        outbox,
        SlowTransport(
            [
                {"ok": True, "code": "sent", "message_id": 1},
                {"ok": True, "code": "sent", "message_id": 2},
            ]
        ),
        owner="slow-worker",
    )

    assert result["delivered"] == 2
    assert FakeClock.renewal_batches[0] == [first["event_id"], second["event_id"]]
    assert [inner_outbox.get(event["event_id"])["state"] for event in (first, second)] == ["delivered", "delivered"]
