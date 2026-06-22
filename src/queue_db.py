from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

JOB_STATUSES = {"pending", "approved", "rejected", "posting", "done", "partial_failed", "failed"}
TARGET_STATUSES = {"pending", "posted", "failed", "skipped", "uncertain"}


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
                """
            )

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
                conn.execute(
                    "INSERT OR IGNORE INTO job_targets(job_id, group_id, body, status) VALUES(?,?,?,?)",
                    (job_id, variant["group_id"], variant["body"], "pending"),
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
        posted_at = now_iso() if status in ("posted", "uncertain") else None
        with self.connect() as conn:
            if increment_attempts:
                conn.execute(
                    """
                    UPDATE job_targets
                    SET status=?, attempts=attempts + 1, last_error=?, posted_at=COALESCE(?, posted_at),
                        screenshot=COALESCE(?, screenshot), permalink=COALESCE(?, permalink)
                    WHERE job_id=? AND group_id=?
                    """,
                    (status, error, posted_at, screenshot, permalink, job_id, group_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE job_targets
                    SET status=?, last_error=?, posted_at=COALESCE(?, posted_at),
                        screenshot=COALESCE(?, screenshot), permalink=COALESCE(?, permalink)
                    WHERE job_id=? AND group_id=?
                    """,
                    (status, error, posted_at, screenshot, permalink, job_id, group_id),
                )

    def approve_job(self, job_id: str) -> None:
        self.update_job_status(job_id, "approved")

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
