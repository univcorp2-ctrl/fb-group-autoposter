"""Never automatically retry an unresolved Messenger thread after 24 hours."""
from datetime import datetime, timedelta, timezone
from src.auto_reply import has_unresolved_attempt

def test_uncertain_attempt_blocks_after_many_days():
    old=(datetime.now(timezone.utc)-timedelta(days=90)).isoformat()
    entries={"old_key":{"thread_id":"1001","created_at":old,
                        "state":"blocked_or_uncertain_no_replay"}}
    assert has_unresolved_attempt(entries,"1001")
    assert not has_unresolved_attempt(entries,"1002")

def test_unconfirmed_attempt_still_blocks_after_new_preview():
    entries={"hash_for_old_message":{"thread_id":"1001",
             "state":"attempted_unconfirmed"}}
    assert has_unresolved_attempt(entries,"1001")

def test_independent_confirmed_other_thread_does_not_block():
    entries={"confirmed":{"thread_id":"1001","state":"confirmed_sent"}}
    assert not has_unresolved_attempt(entries,"1001")

def test_malformed_attempts_fail_closed():
    assert has_unresolved_attempt({"bad":None},"1001")
    assert has_unresolved_attempt(None,"1001")

def test_unknown_state_is_not_treated_as_resolved():
    entries={"unknown":{"thread_id":"1001","state":"unrecognized"}}
    assert has_unresolved_attempt(entries,"1001")
