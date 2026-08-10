from __future__ import annotations

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from messenger_crm import build_dashboard_payload
from messenger_crm.models import CRMEvent


SAMPLE_EVENTS = [
    CRMEvent(
        event_id="ev-fb-001",
        event_type="facebook_reaction",
        customer_external_id="fb-user-001",
        thread_id="fb-thread-001",
        property_id="prop-shinjuku-1ldk",
        occurred_at="2026-07-09T00:05:00+00:00",
        payload={"channel": "facebook_group", "customer_name": "山田 太郎", "property_name": "新宿駅近1LDK"},
    ),
    CRMEvent(
        event_id="ev-msg-001",
        event_type="messenger_inbound",
        customer_external_id="msg-user-002",
        thread_id="msg-thread-002",
        property_id="prop-shibuya-studio",
        occurred_at="2026-07-09T00:25:00+00:00",
        payload={"channel": "facebook_messenger", "customer_name": "佐藤 花子", "property_name": "渋谷ワンルーム"},
    ),
    CRMEvent(
        event_id="ev-line-001",
        event_type="line_inbound",
        customer_external_id="line-user-003",
        thread_id="line-thread-003",
        property_id="prop-ikebukuro-2dk",
        occurred_at="2026-07-09T01:10:00+00:00",
        payload={"channel": "line_official", "customer_name": "鈴木 一郎", "property_name": "池袋2DK"},
    ),
    CRMEvent(
        event_id="ev-email-001",
        event_type="email_inbound",
        customer_external_id="email-user-004",
        thread_id="email-thread-004",
        property_id="prop-yokohama-1ldk",
        occurred_at="2026-07-09T01:20:00+00:00",
        payload={"channel": "email", "customer_name": "田中 美咲", "property_name": "横浜1LDK"},
    ),
    CRMEvent(
        event_id="ev-email-draft-001",
        event_type="draft_created",
        customer_external_id="email-user-004",
        thread_id="email-thread-004",
        property_id="prop-yokohama-1ldk",
        draft_id="draft-email-004",
        occurred_at="2026-07-09T01:22:00+00:00",
        payload={"channel": "email", "customer_name": "田中 美咲", "property_name": "横浜1LDK"},
    ),
    CRMEvent(
        event_id="ev-materials-001",
        event_type="materials_sent",
        customer_external_id="line-user-005",
        thread_id="line-thread-005",
        property_id="prop-nakano-1k",
        occurred_at="2026-07-07T00:00:00+00:00",
        payload={"channel": "line_official", "customer_name": "高橋 健", "property_name": "中野1K"},
    ),
    CRMEvent(
        event_id="ev-materials-reply-001",
        event_type="customer_replied_after_action",
        customer_external_id="line-user-005",
        thread_id="line-thread-005",
        property_id="prop-nakano-1k",
        occurred_at="2026-07-08T08:00:00+00:00",
        payload={"channel": "line_official", "customer_name": "高橋 健", "property_name": "中野1K"},
    ),
]


def main() -> int:
    output_path = ROOT.parent / "output" / "estateboard_crm_dashboard.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(build_dashboard_payload(SAMPLE_EVENTS), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
