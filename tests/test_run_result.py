from __future__ import annotations

import json
import multiprocessing
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.queue_db import QueueDB
from src.run_result import (
    OUTCOME_EXIT_CODES,
    RunIdReuseError,
    RunOverlapError,
    RunResultStore,
    is_fresh_terminal_result,
)

RESERVED_RESULT_FIELDS = {
    "command",
    "exit_code",
    "finalized_by",
    "finished_at",
    "outcome",
    "pre_sqlite_failure",
    "reason",
    "result_at",
    "run_id",
    "schema",
    "started_at",
    "terminal",
}


class _PausingHistoryStore(RunResultStore):
    def __init__(self, root, entered, release):
        super().__init__(root)
        self.entered = entered
        self.release = release

    def _write_atomic(self, path, result):
        if "history" in Path(path).parts:
            self.entered.set()
            if not self.release.wait(10):
                raise TimeoutError("test did not release terminal writer")
        super()._write_atomic(path, result)


def _finish_success_while_paused(root, entered, release, errors):
    try:
        store = _PausingHistoryStore(root, entered, release)
        run = store.read_latest()
        store.finish(run, outcome="success", reason="success")
    except BaseException as exc:
        errors.put(repr(exc))


def _finalize_from_launcher(root, attempted, results, errors):
    try:
        attempted.set()
        result = RunResultStore(root).finalize_from_launcher(
            "run-1", reason="launcher_failed"
        )
        results.put(result)
    except BaseException as exc:
        errors.put(repr(exc))


def _exit_while_holding_result_lock(root, acquired):
    store = RunResultStore(root)
    with store._exclusive_lock():
        acquired.set()
        os._exit(0)


def _race_start(root, command, run_id, gate, results):
    gate.wait(10)
    try:
        run = RunResultStore(root).start(command, run_id=run_id)
        results.put(("started", run["run_id"]))
    except RunOverlapError as exc:
        results.put((exc.reason, exc.active_run_id))


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _terminal_result(tmp_path, *, run_id="run-1", outcome="success", reason="success"):
    store = RunResultStore(tmp_path)
    run = store.start("daily-post", run_id=run_id)
    return store.finish(run, outcome=outcome, reason=reason)


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

    reasons = {
        "success": "success",
        "no_action": "already_posted_today",
        "preflight_blocked": "browser_missing",
        "risk_stopped": "facebook_challenge",
        "submission_ambiguous": "submission_uncertain",
        "posted_delivery_pending": "telegram_failed",
        "internal_error": "launcher_failed",
    }
    result = store.finish(run, outcome=outcome, reason=reasons[outcome])

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
        store.finish(run, outcome="internal_error", reason="launcher_failed")

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

    finalized = store.finalize_from_launcher("run-1", reason="launcher_failed")

    assert finalized["outcome"] == "internal_error"
    assert finalized["exit_code"] == 60
    assert finalized["finalized_by"] == "launcher"
    assert store.finalize_from_launcher("run-1", reason="launcher_failed") == finalized
    assert store.finalize_from_launcher("other-run", reason="launcher_failed") is None


def test_launcher_does_not_overwrite_python_terminal_result(tmp_path):
    store = RunResultStore(tmp_path)
    run = store.start("daily-post", run_id="run-1")
    terminal = store.finish(run, outcome="success", reason="success")

    assert store.finalize_from_launcher("run-1", reason="launcher_failed") == terminal
    assert _read_json(tmp_path / "latest.json") == terminal


def test_concurrent_launcher_cannot_replace_python_terminal_result(tmp_path):
    store = RunResultStore(tmp_path)
    store.start("daily-post", run_id="run-1")
    context = multiprocessing.get_context("spawn")
    writer_entered = context.Event()
    release_writer = context.Event()
    launcher_attempted = context.Event()
    results = context.Queue()
    errors = context.Queue()
    python_writer = context.Process(
        target=_finish_success_while_paused,
        args=(tmp_path, writer_entered, release_writer, errors),
    )
    launcher = context.Process(
        target=_finalize_from_launcher,
        args=(tmp_path, launcher_attempted, results, errors),
    )

    python_writer.start()
    assert writer_entered.wait(10)
    launcher.start()
    assert launcher_attempted.wait(10)
    launcher.join(0.5)
    assert launcher.is_alive(), "launcher did not wait for the active terminal writer"
    release_writer.set()
    python_writer.join(10)
    launcher.join(10)

    assert python_writer.exitcode == 0
    assert launcher.exitcode == 0
    assert errors.empty()
    assert results.get(timeout=2)["outcome"] == "success"
    assert _read_json(tmp_path / "latest.json")["outcome"] == "success"


