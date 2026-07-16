from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from src.queue_db import QueueDB


class FailureKind(StrEnum):
    CHECKPOINT = "checkpoint"
    CAPTCHA = "captcha"
    TWO_FACTOR = "two_factor"
    ACCOUNT_WARNING = "account_warning"
    RESTRICTION = "restriction"
    POSTING_BLOCK = "posting_block"
    UNCLASSIFIED_LOGIN = "unclassified_login"
    SESSION_EXPIRED = "session_expired"
    PUBLIC_VERIFICATION_FAILURE = "public_verification_failure"
    POST_SUBMIT_AMBIGUITY = "post_submit_ambiguity"
    SELECTOR_FAILURE = "selector_failure"
    COMPOSER_FAILURE = "composer_failure"
    CONCURRENT_RUNNER = "concurrent_runner"
    PROFILE_LOCKED = "profile_locked"
    PROFILE_CORRUPT = "profile_corrupt"
    SOURCE_MISSING = "source_missing"
    SOURCE_STALE = "source_stale"
    SOURCE_HASH_MISMATCH = "source_hash_mismatch"
    SOURCE_IDENTITY_MISMATCH = "source_identity_mismatch"
    BROKER_UNKNOWN = "broker_unknown"
    BROWSER_MISSING = "browser_missing"
    RUNTIME_MISMATCH = "runtime_mismatch"
    OTHER_PRESUBMIT_RUNTIME = "other_presubmit_runtime"


GLOBAL_OPERATOR_FAILURES = {
    FailureKind.CHECKPOINT,
    FailureKind.CAPTCHA,
    FailureKind.TWO_FACTOR,
    FailureKind.ACCOUNT_WARNING,
    FailureKind.RESTRICTION,
    FailureKind.POSTING_BLOCK,
    FailureKind.UNCLASSIFIED_LOGIN,
}
ENV_PREFLIGHT_FAILURES = {
    FailureKind.SESSION_EXPIRED,
    FailureKind.CONCURRENT_RUNNER,
    FailureKind.PROFILE_LOCKED,
    FailureKind.SOURCE_MISSING,
    FailureKind.SOURCE_STALE,
    FailureKind.SOURCE_HASH_MISMATCH,
    FailureKind.SOURCE_IDENTITY_MISMATCH,
    FailureKind.BROKER_UNKNOWN,
    FailureKind.BROWSER_MISSING,
    FailureKind.RUNTIME_MISMATCH,
}
GROUP_AMBIGUITY_FAILURES = {
    FailureKind.PUBLIC_VERIFICATION_FAILURE,
    FailureKind.POST_SUBMIT_AMBIGUITY,
}
SELECTOR_FAILURES = {FailureKind.SELECTOR_FAILURE, FailureKind.COMPOSER_FAILURE}


