from types import SimpleNamespace

from src.approval import TelegramApproval
from src.queue_db import QueueDB


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
