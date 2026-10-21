"""Private CRM history is aggregate-only, idempotent and fail-closed."""
import pytest
from scripts.record_crm_operational_snapshot import safe_record, append_private_history

def good():
    return {"schema_version":"messenger-crm-private-aggregate/v1",
            "source":"live_local_json_not_demo","contains_personal_data":False,
            "generated_at_utc":"2026-10-21T08:32:00+00:00",
            **{k:4 for k in (
            "tracked_thread_count","latest_scan_count","latest_need_reply_count",
            "current_active_draft_count","current_premium_approved_count",
            "confirmed_send_count","uncertain_send_count")}}

def test_private_history_inserts_only_counts(tmp_path):
    src=good()
    src["customer_name"]="DO_NOT_SAVE_ME"
    record=safe_record(src)
    path=tmp_path/"private.sqlite"
    assert append_private_history(path,record)==1
    assert append_private_history(path,record)==1
    assert b"DO_NOT_SAVE_ME" not in path.read_bytes()

@pytest.mark.parametrize("field,bad",[
    ("source","sample"),("contains_personal_data",True),
    ("latest_scan_count",-1),("confirmed_send_count","4"),
    ("generated_at_utc","2026-10-21T08:32:00")
])
def test_reject_invalid_or_demo(field,bad):
    src=good()
    src[field]=bad
    with pytest.raises(ValueError):
        safe_record(src)
