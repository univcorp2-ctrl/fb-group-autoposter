"""Durable, credential-free delivery outbox facade.

This module deliberately contains no Telegram transport.  Producers record
delivery obligations here; a later worker may claim and send them.
"""

from __future__ import annotations

from typing import Any

from src.queue_db import QueueDB


class DeliveryOutbox:
    """Small producer/worker API over QueueDB's single SQLite outbox table."""

    def __init__(self, db: QueueDB):
        self.db = db

    def enqueue(self, **kwargs: Any) -> dict[str, Any]:
        return self.db.enqueue_outbox_event(**kwargs)

    def get(self, event_id: str) -> dict[str, Any] | None:
        return self.db.get_outbox_event(event_id)

    def list_events(self) -> list[dict[str, Any]]:
        return self.db.list_outbox_events()

    def claim(self, owner: str, *, limit: int = 1, lease_seconds: int = 60) -> list[dict[str, Any]]:
        return self.db.claim_outbox_events(owner, limit=limit, lease_seconds=lease_seconds)

    def claim_oldest_origin(
        self, owner: str, *, limit: int = 1, lease_seconds: int = 60
    ) -> list[dict[str, Any]]:
        return self.db.claim_outbox_events_for_oldest_origin(owner, limit=limit, lease_seconds=lease_seconds)

    def mark_delivered(self, event_id: str, owner: str, *, remote_message_id: str | None = None) -> dict[str, Any]:
        return self.db.mark_outbox_delivered(event_id, owner, remote_message_id=remote_message_id)

    def mark_failed(self, event_id: str, owner: str, error: str) -> dict[str, Any]:
        return self.db.mark_outbox_failed(event_id, owner, error)

    def mark_ambiguous(self, event_id: str, owner: str, error: str) -> dict[str, Any]:
        return self.db.mark_outbox_ambiguous(event_id, owner, error)

    def retry_or_fail(self, event_id: str, owner: str, error: str, *, max_attempts: int) -> dict[str, Any]:
        return self.db.retry_or_fail_outbox_event(event_id, owner, error, max_attempts=max_attempts)

    def renew_leases(self, event_ids: list[str], owner: str, *, lease_seconds: int = 60) -> set[str]:
        return self.db.renew_outbox_leases(event_ids, owner, lease_seconds=lease_seconds)

    def reset(
        self,
        event_id: str,
        *,
        operator: str | None = None,
        resolution: str | None = None,
        resolved_at: str | None = None,
    ) -> dict[str, Any]:
        return self.db.reset_outbox_event(
            event_id, operator=operator, resolution=resolution, resolved_at=resolved_at
        )
