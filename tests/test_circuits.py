import json
from datetime import UTC, datetime, timedelta

import pytest

from src.circuits import CircuitManager, FailureKind
from src.queue_db import QueueDB


NOW = datetime(2026, 7, 16, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "kind,scope,reason,clearance",
    [
        (FailureKind.CHECKPOINT, "global", "checkpoint", "operator"),
        (FailureKind.CAPTCHA, "global", "captcha", "operator"),
        (FailureKind.TWO_FACTOR, "global", "two_factor", "operator"),
        (FailureKind.ACCOUNT_WARNING, "global", "account_warning", "operator"),
        (FailureKind.RESTRICTION, "global", "restriction", "operator"),
        (FailureKind.POSTING_BLOCK, "global", "posting_block", "operator"),
        (FailureKind.UNCLASSIFIED_LOGIN, "global", "unclassified_login", "operator"),
        (FailureKind.SESSION_EXPIRED, "environment", "session_expired", "preflight"),
        (FailureKind.PROFILE_LOCKED, "environment", "profile_locked", "preflight"),
        (FailureKind.PROFILE_CORRUPT, "environment", "profile_corrupt", "operator_preflight"),
        (FailureKind.CONCURRENT_RUNNER, "environment", "concurrent_runner", "preflight"),
        (FailureKind.SOURCE_MISSING, "environment", "source_missing", "preflight"),
        (FailureKind.SOURCE_STALE, "environment", "source_stale", "preflight"),
        (FailureKind.SOURCE_HASH_MISMATCH, "environment", "source_hash_mismatch", "preflight"),
        (FailureKind.SOURCE_IDENTITY_MISMATCH, "environment", "source_identity_mismatch", "preflight"),
        (FailureKind.BROKER_UNKNOWN, "environment", "broker_unknown", "preflight"),
        (FailureKind.BROWSER_MISSING, "environment", "browser_missing", "preflight"),
        (FailureKind.RUNTIME_MISMATCH, "environment", "runtime_mismatch", "preflight"),
    ],
)
def test_first_occurrence_policies(tmp_path, kind, scope, reason, clearance):
    manager = CircuitManager(QueueDB(tmp_path / "q.db"))
    circuit = manager.record_failure(kind, environment="prod", occurred_at=NOW)
    assert circuit is not None
    assert (circuit["scope"], circuit["reason"], circuit["clearance_mode"]) == (
        scope,
        reason,
        clearance,
    )
    assert circuit["expires_at"] is None


