from __future__ import annotations

import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "fb-autoposter-run/v1"
OUTCOME_EXIT_CODES = {
    "success": 0,
    "no_action": 0,
    "preflight_blocked": 20,
    "risk_stopped": 30,
    "submission_ambiguous": 40,
    "posted_delivery_pending": 50,
    "internal_error": 60,
}
REASON_CODES = frozenset(
    {
        "ai_generation_blocked",
        "already_posted_today",
        "approval_invalidated",
        "approval_pending",
        "browser_missing",
        "facebook_challenge",
        "group_unconfirmed",
        "launcher_failed",
        "overlap_locked",
        "posting_blocked",
        "profile_locked",
        "provider_auth_failed",
        "provider_output_invalid",
        "provider_policy_rejected",
        "provider_timeout",
        "provider_unavailable",
        "run_id_reused",
        "session_expired",
        "source_missing",
        "source_stale",
        "submission_uncertain",
        "success",
        "telegram_failed",
        "telegram_disabled",
        "telegram_polled",
        "telegram_poll_failed",
        "telegram_webhook_owns_callbacks",
        "telegram_webhook_state_unknown",
        "ua_mismatch",
        "verification_failed",
        "web_sync_failed",
    }
)
RESERVED_RESULT_FIELDS = frozenset(
    {
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
)
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "body",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_COMMAND_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
)
_CREDENTIAL_PATTERNS = (
    re.compile(
        r"(?i)\b(authorization|token|password|secret|api[_-]?key|cookie)\b"
        r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+:/=-]{12,}"),
    re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}\b"),
)
_REQUIRED_TERMINAL_FIELDS = frozenset(
    {
        "schema",
        "run_id",
        "command",
        "started_at",
        "finished_at",
        "outcome",
        "reason",
        "exit_code",
        "terminal",
        "result_at",
        "finalized_by",
        "pre_sqlite_failure",
    }
)


class RunOverlapError(RuntimeError):
    reason = "overlap_locked"

    def __init__(self, active_run_id: str) -> None:
        self.active_run_id = active_run_id
        super().__init__(f"active operational run prevents overlap: {active_run_id}")


class RunIdReuseError(RuntimeError):
    reason = "run_id_reused"


def validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("invalid run_id: use 1-128 filename-safe ASCII characters")
    if run_id.upper() in _WINDOWS_RESERVED_NAMES:
        raise ValueError("invalid run_id: Windows reserved filename")
    return run_id


def validate_command(command: str) -> str:
    if not isinstance(command, str) or not _COMMAND_PATTERN.fullmatch(command):
        raise ValueError("invalid command")
    return command


def validate_reason_code(reason: str) -> str:
    if reason not in REASON_CODES:
        raise ValueError(f"invalid reason code: {reason!r}")
    return reason


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"invalid {field}")
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc
    if timestamp.tzinfo is None:
        raise ValueError(f"invalid {field}: timezone required")
    return timestamp.astimezone(UTC)


def validate_timestamp(value: str, field: str) -> str:
    _parse_timestamp(value, field)
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(timestamp: datetime) -> str:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC).isoformat()


