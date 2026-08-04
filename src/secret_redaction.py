"""Shared, defensive removal of credentials from operator-facing data."""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

_BOT_URL_TOKEN = re.compile(r"(https?://api\.telegram\.org/bot)([^/\s?#]+)", re.IGNORECASE)


def _redact_text(value: str, secrets: Sequence[str]) -> str:
    safe = _BOT_URL_TOKEN.sub(r"\1<telegram-token>", value)
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        replacement = "<telegram-chat-id>" if re.fullmatch(r"-?\d{5,}", secret) else "<secret>"
        if ":" in secret:
            replacement = "<telegram-token>"
        safe = safe.replace(secret, replacement)
    return safe


def redact(value: Any, *, secrets: Sequence[str] = ()) -> Any:
    """Return a structurally equivalent value with known Telegram secrets removed."""
    if isinstance(value, str):
        return _redact_text(value, secrets)
    if isinstance(value, BaseException):
        return _redact_text(str(value), secrets)
    if isinstance(value, int) and str(value) in secrets:
        return "<telegram-chat-id>"
    if isinstance(value, Mapping):
        return {redact(key, secrets=secrets): redact(item, secrets=secrets) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(redact(item, secrets=secrets) for item in value)
    if isinstance(value, list):
        return [redact(item, secrets=secrets) for item in value]
    if isinstance(value, set):
        return {redact(item, secrets=secrets) for item in value}
    return value


def redact_log_record(record: logging.LogRecord, *, secrets: Sequence[str] = ()) -> logging.LogRecord:
    """Copy a log record whose rendered message cannot expose supplied secrets."""
    safe = copy.copy(record)
    safe.msg = redact(record.getMessage(), secrets=secrets)
    safe.args = ()
    safe.exc_info = None
    safe.exc_text = None
    safe.stack_info = None
    return safe