def test_group_ambiguity_is_24h_and_marks_attempt_reconcile_only(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    manager = CircuitManager(db)
    attempt_id = _clicked_attempt(db)
    circuit = manager.record_failure(
        FailureKind.POST_SUBMIT_AMBIGUITY,
        group_id="g1",
        attempt_id=attempt_id,
        occurred_at=NOW,
    )
    assert circuit["scope"] == "group"
    assert datetime.fromisoformat(circuit["expires_at"]) == NOW + timedelta(hours=24)
    assert manager.clear(scope="group", subject="g1", actor="operator", at=NOW) is False
    assert db.get_submission_attempt(attempt_id)["state"] == "reconcile_only"
    assert db.get_targets("j1")[0]["status"] == "uncertain"


@pytest.mark.parametrize("kind", [FailureKind.POST_SUBMIT_AMBIGUITY, FailureKind.PUBLIC_VERIFICATION_FAILURE])
def test_group_ambiguity_requires_matching_clicked_attempt_atomically(tmp_path, kind):
    db = QueueDB(tmp_path / "q.db")
    manager = CircuitManager(db)
    with pytest.raises(ValueError, match="attempt_id"):
        manager.record_failure(kind, group_id="g1", occurred_at=NOW)
    attempt_id = _clicked_attempt(db)
    with pytest.raises(ValueError, match="affected group"):
        manager.record_failure(kind, group_id="other", attempt_id=attempt_id, occurred_at=NOW)
    assert manager.active_circuits(at=NOW) == []
    assert db.get_submission_attempt(attempt_id)["state"] == "submitting"


def test_public_verification_failure_atomically_demotes_posted_attempt(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    manager = CircuitManager(db)
    attempt_id = _clicked_attempt(db)
    permalink = "https://www.facebook.com/groups/g1/posts/123"
    db.resolve_submission(attempt_id, outcome="confirmed", permalink=permalink)

    circuit = manager.record_failure(
        FailureKind.PUBLIC_VERIFICATION_FAILURE,
        group_id="g1",
        attempt_id=attempt_id,
        occurred_at=NOW,
    )

    assert circuit["reason"] == "public_verification_failure"
    assert db.get_submission_attempt(attempt_id)["state"] == "reconcile_only"
    target = db.get_targets("j1")[0]
    assert target["status"] == "uncertain"
    assert target["posted_at"] is not None


def test_public_verification_failure_accepts_reconcile_but_ambiguity_rejects_it(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    manager = CircuitManager(db)
    attempt_id = _clicked_attempt(db)
    db.mark_attempt_reconcile_only(attempt_id)
    assert manager.record_failure(
        FailureKind.PUBLIC_VERIFICATION_FAILURE,
        group_id="g1",
        attempt_id=attempt_id,
        occurred_at=NOW,
    )["scope"] == "group"
    with pytest.raises(ValueError, match="submitting"):
        manager.record_failure(
            FailureKind.POST_SUBMIT_AMBIGUITY,
            group_id="g1",
            attempt_id=attempt_id,
            occurred_at=NOW,
        )


def test_selector_threshold_and_rolling_window(tmp_path):
    manager = CircuitManager(QueueDB(tmp_path / "q.db"))
    assert manager.record_failure(FailureKind.SELECTOR_FAILURE, group_id="g1", occurred_at=NOW) is None
    assert manager.record_failure(
        FailureKind.COMPOSER_FAILURE, group_id="g1", occurred_at=NOW + timedelta(hours=23)
    )["scope"] == "group"
    assert manager.clear(scope="group", subject="g1", actor="operator", at=NOW + timedelta(hours=23)) is False
    assert manager.record_successful_preflight(
        "prod", group_id="g1", actor="operator", at=NOW + timedelta(hours=23)
    ) == 0
    assert manager.blocking_circuit(group_id="g1", at=NOW + timedelta(hours=48))["scope"] == "group"
    assert manager.record_successful_preflight(
        "prod", group_id="g1", actor="operator", at=NOW + timedelta(hours=48)
    ) == 1
    assert manager.blocking_circuit(group_id="g1", at=NOW + timedelta(hours=48)) is None

    later = NOW + timedelta(hours=49)
    assert manager.record_failure(FailureKind.SELECTOR_FAILURE, group_id="g2", occurred_at=later) is None
    assert manager.record_failure(
        FailureKind.SELECTOR_FAILURE, group_id="g2", occurred_at=later + timedelta(hours=24, seconds=1)
    ) is None


def test_three_distinct_groups_open_global_24h(tmp_path):
    manager = CircuitManager(QueueDB(tmp_path / "q.db"))
    for offset, group in enumerate(("g1", "g2")):
        assert manager.record_failure(
            FailureKind.SELECTOR_FAILURE,
            group_id=group,
            occurred_at=NOW + timedelta(hours=offset),
        ) is None
    circuit = manager.record_failure(
        FailureKind.COMPOSER_FAILURE, group_id="g3", occurred_at=NOW + timedelta(hours=2)
    )
    assert circuit["scope"] == "global"
    assert circuit["clearance_mode"] == "operator_preflight"
    assert datetime.fromisoformat(circuit["expires_at"]) == NOW + timedelta(hours=26)


def test_other_runtime_threshold_is_three_in_six_hours(tmp_path):
    manager = CircuitManager(QueueDB(tmp_path / "q.db"))
    for hour in (0, 2):
        assert manager.record_failure(
            FailureKind.OTHER_PRESUBMIT_RUNTIME, environment="prod", occurred_at=NOW + timedelta(hours=hour)
        ) is None
    assert manager.record_failure(
        FailureKind.OTHER_PRESUBMIT_RUNTIME, environment="prod", occurred_at=NOW + timedelta(hours=5)
    )["scope"] == "environment"
    assert manager.record_failure(
        FailureKind.OTHER_PRESUBMIT_RUNTIME, environment="other", occurred_at=NOW + timedelta(hours=7)
    ) is None


@pytest.mark.parametrize(
    "order",
    [
        (FailureKind.SESSION_EXPIRED, FailureKind.PROFILE_CORRUPT),
        (FailureKind.PROFILE_CORRUPT, FailureKind.SESSION_EXPIRED),
    ],
)
def test_environment_circuit_merge_is_order_independent_and_requires_operator(tmp_path, order):
    manager = CircuitManager(QueueDB(tmp_path / "q.db"))
    for offset, kind in enumerate(order):
        circuit = manager.record_failure(
            kind, environment="prod", occurred_at=NOW + timedelta(minutes=offset)
        )
    assert circuit["clearance_mode"] == "operator_preflight"
    assert set(json.loads(circuit["reasons_json"])) == {"session_expired", "profile_corrupt"}
    assert manager.record_successful_preflight("prod", actor="operator", at=NOW) == 0
    assert manager.operator_review(
        scope="environment", subject="prod", actor="operator", at=NOW
    ) is True
    assert manager.record_successful_preflight("prod", actor="operator", at=NOW) == 1


def test_repeated_operator_incident_invalidates_stale_review(tmp_path):
    manager = CircuitManager(QueueDB(tmp_path / "q.db"))
    first = manager.record_failure(
        FailureKind.PROFILE_CORRUPT, environment="prod", occurred_at=NOW
    )
    assert manager.operator_review(
        scope="environment", subject="prod", actor="operator", at=NOW + timedelta(minutes=1)
    ) is True
    reviewed = manager.blocking_circuit(environment="prod", at=NOW + timedelta(minutes=1))
    assert reviewed["operator_reviewed_at"] is not None

    repeated = manager.record_failure(
        FailureKind.PROFILE_CORRUPT,
        environment="prod",
        occurred_at=NOW + timedelta(minutes=2),
    )
    assert repeated["circuit_id"] == first["circuit_id"]
    assert repeated["operator_reviewed_at"] is None
    assert repeated["operator_reviewed_by"] is None
    assert manager.record_successful_preflight(
        "prod", actor="operator", at=NOW + timedelta(minutes=3)
    ) == 0
    assert manager.operator_review(
        scope="environment", subject="prod", actor="operator", at=NOW + timedelta(minutes=4)
    ) is True
    assert manager.record_successful_preflight(
        "prod", actor="operator", at=NOW + timedelta(minutes=5)
    ) == 1


def test_weaker_reverse_incident_still_invalidates_operator_review(tmp_path):
    manager = CircuitManager(QueueDB(tmp_path / "q.db"))
    manager.record_failure(FailureKind.PROFILE_CORRUPT, environment="prod", occurred_at=NOW)
    assert manager.operator_review(
        scope="environment", subject="prod", actor="operator", at=NOW + timedelta(minutes=1)
    ) is True

    merged = manager.record_failure(
        FailureKind.SESSION_EXPIRED,
        environment="prod",
        occurred_at=NOW + timedelta(minutes=2),
    )
    assert merged["clearance_mode"] == "operator_preflight"
    assert merged["operator_reviewed_at"] is None
    assert manager.record_successful_preflight(
        "prod", actor="operator", at=NOW + timedelta(minutes=3)
    ) == 0


def test_new_global_incident_resets_review_and_extends_minimum(tmp_path):
    manager = CircuitManager(QueueDB(tmp_path / "q.db"))
    for group in ("g1", "g2", "g3"):
        global_circuit = manager.record_failure(
            FailureKind.SELECTOR_FAILURE, group_id=group, occurred_at=NOW
        )
    assert manager.operator_review(
        scope="global", subject="*", actor="operator", at=NOW + timedelta(hours=1)
    ) is True

    merged = manager.record_failure(
        FailureKind.SELECTOR_FAILURE,
        group_id="g4",
        occurred_at=NOW + timedelta(hours=2),
    )
    assert merged["circuit_id"] == global_circuit["circuit_id"]
    assert merged["operator_reviewed_at"] is None
    assert datetime.fromisoformat(merged["expires_at"]) == NOW + timedelta(hours=26)
    assert manager.record_successful_preflight(
        "prod", actor="operator", at=NOW + timedelta(hours=27)
    ) == 0


def test_ambiguity_then_selector_merges_to_minimum_preflight_with_latest_expiry(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    manager = CircuitManager(db)
    attempt_id = _clicked_attempt(db)
    ambiguity = manager.record_failure(
        FailureKind.POST_SUBMIT_AMBIGUITY,
        group_id="g1",
        attempt_id=attempt_id,
        occurred_at=NOW,
    )
    manager.record_failure(FailureKind.SELECTOR_FAILURE, group_id="g1", occurred_at=NOW)
    merged = manager.record_failure(
        FailureKind.COMPOSER_FAILURE, group_id="g1", occurred_at=NOW + timedelta(hours=2)
    )
    assert merged["circuit_id"] == ambiguity["circuit_id"]
    assert merged["clearance_mode"] == "minimum_preflight"
    assert datetime.fromisoformat(merged["expires_at"]) == NOW + timedelta(hours=26)
    assert set(json.loads(merged["reasons_json"])) == {
        "post_submit_ambiguity", "selector_composer_threshold"
    }
    assert manager.record_successful_preflight(
        "prod", group_id="g1", actor="operator", at=NOW + timedelta(hours=25)
    ) == 0
    assert manager.record_successful_preflight(
        "prod", group_id="g1", actor="operator", at=NOW + timedelta(hours=27)
    ) == 1


def test_nearly_expired_selector_then_ambiguity_gets_fresh_24h_without_weakening(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    manager = CircuitManager(db)
    manager.record_failure(FailureKind.SELECTOR_FAILURE, group_id="g1", occurred_at=NOW)
    selector = manager.record_failure(
        FailureKind.COMPOSER_FAILURE, group_id="g1", occurred_at=NOW + timedelta(hours=1)
    )
    attempt_id = _clicked_attempt(db)
    merged = manager.record_failure(
        FailureKind.POST_SUBMIT_AMBIGUITY,
        group_id="g1",
        attempt_id=attempt_id,
        occurred_at=NOW + timedelta(hours=24),
    )
    assert merged["circuit_id"] == selector["circuit_id"]
    assert merged["clearance_mode"] == "minimum_preflight"
    assert datetime.fromisoformat(merged["expires_at"]) == NOW + timedelta(hours=48)
    assert set(json.loads(merged["reasons_json"])) == {
        "selector_composer_threshold", "post_submit_ambiguity"
    }
    assert manager.clear(scope="group", subject="g1", actor="operator", at=NOW + timedelta(hours=49)) is False


def test_global_precedence_persistence_expiry_and_clearance_authority(tmp_path):
    path = tmp_path / "q.db"
    db = QueueDB(path)
    manager = CircuitManager(db)
    attempt_id = _clicked_attempt(db)
    db.resolve_submission(
        attempt_id,
        outcome="confirmed",
        permalink="https://www.facebook.com/groups/g1/posts/1",
    )
    manager.record_failure(
        FailureKind.PUBLIC_VERIFICATION_FAILURE,
        group_id="g1",
        attempt_id=attempt_id,
        occurred_at=NOW,
    )
    manager.record_failure(FailureKind.CHECKPOINT, occurred_at=NOW + timedelta(minutes=1))

    restarted = CircuitManager(QueueDB(path))
    assert restarted.blocking_circuit(group_id="g1", environment="prod", at=NOW + timedelta(hours=1))["scope"] == "global"
    assert restarted.clear(scope="global", subject="*", actor="scheduler", at=NOW) is False
    assert restarted.clear(scope="global", subject="*", actor="operator", at=NOW) is True
    assert restarted.blocking_circuit(group_id="g1", environment="prod", at=NOW + timedelta(hours=25)) is None


def test_new_failure_reopens_an_expired_group_circuit(tmp_path):
    db = QueueDB(tmp_path / "q.db")
    manager = CircuitManager(db)
    first_attempt = _clicked_attempt(db)
    db.resolve_submission(
        first_attempt,
        outcome="confirmed",
        permalink="https://www.facebook.com/groups/g1/posts/1",
    )
    first = manager.record_failure(
        FailureKind.PUBLIC_VERIFICATION_FAILURE,
        group_id="g1",
        attempt_id=first_attempt,
        occurred_at=NOW,
    )
    second_attempt = _clicked_attempt(db, job_id="j2", property_id="p2")
    db.resolve_submission(
        second_attempt,
        outcome="confirmed",
        permalink="https://www.facebook.com/groups/g1/posts/2",
    )
    second = manager.record_failure(
        FailureKind.PUBLIC_VERIFICATION_FAILURE,
        group_id="g1",
        attempt_id=second_attempt,
        occurred_at=NOW + timedelta(hours=25),
    )
    assert second["circuit_id"] != first["circuit_id"]
    assert manager.blocking_circuit(group_id="g1", at=NOW + timedelta(hours=25))["circuit_id"] == second["circuit_id"]


def test_preflight_and_operator_preflight_clearance(tmp_path):
    manager = CircuitManager(QueueDB(tmp_path / "q.db"))
    manager.record_failure(FailureKind.PROFILE_CORRUPT, environment="prod", occurred_at=NOW)
    assert manager.record_successful_preflight("prod", actor="scheduler", at=NOW) == 0
    manager.record_failure(FailureKind.SESSION_EXPIRED, environment="scheduled-env", occurred_at=NOW)
    assert manager.record_successful_preflight("scheduled-env", actor="scheduled", at=NOW) == 0
    assert manager.blocking_circuit(environment="scheduled-env", at=NOW)["reason"] == "session_expired"
    assert manager.operator_review(scope="environment", subject="prod", actor="operator", at=NOW) is True
    assert manager.record_successful_preflight("prod", actor="operator", at=NOW) == 1


def test_operator_preflight_circuit_does_not_expire_without_both_clearances(tmp_path):
    manager = CircuitManager(QueueDB(tmp_path / "q.db"))
    for group in ("g1", "g2", "g3"):
        manager.record_failure(FailureKind.SELECTOR_FAILURE, group_id=group, occurred_at=NOW)
    assert manager.blocking_circuit(at=NOW + timedelta(hours=25))["scope"] == "global"
    assert manager.record_successful_preflight("prod", actor="operator", at=NOW + timedelta(hours=25)) == 0
    assert manager.operator_review(scope="global", subject="*", actor="operator", at=NOW) is True
    assert manager.record_successful_preflight("prod", actor="operator", at=NOW) == 0
    assert manager.record_successful_preflight(
        "prod", actor="operator", at=NOW + timedelta(hours=25)
    ) == 1


def test_additive_migration_from_legacy_database(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE jobs(job_id TEXT PRIMARY KEY, property_id TEXT, status TEXT, created_at TEXT, updated_at TEXT, degraded INTEGER, payload_json TEXT);"
            "CREATE TABLE job_targets(id INTEGER PRIMARY KEY, job_id TEXT, group_id TEXT, body TEXT, status TEXT, attempts INTEGER, last_error TEXT, posted_at TEXT, screenshot TEXT, permalink TEXT);"
        )
    db = QueueDB(path)
    with db.connect() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {r[1] for r in conn.execute("PRAGMA table_info(job_targets)")}
    assert {"safety_circuits", "circuit_events", "approvals", "submission_attempts"} <= tables
    assert {"source_hash", "normalized_body_hash", "generation_fingerprint", "approval_id", "reconcile_only"} <= columns
    with db.connect() as conn:
        attempt_columns = {r[1] for r in conn.execute("PRAGMA table_info(submission_attempts)")}
    assert {"reopen_count", "last_reopened_at"} <= attempt_columns
    with db.connect() as conn:
        circuit_columns = {r[1] for r in conn.execute("PRAGMA table_info(safety_circuits)")}
    assert "reasons_json" in circuit_columns


def _clicked_attempt(
    db: QueueDB, *, job_id: str = "j1", property_id: str = "p1", group_id: str = "g1"
) -> str:
    db.create_job(
        {"job_id": job_id, "property_id": property_id},
        [{"group_id": group_id, "body": "body", "source_hash": "s", "generation_fingerprint": "f"}],
    )
    approval = db.approve_target(job_id, group_id, source="operator")
    attempt = db.begin_submission(
        job_id, group_id, approval_id=approval["approval_id"], source_hash="s",
        body_hash=approval["body_hash"], generation_fingerprint="f"
    )
    db.mark_click_started(attempt["attempt_id"], at=NOW)
    return attempt["attempt_id"]
