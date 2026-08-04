"""Tests for the persist-until-acknowledged alert flow through Telegram.

Covers raise -> re-notify -> acknowledge (via poll) -> stop, and recovery clear.
Network is fully stubbed; we assert on what would be sent and on store state.
"""
from types import SimpleNamespace

from src.alerts import AlertStore
from src.approval import TelegramApproval
from src.queue_db import QueueDB


def _settings(chat_id="12345"):
    return SimpleNamespace(
        telegram_bot_token="fake-token",
        telegram_chat_id=chat_id,
        telegram_authorized_user_id="",
        auto_approve=False,
        auto_approve_skip_degraded=True,
    )


def _approval(tmp_path, sent):
    """A TelegramApproval whose _post records calls instead of hitting network."""
    db = QueueDB(tmp_path / "jobs.db")
    store = AlertStore(tmp_path / "alerts.json")
    approval = TelegramApproval(_settings(), db, alert_store=store)
    approval._post = lambda method, payload: sent.append((method, payload)) or {"ok": True}
    return approval, store


def test_raise_persistent_alert_records_and_queues_with_ack_button(tmp_path):
    sent: list = []
    approval, store = _approval(tmp_path, sent)

    approval.raise_persistent_alert("session_dead", "再ログインしてください")

    alert = store.get("session_dead")
    assert alert is not None and alert["acknowledged"] is False
    assert alert["notify_count"] == 1
    # The queued payload carries an inline ✅ ack button with callback ack:session_dead.
    assert sent == []
    payload = approval.db.list_outbox_events()[0]["payload"]
    button = payload["reply_markup"]["inline_keyboard"][0][0]
    assert button["callback_data"] == "ack:session_dead"


def test_renotify_resends_until_acknowledged(tmp_path):
    sent: list = []
    approval, store = _approval(tmp_path, sent)
    approval.raise_persistent_alert("session_dead", "msg")
    sent.clear()

    # Two re-notify passes while unacknowledged -> two more queued obligations.
    assert approval.renotify_pending() == 1
    assert approval.renotify_pending() == 1
    assert sent == []
    assert len(approval.db.list_outbox_events()) == 3
    assert store.get("session_dead")["notify_count"] == 3  # 1 initial + 2 resends

    # Operator acknowledges -> no longer re-sent.
    store.acknowledge("session_dead")
    sent.clear()
    assert approval.renotify_pending() == 0
    assert sent == []


def test_delivery_ambiguous_quarantines_alert_and_prevents_future_renotify(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    store = AlertStore(tmp_path / "alerts.json")
    approval = TelegramApproval(_settings(), db, alert_store=store)

    approval.raise_persistent_alert("session_dead", "msg")
    event = db.claim_outbox_events("worker")[0]
    db.mark_outbox_ambiguous(event["event_id"], "worker", "timeout")
    assert approval.renotify_pending() == 1

    assert store.get("session_dead")["delivery_quarantined"] is True
    assert approval.renotify_pending() == 0
    assert AlertStore(store.path).pending_unacknowledged() == []


def test_pre_submit_failure_remains_eligible_for_renotify(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    store = AlertStore(tmp_path / "alerts.json")
    approval = TelegramApproval(_settings(), db, alert_store=store)

    approval.raise_persistent_alert("session_dead", "msg")

    assert store.get("session_dead").get("delivery_quarantined") is False
    assert approval.renotify_pending() == 1
    assert len(db.list_outbox_events()) == 2


def test_poll_ack_callback_acknowledges_alert(tmp_path, monkeypatch):
    sent: list = []
    approval, store = _approval(tmp_path, sent)
    approval.raise_persistent_alert("checkpoint", "checkpoint!")

    # Fake the external transport result; approval still performs real callback handling.
    monkeypatch.setattr(
        approval.transport,
        "get_updates",
        lambda *, offset=None: {
            "ok": True,
            "code": "ok",
            "result": [
                {
                    "update_id": 1,
                    "callback_query": {
                        "from": {"id": 12345},
                        "message": {"chat": {"id": 12345}},
                        "data": "ack:checkpoint",
                    },
                }
            ],
        },
    )

    handled = approval.poll_once()

    assert handled == 1
    assert store.get("checkpoint")["acknowledged"] is True
    # After ack, re-notify is a no-op.
    sent.clear()
    assert approval.renotify_pending() == 0


def test_clear_persistent_alert_removes_and_announces_recovery(tmp_path):
    sent: list = []
    approval, store = _approval(tmp_path, sent)
    approval.raise_persistent_alert("session_dead", "msg")
    sent.clear()

    approval.clear_persistent_alert("session_dead")

    assert store.get("session_dead") is None
    assert sent == []
    assert "復旧" in approval.db.list_outbox_events()[-1]["payload"]["text"]

    # Clearing again (nothing open) sends nothing.
    sent.clear()
    approval.clear_persistent_alert("session_dead")
    assert sent == []


def test_renotify_script_skips_poll_when_no_pending_alerts(tmp_path, monkeypatch):
    from scripts import renotify_alerts

    calls: list[str] = []

    class _Approval:
        def __init__(self, settings, db):
            pass

        def has_pending_alerts(self):
            return False

        def poll_once(self):
            calls.append("poll")
            raise AssertionError("poll_once should stay quiet with no pending alerts")

        def renotify_pending(self):
            calls.append("renotify")
            return 0

    monkeypatch.setattr(renotify_alerts, "TelegramApproval", _Approval)
    settings = _settings()
    settings.db_path = tmp_path / "jobs.db"
    summary = renotify_alerts.renotify(settings)

    assert summary == {"acks_processed": 0, "alerts_resent": 0}
    assert calls == ["renotify"]
