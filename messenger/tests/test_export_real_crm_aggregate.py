"""Read-only CRM reporting uses the durable send ledger, not ephemeral status."""
import json
import pytest
from scripts.export_real_crm_aggregate import build_live_metrics

def test_missing_ledger_refuses_to_report_zero(tmp_path):
    with pytest.raises(ValueError, match="send ledger missing"):
        build_live_metrics(tmp_path)

def test_real_counters_no_private_customer_text(tmp_path):
    (tmp_path / "threads_state.json").write_text(json.dumps({
        "thread-1": {"name": "SECRET_CUSTOMER"},
        "thread-2": {"message": "SECRET_INBOUND"}}))
    (tmp_path / "drafts.json").write_text(json.dumps({"drafts": [
        {"name": "SECRET_CUSTOMER", "draft": "SECRET_REPLY",
         "review_status": "approved"}]}))
    (tmp_path / "draft_daemon_status.json").write_text(json.dumps(
        {"scan": {"scanned": 17, "need_reply": 7}}))
    # Maintenance status lacks totals; durable ledger still records uncertainty.
    (tmp_path / "auto_reply_status.json").write_text(json.dumps({
        "status": "send_paused_fail_closed", "attempted": 0}))
    (tmp_path / "auto_reply_ledger.json").write_text(json.dumps({
        "attempts": {"old": {"thread_id": "thread-1",
                              "state": "blocked_or_uncertain_no_replay"}}}))
    result = build_live_metrics(tmp_path)
    encoded = json.dumps(result)
    assert result["tracked_thread_count"] == 2
    assert result["latest_need_reply_count"] == 7
    assert result["current_premium_approved_count"] == 1
    assert result["uncertain_send_count"] == 1
    assert result["confirmed_send_count"] == 0
    for sensitive in ("thread-1", "SECRET_CUSTOMER",
                      "SECRET_INBOUND", "SECRET_REPLY"):
        assert sensitive not in encoded

def test_malformed_ledger_refuses_reporting(tmp_path):
    (tmp_path / "auto_reply_ledger.json").write_text(
        json.dumps({"attempts": {"bad": None}}))
    with pytest.raises(ValueError, match="invalid ledger"):
        build_live_metrics(tmp_path)
