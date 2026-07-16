from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from src.queue_db import QueueDB
from src.run_result import OUTCOME_EXIT_CODES, RunResultStore, is_fresh_terminal_result


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_terminal_result_is_atomic_and_versioned(tmp_path):
    store = RunResultStore(tmp_path)
    run = store.start("daily-post", run_id="run-1")

    store.finish(run, outcome="preflight_blocked", reason="browser_missing")

    result = _read_json(tmp_path / "latest.json")
    assert result["schema"] == "fb-autoposter-run/v1"
    assert result["run_id"] == "run-1"
    assert result["exit_code"] == 20
    assert result["terminal"] is True
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.parametrize(
    ("outcome", "exit_code"),
    [
        ("success", 0),
        ("no_action", 0),
        ("preflight_blocked", 20),
        ("risk_stopped", 30),
        ("submission_ambiguous", 40),
        ("posted_delivery_pending", 50),
        ("internal_error", 60),
    ],
)
def test_outcomes_have_exact_exit_codes(tmp_path, outcome, exit_code):
    store = RunResultStore(tmp_path / outcome)
    run = store.start("daily-post", run_id=f"run-{outcome}")

    result = store.finish(run, outcome=outcome, reason="test_reason")

    assert OUTCOME_EXIT_CODES[outcome] == exit_code
    assert result["exit_code"] == exit_code


def test_unknown_outcome_is_rejected_without_replacing_start_record(tmp_path):
    store = RunResultStore(tmp_path)
    run = store.start("daily-post", run_id="run-1")

    with pytest.raises(ValueError, match="unknown outcome"):
        store.finish(run, outcome="maybe", reason="bad")

    assert _read_json(tmp_path / "latest.json")["terminal"] is False


def test_second_terminal_write_for_same_run_is_rejected(tmp_path):
    store = RunResultStore(tmp_path)
    run = store.start("daily-post", run_id="run-1")
    store.finish(run, outcome="success", reason="success")

    with pytest.raises(RuntimeError, match="already terminal"):
        store.finish(run, outcome="internal_error", reason="late_failure")

    assert _read_json(tmp_path / "latest.json")["outcome"] == "success"


def test_terminal_run_id_cannot_be_reopened(tmp_path):
    store = RunResultStore(tmp_path)
    run = store.start("daily-post", run_id="run-1")
    terminal = store.finish(run, outcome="success", reason="success")

    with pytest.raises(RuntimeError, match="already terminal"):
        store.start("daily-post", run_id="run-1")

    assert _read_json(tmp_path / "latest.json") == terminal


def test_launcher_finalization_only_replaces_matching_nonterminal_result(tmp_path):
    store = RunResultStore(tmp_path)
    store.start("daily-post", run_id="run-1")

    finalized = store.finalize_from_launcher("run-1", reason="child_exited_without_result")

    assert finalized["outcome"] == "internal_error"
    assert finalized["exit_code"] == 60
    assert finalized["finalized_by"] == "launcher"
    assert store.finalize_from_launcher("run-1", reason="again") == finalized
    assert store.finalize_from_launcher("other-run", reason="wrong_run") is None


def test_launcher_does_not_overwrite_python_terminal_result(tmp_path):
    store = RunResultStore(tmp_path)
    run = store.start("daily-post", run_id="run-1")
    terminal = store.finish(run, outcome="success", reason="success")

    assert store.finalize_from_launcher("run-1", reason="child_exit") == terminal
    assert _read_json(tmp_path / "latest.json") == terminal


def test_result_redacts_sensitive_fields_and_values(tmp_path):
    store = RunResultStore(tmp_path, secrets=["secret-token"])
    run = store.start("daily-post", run_id="run-1")

    store.finish(
        run,
        outcome="internal_error",
        reason="request failed with secret-token",
        details={
            "authorization": "Bearer secret-token",
            "telegram_bot_token": "secret-token",
            "post_body": "private listing copy",
            "safe": "prefix secret-token suffix",
        },
    )

    serialized = (tmp_path / "latest.json").read_text(encoding="utf-8")
    assert "secret-token" not in serialized
    assert "private listing copy" not in serialized
    result = json.loads(serialized)
    assert result["details"]["authorization"] == "[REDACTED]"
    assert result["details"]["post_body"] == "[REDACTED]"


def test_terminal_result_is_copied_to_dated_history(tmp_path):
    timestamp = datetime(2026, 7, 16, 3, 4, 5, tzinfo=UTC)
    store = RunResultStore(tmp_path, clock=lambda: timestamp)
    run = store.start("daily-post", run_id="run-1")

    result = store.finish(run, outcome="no_action", reason="already_posted_today")

    history_path = tmp_path / "history" / "2026-07-16" / "run-1.json"
    assert _read_json(history_path) == result
    assert not list(tmp_path.rglob("*.tmp"))


def test_terminal_result_freshness_requires_age_and_latest_sqlite_run_id():
    now = datetime(2026, 7, 16, 12, tzinfo=UTC)
    result = {
        "terminal": True,
        "run_id": "run-1",
        "finished_at": (now - timedelta(hours=29, minutes=59)).isoformat(),
        "outcome": "success",
    }

    assert is_fresh_terminal_result(result, sqlite_run_id="run-1", now=now) is True
    assert is_fresh_terminal_result(result, sqlite_run_id="run-2", now=now) is False
    stale = {**result, "finished_at": (now - timedelta(hours=30)).isoformat()}
    assert is_fresh_terminal_result(stale, sqlite_run_id="run-1", now=now) is False


def test_only_documented_launcher_owned_pre_sqlite_failure_can_lack_db_row():
    now = datetime(2026, 7, 16, 12, tzinfo=UTC)
    base = {
        "terminal": True,
        "run_id": "run-1",
        "finished_at": (now - timedelta(minutes=1)).isoformat(),
        "outcome": "internal_error",
        "finalized_by": "launcher",
    }

    assert is_fresh_terminal_result(
        {**base, "pre_sqlite_failure": True}, sqlite_run_id=None, now=now
    )
    assert not is_fresh_terminal_result(base, sqlite_run_id=None, now=now)
    assert not is_fresh_terminal_result(
        {**base, "pre_sqlite_failure": True, "finalized_by": "python"},
        sqlite_run_id=None,
        now=now,
    )


def test_queue_db_adds_run_lifecycle_with_shared_run_id(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")

    started = db.start_run("daily-post", run_id="run-1")
    finished = db.finish_run(
        "run-1", outcome="preflight_blocked", reason="browser_missing", exit_code=20
    )

    assert started["run_id"] == "run-1"
    assert finished["run_id"] == "run-1"
    assert finished["outcome"] == "preflight_blocked"
    assert db.latest_run()["run_id"] == "run-1"


def test_runs_migration_does_not_change_existing_posting_rows(tmp_path):
    db_path = tmp_path / "jobs.db"
    db = QueueDB(db_path)
    job_id = db.create_job(
        {"property_id": "p1", "title": "A"}, [{"group_id": "g1", "body": "body"}]
    )
    db.update_target_status(job_id, "g1", "posted")
    before = db.get_targets(job_id)[0]

    migrated = QueueDB(db_path)
    migrated.start_run("daily-post", run_id="run-1")
    after = migrated.get_targets(job_id)[0]

    assert after["status"] == before["status"] == "posted"
    assert after["posted_at"] == before["posted_at"]
