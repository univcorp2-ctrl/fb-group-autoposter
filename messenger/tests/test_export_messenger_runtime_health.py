"""Read-only runtime health exporter tests."""
import json
from scripts.export_messenger_runtime_health import build_snapshot


def test_snapshot_is_aggregate_and_has_no_customer_data(tmp_path):
    (tmp_path / "drafts.json").write_text(json.dumps({
        "drafts": [{
            "thread_id": "SENSITIVE-THREAD-ID",
            "name": "SENSITIVE-CUSTOMER-NAME",
            "draft": "SENSITIVE-MESSAGE",
            "review_status": "approved",
            "material": {"approved": True, "drive_file_id": "SENSITIVE-DRIVE-ID"}
        }]
    }), encoding="utf-8")
    (tmp_path / "draft_daemon_status.json").write_text(json.dumps({
        "running": True, "send_enabled": True,
        "scan": {"scanned": 9, "need_reply": 4, "logged_in": True}
    }), encoding="utf-8")
    result = build_snapshot(tmp_path)
    text = json.dumps(result)
    for secret in ("SENSITIVE-THREAD-ID", "SENSITIVE-CUSTOMER-NAME",
                   "SENSITIVE-MESSAGE", "SENSITIVE-DRIVE-ID"):
        assert secret not in text
    assert result["review_approved_count"] == 1
    assert result["material_approved_count"] == 1
    assert result["scanned_count"] == 9
    assert result["estateboard_published_verified"] is False


def test_missing_status_never_claims_healthy(tmp_path):
    result = build_snapshot(tmp_path)
    assert result["daemon_running"] is False
    assert result["browser_authenticated"] is False
    assert result["confirmed_sent_total"] == 0