def test_result_lock_is_released_when_owner_process_exits(tmp_path):
    store = RunResultStore(tmp_path)
    run = store.start("daily-post", run_id="run-1")
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    owner = context.Process(target=_exit_while_holding_result_lock, args=(tmp_path, acquired))

    owner.start()
    assert acquired.wait(10)
    owner.join(10)
    assert owner.exitcode == 0

    result = store.finish(run, outcome="success", reason="success")
    assert result["outcome"] == "success"


def test_different_run_cannot_replace_active_run(tmp_path):
    store = RunResultStore(tmp_path)
    active = store.start("daily-post", run_id="run-1")

    with pytest.raises(RunOverlapError) as error:
        store.start("keepalive", run_id="run-2")

    assert error.value.reason == "overlap_locked"
    assert error.value.active_run_id == "run-1"
    assert _read_json(tmp_path / "latest.json") == active


def test_same_run_and_command_start_is_idempotent(tmp_path):
    store = RunResultStore(tmp_path)
    first = store.start("daily-post", run_id="run-1")

    assert store.start("daily-post", run_id="run-1") == first


def test_same_run_id_with_different_command_is_rejected(tmp_path):
    store = RunResultStore(tmp_path)
    store.start("daily-post", run_id="run-1")

    with pytest.raises(RunIdReuseError, match="different command"):
        store.start("keepalive", run_id="run-1")


def test_multiprocess_starts_allow_exactly_one_active_run(tmp_path):
    context = multiprocessing.get_context("spawn")
    gate = context.Event()
    results = context.Queue()
    processes = [
        context.Process(target=_race_start, args=(tmp_path, "daily-post", "run-1", gate, results)),
        context.Process(target=_race_start, args=(tmp_path, "keepalive", "run-2", gate, results)),
    ]
    for process in processes:
        process.start()
    gate.set()
    for process in processes:
        process.join(10)

    assert [process.exitcode for process in processes] == [0, 0]
    outcomes = [results.get(timeout=2), results.get(timeout=2)]
    assert sorted(outcome[0] for outcome in outcomes) == ["overlap_locked", "started"]
    started_run_id = next(value for state, value in outcomes if state == "started")
    assert _read_json(tmp_path / "latest.json")["run_id"] == started_run_id


@pytest.mark.parametrize(
    "run_id",
    [
        "",
        ".",
        "..",
        "../escape",
        "folder/run",
        "folder\\run",
        "run:1",
        "run 1",
        "run\n1",
        "CON",
        "lpt1",
        "-run",
        "a" * 129,
    ],
)
def test_invalid_run_ids_are_rejected_without_files(tmp_path, run_id):
    with pytest.raises(ValueError, match="invalid run_id"):
        RunResultStore(tmp_path / "results").start("daily-post", run_id=run_id)

    assert not (tmp_path / "escape.json").exists()
    assert not (tmp_path / "results" / "latest.json").exists()


def test_completed_run_id_cannot_be_reused_after_newer_runs(tmp_path):
    store = RunResultStore(tmp_path)
    first = store.start("daily-post", run_id="run-1")
    first_result = store.finish(first, outcome="success", reason="success")
    second = store.start("keepalive", run_id="run-2")
    store.finish(second, outcome="no_action", reason="already_posted_today")

    with pytest.raises(RunIdReuseError) as error:
        store.start("daily-post", run_id="run-1")

    assert error.value.reason == "run_id_reused"
    history = tmp_path / "history" / first_result["finished_at"][:10] / "run-1.json"
    assert _read_json(history) == first_result


@pytest.mark.parametrize("reserved_key", sorted(RESERVED_RESULT_FIELDS))
def test_finish_rejects_reserved_result_fields(tmp_path, reserved_key):
    store = RunResultStore(tmp_path)
    run = store.start("daily-post", run_id="run-1")

    with pytest.raises(ValueError, match="reserved result fields"):
        store.finish(
            run,
            outcome="preflight_blocked",
            reason="browser_missing",
            extra_fields={reserved_key: "attacker-controlled"},
        )

    latest = _read_json(tmp_path / "latest.json")
    assert latest["schema"] == "fb-autoposter-run/v1"
    assert latest["run_id"] == "run-1"
    assert latest["terminal"] is False


