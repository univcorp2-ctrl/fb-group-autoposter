"""Minimal Telegram notifier (self-contained; mirrors the autoposter's pattern).

Best-effort: if the bot token / chat id are unset it logs and no-ops. Never
raises into the caller — a notification failure must not break a scan run.
"""

from __future__ import annotations

import importlib
import logging
import sys
import types
from pathlib import Path
from typing import Any


def _shared_transport_type():
    """Load the parent transport under an alias to avoid this role's `src` name clash."""
    package_name = "_fb_group_autoposter_shared"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(Path(__file__).resolve().parents[2] / "src")]
        sys.modules[package_name] = package
    return importlib.import_module(f"{package_name}.telegram_transport").TelegramTransport


TelegramTransport = _shared_transport_type()

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, *, transport: Any | None = None):
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
        try:
            result = self.transport.send_message(text, disable_web_page_preview=True)
            if result.get("ok"):
                return True
            log.warning("telegram send failed: code=%s", result.get("code", "unknown"))
        except Exception:  # noqa: BLE001 - notification must never crash the run
            log.warning("telegram send failed: code=unexpected")
            return False
        return False
