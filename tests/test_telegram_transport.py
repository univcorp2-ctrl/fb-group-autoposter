from __future__ import annotations

from dataclasses import dataclass

import requests
import pytest

from src.telegram_transport import PreSubmitFailure, TelegramTransport


TOKEN = "123456:ABCdef-ghI_jklMNopQRstuVWXyz"
CHAT_ID = "-1001234567890"


@dataclass
class FakeResponse:
    payload: dict
    status_code: int = 200

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)

    def json(self):
        return self.payload


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _transport(http):
    return TelegramTransport(TOKEN, CHAT_ID, http_request=http)


def test_probe_reports_webhook_mode_and_redacts_all_returned_values():
    http = FakeHttp(
        [
            FakeResponse({"ok": True, "result": {"id": 7, "token": TOKEN}}),
            FakeResponse({"ok": True, "result": {"id": int(CHAT_ID), "title": "ops"}}),
            FakeResponse({"ok": True, "result": {"url": "https://example.test/hook"}}),
        ]
    )

    result = _transport(http).probe()

    assert result["ok"] is True
    assert result["inbound_mode"] == "webhook"
    assert TOKEN not in repr(result)
    assert CHAT_ID not in repr(result)
    assert [call[1].rsplit("/", 1)[-1] for call in http.calls] == ["getMe", "getChat", "getWebhookInfo"]


def test_active_webhook_prohibits_get_updates_but_permits_outbound_send():
    http = FakeHttp([FakeResponse({"ok": True, "result": {"message_id": 55}})])
    transport = _transport(http)
    transport.inbound_mode = "webhook"

    blocked = transport.get_updates()
    sent = transport.send_message("hello")

    assert blocked == {"ok": False, "code": "webhook_active", "inbound_mode": "webhook"}
    assert sent == {"ok": True, "code": "sent", "message_id": 55}
    assert len(http.calls) == 1
    assert http.calls[0][1].endswith("/sendMessage")


def test_unknown_mode_checks_webhook_before_polling_and_fails_closed_when_active():
    http = FakeHttp([FakeResponse({"ok": True, "result": {"url": "https://example.test/hook"}})])

    result = _transport(http).get_updates()

    assert result == {"ok": False, "code": "webhook_active", "inbound_mode": "webhook"}
    assert [call[1].rsplit("/", 1)[-1] for call in http.calls] == ["getWebhookInfo"]


def test_unknown_mode_fails_closed_when_webhook_probe_fails_without_polling():
    http = FakeHttp([requests.ConnectionError("unavailable")])

    result = _transport(http).get_updates()

    assert result == {"ok": False, "code": "inbound_mode_unknown", "inbound_mode": "unknown"}
    assert [call[1].rsplit("/", 1)[-1] for call in http.calls] == ["getWebhookInfo"]


@pytest.mark.parametrize("webhook_result", [None, [], {}, {"url": None}, {"url": 1}, {"url": False}])
def test_unknown_mode_fails_closed_for_malformed_webhook_success(webhook_result):
    http = FakeHttp([FakeResponse({"ok": True, "result": webhook_result})])

    result = _transport(http).get_updates()

    assert result == {"ok": False, "code": "inbound_mode_unknown", "inbound_mode": "unknown"}
    assert [call[1].rsplit("/", 1)[-1] for call in http.calls] == ["getWebhookInfo"]


def test_send_timeout_is_delivery_ambiguous_without_retry_or_secret_leak():
    http = FakeHttp([requests.Timeout(f"POST bot{TOKEN} chat {CHAT_ID}")])

    result = _transport(http).send_message("hello")

    assert result["ok"] is False
    assert result["code"] == "delivery_ambiguous"
    assert TOKEN not in repr(result)
    assert CHAT_ID not in repr(result)
    assert len(http.calls) == 1


def test_proven_pre_submit_failure_is_retryable_safe_code():
    http = FakeHttp([PreSubmitFailure(f"bad proxy for {TOKEN} {CHAT_ID}")])

    result = _transport(http).send_message("hello")

    assert result["ok"] is False
    assert result["code"] == "retryable_pre_submit"
    assert "error" not in result
    assert len(http.calls) == 1
