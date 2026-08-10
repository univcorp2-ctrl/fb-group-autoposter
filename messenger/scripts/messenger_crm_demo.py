from __future__ import annotations

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from messenger_crm import MessengerCRMRepository, MessengerMessage, ConversationSnapshot, ReplyDraftService, DraftContext
from messenger_crm.models import CRMEvent, MessageDirection


def main() -> int:
    db_path = ROOT / "data" / "messenger_crm_demo.db"
    output_path = ROOT.parent / "output" / "messenger_crm_snapshot.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    snapshot = ConversationSnapshot(
        thread_id="thread_demo_001",
        customer_external_id="customer_demo_001",
        customer_name="山田 太郎",
        property_id="property_demo_001",
        post_id="fb_post_demo_001",
        messages=[
            MessengerMessage(
                external_id="msg_demo_001",
                thread_id="thread_demo_001",
                sender_name="山田 太郎",
                direction=MessageDirection.INBOUND.value,
                body="この物件の資料と初期費用を知りたいです。",
                sent_at="2026-07-09T09:00:00+09:00",
            )
        ],
        tags=["demo", "materials"],
    )
    context = DraftContext(
        operator_name="Hiro",
        company_name="EstateBoard 物件紹介",
        property_payload={"title": "駅近1LDK", "area": "新宿", "price": "12万円", "layout": "1LDK"},
    )

    repository = MessengerCRMRepository(db_path)
    repository.upsert_snapshot(snapshot)
    draft = ReplyDraftService().create_draft(snapshot, context)
    if draft is None:
        raise RuntimeError("demo snapshot should create a reply draft")
    repository.save_draft(draft)
    repository.record_events(
        [
            CRMEvent.from_payload(
                event_type="messenger_inbound",
                customer_external_id=snapshot.customer_external_id,
                thread_id=snapshot.thread_id,
                property_id=snapshot.property_id,
                payload={"message_count": len(snapshot.messages)},
            ),
            CRMEvent.from_payload(
                event_type="draft_created",
                customer_external_id=snapshot.customer_external_id,
                thread_id=snapshot.thread_id,
                property_id=snapshot.property_id,
                draft_id=draft.draft_id,
                payload={"intent": draft.intent, "confidence": draft.confidence},
            ),
        ]
    )

    output_path.write_text(json.dumps(repository.export_estateboard_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