def test_direct_reserved_field_cannot_override_exact_exit_mapping(tmp_path):
    store = RunResultStore(tmp_path)
    run = store.start("daily-post", run_id="run-1")

    with pytest.raises(ValueError, match="exit_code"):
        store.finish(
            run,
            outcome="preflight_blocked",
            reason="browser_missing",
            exit_code=0,
        )

    assert _read_json(tmp_path / "latest.json")["terminal"] is False


def test_result_redacts_sensitive_fields_and_values_without_caller_secret_list(tmp_path):
    store = RunResultStore(tmp_path)
    run = store.start("daily-post", run_id="run-1")

    store.finish(
        run,
        outcome="internal_error",
        reason="provider_auth_failed",
        details={
            "authorization": "Bearer 123456:abcdefghijklmnopqrstuvwxyzABCDE",
            "telegram_bot_token": "123456:abcdefghijklmnopqrstuvwxyzABCDE",
            "post_body": "private listing copy",
            "safe": "request failed Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
        },
        exception="request failed token=abcdefghijklmnopqrstuvwxyzABCDE",
    )

    serialized = (tmp_path / "latest.json").read_text(encoding="utf-8")
    assert "abcdefghijklmnopqrstuvwxyz" not in serialized
    assert "private listing copy" not in serialized
    result = json.loads(serialized)
    assert result["details"]["authorization"] == "[REDACTED]"
    assert result["details"]["post_body"] == "[REDACTED]"
    assert "abcdefghijklmnopqrstuvwxyz" not in result["exception"]


@pytest.mark.parametrize("reason", ["free text", "database_password_leaked", "TOKEN=abc"])
def test_reason_must_be_an_allowlisted_code(tmp_path, reason):
    store = RunResultStore(tmp_path)
    run = store.start("daily-post", run_id="run-1")

    with pytest.raises(ValueError, match="reason code"):
        store.finish(run, outcome="internal_error", reason=reason)

    assert _read_json(tmp_path / "latest.json")["terminal"] is False


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
    started = now - timedelta(hours=30)
    result = {
        "schema": "fb-autoposter-run/v1",
        "terminal": True,
        "run_id": "run-1",
        "command": "daily-post",
        "started_at": started.isoformat(),
        "finished_at": (now - timedelta(hours=29, minutes=59)).isoformat(),
        "result_at": (now - timedelta(hours=29, minutes=59)).isoformat(),
        "outcome": "success",
        "reason": "success",
        "exit_code": 0,
        "finalized_by": "python",
        "pre_sqlite_failure": False,
    }

    assert is_fresh_terminal_result(result, sqlite_run_id="run-1", now=now) is True
    assert is_fresh_terminal_result(result, sqlite_run_id="run-2", now=now) is False
    stale = {**result, "finished_at": (now - timedelta(hours=30)).isoformat()}
    assert is_fresh_terminal_result(stale, sqlite_run_id="run-1", now=now) is False


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("schema", "wrong/v1"),
        ("terminal", False),
        ("run_id", "../bad"),
        ("command", ""),
        ("started_at", "not-a-time"),
        ("finished_at", "not-a-time"),
        ("result_at", "not-a-time"),
        ("outcome", "unknown"),
        ("reason", "free text"),
        ("exit_code", 60),
        ("finalized_by", "attacker"),
        ("pre_sqlite_failure", "yes"),
    ],
)
def test_freshness_rejects_noncanonical_terminal_results(tmp_path, field, bad_value):
    result = _terminal_result(tmp_path)
    result[field] = bad_value

    assert not is_fresh_terminal_result(result, sqlite_run_id="run-1")


