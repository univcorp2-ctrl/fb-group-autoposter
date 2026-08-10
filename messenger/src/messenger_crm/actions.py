from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

from .channels import CustomerStatus, NextAction, ResponseChannel
from .models import CRMEvent


def _parse_iso(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _hours_since(value: str, now: datetime | None = None) -> float:
    current = now or datetime.now(timezone.utc)
    return max((current - _parse_iso(value)).total_seconds() / 3600, 0.0)


def infer_customer_status(events: Iterable[CRMEvent]) -> dict[str, str]:
    """Infer the latest CRM status per customer from chronological events."""

    grouped: dict[str, list[CRMEvent]] = defaultdict(list)
    for event in events:
        grouped[event.customer_external_id].append(event)

    statuses: dict[str, str] = {}
    for customer_id, customer_events in grouped.items():
        ordered = sorted(customer_events, key=lambda event: event.occurred_at)
        latest = ordered[-1]
        event_types = [event.event_type for event in ordered]
        if latest.event_type in {CustomerStatus.VIEWING_SCHEDULED.value, CustomerStatus.CLOSED.value}:
            statuses[customer_id] = latest.event_type
        elif latest.event_type == "draft_created" or ("draft_created" in event_types and latest.event_type.endswith("_draft_ready")):
            statuses[customer_id] = CustomerStatus.DRAFT_READY.value
        elif latest.event_type in {"messenger_inbound", "line_inbound", "email_inbound", "facebook_reaction"}:
            statuses[customer_id] = CustomerStatus.NEEDS_REPLY.value
        elif latest.event_type in {"materials_sent", "draft_sent_by_human", "line_reply_sent", "email_reply_sent"}:
            statuses[customer_id] = CustomerStatus.WAITING_CUSTOMER.value
        elif latest.event_type == "follow_up_due":
            statuses[customer_id] = CustomerStatus.FOLLOW_UP_DUE.value
        else:
            statuses[customer_id] = CustomerStatus.NEW_REACTION.value
    return statuses


def build_next_actions(events: Iterable[CRMEvent], now: datetime | None = None) -> list[NextAction]:
    """Build prioritized next actions for the one-screen CRM dashboard."""

    grouped: dict[str, list[CRMEvent]] = defaultdict(list)
    for event in events:
        grouped[event.customer_external_id].append(event)

    actions: list[NextAction] = []
    for customer_id, customer_events in grouped.items():
        ordered = sorted(customer_events, key=lambda event: event.occurred_at)
        latest = ordered[-1]
        customer_name = str(latest.payload.get("customer_name") or customer_id)
        channel = str(latest.payload.get("channel") or _channel_from_event(latest.event_type))
        status = infer_customer_status(customer_events)[customer_id]
        hours_elapsed = _hours_since(latest.occurred_at, now)

        if status == CustomerStatus.NEEDS_REPLY.value:
            actions.append(
                NextAction(
                    customer_external_id=customer_id,
                    customer_name=customer_name,
                    channel=channel,
                    status=status,
                    priority="high",
                    action_label="返信下書きを確認",
                    reason="顧客からの最新反応にまだ返信がありません。",
                    draft_hint="問い合わせ内容を要約し、資料送付・内見希望・条件相談のどれかを確認します。",
                    metadata={"hours_since_latest_event": round(hours_elapsed, 1)},
                )
            )
        elif status == CustomerStatus.DRAFT_READY.value:
            actions.append(
                NextAction(
                    customer_external_id=customer_id,
                    customer_name=customer_name,
                    channel=channel,
                    status=status,
                    priority="high",
                    action_label="下書きを承認して送信",
                    reason="AI下書きが作成済みですが、まだ承認が完了していません。",
                    metadata={"hours_since_latest_event": round(hours_elapsed, 1)},
                )
            )
        elif status == CustomerStatus.WAITING_CUSTOMER.value and hours_elapsed >= 24:
            actions.append(
                NextAction(
                    customer_external_id=customer_id,
                    customer_name=customer_name,
                    channel=channel,
                    status=CustomerStatus.FOLLOW_UP_DUE.value,
                    priority="medium",
                    action_label="フォローアップ下書きを作成",
                    reason="資料送付または返信後、24時間以上反応が止まっています。",
                    draft_hint="資料をご覧になったか、内見希望日があるかを軽く確認します。",
                    metadata={"hours_since_latest_event": round(hours_elapsed, 1)},
                )
            )
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(actions, key=lambda action: (priority_order.get(action.priority, 9), action.customer_name))


def _channel_from_event(event_type: str) -> str:
    if event_type.startswith("line_"):
        return ResponseChannel.LINE_OFFICIAL.value
    if event_type.startswith("email_"):
        return ResponseChannel.EMAIL.value
    if event_type.startswith("facebook_"):
        return ResponseChannel.FACEBOOK_GROUP.value
    return ResponseChannel.FACEBOOK_MESSENGER.value
