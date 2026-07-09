from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from messenger_crm.actions import build_next_actions, infer_customer_status
from messenger_crm.channels import CustomerStatus, ResponseChannel, get_channel_capabilities
from messenger_crm.dashboard_payload import build_dashboard_payload
from messenger_crm.models import CRMEvent


def event(event_type: str, customer: str, channel: str, occurred_at: str) -> CRMEvent:
    return CRMEvent(
        event_id=f"{event_type}-{customer}",
        event_type=event_type,
        customer_external_id=customer,
        thread_id=f"thread-{customer}",
        property_id="property-001",
        occurred_at=occurred_at,
        payload={"channel": channel, "customer_name": f"顧客{customer}"},
    )


def test_channel_capabilities_include_required_response_channels() -> None:
    channels = {item["channel"] for item in get_channel_capabilities()}
    assert ResponseChannel.FACEBOOK_GROUP.value in channels
    assert ResponseChannel.LINE_OFFICIAL.value in channels
    assert ResponseChannel.FACEBOOK_MESSENGER.value in channels
    assert ResponseChannel.EMAIL.value in channels


def test_status_and_next_action_for_inbound_customer() -> None:
    events = [event("line_inbound", "001", ResponseChannel.LINE_OFFICIAL.value, "2026-07-09T00:00:00+00:00")]
    statuses = infer_customer_status(events)
    actions = build_next_actions(events, now=datetime(2026, 7, 9, 3, 0, tzinfo=timezone.utc))
    assert statuses["001"] == CustomerStatus.NEEDS_REPLY.value
    assert actions[0].priority == "high"
    assert actions[0].action_label == "返信下書きを確認"


def test_follow_up_alert_after_waiting_customer_for_24_hours() -> None:
    events = [event("materials_sent", "002", ResponseChannel.EMAIL.value, "2026-07-07T00:00:00+00:00")]
    actions = build_next_actions(events, now=datetime(2026, 7, 9, 1, 0, tzinfo=timezone.utc))
    assert actions[0].status == CustomerStatus.FOLLOW_UP_DUE.value
    assert actions[0].priority == "medium"
    assert "24時間" in actions[0].reason


def test_dashboard_payload_contains_one_screen_sections() -> None:
    events = [
        event("facebook_reaction", "001", ResponseChannel.FACEBOOK_GROUP.value, "2026-07-09T00:00:00+00:00"),
        event("line_inbound", "002", ResponseChannel.LINE_OFFICIAL.value, "2026-07-09T01:00:00+00:00"),
        event("email_inbound", "003", ResponseChannel.EMAIL.value, "2026-07-09T02:00:00+00:00"),
        event("draft_created", "003", ResponseChannel.EMAIL.value, "2026-07-09T02:10:00+00:00"),
    ]
    payload = build_dashboard_payload(events)
    assert payload["schema_version"] == "estateboard-crm-dashboard/v1"
    assert payload["channel_counts"][ResponseChannel.LINE_OFFICIAL.value] == 1
    assert len(payload["recent_reactions"]) == 3
    assert len(payload["next_actions"]) >= 1
