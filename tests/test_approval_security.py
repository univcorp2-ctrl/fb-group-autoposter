from types import SimpleNamespace

import requests

from src.approval import TelegramApproval
from src.queue_db import QueueDB


def make_settings(chat_id="12345", authorized_user_id=""):
    return SimpleNamespace(
        telegram_bot_token="fake-token",
        telegram_chat_id=chat_id,
        telegram_authorized_user_id=authorized_user_id,
        auto_approve=False,
        auto_approve_skip_degraded=True,
    )


def test_is_authorized_sender_accepts_matching_from_id(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    approval = TelegramApproval(make_settings("12345"), db)
    callback = {"from": {"id": 12345}, "message": {"chat": {"id": 12345}}}
    assert approval._is_authorized_sender(callback) is True


def test_is_authorized_sender_rejects_unknown_sender(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    approval = TelegramApproval(make_settings("12345"), db)
    callback = {"from": {"id": 99999}, "message": {"chat": {"id": 99999}}}
    assert approval._is_authorized_sender(callback) is False


def test_is_authorized_sender_rejects_matching_message_chat_without_matching_sender(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    approval = TelegramApproval(make_settings("12345"), db)
    callback = {"from": {"id": 67890}, "message": {"chat": {"id": 12345}}}
    assert approval._is_authorized_sender(callback) is False


def test_is_authorized_sender_handles_missing_from(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    approval = TelegramApproval(make_settings("12345"), db)
    callback = {"message": {"chat": {"id": 12345}}}
    assert approval._is_authorized_sender(callback) is False


def test_is_authorized_sender_handles_missing_message(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    approval = TelegramApproval(make_settings("12345"), db)
    callback = {"from": {"id": 12345}}
    assert approval._is_authorized_sender(callback) is True


def test_is_authorized_sender_rejects_shared_chat_without_explicit_user(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    approval = TelegramApproval(make_settings("-1001234567890"), db)
    callback = {"from": {"id": 777}, "message": {"chat": {"id": -1001234567890}}}

    assert approval._is_authorized_sender(callback) is False


def test_is_authorized_sender_accepts_explicit_authorized_user_in_shared_chat(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    approval = TelegramApproval(make_settings("-1001234567890", authorized_user_id="777"), db)
    callback = {"from": {"id": 777}, "message": {"chat": {"id": -1001234567890}}}

    assert approval._is_authorized_sender(callback) is True


def test_sanitize_error_removes_telegram_token(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    approval = TelegramApproval(make_settings("12345"), db)
    exc = requests.RequestException(
        "GET https://api.telegram.org/botfake-token/getUpdates failed"
    )

    sanitized = approval._sanitize_error(exc)

    assert "fake-token" not in sanitized
    assert "<telegram-token>" in sanitized


def test_persistent_alert_failure_log_never_contains_token_or_chat_id(tmp_path, caplog):
    class Transport:
        enabled = True

        def send_message(self, *args, **kwargs):
            raise requests.RequestException("failed botfake-token for chat 12345")

    db = QueueDB(tmp_path / "jobs.db")
    approval = TelegramApproval(make_settings("12345"), db, transport=Transport())

    approval.send_persistent_alert("session_dead", "re-login")

    assert "fake-token" not in caplog.text
    assert "12345" not in caplog.text
