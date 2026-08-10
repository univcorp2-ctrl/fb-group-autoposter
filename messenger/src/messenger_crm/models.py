from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    SYSTEM = "system"


class DraftStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SENT_BY_HUMAN = "sent_by_human"
    REJECTED = "rejected"


@dataclass(frozen=True)
class MessengerMessage:
    external_id: str
    thread_id: str
    sender_name: str
    direction: str
    body: str
    sent_at: str
    attachments: list[str] = field(default_factory=list)

    def is_customer_message(self) -> bool:
        return self.direction == MessageDirection.INBOUND.value

    def to_record(self) -> dict[str, Any]:
        return {
            "external_id": self.external_id,
            "thread_id": self.thread_id,
            "sender_name": self.sender_name,
            "direction": self.direction,
            "body": self.body,
            "sent_at": self.sent_at,
            "attachments": self.attachments,
        }


@dataclass(frozen=True)
class ConversationSnapshot:
    thread_id: str
    customer_external_id: str
    customer_name: str
    source: str = "facebook_messenger"
    property_id: str | None = None
    post_id: str | None = None
    messages: list[MessengerMessage] = field(default_factory=list)
    captured_at: str = field(default_factory=utc_now_iso)
    tags: list[str] = field(default_factory=list)

    def last_message(self) -> MessengerMessage | None:
        if not self.messages:
            return None
        return sorted(self.messages, key=lambda message: message.sent_at)[-1]

    def last_customer_message(self) -> MessengerMessage | None:
        customer_messages = [message for message in self.messages if message.is_customer_message()]
        if not customer_messages:
            return None
        return sorted(customer_messages, key=lambda message: message.sent_at)[-1]

    def needs_reply(self) -> bool:
        """Return True when the latest message is from the customer.

        This keeps automation in draft-only mode. The result means "prepare a
        human-reviewed reply draft", not "send automatically".
        """

        latest = self.last_message()
        return bool(latest and latest.is_customer_message() and latest.body.strip())

    def snapshot_hash(self) -> str:
        return stable_hash(self.to_record())

    def to_record(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "customer_external_id": self.customer_external_id,
            "customer_name": self.customer_name,
            "source": self.source,
            "property_id": self.property_id,
            "post_id": self.post_id,
            "messages": [message.to_record() for message in self.messages],
            "captured_at": self.captured_at,
            "tags": self.tags,
        }


@dataclass(frozen=True)
class ReplyDraft:
    draft_id: str
    thread_id: str
    customer_external_id: str
    body: str
    intent: str
    confidence: float
    source_snapshot_hash: str
    status: str = DraftStatus.PENDING_APPROVAL.value
    created_at: str = field(default_factory=utc_now_iso)

    def to_record(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "thread_id": self.thread_id,
            "customer_external_id": self.customer_external_id,
            "body": self.body,
            "intent": self.intent,
            "confidence": self.confidence,
            "source_snapshot_hash": self.source_snapshot_hash,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class CRMEvent:
    event_id: str
    event_type: str
    customer_external_id: str
    thread_id: str | None = None
    property_id: str | None = None
    draft_id: str | None = None
    occurred_at: str = field(default_factory=utc_now_iso)
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(
        cls,
        *,
        event_type: str,
        customer_external_id: str,
        thread_id: str | None = None,
        property_id: str | None = None,
        draft_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> "CRMEvent":
        normalized_payload = payload or {}
        event_id = stable_hash(
            {
                "event_type": event_type,
                "customer_external_id": customer_external_id,
                "thread_id": thread_id,
                "property_id": property_id,
                "draft_id": draft_id,
                "payload": normalized_payload,
                "occurred_at": normalized_payload.get("occurred_at"),
            }
        )
        return cls(
            event_id=event_id,
            event_type=event_type,
            customer_external_id=customer_external_id,
            thread_id=thread_id,
            property_id=property_id,
            draft_id=draft_id,
            payload=normalized_payload,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "customer_external_id": self.customer_external_id,
            "thread_id": self.thread_id,
            "property_id": self.property_id,
            "draft_id": self.draft_id,
            "occurred_at": self.occurred_at,
            "payload": self.payload,
        }
