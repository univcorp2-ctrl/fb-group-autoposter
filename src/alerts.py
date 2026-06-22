"""Persistent, acknowledge-until-cleared alert store.

Some failures — a dead FB login, a checkpoint/captcha/2FA challenge — cannot be
fixed by a retry; they need a human to re-login. For these, a single Telegram
"ping" is not enough: if the operator misses it, posting silently stays down.

This store records such alerts to a file so that a separate, frequently-run
re-notifier (`scripts/renotify_alerts.py`) keeps re-sending each one to Telegram
until the operator explicitly acknowledges it (taps the ✅ button) or the
condition clears on its own (a later healthy run calls `clear`). The state
survives process exits and reboots, so the obligation to notify is never lost.

Design notes:
  - One JSON file, written atomically (temp + os.replace) so a crash mid-write
    never corrupts the store.
  - `raise_alert` is idempotent per kind: re-raising an open alert refreshes its
    message and bumps an occurrence counter but never un-acknowledges it. An
    episode ends only at `clear` (recovery); the next failure after a clear is a
    fresh, unacknowledged alert that re-arms notifications.
  - The clock is injectable for tests.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

DEFAULT_PATH = Path("data/pending_alerts.json")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class AlertStore:
    """File-backed store of open alerts keyed by `kind` (e.g. "session_dead")."""

    def __init__(
        self,
        path: str | Path = DEFAULT_PATH,
        *,
        now_fn: Callable[[], str] = _now_iso,
    ) -> None:
        self.path = Path(path)
        self._now = now_fn

    # --- persistence -------------------------------------------------------
    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("alert store unreadable, starting empty: %s", exc)
            return {}
        alerts = data.get("alerts") if isinstance(data, dict) else None
        return alerts if isinstance(alerts, dict) else {}

    def _save(self, alerts: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"alerts": alerts}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    # --- mutations ---------------------------------------------------------
    def raise_alert(self, kind: str, message: str) -> dict[str, Any]:
        """Open `kind` (or refresh it if already open). Never un-acknowledges."""
        alerts = self._load()
        now = self._now()
        existing = alerts.get(kind)
        if existing:
            existing["message"] = message
            existing["last_raised"] = now
            existing["occurrences"] = int(existing.get("occurrences", 1)) + 1
            alert = existing
        else:
            alert = {
                "kind": kind,
                "message": message,
                "first_raised": now,
                "last_raised": now,
                "occurrences": 1,
                "acknowledged": False,
                "acknowledged_at": None,
                "notify_count": 0,
                "last_notified": None,
            }
            alerts[kind] = alert
        self._save(alerts)
        return dict(alert)

    def acknowledge(self, kind: str) -> bool:
        """Operator confirms they have seen `kind`; re-notification stops."""
        alerts = self._load()
        alert = alerts.get(kind)
        if not alert:
            return False
        alert["acknowledged"] = True
        alert["acknowledged_at"] = self._now()
        self._save(alerts)
        return True

    def mark_notified(self, kind: str) -> None:
        alerts = self._load()
        alert = alerts.get(kind)
        if not alert:
            return
        alert["notify_count"] = int(alert.get("notify_count", 0)) + 1
        alert["last_notified"] = self._now()
        self._save(alerts)

    def clear(self, kind: str) -> bool:
        """Condition resolved (e.g. session recovered): remove the alert."""
        alerts = self._load()
        if kind not in alerts:
            return False
        del alerts[kind]
        self._save(alerts)
        return True

    # --- queries -----------------------------------------------------------
    def get(self, kind: str) -> dict[str, Any] | None:
        alert = self._load().get(kind)
        return dict(alert) if alert else None

    def all(self) -> list[dict[str, Any]]:
        return [dict(a) for a in self._load().values()]

    def pending_unacknowledged(self) -> list[dict[str, Any]]:
        """Open alerts the operator has NOT acknowledged yet (need re-notify)."""
        return [dict(a) for a in self._load().values() if not a.get("acknowledged")]
