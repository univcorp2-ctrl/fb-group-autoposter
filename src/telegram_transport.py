"""Small, bounded Telegram Bot API transport with safe operational outcomes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import requests

from .secret_redaction import redact

log = logging.getLogger(__name__)


class PreSubmitFailure(requests.RequestException):
    """A caller-proven failure that occurred before an HTTP request was submitted."""


HttpRequest = Callable[..., Any]


class TelegramTransport:
    """One-request Telegram operations; never retries ambiguous delivery."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        http_request: HttpRequest | None = None,
        timeout: int = 20,
    ):
        self.token = token
        self.chat_id = chat_id
        self._http_request = http_request or requests.request
        self.timeout = timeout
        self.inbound_mode = "disabled" if not token or not chat_id else "unknown"

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    @property
    def _secrets(self) -> tuple[str, ...]:
        return tuple(value for value in (self.token, self.chat_id) if value)

    def _url(self, endpoint: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{endpoint}"

    def _api(
        self, endpoint: str, *, http_method: str = "POST", payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "code": "disabled", "inbound_mode": "disabled"}
        try:
            kwargs: dict[str, Any] = {"timeout": self.timeout}
            if payload:
                kwargs["params" if http_method == "GET" else "json"] = payload
            response = self._http_request(http_method, self._url(endpoint), **kwargs)
            response.raise_for_status()
            data = response.json()
        except PreSubmitFailure:
            log.warning("telegram request did not submit endpoint=%s", endpoint)
            return {"ok": False, "code": "retryable_pre_submit"}
        except requests.Timeout:
            log.warning("telegram request timed out endpoint=%s", endpoint)
            return {"ok": False, "code": "delivery_ambiguous"}
        except requests.RequestException:
            log.warning("telegram request failed endpoint=%s", endpoint)
            return {"ok": False, "code": "transport_error"}
        except (TypeError, ValueError):
            log.warning("telegram response was invalid endpoint=%s", endpoint)
            return {"ok": False, "code": "invalid_response"}
        if not isinstance(data, dict) or data.get("ok") is not True:
            return {"ok": False, "code": "telegram_api_error"}
        return {"ok": True, "code": "ok", "result": redact(data.get("result"), secrets=self._secrets)}

    def get_me(self) -> dict[str, Any]:
        return self._api("getMe")

    def get_chat(self) -> dict[str, Any]:
        return self._api("getChat", payload={"chat_id": self.chat_id})

    def get_webhook_info(self) -> dict[str, Any]:
        return self._api("getWebhookInfo")

    @staticmethod
    def _inbound_mode_from_webhook(result: Any) -> str:
        if not isinstance(result, dict) or "url" not in result or not isinstance(result["url"], str):
            return "unknown"
        return "polling" if result["url"] == "" else "webhook"

    def probe(self) -> dict[str, Any]:
        """Read Telegram configuration without sending a message or changing state."""
        if not self.enabled:
            return {"ok": False, "code": "disabled", "inbound_mode": "disabled"}
        get_me = self.get_me()
        get_chat = self.get_chat()
        webhook = self.get_webhook_info()
        if not all(result.get("ok") for result in (get_me, get_chat, webhook)):
            self.inbound_mode = "unknown"
            return {"ok": False, "code": "probe_failed", "inbound_mode": self.inbound_mode}
        webhook_result = webhook.get("result")
        self.inbound_mode = self._inbound_mode_from_webhook(webhook_result)
        if self.inbound_mode == "unknown":
            return {"ok": False, "code": "probe_failed", "inbound_mode": self.inbound_mode}
        return {
            "ok": True,
            "code": "probed",
            "inbound_mode": self.inbound_mode,
            "get_me": get_me["result"],
            "get_chat": get_chat["result"],
            "webhook": webhook_result,
        }

    def get_updates(self, *, offset: int | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "code": "disabled", "inbound_mode": "disabled"}
        if self.inbound_mode == "unknown":
            webhook = self.get_webhook_info()
            if not webhook.get("ok"):
                return {"ok": False, "code": "inbound_mode_unknown", "inbound_mode": "unknown"}
            webhook_result = webhook.get("result")
            self.inbound_mode = self._inbound_mode_from_webhook(webhook_result)
            if self.inbound_mode == "unknown":
                return {"ok": False, "code": "inbound_mode_unknown", "inbound_mode": "unknown"}
        if self.inbound_mode == "webhook":
            return {"ok": False, "code": "webhook_active", "inbound_mode": "webhook"}
        payload: dict[str, Any] = {"timeout": 0}
        if offset is not None:
            payload["offset"] = offset
        result = self._api("getUpdates", http_method="GET", payload=payload)
        if result.get("ok"):
            self.inbound_mode = "polling"
            result["inbound_mode"] = self.inbound_mode
        return result

    def send_message(
        self, text: str, *, reply_markup: dict[str, Any] | None = None, disable_web_page_preview: bool = False
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": self.chat_id, "text": text[:4096]}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if disable_web_page_preview:
            payload["disable_web_page_preview"] = True
        result = self._api("sendMessage", payload=payload)
        if not result.get("ok"):
            return result
        message = result.get("result")
        message_id = message.get("message_id") if isinstance(message, dict) else None
        return {"ok": True, "code": "sent", "message_id": message_id}