def test_only_documented_launcher_owned_pre_sqlite_failure_can_lack_db_row():
    now = datetime(2026, 7, 16, 12, tzinfo=UTC)
    base = {
        "schema": "fb-autoposter-run/v1",
        "terminal": True,
        "run_id": "run-1",
        "command": "daily-post",
        "started_at": (now - timedelta(minutes=2)).isoformat(),
        "finished_at": (now - timedelta(minutes=1)).isoformat(),
        "result_at": (now - timedelta(minutes=1)).isoformat(),
        "outcome": "internal_error",
        "reason": "launcher_failed",
        "exit_code": 60,
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
    result = _terminal_result(
        tmp_path / "results",
        outcome="preflight_blocked",
        reason="browser_missing",
    )

    started = db.start_run("daily-post", run_id="run-1", started_at=result["started_at"])
    finished = db.finish_run("run-1", result=result)

    assert started["run_id"] == "run-1"
    assert finished["run_id"] == "run-1"
    assert finished["outcome"] == "preflight_blocked"
    assert db.latest_run()["run_id"] == "run-1"


def test_queue_db_rejects_invalid_started_at(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")

    with pytest.raises(ValueError, match="started_at"):
        db.start_run("daily-post", run_id="run-1", started_at="not-a-time")


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("schema", "wrong/v1"),
        ("outcome", "unknown"),
        ("exit_code", 0),
        ("reason", "free text with password=secret"),
        ("run_id", "other-run"),
    ],
)
def test_queue_db_rejects_noncanonical_terminal_results(tmp_path, field, bad_value):
    result = _terminal_result(tmp_path / "results", outcome="internal_error", reason="launcher_failed")
    db = QueueDB(tmp_path / "jobs.db")
    db.start_run("daily-post", run_id="run-1", started_at=result["started_at"])
    result[field] = bad_value

    with pytest.raises(ValueError):
        db.finish_run("run-1", result=result)

    assert db.get_run("run-1")["finished_at"] is None


def test_queue_db_sanitizes_canonical_result_before_persisting(tmp_path):
    result = _terminal_result(tmp_path / "results", outcome="internal_error", reason="provider_auth_failed")
    result["details"] = {"safe": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz"}
    db = QueueDB(tmp_path / "jobs.db")
    db.start_run("daily-post", run_id="run-1", started_at=result["started_at"])

    db.finish_run("run-1", result=result)

    stored = db.get_run("run-1")
    assert "abcdefghijklmnopqrstuvwxyz" not in stored["result_json"]


def test_runs_migration_does_not_change_existing_posting_rows(tmp_path):
    db_path = tmp_path / "jobs.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE jobs (
              job_id TEXT PRIMARY KEY, property_id TEXT NOT NULL, status TEXT NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, degraded INTEGER DEFAULT 0,
              payload_json TEXT NOT NULL
            );
            CREATE TABLE job_targets (
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, group_id TEXT NOT NULL,
              body TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER DEFAULT 0,
              last_error TEXT, posted_at TEXT, screenshot TEXT, permalink TEXT,
              UNIQUE(job_id, group_id)
            );
            CREATE TABLE heartbeat (component TEXT PRIMARY KEY, last_seen TEXT NOT NULL);
            CREATE TABLE group_circuit (
              group_id TEXT PRIMARY KEY, consecutive_failures INTEGER NOT NULL DEFAULT 0,
              disabled_suggested INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
            );
            INSERT INTO jobs VALUES(
              'job-1', 'p1', 'done', '2026-01-01T00:00:00+00:00',
              '2026-01-01T00:00:00+00:00', 0, '{}'
            );
            INSERT INTO job_targets(
              job_id, group_id, body, status, posted_at
            ) VALUES('job-1', 'g1', 'body', 'posted', '2026-01-01T00:01:00+00:00');
            """
        )

    migrated = QueueDB(db_path)
    migrated.start_run("daily-post", run_id="run-1")
    after = migrated.get_targets("job-1")[0]

    assert after["status"] == "posted"
    assert after["posted_at"] == "2026-01-01T00:01:00+00:00"


def test_launcher_reconciles_history_when_latest_terminal_write_failed(tmp_path):
    class LatestTerminalFailureStore(RunResultStore):
        def _write_atomic(self, path, result):
            if Path(path).name == "latest.json" and result.get("terminal"):
                raise OSError("injected latest write failure")
            super()._write_atomic(path, result)

    store = LatestTerminalFailureStore(tmp_path)
    run = store.start("daily-post", run_id="run-1")
    with pytest.raises(OSError, match="injected"):
        store.finish(run, outcome="success", reason="success")

    assert _read_json(tmp_path / "latest.json")["terminal"] is False
    reconciled = RunResultStore(tmp_path).finalize_from_launcher(
        "run-1", reason="launcher_failed"
    )
    assert reconciled["outcome"] == "success"
    assert _read_json(tmp_path / "latest.json") == reconciled


def test_launcher_rejects_noncanonical_existing_terminal_result(tmp_path):
    store = RunResultStore(tmp_path)
    _terminal_result(tmp_path)
    corrupted = _read_json(tmp_path / "latest.json")
    corrupted["exit_code"] = 60
    (tmp_path / "latest.json").write_text(json.dumps(corrupted), encoding="utf-8")

    with pytest.raises(ValueError, match="exit_code"):
        store.finalize_from_launcher("run-1", reason="launcher_failed")
