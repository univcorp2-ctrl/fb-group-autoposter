from types import SimpleNamespace

import requests

from src.approval import TelegramApproval
from src.queue_db import QueueDB


def make_settings(chat_id="12345"):
    return SimpleNamespace(
        telegram_bot_token="fake-token",
        telegram_chat_id=chat_id,
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


def test_is_authorized_sender_accepts_matching_chat_id(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    approval = TelegramApproval(make_settings("12345"), db)
    callback = {"from": {"id": 67890}, "message": {"chat": {"id": 12345}}}
    assert approval._is_authorized_sender(callback) is True


def test_is_authorized_sender_handles_missing_from(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    approval = TelegramApproval(make_settings("12345"), db)
    callback = {"message": {"chat": {"id": 12345}}}
    assert approval._is_authorized_sender(callback) is True


def test_is_authorized_sender_handles_missing_message(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    approval = TelegramApproval(make_settings("12345"), db)
    callback = {"from": {"id": 12345}}
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
