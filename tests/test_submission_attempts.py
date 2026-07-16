import sqlite3

import pytest

from src.queue_db import AUTO_APPROVAL_GATE_KEYS, QueueDB, normalized_body_hash


def prepared(db: QueueDB, *, job_id="j", property_id="p", body=" Hello\r\nworld ", fingerprint="f1"):
    db.create_job(
        {"job_id": job_id, "property_id": property_id},
        [{"group_id": "g", "body": body, "source_hash": "s1", "generation_fingerprint": fingerprint}],
    )
    return db.approve_target(job_id, "g", source="operator")


def begin(db, approval, *, job_id="j", fingerprint="f1"):
    return db.begin_submission(
        job_id,
        "g",
        approval_id=approval["approval_id"],
        source_hash="s1",
        body_hash=approval["body_hash"],
        generation_fingerprint=fingerprint,
    )


def test_approval_is_immutable_bound_and_matching_approval_begins_transaction(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    approval = prepared(db)
    assert approval["body_hash"] == normalized_body_hash("Hello\nworld")
    assert db.get_targets("j")[0]["status"] == "approved"

    attempt = begin(db, approval)
    assert attempt["state"] == "submitting"
    assert db.get_targets("j")[0]["status"] == "submitting"
    with pytest.raises(sqlite3.IntegrityError):
        with db.connect() as conn:
            conn.execute("UPDATE approvals SET source_hash='changed' WHERE approval_id=?", (approval["approval_id"],))


@pytest.mark.parametrize("field,value", [("source_hash", "s2"), ("body_hash", "bad"), ("generation_fingerprint", "f2"), ("approval_id", "bad")])
def test_attempt_refuses_any_approval_mismatch(tmp_path, field, value):
    db = QueueDB(tmp_path / "q.db")
    approval = prepared(db)
    kwargs = dict(
        approval_id=approval["approval_id"], source_hash="s1",
        body_hash=approval["body_hash"], generation_fingerprint="f1"
    )
    kwargs[field] = value
    with pytest.raises(ValueError, match="approval mismatch"):
        db.begin_submission("j", "g", **kwargs)


def test_explicit_auto_policy_requires_all_gates(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    db.create_job(
        {"job_id": "j", "property_id": "p"},
        [{"group_id": "g", "body": "b", "source_hash": "s", "generation_fingerprint": "f"}],
    )
    complete = {key: True for key in AUTO_APPROVAL_GATE_KEYS}
    with pytest.raises(ValueError, match="disabled"):
        db.auto_approve_target("j", "g", gates=complete)
    with pytest.raises(ValueError, match="canonical"):
        db.auto_approve_target(
            "j", "g", auto_approve_enabled=True, gates={"fresh": True, "identity": True}
        )
    failing = complete | {next(iter(AUTO_APPROVAL_GATE_KEYS)): False}
    with pytest.raises(ValueError, match="all auto-approval gates"):
        db.auto_approve_target("j", "g", auto_approve_enabled=True, gates=failing)
    assert db.get_targets("j")[0]["status"] == "pending_approval"
    assert db.auto_approve_target(
        "j", "g", auto_approve_enabled=True, gates=complete
    )["source"] == "auto_policy"


@pytest.mark.parametrize(
    "property_id,group_id,body,source_hash,fingerprint",
    [
        ("", "g", "body", "source", "fp"),
        ("p", "", "body", "source", "fp"),
        ("p", "g", "body", "", "fp"),
        ("p", "g", "body", "source", ""),
        ("p", "g", "", "source", "fp"),
    ],
)
def test_approval_rejects_missing_binding_fields(
    tmp_path, property_id, group_id, body, source_hash, fingerprint
):
    db = QueueDB(tmp_path / "q.db")
    db.create_job(
        {"job_id": "j", "property_id": property_id},
        [{"group_id": group_id, "body": body, "source_hash": source_hash,
          "generation_fingerprint": fingerprint}],
    )
    with pytest.raises(ValueError, match="approval binding"):
        db.approve_target("j", group_id, source="operator")


def test_content_change_invalidates_approval_and_stale_callback_is_rejected(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    approval = prepared(db)
    db.set_target_content("j", "g", body="different", source_hash="s1", generation_fingerprint="f1")
    assert db.get_targets("j")[0]["status"] == "pending_approval"
    with pytest.raises(ValueError, match="stale approval"):
        db.approve_target("j", "g", source="telegram", approval_id=approval["approval_id"])


@pytest.mark.parametrize(
    "body,source_hash,fingerprint",
    [("changed", "s1", "f1"), (" Hello\r\nworld ", "s2", "f1"), (" Hello\r\nworld ", "s1", "f2")],
)
def test_each_bound_field_change_requires_new_approval(tmp_path, body, source_hash, fingerprint):
    db = QueueDB(tmp_path / "q.db")
    prepared(db)
    db.set_target_content(
        "j", "g", body=body, source_hash=source_hash, generation_fingerprint=fingerprint
    )
    assert db.get_targets("j")[0]["status"] == "pending_approval"


def test_identical_target_content_is_idempotent_for_approved_target(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    approval = prepared(db)
    db.set_target_content(
        "j", "g", body=" Hello\r\nworld ", source_hash="s1", generation_fingerprint="f1"
    )
    target = db.get_targets("j")[0]
    assert target["status"] == "approved"
    assert target["approval_id"] == approval["approval_id"]


def test_identical_target_content_does_not_abort_active_preclick_attempt(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    approval = prepared(db)
    attempt = begin(db, approval)
    db.set_target_content(
        "j", "g", body=" Hello\r\nworld ", source_hash="s1", generation_fingerprint="f1"
    )
    assert db.get_submission_attempt(attempt["attempt_id"])["state"] == "submitting"
    assert db.get_targets("j")[0]["status"] == "submitting"


def test_preclick_abort_and_recovery_return_to_approved(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    approval = prepared(db)
    attempt = begin(db, approval)
    db.abort_submission_preclick(attempt["attempt_id"], reason="planned")
    assert db.get_submission_attempt(attempt["attempt_id"])["state"] == "aborted_preclick"
    assert db.get_targets("j")[0]["status"] == "approved"

    reopened = begin(db, approval)
    assert reopened["attempt_id"] == attempt["attempt_id"]
    assert reopened["reopen_count"] == 1
    assert db.recover_incomplete_attempts() == 1
    assert db.get_submission_attempt(reopened["attempt_id"])["state"] == "aborted_preclick"
    assert db.get_targets("j")[0]["status"] == "approved"


def test_content_invalidation_atomically_aborts_active_preclick_attempt(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    approval = prepared(db)
    attempt = begin(db, approval)

    db.set_target_content("j", "g", body="changed", source_hash="s2", generation_fingerprint="f2")

    assert db.get_targets("j")[0]["status"] == "pending_approval"
    stale = db.get_submission_attempt(attempt["attempt_id"])
    assert stale["state"] == "aborted_preclick"
    assert stale["last_error"] == "content_invalidated"
    with pytest.raises(ValueError, match="awaiting click"):
        db.mark_click_started(attempt["attempt_id"])


def test_duplicate_approval_callback_cannot_reset_active_attempt(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    approval = prepared(db)
    attempt = begin(db, approval)
    with pytest.raises(ValueError, match="active submission"):
        db.approve_target(
            "j", "g", source="telegram", approval_id=approval["approval_id"]
        )
    assert db.get_submission_attempt(attempt["attempt_id"])["state"] == "submitting"
    assert db.get_targets("j")[0]["status"] == "submitting"


@pytest.mark.parametrize("stage", ["after_click", "after_response", "during_verification"])
def test_crash_after_click_boundary_is_permanently_reconcile_only(tmp_path, stage):
    db = QueueDB(tmp_path / "q.db")
    approval = prepared(db)
    attempt = begin(db, approval)
    db.mark_click_started(attempt["attempt_id"])
    if stage in {"after_response", "during_verification"}:
        db.mark_submission_response(attempt["attempt_id"])
    if stage == "during_verification":
        db.mark_verification_started(attempt["attempt_id"])

    assert db.recover_incomplete_attempts() == 1
    assert db.get_targets("j")[0]["status"] == "uncertain"
    assert db.get_submission_attempt(attempt["attempt_id"])["state"] == "reconcile_only"
    assert db.submission_eligible("j", "g") is False
    db.set_target_content("j", "g", body="new", source_hash="s2", generation_fingerprint="f2")
    assert db.get_targets("j")[0]["status"] == "uncertain"
    with pytest.raises(ValueError, match="click boundary"):
        db.approve_target("j", "g", source="operator")
    with pytest.raises(ValueError, match="click boundary"):
        db.update_target_status("j", "g", "approved")


def test_verification_transitions_and_posted_at_semantics(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    approval = prepared(db)
    attempt = begin(db, approval)
    db.mark_click_started(attempt["attempt_id"])
    permalink = "https://www.facebook.com/groups/g/posts/1"
    db.resolve_submission(attempt["attempt_id"], outcome="confirmed", permalink=permalink)
    target = db.get_targets("j")[0]
    first_posted_at = target["posted_at"]
    assert (target["status"], target["permalink"]) == ("posted", permalink)

    db.verify_submission(attempt["attempt_id"], outcome="invalid")
    assert db.get_targets("j")[0]["status"] == "uncertain"
    assert db.get_targets("j")[0]["posted_at"] == first_posted_at
    assert db.verify_submission(attempt["attempt_id"], outcome="inconclusive")["state"] == "reconcile_only"
    assert db.verify_submission(
        attempt["attempt_id"], outcome="confirmed", permalink=permalink
    )["state"] == "posted"
    assert db.get_targets("j")[0]["posted_at"] == first_posted_at


def test_resolve_submission_cannot_reverify_or_demote_posted_attempt(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    approval = prepared(db)
    attempt = begin(db, approval)
    db.mark_click_started(attempt["attempt_id"])
    permalink = "https://www.facebook.com/groups/g/posts/123"
    db.resolve_submission(attempt["attempt_id"], outcome="confirmed", permalink=permalink)

    with pytest.raises(ValueError, match="currently submitting"):
        db.resolve_submission(attempt["attempt_id"], outcome="ambiguous")
    with pytest.raises(ValueError, match="currently submitting"):
        db.resolve_submission(attempt["attempt_id"], outcome="confirmed", permalink=permalink)
    assert db.get_submission_attempt(attempt["attempt_id"])["state"] == "posted"
    assert db.get_targets("j")[0]["status"] == "posted"


@pytest.mark.parametrize(
    "permalink",
    [
        None,
        "",
        "http://facebook.com/groups/g/posts/1",
        "https://example.com/posts/1",
        "https://facebook.com/",
        "https://www.facebook.com/help",
        "https://www.facebook.com/groups/g/posts/",
        "https://www.facebook.com/user/permalink/",
        "https://www.facebook.com/share/p/",
    ],
)
def test_confirmation_requires_captured_https_facebook_permalink(tmp_path, permalink):
    db = QueueDB(tmp_path / "q.db")
    approval = prepared(db)
    attempt = begin(db, approval)
    db.mark_click_started(attempt["attempt_id"])
    with pytest.raises(ValueError, match="Facebook permalink"):
        db.resolve_submission(attempt["attempt_id"], outcome="confirmed", permalink=permalink)
    assert db.get_submission_attempt(attempt["attempt_id"])["state"] == "reconcile_only"
    assert db.get_targets("j")[0]["status"] == "uncertain"


@pytest.mark.parametrize(
    "permalink",
    [
        "https://www.facebook.com/groups/g/posts/123",
        "https://facebook.com/user/permalink/abc_123/",
        "https://m.facebook.com/share/p/AbC123/",
    ],
)
def test_facebook_permalink_requires_and_accepts_post_identifier(tmp_path, permalink):
    db = QueueDB(tmp_path / "q.db")
    approval = prepared(db)
    attempt = begin(db, approval)
    db.mark_click_started(attempt["attempt_id"])
    assert db.resolve_submission(
        attempt["attempt_id"], outcome="confirmed", permalink=permalink
    )["state"] == "posted"


def test_verify_only_api_never_creates_attempt_or_submits(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    prepared(db)
    with pytest.raises(ValueError, match="attempt not found"):
        db.verify_submission("missing", outcome="confirmed")
    assert db.list_submission_attempts() == []
    assert db.get_targets("j")[0]["status"] == "approved"
