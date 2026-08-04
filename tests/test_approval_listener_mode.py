from __future__ import annotations

from types import SimpleNamespace

from src.approval import TelegramApproval
from src.queue_db import QueueDB


def _settings():
    return SimpleNamespace(
        telegram_bot_token="123456:fake_token_abcdefghijklmnop",
        telegram_chat_id="12345",
        telegram_authorized_user_id="12345",
        auto_approve=False,
        auto_approve_skip_degraded=True,
    )


class FakeTransport:
    enabled = True

    def __init__(self, webhook_response, update_response=None):
        self.webhook_response = webhook_response
        self.update_response = update_response or {"ok": True, "result": []}
        self.calls: list[str] = []

    def get_webhook_info(self):
        self.calls.append("getWebhookInfo")
        return self.webhook_response

    def get_updates(self, *, offset=None):
        self.calls.append("getUpdates")
        return self.update_response


def test_active_webhook_is_a_successful_noop_without_getupdates(tmp_path):
    transport = FakeTransport({"ok": True, "result": {"url": "https://example.test/callback"}})
    approval = TelegramApproval(_settings(), QueueDB(tmp_path / "jobs.db"), transport=transport)

    assert approval.poll_once() == 0
    assert approval.last_poll_reason == "telegram_webhook_owns_callbacks"
    assert transport.calls == ["getWebhookInfo"]
    assert approval.db.list_outbox_events() == []


def test_unknown_webhook_state_fails_closed_and_queues_alert(tmp_path):
    transport = FakeTransport({"ok": True, "result": {"url": None}})
    approval = TelegramApproval(_settings(), QueueDB(tmp_path / "jobs.db"), transport=transport)

    assert approval.poll_once() == 0
    assert approval.last_poll_reason == "telegram_webhook_state_unknown"
    events = approval.db.list_outbox_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "persistent_alert"
    assert transport.calls == ["getWebhookInfo"]


def test_polling_requires_a_fresh_explicit_empty_webhook_url(tmp_path):
    transport = FakeTransport(
        {"ok": True, "result": {"url": ""}},
        {"ok": True, "result": []},
    )
    transport.inbound_mode = "polling"
    approval = TelegramApproval(_settings(), QueueDB(tmp_path / "jobs.db"), transport=transport)

    assert approval.poll_once() == 0
    assert approval.last_poll_reason == "telegram_polled"
    assert transport.calls == ["getWebhookInfo", "getUpdates"]
