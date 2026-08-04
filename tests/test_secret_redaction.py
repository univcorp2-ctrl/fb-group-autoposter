import logging

from src.secret_redaction import redact, redact_log_record


TOKEN = "123456:ABCdef-ghI_jklMNopQRstuVWXyz"
CHAT_ID = "-1001234567890"


def test_redact_removes_exact_values_and_telegram_url_segments():
    text = (
        f"token={TOKEN} chat={CHAT_ID} "
        f"https://api.telegram.org/bot{TOKEN}/sendMessage?chat_id={CHAT_ID}"
    )

    safe = redact(text, secrets=[TOKEN, CHAT_ID])

    assert TOKEN not in safe
    assert CHAT_ID not in safe
    assert "<telegram-token>" in safe
    assert "<telegram-chat-id>" in safe


def test_redact_sanitizes_nested_results_and_request_exception_text():
    payload = {
        "request": {"url": f"https://api.telegram.org/bot{TOKEN}/getMe"},
        "result": [{"chat": {"id": CHAT_ID}, "error": f"bot{TOKEN} rejected {CHAT_ID}"}],
    }

    safe = redact(payload, secrets=[TOKEN, CHAT_ID])

    assert TOKEN not in repr(safe)
    assert CHAT_ID not in repr(safe)
    assert safe["request"]["url"].endswith("bot<telegram-token>/getMe")
    assert safe["result"][0]["chat"]["id"] == "<telegram-chat-id>"


def test_redact_removes_numeric_chat_ids_returned_by_api_results():
    safe = redact({"id": int(CHAT_ID)}, secrets=[CHAT_ID])

    assert safe == {"id": "<telegram-chat-id>"}


def test_redact_log_record_removes_secret_from_message_and_args():
    record = logging.LogRecord(
        "telegram", logging.ERROR, __file__, 1, "failed %s for %s", (TOKEN, CHAT_ID), None
    )

    safe = redact_log_record(record, secrets=[TOKEN, CHAT_ID])

    assert TOKEN not in safe.getMessage()
    assert CHAT_ID not in safe.getMessage()
