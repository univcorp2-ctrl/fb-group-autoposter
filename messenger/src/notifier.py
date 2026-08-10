"""Minimal Telegram notifier (self-contained; mirrors the autoposter's pattern).

Best-effort: if the bot token / chat id are unset it logs and no-ops. Never
raises into the caller — a notification failure must not break a scan run.
"""

from __future__ import annotations

import logging

from src.telegram_transport import TelegramTransport

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, *, transport: TelegramTransport | None = None):
        self.token = token
        self.chat_id = chat_id
        self.transport = transport or TelegramTransport(token, chat_id)

    @property
    def enabled(self) -> bool:
        return self.transport.enabled

    def send_message(self, text: str) -> bool:
        if not self.enabled:
            log.info("telegram disabled; message not sent")
            return False
        result = self.transport.send_message(text, disable_web_page_preview=True)
        if result.get("ok"):
            return True
        log.warning("telegram send failed: %s", result.get("code", "unknown"))
        return False
