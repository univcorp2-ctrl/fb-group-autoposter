"""The new CRM status feed must never export customer data."""
import json
from scripts.export_real_crm_aggregate import build_live_metrics


def test_empty_sources_fail_closed(tmp_path):
    result = build_live_metrics(tmp_path)
    assert result["tracked_thread_count"] == 0
    assert result["estateboard_publication_confirmed"] is False


def test_real_counters_no_sensitive_text(tmp_path):
    (tmp_path / "threads_state.json").write_text(json.dumps({
        "thread-1": {"name": "SECRET_CUSTOMER"},
        "thread-2": {"message": "SECRET_INBOUND"}}))
    (tmp_path / "drafts.json").write_text(json.dumps({"drafts": [
        {"name": "SECRET_CUSTOMER", "draft": "SECRET_REPLY",
         "review_status": "approved"}]}))
    (tmp_path / "draft_daemon_status.json").write_text(json.dumps({
        "scan": {"scanned": 17, "need_reply": 7}}))
    (tmp_path / "auto_reply_status.json").write_text(json.dumps({
        "confirmed_total": 0, "uncertain_total": 1}))
    result = build_live_metrics(tmp_path)
    encoded = json.dumps(result)
    assert result["tracked_thread_count"] == 2
    assert result["latest_need_reply_count"] == 7
    assert result["current_premium_approved_count"] == 1
    assert result["uncertain_send_count"] == 1
    for sensitive in ("thread-1", "SECRET_CUSTOMER", "SECRET_INBOUND", "SECRET_REPLY"):
        assert sensitive not in encoded
