from __future__ import annotations

from typing import Iterable

from .actions import build_next_actions, infer_customer_status
from .analytics import build_kpi_summary
from .channels import get_channel_capabilities
from .models import CRMEvent


INBOUND_EVENTS = {"facebook_reaction", "messenger_inbound", "line_inbound", "email_inbound"}


def build_dashboard_payload(events: Iterable[CRMEvent]) -> dict[str, object]:
    event_list = list(events)
    statuses = infer_customer_status(event_list)
    next_actions = build_next_actions(event_list)
    channel_counts: dict[str, int] = {}
    recent_reactions: list[dict[str, object]] = []

    for event in sorted(event_list, key=lambda item: item.occurred_at, reverse=True):
        channel = str(event.payload.get("channel") or "facebook_messenger")
        channel_counts[channel] = channel_counts.get(channel, 0) + 1
        if event.event_type in INBOUND_EVENTS:
            recent_reactions.append(
                {
                    "customer_external_id": event.customer_external_id,
                    "customer_name": event.payload.get("customer_name") or event.customer_external_id,
                    "channel": channel,
                    "event_type": event.event_type,
                    "occurred_at": event.occurred_at,
                    "property_id": event.property_id,
                    "property_name": event.payload.get("property_name") or event.property_id,
                    "status": statuses.get(event.customer_external_id, "new_reaction"),
                }
            )

    return {
        "schema_version": "estateboard-crm-dashboard/v1",
        "kpi": build_kpi_summary(event_list),
        "channel_counts": channel_counts,
        "customer_statuses": statuses,
        "recent_reactions": recent_reactions[:10],
        "next_actions": [action.to_record() for action in next_actions[:10]],
        "channel_capabilities": get_channel_capabilities(),
    }
