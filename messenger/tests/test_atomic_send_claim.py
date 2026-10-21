"""Regression tests for precommitted auto-reply claims. No browser/send access."""
import json
from datetime import datetime, timedelta

import pytest

from scripts.send_one_playwright_reply import JST, _assert_global_send_guard


def ledger(tmp_path, *, key="inbound1", nonce="test-nonce", state="attempted_unconfirmed", age_minutes=0):
    row = {
        "thread_id": "123", "claim_nonce": nonce, "state": state,
        "created_at": (datetime.now(JST) - timedelta(minutes=age_minutes)).isoformat(),
    }
    (tmp_path / "auto_reply_ledger.json").write_text(
        json.dumps({"attempts": {key: row}}), encoding="utf-8"
    )
    return row


def test_matching_claim_can_pass_readonly_checks(tmp_path):
    ledger(tmp_path)
    _assert_global_send_guard(tmp_path, "123", auto_claim="test-nonce")
    assert not (tmp_path / "send_claims").exists()


def test_exact_claim_consumed_only_once(tmp_path):
    ledger(tmp_path)
    _assert_global_send_guard(tmp_path, "123", auto_claim="test-nonce", consume=True)
    assert (tmp_path / "send_claims" / "inbound1.claimed").exists()
    with pytest.raises(RuntimeError, match="already_consumed"):
        _assert_global_send_guard(tmp_path, "123", auto_claim="test-nonce", consume=True)


@pytest.mark.parametrize("claim", ["", "wrong-token"])
def test_unclaimed_or_wrong_claim_never_overrides_pending(tmp_path, claim):
    ledger(tmp_path)
    with pytest.raises(RuntimeError, match="uncertain_prior_delivery"):
        _assert_global_send_guard(tmp_path, "123", auto_claim=claim)


def test_other_unresolved_attempt_blocks_even_matching_claim(tmp_path):
    ledger(tmp_path)
    data = json.loads((tmp_path / "auto_reply_ledger.json").read_text())
    data["attempts"]["older"] = {
        "thread_id": "123", "state": "blocked_or_uncertain_no_replay"
    }
    (tmp_path / "auto_reply_ledger.json").write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match="uncertain_prior_delivery"):
        _assert_global_send_guard(tmp_path, "123", auto_claim="test-nonce")


def test_pause_marker_overrides_every_claim(tmp_path):
    ledger(tmp_path)
    (tmp_path / "send_pause.lock").touch()
    with pytest.raises(RuntimeError, match="send_paused"):
        _assert_global_send_guard(tmp_path, "123", auto_claim="test-nonce", consume=True)
    assert not (tmp_path / "send_claims").exists()


def test_claim_expiration_is_fail_closed(tmp_path):
    ledger(tmp_path, age_minutes=7)
    with pytest.raises(RuntimeError, match="expired"):
        _assert_global_send_guard(tmp_path, "123", auto_claim="test-nonce")


def test_no_claim_entry_fails_closed(tmp_path):
    ledger(tmp_path)
    with pytest.raises(RuntimeError, match="missing"):
        _assert_global_send_guard(tmp_path, "987", auto_claim="test-nonce")


def test_prior_confirmed_delivery_still_allowed_for_distinct_message(tmp_path):
    ledger(tmp_path, key="prior", state="confirmed_sent")
    row = ledger(tmp_path, key="new")
    (tmp_path / "auto_reply_ledger.json").write_text(json.dumps({
        "attempts": {"prior": {**row, "state": "confirmed_sent"}, "new": row}
    }))
    _assert_global_send_guard(tmp_path, "123", auto_claim="test-nonce")


def test_corrupt_ledger_never_authorizes(tmp_path):
    (tmp_path / "auto_reply_ledger.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unreadable"):
        _assert_global_send_guard(tmp_path, "123", auto_claim="test-nonce")
