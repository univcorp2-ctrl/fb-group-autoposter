from types import SimpleNamespace

from src.approval import TelegramApproval
from src.queue_db import QueueDB
from src.telegram_transport import TelegramTransport


def settings(auto=True, telegram=False):
    return SimpleNamespace(
        telegram_bot_token="fake-token" if telegram else "",
        telegram_chat_id="12345" if telegram else "",
        auto_approve=auto,
        auto_approve_skip_degraded=True,
    )


def test_auto_approve_marks_non_degraded_job(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "p", "title": "A"}, [{"group_id": "g", "body": "body"}], degraded=False)
    approval = TelegramApproval(settings(auto=True, telegram=True), db)
    sent = []
    approval._post = lambda method, payload: sent.append((method, payload)) or {"ok": True}

    approval.auto_or_send_preview(job_id)

    assert db.get_job(job_id)["status"] == "approved"
    assert sent == []


def test_auto_approve_skips_degraded_when_configured(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "p", "title": "A"}, [{"group_id": "g", "body": "body"}], degraded=True)
    approval = TelegramApproval(settings(auto=True), db)
    approval.auto_or_send_preview(job_id)
    assert db.get_job(job_id)["status"] == "pending"


def test_send_message_delegates_composed_payload_to_transport(tmp_path):
    class Transport:
        enabled = True

        def __init__(self):
            self.calls = []

        def send_message(self, text, *, reply_markup=None, disable_web_page_preview=False):
            self.calls.append((text, reply_markup, disable_web_page_preview))
            return {"ok": True, "code": "sent", "message_id": 7}

    db = QueueDB(tmp_path / "jobs.db")
    transport = Transport()
    approval = TelegramApproval(settings(auto=False, telegram=True), db, transport=transport)

    approval.send_message("safe message", reply_markup={"inline_keyboard": []})

    assert transport.calls == [("safe message", {"inline_keyboard": []}, False)]


def test_poll_once_with_fresh_transport_checks_webhook_before_polling(tmp_path):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True, "result": {"url": "https://example.test/hook"}}

    calls = []

    def http_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return Response()

    db = QueueDB(tmp_path / "jobs.db")
    transport = TelegramTransport("123456:fake_token_abcdefghijklmnop", "12345", http_request=http_request)
    approval = TelegramApproval(settings(auto=False, telegram=True), db, transport=transport)

    assert approval.poll_once() == 0
    assert [url.rsplit("/", 1)[-1] for _, url, _ in calls] == ["getWebhookInfo"]
