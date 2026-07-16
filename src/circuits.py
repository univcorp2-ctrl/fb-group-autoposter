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
        if kind in GROUP_AMBIGUITY_FAILURES:
            return self._record_group_ambiguity(
                kind,
                group_id=group_id,
                attempt_id=attempt_id,
                occurred_at=at,
                environment=environment,
                metadata=metadata,
            )
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO circuit_events(kind, group_id, environment, occurred_at, metadata_json)
                   VALUES(?,?,?,?,?)""",
                (kind.value, group_id, environment, at.isoformat(), json.dumps(metadata or {}, sort_keys=True)),
            )

        if kind in GLOBAL_OPERATOR_FAILURES:
            return self._open("global", "*", kind.value, at, clearance_mode="operator")
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
                    expires_at=at + timedelta(hours=24), clearance_mode="minimum_preflight",
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

    def _record_group_ambiguity(
        self,
        kind: FailureKind,
        *,
        group_id: str | None,
        attempt_id: str | None,
        occurred_at: datetime,
        environment: str,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not group_id:
            raise ValueError("group_id is required for group failure")
        if not attempt_id:
            raise ValueError("attempt_id is required for ambiguity or verification failure")
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            attempt = conn.execute(
                "SELECT * FROM submission_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if attempt is None or attempt["group_id"] != group_id or attempt["click_started_at"] is None:
                raise ValueError("attempt does not match affected group and clicked/submitting state")
            allowed_attempt_states = (
                {"submitting"}
                if kind == FailureKind.POST_SUBMIT_AMBIGUITY
                else {"posted", "reconcile_only"}
            )
            if attempt["state"] not in allowed_attempt_states:
                expected = "submitting" if kind == FailureKind.POST_SUBMIT_AMBIGUITY else "posted/reconcile_only"
                raise ValueError(f"{kind.value} requires a {expected} attempt")
            target = conn.execute(
                "SELECT status FROM job_targets WHERE job_id=? AND group_id=?",
                (attempt["job_id"], group_id),
            ).fetchone()
            allowed_target_states = (
                {"submitting"}
                if kind == FailureKind.POST_SUBMIT_AMBIGUITY
                else {"posted", "uncertain"}
            )
            if target is None or target["status"] not in allowed_target_states:
                raise ValueError("attempt and affected target state do not match")
            conn.execute(
                """INSERT INTO circuit_events(kind, group_id, environment, occurred_at, metadata_json)
                   VALUES(?,?,?,?,?)""",
                (
                    kind.value, group_id, environment, occurred_at.isoformat(),
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )
            conn.execute(
                """UPDATE submission_attempts SET state='reconcile_only', last_error=?
                   WHERE attempt_id=? AND click_started_at IS NOT NULL""",
                (kind.value, attempt_id),
            )
            conn.execute(
                """UPDATE job_targets SET status='uncertain', reconcile_only=1,
                   posted_at=COALESCE(posted_at, ?)
                   WHERE job_id=? AND group_id=?""",
                (attempt["click_started_at"], attempt["job_id"], group_id),
            )
            return self._open_in_connection(
                conn,
                "group",
                group_id,
                kind.value,
                occurred_at,
                expires_at=occurred_at + timedelta(hours=24),
                clearance_mode="expiry",
            )

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
            return self._open_in_connection(
                conn, scope, subject, reason, opened_at,
                expires_at=expires_at, clearance_mode=clearance_mode,
            )

    @staticmethod
    def _open_in_connection(
        conn: Any,
        scope: str,
        subject: str,
        reason: str,
        opened_at: datetime,
        *,
        expires_at: datetime | None,
        clearance_mode: str,
    ) -> dict[str, Any]:
        current = conn.execute(
                """SELECT * FROM safety_circuits WHERE scope=? AND subject=? AND cleared_at IS NULL
                   AND (expires_at IS NULL OR expires_at>? OR clearance_mode!='expiry')
                   ORDER BY opened_at DESC LIMIT 1""",
                (scope, subject, opened_at.isoformat()),
            ).fetchone()
        if current:
            existing_mode = current["clearance_mode"]
            merged_mode = CircuitManager._merge_clearance_modes(
                existing_mode,
                clearance_mode,
                existing_has_expiry=current["expires_at"] is not None,
                incoming_has_expiry=expires_at is not None,
            )
            expiry_values = [
                value
                for value in (
                    current["expires_at"],
                    expires_at.isoformat() if expires_at else None,
                )
                if value is not None
            ]
            merged_expiry = (
                max(expiry_values, key=datetime.fromisoformat) if expiry_values else None
            )
            reasons = list(json.loads(current["reasons_json"] or "[]"))
            if current["reason"] not in reasons:
                reasons.append(current["reason"])
            if reason not in reasons:
                reasons.append(reason)
            ranks = {
                "expiry": 1,
                "preflight": 2,
                "operator": 3,
                "minimum_preflight": 4,
                "operator_preflight": 5,
            }
            primary_reason = (
                reason
                if ranks.get(clearance_mode, 0) > ranks.get(existing_mode, 0)
                else current["reason"]
            )
            conn.execute(
                """UPDATE safety_circuits
                   SET reason=?, reasons_json=?, expires_at=?, clearance_mode=?
                   WHERE circuit_id=?""",
                (
                    primary_reason,
                    json.dumps(reasons, sort_keys=True),
                    merged_expiry,
                    merged_mode,
                    current["circuit_id"],
                ),
            )
            row = conn.execute(
                "SELECT * FROM safety_circuits WHERE circuit_id=?",
                (current["circuit_id"],),
            ).fetchone()
            return dict(row)
        circuit_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO safety_circuits(
               circuit_id, scope, subject, reason, reasons_json,
               opened_at, expires_at, clearance_mode
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                circuit_id, scope, subject, reason, json.dumps([reason]), opened_at.isoformat(),
                expires_at.isoformat() if expires_at else None, clearance_mode,
            ),
        )
        row = conn.execute(
            "SELECT * FROM safety_circuits WHERE circuit_id=?", (circuit_id,)
        ).fetchone()
        return dict(row)

    @staticmethod
    def _merge_clearance_modes(
        existing: str,
        incoming: str,
        *,
        existing_has_expiry: bool,
        incoming_has_expiry: bool,
    ) -> str:
        modes = {existing, incoming}
        requires_operator = bool(modes & {"operator", "operator_preflight"})
        requires_preflight = bool(
            modes & {"preflight", "minimum_preflight", "operator_preflight"}
        )
        requires_minimum = (
            existing_has_expiry or incoming_has_expiry
        ) and bool(modes & {"expiry", "minimum_preflight", "operator_preflight"})
        if requires_operator and (requires_preflight or requires_minimum):
            return "operator_preflight"
        if requires_operator:
            return "operator"
        if requires_preflight and requires_minimum:
            return "minimum_preflight"
        if requires_preflight:
            return "preflight"
        return "expiry"

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
            if row is None or row["clearance_mode"] != "operator":
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
        self,
        environment: str,
        *,
        actor: str,
        group_id: str | None = None,
        at: datetime | str | None = None,
    ) -> int:
        if actor not in {"operator", "preflight"}:
            return 0
        instant = _timestamp(at)
        timestamp = instant.isoformat()
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM safety_circuits WHERE cleared_at IS NULL
                   AND ((scope='environment' AND subject=?) OR scope='global'
                     OR (scope='group' AND subject=?))
                   AND clearance_mode IN (
                     'preflight', 'minimum_preflight', 'operator_preflight'
                   )""",
                (environment, group_id),
            ).fetchall()
            eligible = [
                row for row in rows
                if (row["expires_at"] is None or instant >= datetime.fromisoformat(row["expires_at"]))
                and (
                    row["clearance_mode"] in {"preflight", "minimum_preflight"}
                    or row["operator_reviewed_at"] is not None
                )
            ]
            for row in eligible:
                conn.execute(
                    """UPDATE safety_circuits SET cleared_at=?, cleared_by=?, clearance_reason='successful_preflight'
                       WHERE circuit_id=?""",
                    (timestamp, actor, row["circuit_id"]),
                )
        return len(eligible)
