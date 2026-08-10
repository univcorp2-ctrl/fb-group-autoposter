from __future__ import annotations

from collections import Counter
from typing import Iterable

from .models import CRMEvent


def calculate_reaction_rate(sent_actions: int, customer_replies: int) -> float:
    """Return customer reaction rate as a percentage rounded to one decimal."""

    if sent_actions <= 0:
        return 0.0
    return round((customer_replies / sent_actions) * 100, 1)


def build_kpi_summary(events: Iterable[CRMEvent]) -> dict[str, object]:
    event_list = list(events)
    counts = Counter(event.event_type for event in event_list)
    unique_customers = {event.customer_external_id for event in event_list if event.customer_external_id}
    sent_actions = counts["materials_sent"] + counts["follow_up_sent"] + counts["draft_sent_by_human"]
    customer_replies = counts["customer_replied_after_action"] + counts["messenger_inbound"]
    return {
        "total_events": len(event_list),
        "unique_customers": len(unique_customers),
        "drafts_created": counts["draft_created"],
        "materials_sent": counts["materials_sent"],
        "follow_ups_sent": counts["follow_up_sent"],
        "customer_replies": customer_replies,
        "reaction_rate_percent": calculate_reaction_rate(sent_actions, customer_replies),
        "event_counts": dict(counts),
    }