def _timestamp(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


class CircuitManager:
    """Durable safety-policy evaluator with no browser or network dependencies."""

    def __init__(self, db: QueueDB):
        self.db = db

    def record_failure(
        self,
        kind: FailureKind | str,
        *,
        group_id: str | None = None,
        environment: str = "default",
        attempt_id: str | None = None,
        occurred_at: datetime | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        kind = FailureKind(kind)
        at = _timestamp(occurred_at)
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO circuit_events(kind, group_id, environment, occurred_at, metadata_json)
                   VALUES(?,?,?,?,?)""",
                (kind.value, group_id, environment, at.isoformat(), json.dumps(metadata or {}, sort_keys=True)),
            )

        if kind in GLOBAL_OPERATOR_FAILURES:
            return self._open("global", "*", kind.value, at, clearance_mode="operator")
        if kind in GROUP_AMBIGUITY_FAILURES:
            if not group_id:
                raise ValueError("group_id is required for group failure")
            if attempt_id:
                self.db.mark_attempt_reconcile_only(attempt_id, reason=kind.value)
            return self._open(
                "group", group_id, kind.value, at,
                expires_at=at + timedelta(hours=24), clearance_mode="expiry",
            )
        if kind in SELECTOR_FAILURES:
            if not group_id:
                raise ValueError("group_id is required for selector/composer failure")
            since = (at - timedelta(hours=24)).isoformat()
            placeholders = ",".join("?" for _ in SELECTOR_FAILURES)
            values = [item.value for item in SELECTOR_FAILURES]
            with self.db.connect() as conn:
                distinct = conn.execute(
                    f"""SELECT COUNT(DISTINCT group_id) AS count FROM circuit_events
                        WHERE kind IN ({placeholders}) AND occurred_at>=? AND occurred_at<=?""",
                    (*values, since, at.isoformat()),
                ).fetchone()["count"]
                same_group = conn.execute(
                    f"""SELECT COUNT(*) AS count FROM circuit_events
                        WHERE kind IN ({placeholders}) AND group_id=?
                          AND occurred_at>=? AND occurred_at<=?""",
                    (*values, group_id, since, at.isoformat()),
                ).fetchone()["count"]
            if distinct >= 3:
                return self._open(
                    "global", "*", "failures_three_distinct_groups", at,
                    expires_at=at + timedelta(hours=24), clearance_mode="operator_preflight",
                )
            if same_group >= 2:
                return self._open(
                    "group", group_id, "selector_composer_threshold", at,
                    expires_at=at + timedelta(hours=24), clearance_mode="expiry",
                )
            return None
        if kind == FailureKind.PROFILE_CORRUPT:
            return self._open(
                "environment", environment, kind.value, at, clearance_mode="operator_preflight"
            )
        if kind in ENV_PREFLIGHT_FAILURES:
            return self._open("environment", environment, kind.value, at, clearance_mode="preflight")
        if kind == FailureKind.OTHER_PRESUBMIT_RUNTIME:
            since = (at - timedelta(hours=6)).isoformat()
            with self.db.connect() as conn:
                count = conn.execute(
                    """SELECT COUNT(*) AS count FROM circuit_events
                       WHERE kind=? AND environment=? AND occurred_at>=? AND occurred_at<=?""",
                    (kind.value, environment, since, at.isoformat()),
                ).fetchone()["count"]
            if count >= 3:
                return self._open("environment", environment, kind.value, at, clearance_mode="preflight")
        return None

    def _open(
        self,
        scope: str,
        subject: str,
        reason: str,
        opened_at: datetime,
        *,
        expires_at: datetime | None = None,
        clearance_mode: str,
    ) -> dict[str, Any]:
        with self.db.connect() as conn:
            current = conn.execute(
                """SELECT * FROM safety_circuits WHERE scope=? AND subject=? AND cleared_at IS NULL
                   AND (expires_at IS NULL OR expires_at>? OR clearance_mode!='expiry')
                   ORDER BY opened_at DESC LIMIT 1""",
                (scope, subject, opened_at.isoformat()),
            ).fetchone()
            if current:
                return dict(current)
            circuit_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO safety_circuits(
                   circuit_id, scope, subject, reason, opened_at, expires_at, clearance_mode
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    circuit_id, scope, subject, reason, opened_at.isoformat(),
                    expires_at.isoformat() if expires_at else None, clearance_mode,
                ),
            )
            row = conn.execute("SELECT * FROM safety_circuits WHERE circuit_id=?", (circuit_id,)).fetchone()
        return dict(row)

    def blocking_circuit(
        self,
        *,
        group_id: str | None = None,
        environment: str = "default",
        at: datetime | str | None = None,
    ) -> dict[str, Any] | None:
        timestamp = _timestamp(at).isoformat()
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT *, CASE scope WHEN 'global' THEN 0 WHEN 'environment' THEN 1 ELSE 2 END AS precedence
                   FROM safety_circuits
                   WHERE cleared_at IS NULL
                     AND (expires_at IS NULL OR expires_at>? OR clearance_mode!='expiry')
                     AND ((scope='global' AND subject='*')
                       OR (scope='environment' AND subject=?)
                       OR (scope='group' AND subject=?))
                   ORDER BY precedence, opened_at DESC LIMIT 1""",
                (timestamp, environment, group_id),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result.pop("precedence", None)
        return result

    def active_circuits(self, *, at: datetime | str | None = None) -> list[dict[str, Any]]:
        timestamp = _timestamp(at).isoformat()
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM safety_circuits WHERE cleared_at IS NULL
                   AND (expires_at IS NULL OR expires_at>? OR clearance_mode!='expiry')
                   ORDER BY opened_at""",
                (timestamp,),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear(
        self,
        *,
        scope: str,
        subject: str,
        actor: str,
        reason: str = "operator_clear",
        at: datetime | str | None = None,
    ) -> bool:
        if actor != "operator":
            return False
        timestamp = _timestamp(at).isoformat()
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT * FROM safety_circuits WHERE scope=? AND subject=? AND cleared_at IS NULL
                   ORDER BY opened_at DESC LIMIT 1""",
                (scope, subject),
            ).fetchone()
            if row is None or row["clearance_mode"] not in {"operator", "expiry"}:
                return False
            conn.execute(
                """UPDATE safety_circuits SET cleared_at=?, cleared_by=?, clearance_reason=?
                   WHERE circuit_id=?""",
                (timestamp, actor, reason, row["circuit_id"]),
            )
        return True

    def operator_review(
        self, *, scope: str, subject: str, actor: str, at: datetime | str | None = None
    ) -> bool:
        if actor != "operator":
            return False
        with self.db.connect() as conn:
            cursor = conn.execute(
                """UPDATE safety_circuits SET operator_reviewed_at=?, operator_reviewed_by=?
                   WHERE scope=? AND subject=? AND cleared_at IS NULL
                     AND clearance_mode='operator_preflight'""",
                (_timestamp(at).isoformat(), actor, scope, subject),
            )
        return cursor.rowcount > 0

    def record_successful_preflight(
        self, environment: str, *, actor: str, at: datetime | str | None = None
    ) -> int:
        if actor == "scheduler":
            return 0
        timestamp = _timestamp(at).isoformat()
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM safety_circuits WHERE cleared_at IS NULL
                   AND ((scope='environment' AND subject=?) OR scope='global')
                   AND clearance_mode IN ('preflight', 'operator_preflight')""",
                (environment,),
            ).fetchall()
            eligible = [
                row for row in rows
                if row["clearance_mode"] == "preflight" or row["operator_reviewed_at"] is not None
            ]
            for row in eligible:
                conn.execute(
                    """UPDATE safety_circuits SET cleared_at=?, cleared_by=?, clearance_reason='successful_preflight'
                       WHERE circuit_id=?""",
                    (timestamp, actor, row["circuit_id"]),
                )
        return len(eligible)
