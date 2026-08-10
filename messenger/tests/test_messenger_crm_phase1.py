from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from messenger_crm import MessengerCRMRepository, ReplyDraftService, DraftContext, build_kpi_summary
from messenger_crm.analytics import calculate_reaction_rate
from messenger_crm.models import CRMEvent, ConversationSnapshot, MessengerMessage, MessageDirection


def sample_snapshot() -> ConversationSnapshot:
    return ConversationSnapshot(
        thread_id="thread_001",
        customer_external_id="customer_001",
        customer_name="佐藤 花子",
        property_id="property_001",
        post_id="post_001",
        messages=[
            MessengerMessage(
                external_id="msg_001",
                thread_id="thread_001",
                sender_name="佐藤 花子",
                direction=MessageDirection.INBOUND.value,
                body="資料を送ってください。内見も可能ですか？",
                sent_at="2026-07-09T08:30:00+09:00",
            )
        ],
    )


def test_snapshot_needs_reply_when_latest_message_is_customer() -> None:
    snapshot = sample_snapshot()
    assert snapshot.needs_reply() is True
    assert snapshot.last_customer_message() is not None


def test_reply_draft_is_draft_only_and_mentions_property() -> None:
    draft = ReplyDraftService().create_draft(
        sample_snapshot(),
        DraftContext(property_payload={"title": "代々木1LDK", "area": "代々木", "price": "13万円"}),
    )
    assert draft is not None
    assert draft.status == "pending_approval"
    assert "代々木1LDK" in draft.body
    assert "送信しました" not in draft.body
    assert draft.intent in {"materials_request", "viewing_request"}


def test_repository_exports_estateboard_payload(tmp_path: Path) -> None:
    repository = MessengerCRMRepository(tmp_path / "crm.db")
    snapshot = sample_snapshot()
    draft = ReplyDraftService().create_draft(snapshot, DraftContext())
    assert draft is not None

    repository.upsert_snapshot(snapshot)
    repository.save_draft(draft)
    repository.record_event(
        CRMEvent.from_payload(
            event_type="draft_created",
            customer_external_id=snapshot.customer_external_id,
            thread_id=snapshot.thread_id,
            property_id=snapshot.property_id,
            draft_id=draft.draft_id,
            payload={"intent": draft.intent},
        )
    )

    payload = repository.export_estateboard_payload()
    assert payload["schema_version"] == "messenger-crm-phase1/v1"
    assert payload["summary"]["customers"] == 1
    assert payload["summary"]["pending_approval"] == 1
    assert payload["events"][0]["event_type"] == "draft_created"


def test_kpi_summary_and_reaction_rate() -> None:
    events = [
        CRMEvent.from_payload(event_type="materials_sent", customer_external_id="c1"),
        CRMEvent.from_payload(event_type="follow_up_sent", customer_external_id="c1"),
        CRMEvent.from_payload(event_type="customer_replied_after_action", customer_external_id="c1"),
        CRMEvent.from_payload(event_type="draft_created", customer_external_id="c2"),
    ]
    summary = build_kpi_summary(events)
    assert calculate_reaction_rate(2, 1) == 50.0
    assert summary["unique_customers"] == 2
    assert summary["reaction_rate_percent"] == 50.0
