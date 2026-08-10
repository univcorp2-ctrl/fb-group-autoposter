"""Minimal Telegram notifier (self-contained; mirrors the autoposter's pattern).

Best-effort: if the bot token / chat id are unset it logs and no-ops. Never
raises into the caller — a notification failure must not break a scan run.
"""

from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}" if token else ""

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send_message(self, text: str) -> bool:
        if not self.enabled:
            log.info("telegram disabled; message not sent")
            return False
        try:
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": text[:4096], "disable_web_page_preview": True},
                timeout=20,
            )
            resp.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001 - notification must never crash the run
            sanitized = str(exc).replace(self.token, "<telegram-token>") if self.token else str(exc)
            log.warning("telegram send failed: %s", sanitized[:300])
            return False
