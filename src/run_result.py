from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterable, Mapping
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
        return redacted
    return value


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
        current = self.read_latest()
        if current is not None and current.get("run_id") == run_id:
            if current.get("terminal"):
                raise RuntimeError(f"run is already terminal: {run_id}")
            return current

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
        **fields: Any,
    ) -> dict[str, Any]:
        if outcome not in OUTCOME_EXIT_CODES:
            raise ValueError(f"unknown outcome: {outcome}")

        current = self.read_latest()
        run_id = str(run["run_id"])
        if current is None or current.get("run_id") != run_id:
            raise RuntimeError(f"latest result does not match run: {run_id}")
        if current.get("terminal"):
            raise RuntimeError(f"run is already terminal: {run_id}")

        timestamp = _iso(self.clock())
        result = {
            **dict(current),
            "finished_at": timestamp,
            "outcome": outcome,
            "reason": reason,
            "exit_code": OUTCOME_EXIT_CODES[outcome],
            "terminal": True,
            "result_at": timestamp,
            **fields,
        }
        result = _redact(result, self.secrets)
        history_path = self.root / "history" / timestamp[:10] / f"{run_id}.json"
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
        current = self.read_latest()
        if current is None or current.get("run_id") != run_id:
            return None
        if current.get("terminal"):
            return current
        return self.finish(
            current,
            outcome="internal_error",
            reason=reason,
            finalized_by="launcher",
            pre_sqlite_failure=pre_sqlite_failure,
        )

    def read_latest(self) -> dict[str, Any] | None:
        try:
            return json.loads(self.latest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

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
    if not result or not result.get("terminal") or not result.get("finished_at"):
        return False
    try:
        finished_at = datetime.fromisoformat(str(result["finished_at"]))
    except ValueError:
        return False
    if finished_at.tzinfo is None:
        return False

    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    age_hours = (current_time.astimezone(UTC) - finished_at.astimezone(UTC)).total_seconds() / 3600
    if not 0 <= age_hours < max_age_hours:
        return False

    if result.get("run_id") == sqlite_run_id:
        return True
    return bool(
        sqlite_run_id is None
        and result.get("finalized_by") == "launcher"
        and result.get("pre_sqlite_failure") is True
    )
