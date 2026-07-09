from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ResponseChannel(str, Enum):
    FACEBOOK_GROUP = "facebook_group"
    FACEBOOK_MESSENGER = "facebook_messenger"
    LINE_OFFICIAL = "line_official"
    EMAIL = "email"


class CustomerStatus(str, Enum):
    NEW_REACTION = "new_reaction"
    NEEDS_REPLY = "needs_reply"
    DRAFT_READY = "draft_ready"
    MATERIALS_SENT = "materials_sent"
    WAITING_CUSTOMER = "waiting_customer"
    FOLLOW_UP_DUE = "follow_up_due"
    VIEWING_SCHEDULED = "viewing_scheduled"
    CLOSED = "closed"


@dataclass(frozen=True)
class ChannelCapability:
    channel: str
    read_supported: bool
    draft_supported: bool
    send_supported: bool
    preferred_integration: str
    notes: str


@dataclass(frozen=True)
class NextAction:
    customer_external_id: str
    customer_name: str
    channel: str
    status: str
    priority: str
    action_label: str
    reason: str
    draft_hint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "customer_external_id": self.customer_external_id,
            "customer_name": self.customer_name,
            "channel": self.channel,
            "status": self.status,
            "priority": self.priority,
            "action_label": self.action_label,
            "reason": self.reason,
            "draft_hint": self.draft_hint,
            "metadata": self.metadata,
        }


DEFAULT_CHANNEL_CAPABILITIES: tuple[ChannelCapability, ...] = (
    ChannelCapability(
        channel=ResponseChannel.FACEBOOK_GROUP.value,
        read_supported=True,
        draft_supported=True,
        send_supported=False,
        preferred_integration="existing fb-group-autoposter queue + human approval",
        notes="投稿と反応を計測し、個別対応はCRM下書きと承認ログで管理します。",
    ),
    ChannelCapability(
        channel=ResponseChannel.FACEBOOK_MESSENGER.value,
        read_supported=True,
        draft_supported=True,
        send_supported=False,
        preferred_integration="manual browser session + Playwright assisted extraction",
        notes="Messengerの問い合わせを読み取り補助し、送信前に人間が下書きを確認します。",
    ),
    ChannelCapability(
        channel=ResponseChannel.LINE_OFFICIAL.value,
        read_supported=True,
        draft_supported=True,
        send_supported=True,
        preferred_integration="LINE Messaging API / webhook / rich menu",
        notes="公式APIでWebhook受信、顧客ID管理、承認後返信まで拡張できます。",
    ),
    ChannelCapability(
        channel=ResponseChannel.EMAIL.value,
        read_supported=True,
        draft_supported=True,
        send_supported=True,
        preferred_integration="IMAP/Gmail API + SMTP/Gmail API",
        notes="問い合わせメールを分類し、AI下書きと送信履歴をCRMイベント化します。",
    ),
)


def get_channel_capabilities() -> list[dict[str, Any]]:
    return [capability.__dict__ for capability in DEFAULT_CHANNEL_CAPABILITIES]
