"""Minimal Telegram notifier for the Messenger draft assistant.

This module is intentionally self-contained. It sends at most one Bot API
request per notification, never retries an ambiguous delivery, never logs the
bot token/chat id, and never lets notification failure abort the Messenger scan.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

import requests

log = logging.getLogger(__name__)


class TelegramTransportLike(Protocol):
    @property
    def enabled(self) -> bool: ...

    def send_message(
        self,
        text: str,
        *,
        disable_web_page_preview: bool = False,
    ) -> dict[str, Any]: ...


class TelegramTransport:
    """Single-request outbound Telegram transport with no automatic retry."""

    def __init__(self, token: str, chat_id: str, *, timeout: int = 20):
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send_message(
        self,
        text: str,
        *,
        disable_web_page_preview: bool = False,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "code": "disabled"}

        payload: dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text[:4096],
        }
        if disable_web_page_preview:
            payload["disable_web_page_preview"] = True

        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout:
            log.warning("telegram notification timed out; delivery is ambiguous")
            return {"ok": False, "code": "delivery_ambiguous"}
        except requests.RequestException:
            log.warning("telegram notification transport failed")
            return {"ok": False, "code": "transport_error"}
        except (TypeError, ValueError):
            log.warning("telegram notification returned invalid JSON")
            return {"ok": False, "code": "invalid_response"}

        if not isinstance(data, dict) or data.get("ok") is not True:
            return {"ok": False, "code": "telegram_api_error"}
        result = data.get("result")
        message_id = result.get("message_id") if isinstance(result, dict) else None
        return {"ok": True, "code": "sent", "message_id": message_id}


class TelegramNotifier:
    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        transport: TelegramTransportLike | None = None,
    ):
        self.transport = transport or TelegramTransport(token, chat_id)

    @property
    def enabled(self) -> bool:
        return self.transport.enabled

    def send_message(self, text: str) -> bool:
        if not self.enabled:
            log.info("telegram disabled; message not sent")
            return False
        result = self.transport.send_message(
            text,
            disable_web_page_preview=True,
        )
        if result.get("ok"):
            return True
        log.warning("telegram send failed: %s", result.get("code", "unknown"))
        return False
