"""Local JSON state: remember which thread states we have already drafted for, so
re-runs do not re-notify about an unchanged conversation.

State key = thread_id. We store a fingerprint of the last message preview; when a
NEW message arrives (preview changes) the thread is considered "fresh" again and a
new draft is produced.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def _fingerprint(preview: str) -> str:
    return hashlib.sha256((preview or "").encode("utf-8")).hexdigest()[:16]


class ThreadStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._state: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._state = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 - corrupt state should not crash
                log.warning("could not read state, starting fresh: %s", exc)
                self._state = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_new_state(self, thread_id: str, preview: str) -> bool:
        """True when this thread has no record, or its last message changed since
        we last drafted for it."""
        prev = self._state.get(str(thread_id))
        if prev is None:
            return True
        return prev.get("fingerprint") != _fingerprint(preview)

    def mark_drafted(self, thread_id: str, preview: str, *, drafted_at: str) -> None:
        self._state[str(thread_id)] = {
            "fingerprint": _fingerprint(preview),
            "drafted_at": drafted_at,
        }