def _redact(value: Any, secrets: tuple[str, ...], *, key: str = "") -> Any:
    if any(part in key.lower() for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(item_key): _redact(item, secrets, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, tuple):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            redacted = redacted.replace(secret, "[REDACTED]")
        for pattern in _CREDENTIAL_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    return value


def sanitize_terminal_result(result: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise ValueError("terminal result must be a mapping")
    missing = _REQUIRED_TERMINAL_FIELDS.difference(result)
    if missing:
        raise ValueError(f"terminal result missing fields: {', '.join(sorted(missing))}")
    if result.get("schema") != SCHEMA or result.get("terminal") is not True:
        raise ValueError("invalid terminal result schema or state")

    validate_run_id(result.get("run_id"))
    validate_command(result.get("command"))
    validate_reason_code(result.get("reason"))
    outcome = result.get("outcome")
    if outcome not in OUTCOME_EXIT_CODES:
        raise ValueError(f"unknown outcome: {outcome}")
    if type(result.get("exit_code")) is not int or result["exit_code"] != OUTCOME_EXIT_CODES[outcome]:
        raise ValueError("exit_code does not match outcome")
    if result.get("finalized_by") not in {"python", "launcher"}:
        raise ValueError("invalid finalizer")
    if type(result.get("pre_sqlite_failure")) is not bool:
        raise ValueError("pre_sqlite_failure must be boolean")
    if result["pre_sqlite_failure"] and not (
        result["finalized_by"] == "launcher" and outcome == "internal_error"
    ):
        raise ValueError("pre-SQLite failure must be launcher-owned internal_error")

    started_at = _parse_timestamp(result.get("started_at"), "started_at")
    finished_at = _parse_timestamp(result.get("finished_at"), "finished_at")
    result_at = _parse_timestamp(result.get("result_at"), "result_at")
    if finished_at < started_at or result_at != finished_at:
        raise ValueError("invalid terminal timestamp ordering")

    sanitized = _redact(dict(result), ())
    try:
        json.dumps(sanitized, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("terminal result is not JSON serializable") from exc
    return sanitized


class RunResultStore:
    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime] = _utc_now,
        secrets: Iterable[str] = (),
    ) -> None:
        self.root = Path(root)
        self.clock = clock
        self.secrets = tuple(secret for secret in secrets if secret)

    @property
    def latest_path(self) -> Path:
        return self.root / "latest.json"

    def start(self, command: str, *, run_id: str) -> dict[str, Any]:
        validate_run_id(run_id)
        validate_command(command)
        with self._exclusive_lock():
            current = self.read_latest()
            if current is not None and not current.get("terminal"):
                active_run_id = str(current.get("run_id"))
                if active_run_id != run_id:
                    raise RunOverlapError(active_run_id)
                if current.get("command") != command:
                    raise RunIdReuseError(f"run_id reused for different command: {run_id}")
                self._claim_run_id(run_id, command, allow_existing=True)
                return current
            if current is not None and current.get("run_id") == run_id:
                raise RunIdReuseError(f"run is already terminal; run_id cannot be reused: {run_id}")
            if self._read_existing_history(run_id) is not None:
                raise RunIdReuseError(f"run_id history already exists: {run_id}")
            self._claim_run_id(run_id, command)

            timestamp = _iso(self.clock())
            result = {
                "schema": SCHEMA,
                "run_id": run_id,
                "command": command,
                "started_at": timestamp,
                "finished_at": None,
                "outcome": "running",
                "reason": "started",
                "exit_code": None,
                "terminal": False,
                "result_at": timestamp,
            }
            self._write_atomic(self.latest_path, result)
            return result

    def finish(
        self,
        run: Mapping[str, Any],
        *,
        outcome: str,
        reason: str,
        extra_fields: Mapping[str, Any] | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        if outcome not in OUTCOME_EXIT_CODES:
            raise ValueError(f"unknown outcome: {outcome}")
        validate_reason_code(reason)
        supplied_fields = {**(extra_fields or {}), **fields}
        reserved = RESERVED_RESULT_FIELDS.intersection(supplied_fields)
        if reserved:
            names = ", ".join(sorted(reserved))
            raise ValueError(f"reserved result fields cannot be supplied: {names}")

        with self._exclusive_lock():
            return self._finish_locked(
                run,
                outcome=outcome,
                reason=reason,
                finalized_by="python",
                pre_sqlite_failure=False,
                fields=supplied_fields,
            )

    def _finish_locked(
        self,
        run: Mapping[str, Any],
        *,
        outcome: str,
        reason: str,
        finalized_by: str,
        pre_sqlite_failure: bool,
        fields: Mapping[str, Any],
    ) -> dict[str, Any]:
        current = self.read_latest()
        run_id = str(run["run_id"])
        if current is None or current.get("run_id") != run_id:
            raise RuntimeError(f"latest result does not match run: {run_id}")
        if current.get("terminal"):
            raise RuntimeError(f"run is already terminal: {run_id}")
        existing_history = self._read_existing_history(run_id)
        if existing_history is not None:
            self._write_atomic(self.latest_path, existing_history)
            return existing_history

        timestamp = _iso(self.clock())
        result = {
            **dict(current),
            "finished_at": timestamp,
            "outcome": outcome,
            "reason": reason,
            "exit_code": OUTCOME_EXIT_CODES[outcome],
            "terminal": True,
            "result_at": timestamp,
            "finalized_by": finalized_by,
            "pre_sqlite_failure": pre_sqlite_failure,
            **fields,
        }
        result = sanitize_terminal_result(_redact(result, self.secrets))
        history_path = self._history_path(run_id, timestamp[:10])
        if history_path.exists():
            raise RunIdReuseError(f"run_id history already exists: {run_id}")
        self._write_atomic(history_path, result)
        self._write_atomic(self.latest_path, result)
        return result

    def finalize_from_launcher(
        self,
        run_id: str,
        *,
        reason: str,
        pre_sqlite_failure: bool = False,
    ) -> dict[str, Any] | None:
        validate_run_id(run_id)
        validate_reason_code(reason)
        with self._exclusive_lock():
            current = self.read_latest()
            if current is None or current.get("run_id") != run_id:
                return None
            if current.get("terminal"):
                return sanitize_terminal_result(current)
            return self._finish_locked(
                current,
                outcome="internal_error",
                reason=reason,
                finalized_by="launcher",
                pre_sqlite_failure=pre_sqlite_failure,
                fields={},
            )

    def _claim_run_id(self, run_id: str, command: str, *, allow_existing: bool = False) -> None:
        root = self.root.resolve()
        claims_root = (root / ".run-claims").resolve()
        try:
            claims_root.relative_to(root)
        except ValueError as exc:
            raise ValueError("run claim path escapes result root") from exc
        claims_root.mkdir(parents=True, exist_ok=True)
        claim_path = (claims_root / f"{run_id}.claim").resolve()
        try:
            claim_path.relative_to(claims_root)
        except ValueError as exc:
            raise ValueError("invalid run_id claim path") from exc
        try:
            descriptor = os.open(claim_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if allow_existing:
                claimed_command = claim_path.read_text(encoding="utf-8")
                if claimed_command == command:
                    return
            raise RunIdReuseError(f"run_id already claimed: {run_id}") from None
        with os.fdopen(descriptor, "w", encoding="utf-8") as claim_file:
            claim_file.write(command)
            claim_file.flush()
            os.fsync(claim_file.fileno())

    def _history_path(self, run_id: str, date: str) -> Path:
        validate_run_id(run_id)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError("invalid history date")
        root = self.root.resolve()
        history_root = (root / "history").resolve()
        try:
            history_root.relative_to(root)
        except ValueError as exc:
            raise ValueError("history path escapes result root") from exc
        candidate = (history_root / date / f"{run_id}.json").resolve()
        try:
            candidate.relative_to(history_root)
        except ValueError as exc:
            raise ValueError("history path escapes result root") from exc
        return candidate

    def _read_existing_history(self, run_id: str) -> dict[str, Any] | None:
        history_root = self.root / "history"
        if not history_root.exists():
            return None
        matches = []
        for date_dir in history_root.iterdir():
            if date_dir.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_dir.name):
                candidate = self._history_path(run_id, date_dir.name)
                if candidate.exists():
                    matches.append(candidate)
        if len(matches) > 1:
            raise RuntimeError(f"multiple history results found for run_id: {run_id}")
        if not matches:
            return None
        result = json.loads(matches[0].read_text(encoding="utf-8"))
        canonical = sanitize_terminal_result(result)
        if canonical["run_id"] != run_id:
            raise RuntimeError(f"history run_id mismatch: {run_id}")
        return canonical

    def read_latest(self) -> dict[str, Any] | None:
        try:
            return json.loads(self.latest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    @contextmanager
    def _exclusive_lock(self, *, timeout_seconds: float = 15) -> Any:
        """Serialize result transitions across processes.

        The sidecar is intentionally persistent. Removing a lock file can let one process
        lock an old file object while another locks a newly created path. The operating
        system releases the advisory byte-range lock when the handle closes or its owner
        exits, so an abrupt launcher/Python exit cannot leave a stale lock behind.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / ".run-result.lock"
        lock_file = lock_path.open("a+b", buffering=0)
        acquired = False
        deadline = time.monotonic() + timeout_seconds
        try:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                os.fsync(lock_file.fileno())
            while True:
                try:
                    lock_file.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"timed out waiting for result lock: {lock_path}") from exc
                    time.sleep(0.02)
            yield
        finally:
            if acquired:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

    @staticmethod
    def _write_atomic(path: Path, result: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
            ) as temp_file:
                temp_path = Path(temp_file.name)
                json.dump(result, temp_file, ensure_ascii=False, indent=2, sort_keys=True)
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, path)
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise


def is_fresh_terminal_result(
    result: Mapping[str, Any] | None,
    *,
    sqlite_run_id: str | None,
    now: datetime | None = None,
    max_age_hours: float = 30,
) -> bool:
    if not result:
        return False
    try:
        canonical = sanitize_terminal_result(result)
        finished_at = _parse_timestamp(canonical["finished_at"], "finished_at")
    except (TypeError, ValueError):
        return False

    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    age_hours = (current_time.astimezone(UTC) - finished_at.astimezone(UTC)).total_seconds() / 3600
    if not 0 <= age_hours < max_age_hours:
        return False

    if canonical["run_id"] == sqlite_run_id:
        return True
    return bool(
        sqlite_run_id is None
        and canonical["finalized_by"] == "launcher"
        and canonical["pre_sqlite_failure"] is True
    )
