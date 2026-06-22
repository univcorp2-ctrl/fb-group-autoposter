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


def test_raise_persistent_alert_records_and_sends_with_ack_button(tmp_path):
    sent: list = []
    approval, store = _approval(tmp_path, sent)

    approval.raise_persistent_alert("session_dead", "再ログインしてください")

    alert = store.get("session_dead")
    assert alert is not None and alert["acknowledged"] is False
    assert alert["notify_count"] == 1
    # The single send carries an inline ✅ ack button with callback ack:session_dead.
    assert len(sent) == 1
    _, payload = sent[0]
    button = payload["reply_markup"]["inline_keyboard"][0][0]
    assert button["callback_data"] == "ack:session_dead"


def test_renotify_resends_until_acknowledged(tmp_path):
    sent: list = []
    approval, store = _approval(tmp_path, sent)
    approval.raise_persistent_alert("session_dead", "msg")
    sent.clear()

    # Two re-notify passes while unacknowledged -> two more sends.
    assert approval.renotify_pending() == 1
    assert approval.renotify_pending() == 1
    assert len(sent) == 2
    assert store.get("session_dead")["notify_count"] == 3  # 1 initial + 2 resends

    # Operator acknowledges -> no longer re-sent.
    store.acknowledge("session_dead")
    sent.clear()
    assert approval.renotify_pending() == 0
    assert sent == []


def test_poll_ack_callback_acknowledges_alert(tmp_path, monkeypatch):
    sent: list = []
    approval, store = _approval(tmp_path, sent)
    approval.raise_persistent_alert("checkpoint", "checkpoint!")

    # Stub Telegram getUpdates to return an authorized ✅ tap on the alert.
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "result": [
                    {
                        "update_id": 1,
                        "callback_query": {
                            "from": {"id": 12345},
                            "message": {"chat": {"id": 12345}},
                            "data": "ack:checkpoint",
                        },
                    }
                ]
            }

    monkeypatch.setattr("src.approval.requests.get", lambda *a, **k: _Resp())

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
    assert len(sent) == 1  # a recovery notice was sent
    assert "復旧" in sent[0][1]["text"]

    # Clearing again (nothing open) sends nothing.
    sent.clear()
    approval.clear_persistent_alert("session_dead")
    assert sent == []
