from __future__ import annotations

import json
import hashlib
import sqlite3
import re
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse

from src.run_result import (
    sanitize_terminal_result,
    validate_command,
    validate_run_id,
    validate_timestamp,
)

JOB_STATUSES = {"pending", "approved", "rejected", "posting", "done", "partial_failed", "failed"}
TARGET_STATUSES = {
    "pending", "pending_approval", "approved", "submitting", "posted",
    "failed", "skipped", "uncertain",
}
AUTO_APPROVAL_GATE_KEYS = frozenset(
    {
        "source_present",
        "source_fresh",
        "source_hash_matches",
        "property_identity_matches",
        "broker_known",
        "body_hash_matches",
        "generation_fingerprint_matches",
        "circuit_clear",
        "session_healthy",
        "runtime_healthy",
        "group_allowed",
        "duplicate_clear",
    }
)


def normalized_body_hash(body: str) -> str:
    """Stable SHA-256 over the body representation shown to an approver."""
    normalized = unicodedata.normalize("NFC", body).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.strip().split("\n"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _jst_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Tokyo"))
    except Exception:
        from datetime import timezone

        return datetime.now(timezone(timedelta(hours=9)))


def jst_today_utc_bounds() -> tuple[str, str]:
    """UTC ISO bounds [start, end) covering the current JST calendar day.

    Cadence is reasoned about in JST (the schedule is JST), but timestamps are
    stored in UTC. Comparing stored UTC ISO strings against these UTC bounds is
    timezone-correct and DB-agnostic (lexicographic order matches chronological
    order because every stored timestamp uses the same +00:00 suffix).
    """
    now_jst = _jst_now()
    start_jst = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_jst.astimezone(UTC)
    return start_utc.isoformat(), (start_utc + timedelta(hours=24)).isoformat()


class QueueDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                  job_id        TEXT PRIMARY KEY,
                  property_id   TEXT NOT NULL,
                  status        TEXT NOT NULL,
                  created_at    TEXT NOT NULL,
                  updated_at    TEXT NOT NULL,
                  degraded      INTEGER DEFAULT 0,
                  payload_json  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_targets (
                  id            INTEGER PRIMARY KEY AUTOINCREMENT,
                  job_id        TEXT NOT NULL,
                  group_id      TEXT NOT NULL,
                  body          TEXT NOT NULL,
                  status        TEXT NOT NULL,
                  attempts      INTEGER DEFAULT 0,
                  last_error    TEXT,
                  posted_at     TEXT,
                  screenshot    TEXT,
                  permalink     TEXT,
                  UNIQUE(job_id, group_id),
                  FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS heartbeat (
                  component   TEXT PRIMARY KEY,
                  last_seen   TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS group_circuit (
                  group_id TEXT PRIMARY KEY,
                  consecutive_failures INTEGER NOT NULL DEFAULT 0,
                  disabled_suggested INTEGER NOT NULL DEFAULT 0,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                  run_id       TEXT PRIMARY KEY,
                  command      TEXT NOT NULL,
                  started_at   TEXT NOT NULL,
                  finished_at  TEXT,
                  outcome      TEXT,
                  reason       TEXT,
                  exit_code    INTEGER,
                  result_json  TEXT
                );

                CREATE TABLE IF NOT EXISTS safety_circuits (
                  circuit_id TEXT PRIMARY KEY,
                  scope TEXT NOT NULL,
                  subject TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  opened_at TEXT NOT NULL,
                  expires_at TEXT,
                  clearance_mode TEXT NOT NULL,
                  operator_reviewed_at TEXT,
                  operator_reviewed_by TEXT,
                  cleared_at TEXT,
                  cleared_by TEXT,
                  clearance_reason TEXT
                );

                CREATE TABLE IF NOT EXISTS circuit_events (
                  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  kind TEXT NOT NULL,
                  group_id TEXT,
                  environment TEXT,
                  occurred_at TEXT NOT NULL,
                  metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS approvals (
                  approval_id TEXT PRIMARY KEY,
                  job_id TEXT NOT NULL,
                  property_id TEXT NOT NULL,
                  group_id TEXT NOT NULL,
                  source_hash TEXT NOT NULL,
                  body_hash TEXT NOT NULL,
                  generation_fingerprint TEXT NOT NULL,
                  source TEXT NOT NULL,
                  approved_at TEXT NOT NULL,
                  FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS submission_attempts (
                  attempt_id TEXT PRIMARY KEY,
                  job_id TEXT NOT NULL,
                  property_id TEXT NOT NULL,
                  group_id TEXT NOT NULL,
                  approval_id TEXT NOT NULL,
                  state TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  click_started_at TEXT,
                  response_received_at TEXT,
                  verification_started_at TEXT,
                  completed_at TEXT,
                  last_error TEXT,
                  permalink TEXT,
                  reopen_count INTEGER NOT NULL DEFAULT 0,
                  last_reopened_at TEXT,
                  UNIQUE(property_id, group_id, approval_id),
                  FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
                  FOREIGN KEY(approval_id) REFERENCES approvals(approval_id)
                );
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(job_targets)")}
            additions = {
                "source_hash": "TEXT",
                "normalized_body_hash": "TEXT",
                "generation_fingerprint": "TEXT",
                "approval_id": "TEXT",
                "reconcile_only": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, declaration in additions.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE job_targets ADD COLUMN {name} {declaration}")
            attempt_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(submission_attempts)")
            }
            attempt_additions = {
                "reopen_count": "INTEGER NOT NULL DEFAULT 0",
                "last_reopened_at": "TEXT",
            }
            for name, declaration in attempt_additions.items():
                if name not in attempt_columns:
                    conn.execute(
                        f"ALTER TABLE submission_attempts ADD COLUMN {name} {declaration}"
                    )
            conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_circuits_active
                  ON safety_circuits(scope, subject, cleared_at, opened_at);
                CREATE INDEX IF NOT EXISTS idx_circuit_events_window
                  ON circuit_events(kind, occurred_at, group_id, environment);
                CREATE INDEX IF NOT EXISTS idx_attempts_target
                  ON submission_attempts(property_id, group_id, click_started_at);
                CREATE TRIGGER IF NOT EXISTS approvals_immutable_update
                  BEFORE UPDATE ON approvals BEGIN
                    SELECT RAISE(ABORT, 'approvals are immutable');
                  END;
                CREATE TRIGGER IF NOT EXISTS approvals_immutable_delete
                  BEFORE DELETE ON approvals BEGIN
                    SELECT RAISE(ABORT, 'approvals are immutable');
                  END;
                """
            )

    def start_run(
        self,
        command: str,
        *,
        run_id: str,
        started_at: str | None = None,
    ) -> dict[str, Any]:
        validate_run_id(run_id)
        validate_command(command)
        timestamp = started_at or now_iso()
        validate_timestamp(timestamp, "started_at")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO runs(run_id, command, started_at) VALUES(?,?,?)",
                (run_id, command, timestamp),
            )
        run = self.get_run(run_id)
        assert run is not None
        return run

    def finish_run(
        self,
        run_id: str,
        *,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        validate_run_id(run_id)
        canonical = sanitize_terminal_result(result)
        if canonical["run_id"] != run_id:
            raise ValueError("terminal result run_id does not match SQLite run")
        serialized = json.dumps(canonical, ensure_ascii=False, sort_keys=True)
        with self.connect() as conn:
            existing = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if existing is None:
                raise RuntimeError(f"run missing or already terminal: {run_id}")
            if existing["command"] != canonical["command"]:
                raise ValueError("terminal result command does not match SQLite run")
            if existing["started_at"] != canonical["started_at"]:
                raise ValueError("terminal result started_at does not match SQLite run")
            cursor = conn.execute(
                """
                UPDATE runs
                SET finished_at=?, outcome=?, reason=?, exit_code=?, result_json=?
                WHERE run_id=? AND finished_at IS NULL
                """,
                (
                    canonical["finished_at"],
                    canonical["outcome"],
                    canonical["reason"],
                    canonical["exit_code"],
                    serialized,
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"run missing or already terminal: {run_id}")
        run = self.get_run(run_id)
        assert run is not None
        return run

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def latest_run(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def create_job(self, property_data: dict[str, Any], variants: list[dict[str, Any]], *, degraded: bool = False) -> str:
        job_id = property_data.get("job_id") or str(uuid.uuid4())
        property_id = property_data.get("property_id") or job_id
        ts = now_iso()
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO jobs(job_id, property_id, status, created_at, updated_at, degraded, payload_json) VALUES(?,?,?,?,?,?,?)",
                (job_id, property_id, "pending", ts, ts, int(degraded), json.dumps(property_data, ensure_ascii=False)),
            )
            for variant in variants:
                source_hash = variant.get("source_hash")
                fingerprint = variant.get("generation_fingerprint")
                target_status = "pending_approval" if source_hash is not None or fingerprint is not None else "pending"
                conn.execute(
                    """INSERT OR IGNORE INTO job_targets(
                       job_id, group_id, body, status, source_hash,
                       normalized_body_hash, generation_fingerprint
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (
                        job_id, variant["group_id"], variant["body"], target_status,
                        source_hash, normalized_body_hash(variant["body"]), fingerprint,
                    ),
                )
        return job_id

    def update_job_status(self, job_id: str, status: str) -> None:
        if status not in JOB_STATUSES:
            raise ValueError(f"invalid job status: {status}")
        with self.connect() as conn:
            conn.execute("UPDATE jobs SET status=?, updated_at=? WHERE job_id=?", (status, now_iso(), job_id))

    def update_target_status(
        self,
        job_id: str,
        group_id: str,
        status: str,
        *,
        error: str | None = None,
        screenshot: str | None = None,
        permalink: str | None = None,
        increment_attempts: bool = False,
    ) -> None:
        if status not in TARGET_STATUSES:
            raise ValueError(f"invalid target status: {status}")
        # 'uncertain' very likely DID publish (we just could not verify it), so
        # stamp it like a post. The same-group spacing guard and daily cap then
        # treat it as a real post and never over-post (block-avoidance first).
        # IMPORTANT: posted_at is the FIRST-post time and must never be overwritten.
        # The SQL uses COALESCE(posted_at, ?) so a later re-verify (uncertain->posted,
        # or a verify sweep re-confirming) keeps the original time. Overwriting it
        # collapsed many historical posts onto the verify time, which wrongly
        # inflated count_posts_today() and blocked all new posting via daily_limit.
        posted_at = now_iso() if status in ("posted", "uncertain") else None
        with self.connect() as conn:
            if status in {"pending", "pending_approval", "approved", "submitting"}:
                target = conn.execute(
                    """SELECT j.property_id FROM job_targets t JOIN jobs j ON j.job_id=t.job_id
                       WHERE t.job_id=? AND t.group_id=?""",
                    (job_id, group_id),
                ).fetchone()
                if target and conn.execute(
                    """SELECT 1 FROM submission_attempts
                       WHERE property_id=? AND group_id=? AND click_started_at IS NOT NULL LIMIT 1""",
                    (target["property_id"], group_id),
                ).fetchone():
                    raise ValueError("click boundary permanently prevents an eligible target state")
            if increment_attempts:
                conn.execute(
                    """
                    UPDATE job_targets
                    SET status=?, attempts=attempts + 1, last_error=?, posted_at=COALESCE(posted_at, ?),
                        screenshot=COALESCE(?, screenshot), permalink=COALESCE(?, permalink)
                    WHERE job_id=? AND group_id=?
                    """,
                    (status, error, posted_at, screenshot, permalink, job_id, group_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE job_targets
                    SET status=?, last_error=?, posted_at=COALESCE(posted_at, ?),
                        screenshot=COALESCE(?, screenshot), permalink=COALESCE(?, permalink)
                    WHERE job_id=? AND group_id=?
                    """,
                    (status, error, posted_at, screenshot, permalink, job_id, group_id),
                )

    def approve_job(self, job_id: str) -> None:
        self.update_job_status(job_id, "approved")

    def approve_target(
        self,
        job_id: str,
        group_id: str,
        *,
        source: str,
        approval_id: str | None = None,
        approved_at: str | None = None,
    ) -> dict[str, Any]:
        if source not in {"telegram", "operator", "auto_policy"}:
            raise ValueError("invalid approval source")
        with self.connect() as conn:
            target = conn.execute(
                """SELECT t.*, j.property_id, j.payload_json FROM job_targets t JOIN jobs j ON j.job_id=t.job_id
                   WHERE t.job_id=? AND t.group_id=?""",
                (job_id, group_id),
            ).fetchone()
            if target is None:
                raise ValueError("target not found")
            clicked = conn.execute(
                "SELECT 1 FROM submission_attempts WHERE property_id=? AND group_id=? AND click_started_at IS NOT NULL LIMIT 1",
                (target["property_id"], group_id),
            ).fetchone()
            if clicked:
                raise ValueError("click boundary permanently prevents approval")
            if target["status"] == "submitting":
                raise ValueError("active submission attempt prevents approval changes")
            source_hash = target["source_hash"] or ""
            body_hash = target["normalized_body_hash"] or normalized_body_hash(target["body"])
            fingerprint = target["generation_fingerprint"] or ""
            payload_property_id = json.loads(target["payload_json"]).get("property_id")
            if not all(
                isinstance(value, str) and value.strip()
                for value in (
                    payload_property_id, target["property_id"], group_id, target["body"], source_hash,
                    body_hash, fingerprint,
                )
            ):
                raise ValueError("approval binding fields must all be non-empty")
            if approval_id is not None:
                old = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
                if old is None or any(
                    old[name] != value
                    for name, value in (
                        ("job_id", job_id), ("group_id", group_id),
                        ("source_hash", source_hash), ("body_hash", body_hash),
                        ("generation_fingerprint", fingerprint),
                    )
                ):
                    raise ValueError("stale approval callback")
                row = old
            else:
                approval_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO approvals(
                       approval_id, job_id, property_id, group_id, source_hash, body_hash,
                       generation_fingerprint, source, approved_at
                       ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        approval_id, job_id, target["property_id"], group_id, source_hash,
                        body_hash, fingerprint, source, approved_at or now_iso(),
                    ),
                )
                row = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
            conn.execute(
                """UPDATE job_targets SET status='approved', approval_id=?, source_hash=?,
                   normalized_body_hash=?, generation_fingerprint=?, reconcile_only=0
                   WHERE job_id=? AND group_id=?""",
                (approval_id, source_hash, body_hash, fingerprint, job_id, group_id),
            )
        return dict(row)

    def auto_approve_target(
        self,
        job_id: str,
        group_id: str,
        *,
        gates: dict[str, bool],
        auto_approve_enabled: bool = False,
    ) -> dict[str, Any]:
        if auto_approve_enabled is not True:
            raise ValueError("auto approval is disabled")
        if set(gates) != AUTO_APPROVAL_GATE_KEYS:
            raise ValueError("canonical auto-approval gate set is required")
        if not all(value is True for value in gates.values()):
            raise ValueError("all auto-approval gates must pass")
        return self.approve_target(job_id, group_id, source="auto_policy")

    def set_target_content(
        self,
        job_id: str,
        group_id: str,
        *,
        body: str,
        source_hash: str,
        generation_fingerprint: str,
    ) -> None:
        body_hash = normalized_body_hash(body)
        with self.connect() as conn:
            # Serialize content invalidation against mark_click_started(). Once
            # this lock is held, either the pre-click attempt is aborted here or
            # a previously committed click boundary is observed and preserved.
            conn.execute("BEGIN IMMEDIATE")
            target = conn.execute(
                """SELECT t.*, j.property_id FROM job_targets t JOIN jobs j ON j.job_id=t.job_id
                   WHERE t.job_id=? AND t.group_id=?""",
                (job_id, group_id),
            ).fetchone()
            if target is None:
                raise ValueError("target not found")
            if (
                target["normalized_body_hash"] == body_hash
                and target["source_hash"] == source_hash
                and target["generation_fingerprint"] == generation_fingerprint
            ):
                return
            clicked = conn.execute(
                "SELECT 1 FROM submission_attempts WHERE property_id=? AND group_id=? AND click_started_at IS NOT NULL LIMIT 1",
                (target["property_id"], group_id),
            ).fetchone()
            status = target["status"] if clicked else "pending_approval"
            approval_id = target["approval_id"] if clicked else None
            if not clicked:
                timestamp = now_iso()
                conn.execute(
                    """UPDATE submission_attempts
                       SET state='aborted_preclick', completed_at=?, last_error='content_invalidated'
                       WHERE job_id=? AND group_id=? AND state='submitting'
                         AND click_started_at IS NULL""",
                    (timestamp, job_id, group_id),
                )
            conn.execute(
                """UPDATE job_targets SET body=?, source_hash=?, normalized_body_hash=?,
                   generation_fingerprint=?, status=?, approval_id=? WHERE job_id=? AND group_id=?""",
                (body, source_hash, body_hash, generation_fingerprint, status, approval_id, job_id, group_id),
            )

    def begin_submission(
        self,
        job_id: str,
        group_id: str,
        *,
        approval_id: str,
        source_hash: str,
        body_hash: str,
        generation_fingerprint: str,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            target = conn.execute(
                """SELECT t.*, j.property_id FROM job_targets t JOIN jobs j ON j.job_id=t.job_id
                   WHERE t.job_id=? AND t.group_id=?""",
                (job_id, group_id),
            ).fetchone()
            approval = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
            values = (source_hash, body_hash, generation_fingerprint, approval_id)
            target_values = (
                target["source_hash"] if target else None,
                target["normalized_body_hash"] if target else None,
                target["generation_fingerprint"] if target else None,
                target["approval_id"] if target else None,
            )
            approval_values = (
                approval["source_hash"] if approval else None,
                approval["body_hash"] if approval else None,
                approval["generation_fingerprint"] if approval else None,
                approval["approval_id"] if approval else None,
            )
            if target is None or target["status"] != "approved" or values != target_values or values != approval_values:
                raise ValueError("approval mismatch")
            if (
                approval["job_id"] != job_id
                or approval["group_id"] != group_id
                or approval["property_id"] != target["property_id"]
                or not all(isinstance(value, str) and value.strip() for value in values)
                or not target["property_id"].strip()
                or not group_id.strip()
            ):
                raise ValueError("approval mismatch")
            if conn.execute(
                "SELECT 1 FROM submission_attempts WHERE property_id=? AND group_id=? AND click_started_at IS NOT NULL LIMIT 1",
                (target["property_id"], group_id),
            ).fetchone():
                raise ValueError("click boundary permanently prevents a new attempt")
            existing = conn.execute(
                """SELECT * FROM submission_attempts
                   WHERE property_id=? AND group_id=? AND approval_id=?""",
                (target["property_id"], group_id, approval_id),
            ).fetchone()
            if existing:
                if existing["state"] != "aborted_preclick" or existing["click_started_at"] is not None:
                    raise ValueError("existing attempt cannot be reopened")
                attempt_id = existing["attempt_id"]
                reopened_at = created_at or now_iso()
                conn.execute(
                    """UPDATE submission_attempts
                       SET state='submitting', completed_at=NULL, last_error=NULL,
                           response_received_at=NULL, verification_started_at=NULL,
                           reopen_count=reopen_count+1, last_reopened_at=?
                       WHERE attempt_id=? AND state='aborted_preclick'
                         AND click_started_at IS NULL""",
                    (reopened_at, attempt_id),
                )
            else:
                attempt_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO submission_attempts(
                       attempt_id, job_id, property_id, group_id, approval_id, state, created_at
                       ) VALUES(?,?,?,?,?,'submitting',?)""",
                    (
                        attempt_id, job_id, target["property_id"], group_id,
                        approval_id, created_at or now_iso(),
                    ),
                )
            conn.execute(
                "UPDATE job_targets SET status='submitting' WHERE job_id=? AND group_id=? AND status='approved'",
                (job_id, group_id),
            )
            row = conn.execute("SELECT * FROM submission_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        return dict(row)

    def get_submission_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM submission_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        return dict(row) if row else None

    def list_submission_attempts(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM submission_attempts ORDER BY created_at, rowid").fetchall()
        return [dict(row) for row in rows]

    def mark_click_started(self, attempt_id: str, *, at: datetime | str | None = None) -> dict[str, Any]:
        timestamp = at.isoformat() if isinstance(at, datetime) else (at or now_iso())
        with self.connect() as conn:
            cursor = conn.execute(
                """UPDATE submission_attempts SET click_started_at=?
                   WHERE attempt_id=? AND state='submitting' AND click_started_at IS NULL""",
                (timestamp, attempt_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("attempt is not awaiting click")
        return self.get_submission_attempt(attempt_id)  # type: ignore[return-value]

    def mark_submission_response(self, attempt_id: str, *, at: str | None = None) -> dict[str, Any]:
        return self._stamp_attempt(attempt_id, "response_received_at", at or now_iso())

    def mark_verification_started(self, attempt_id: str, *, at: str | None = None) -> dict[str, Any]:
        return self._stamp_attempt(attempt_id, "verification_started_at", at or now_iso())

    def _stamp_attempt(self, attempt_id: str, column: str, timestamp: str) -> dict[str, Any]:
        if column not in {"response_received_at", "verification_started_at"}:
            raise ValueError("invalid attempt timestamp")
        with self.connect() as conn:
            cursor = conn.execute(
                f"UPDATE submission_attempts SET {column}=? WHERE attempt_id=? AND click_started_at IS NOT NULL",
                (timestamp, attempt_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("click boundary not recorded")
        return self.get_submission_attempt(attempt_id)  # type: ignore[return-value]

    def abort_submission_preclick(self, attempt_id: str, *, reason: str = "") -> dict[str, Any]:
        with self.connect() as conn:
            attempt = conn.execute("SELECT * FROM submission_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if attempt is None or attempt["state"] != "submitting" or attempt["click_started_at"] is not None:
                raise ValueError("pre-click abort is not allowed")
            conn.execute(
                "UPDATE submission_attempts SET state='aborted_preclick', completed_at=?, last_error=? WHERE attempt_id=?",
                (now_iso(), reason, attempt_id),
            )
            conn.execute(
                "UPDATE job_targets SET status='approved' WHERE job_id=? AND group_id=? AND status='submitting'",
                (attempt["job_id"], attempt["group_id"]),
            )
        return self.get_submission_attempt(attempt_id)  # type: ignore[return-value]

    def mark_attempt_reconcile_only(self, attempt_id: str, *, reason: str = "ambiguous") -> dict[str, Any]:
        with self.connect() as conn:
            attempt = conn.execute("SELECT * FROM submission_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if attempt is None or attempt["click_started_at"] is None:
                raise ValueError("reconcile-only requires a click boundary")
            conn.execute(
                "UPDATE submission_attempts SET state='reconcile_only', last_error=? WHERE attempt_id=?",
                (reason, attempt_id),
            )
            conn.execute(
                """UPDATE job_targets SET status='uncertain', reconcile_only=1,
                   posted_at=COALESCE(posted_at, ?) WHERE job_id=? AND group_id=?""",
                (attempt["click_started_at"], attempt["job_id"], attempt["group_id"]),
            )
        return self.get_submission_attempt(attempt_id)  # type: ignore[return-value]

    def recover_incomplete_attempts(self) -> int:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM submission_attempts WHERE state='submitting'").fetchall()
        for row in rows:
            if row["click_started_at"] is None:
                self.abort_submission_preclick(row["attempt_id"], reason="process_recovery_before_click")
            else:
                self.mark_attempt_reconcile_only(row["attempt_id"], reason="process_exit_after_click")
        return len(rows)

    def resolve_submission(
        self, attempt_id: str, *, outcome: str, permalink: str | None = None
    ) -> dict[str, Any]:
        attempt = self.get_submission_attempt(attempt_id)
        if attempt is None or attempt["state"] != "submitting":
            raise ValueError("resolve_submission requires a currently submitting attempt")
        if outcome == "confirmed":
            return self._confirm_submission(attempt_id, permalink=permalink)
        if outcome in {"ambiguous", "inconclusive"}:
            return self.mark_attempt_reconcile_only(attempt_id, reason=outcome)
        raise ValueError("invalid submission outcome")

    def verify_submission(
        self, attempt_id: str, *, outcome: str, permalink: str | None = None
    ) -> dict[str, Any]:
        attempt = self.get_submission_attempt(attempt_id)
        if attempt is None:
            raise ValueError("attempt not found")
        if attempt["click_started_at"] is None:
            raise ValueError("verification requires a click boundary")
        if outcome == "confirmed":
            return self._confirm_submission(attempt_id, permalink=permalink)
        if outcome == "invalid":
            return self.mark_attempt_reconcile_only(attempt_id, reason="verification_invalid")
        if outcome == "inconclusive":
            return attempt
        raise ValueError("invalid verification outcome")

    def _confirm_submission(self, attempt_id: str, *, permalink: str | None) -> dict[str, Any]:
        if not self._is_valid_facebook_permalink(permalink):
            self.mark_attempt_reconcile_only(
                attempt_id, reason="missing_or_invalid_facebook_permalink"
            )
            raise ValueError("a captured HTTPS Facebook permalink is required")
        with self.connect() as conn:
            attempt = conn.execute("SELECT * FROM submission_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if attempt is None or attempt["click_started_at"] is None:
                raise ValueError("confirmation requires a click boundary")
            conn.execute(
                """UPDATE submission_attempts SET state='posted', completed_at=?, permalink=COALESCE(?, permalink)
                   WHERE attempt_id=?""",
                (now_iso(), permalink, attempt_id),
            )
            conn.execute(
                """UPDATE job_targets SET status='posted', reconcile_only=1,
                   posted_at=COALESCE(posted_at, ?), permalink=COALESCE(?, permalink)
                   WHERE job_id=? AND group_id=?""",
                (attempt["click_started_at"], permalink, attempt["job_id"], attempt["group_id"]),
            )
        return self.get_submission_attempt(attempt_id)  # type: ignore[return-value]

    @staticmethod
    def _is_valid_facebook_permalink(permalink: str | None) -> bool:
        if not isinstance(permalink, str) or not permalink.strip():
            return False
        parsed = urlparse(permalink)
        host = (parsed.hostname or "").lower()
        segments = [segment for segment in parsed.path.split("/") if segment]
        query = parse_qs(parsed.query)
        identifier = re.compile(r"^[A-Za-z0-9_-]+$")
        group_post = any(
            segments[index] == "groups"
            and index + 3 < len(segments)
            and bool(identifier.fullmatch(segments[index + 1]))
            and segments[index + 2] == "posts"
            and bool(identifier.fullmatch(segments[index + 3]))
            for index in range(len(segments))
        )
        permalink_path = any(
            segment == "permalink"
            and index + 1 < len(segments)
            and bool(identifier.fullmatch(segments[index + 1]))
            for index, segment in enumerate(segments)
        )
        share_path = any(
            segments[index:index + 2] == ["share", "p"]
            and index + 2 < len(segments)
            and bool(identifier.fullmatch(segments[index + 2]))
            for index in range(len(segments))
        )
        story_id = (query.get("story_fbid") or query.get("fbid") or [""])[0]
        query_permalink = (
            bool(segments)
            and segments[-1] in {"story.php", "photo.php"}
            and bool(identifier.fullmatch(story_id))
        )
        return (
            parsed.scheme == "https"
            and (host == "facebook.com" or host.endswith(".facebook.com"))
            and (group_post or permalink_path or share_path or query_permalink)
        )

    def submission_eligible(self, job_id: str, group_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT t.status, t.reconcile_only, j.property_id FROM job_targets t
                   JOIN jobs j ON j.job_id=t.job_id WHERE t.job_id=? AND t.group_id=?""",
                (job_id, group_id),
            ).fetchone()
            if row is None or row["status"] != "approved" or row["reconcile_only"]:
                return False
            clicked = conn.execute(
                "SELECT 1 FROM submission_attempts WHERE property_id=? AND group_id=? AND click_started_at IS NOT NULL LIMIT 1",
                (row["property_id"], group_id),
            ).fetchone()
        return clicked is None

    def reject_job(self, job_id: str, reason: str = "") -> None:
        self.update_job_status(job_id, "rejected")
        with self.connect() as conn:
            conn.execute(
                "UPDATE job_targets SET status='skipped', last_error=? WHERE job_id=? AND status='pending'",
                (reason, job_id),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def get_targets(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM job_targets WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
        return [dict(r) for r in rows]

    def pending_jobs(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def approved_jobs(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM jobs WHERE status IN ('approved', 'partial_failed') ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def unposted_targets(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM job_targets WHERE job_id=? AND status IN ('pending','failed') ORDER BY id",
                (job_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def finalize_job_from_targets(self, job_id: str) -> str:
        # Only a 'failed' target is a real failure. 'skipped' is a guard saying
        # "correctly did nothing" (daily cap, same-group spacing, duplicate,
        # outside active hours) and must not be reported as a failure — that was
        # surfacing as a scary `failed` summary even on perfectly healthy runs.
        # 'uncertain' very likely published, so it counts as success here.
        targets = self.get_targets(job_id)
        succeeded = [t for t in targets if t["status"] in ("posted", "uncertain")]
        failed = [t for t in targets if t["status"] == "failed"]
        if not targets:
            status = "failed"
        elif failed and succeeded:
            status = "partial_failed"
        elif failed:
            status = "failed"
        else:
            # all posted/uncertain/skipped -> nothing went wrong
            status = "done"
        self.update_job_status(job_id, status)
        return status

    def mark_heartbeat(self, component: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO heartbeat(component, last_seen) VALUES(?, ?) ON CONFLICT(component) DO UPDATE SET last_seen=excluded.last_seen",
                (component, now_iso()),
            )

    def heartbeat_age_minutes(self, component: str) -> float | None:
        with self.connect() as conn:
            row = conn.execute("SELECT last_seen FROM heartbeat WHERE component=?", (component,)).fetchone()
        if not row:
            return None
        last = datetime.fromisoformat(row["last_seen"])
        return (datetime.now(UTC) - last).total_seconds() / 60

    def count_posts_today(self) -> int:
        # Count posted AND uncertain (uncertain very likely published) within the
        # current JST calendar day. Fall back to the job's updated_at when
        # posted_at is missing (older uncertain rows).
        start, end = jst_today_utc_bounds()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM job_targets t JOIN jobs j ON j.job_id = t.job_id
                WHERE t.status IN ('posted', 'uncertain')
                  AND COALESCE(t.posted_at, j.updated_at) >= ?
                  AND COALESCE(t.posted_at, j.updated_at) <  ?
                """,
                (start, end),
            ).fetchone()
        return int(row["c"])

    def posted_same_group_today(self, group_id: str) -> bool:
        # Calendar-day (JST) spacing: at most one post per group per day. The
        # morning run posts (group not yet done today); the evening run skips
        # (already done). This guarantees exactly one post per group every day
        # with no gap days — unlike an hours-based interval, which drifts the
        # post later each day until a whole day gets skipped. Counts uncertain
        # too, and uses the job's updated_at when posted_at is missing.
        start, end = jst_today_utc_bounds()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM job_targets t JOIN jobs j ON j.job_id = t.job_id
                WHERE t.group_id = ? AND t.status IN ('posted', 'uncertain')
                  AND COALESCE(t.posted_at, j.updated_at) >= ?
                  AND COALESCE(t.posted_at, j.updated_at) <  ?
                LIMIT 1
                """,
                (group_id, start, end),
            ).fetchone()
        return row is not None

    def posted_same_group_recently(self, group_id: str, hours: int) -> bool:
        # Guarantee a full gap before posting to the same group again. Counts
        # uncertain too, and uses the job's updated_at when posted_at is missing
        # so historical uncertain posts still enforce the gap.
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM job_targets t JOIN jobs j ON j.job_id = t.job_id
                WHERE t.group_id = ? AND t.status IN ('posted', 'uncertain')
                  AND COALESCE(t.posted_at, j.updated_at) > ?
                LIMIT 1
                """,
                (group_id, cutoff),
            ).fetchone()
        return row is not None

    def duplicate_property_recently(self, property_id: str, group_id: str, minutes: int = 180) -> bool:
        cutoff = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM jobs j JOIN job_targets t ON j.job_id=t.job_id
                WHERE j.property_id=? AND t.group_id=? AND t.status='posted' AND t.posted_at > ?
                LIMIT 1
                """,
                (property_id, group_id, cutoff),
            ).fetchone()
        return row is not None

    def duplicate_property_completed_or_uncertain_ever(self, property_id: str, group_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM jobs j JOIN job_targets t ON j.job_id=t.job_id
                WHERE j.property_id=? AND t.group_id=? AND t.status IN ('posted', 'uncertain')
                LIMIT 1
                """,
                (property_id, group_id),
            ).fetchone()
        return row is not None

    def duplicate_property_posted_ever(self, property_id: str, group_id: str) -> bool:
        return self.duplicate_property_completed_or_uncertain_ever(property_id, group_id)

    def record_group_result(self, group_id: str, *, success: bool, threshold: int) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT consecutive_failures FROM group_circuit WHERE group_id=?", (group_id,)).fetchone()
            failures = 0 if success else ((row["consecutive_failures"] if row else 0) + 1)
            suggest = int(failures >= threshold)
            conn.execute(
                """
                INSERT INTO group_circuit(group_id, consecutive_failures, disabled_suggested, updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(group_id) DO UPDATE SET consecutive_failures=excluded.consecutive_failures,
                    disabled_suggested=excluded.disabled_suggested, updated_at=excluded.updated_at
                """,
                (group_id, failures, suggest, now_iso()),
            )
        return bool(suggest)

    def reset_stale_posting_jobs(self) -> int:
        with self.connect() as conn:
            rows = conn.execute("SELECT job_id FROM jobs WHERE status='posting'").fetchall()
            for row in rows:
                conn.execute("UPDATE jobs SET status='approved', updated_at=? WHERE job_id=?", (now_iso(), row["job_id"]))
        return len(rows)

    def posted_property_ids(self) -> set[str]:
        """property_ids that should not be posted again."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT j.property_id
                FROM jobs j
                JOIN job_targets t ON t.job_id = j.job_id
                WHERE t.status IN ('posted', 'uncertain')
                """
            ).fetchall()
        return {row["property_id"] for row in rows}

    def posted_property_ids_for_group(self, group_id: str) -> set[str]:
        """property_ids already posted to THIS group (so it never repeats one).

        Per-group history: each group independently excludes only the properties
        it has itself posted, so different groups can post different properties.
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT j.property_id
                FROM jobs j
                JOIN job_targets t ON t.job_id = j.job_id
                WHERE t.group_id = ? AND t.status IN ('posted', 'uncertain')
                """,
                (group_id,),
            ).fetchall()
        return {row["property_id"] for row in rows}
