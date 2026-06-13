"""Monitoring: report posting cadence and flag if posting has stalled.

Reads the queue DB and reports:
  - successful posts in the last 24h / 48h / 7d,
  - the most recent successful post (time + property),
  - recent failed/uncertain targets,
  - a health verdict (stalled if no successful post in the last STALL_HOURS).

Writes a machine-readable status to logs/monitor_status.json and prints a
human summary. Exit code is non-zero when posting is considered stalled, so a
scheduler can treat it as an alert condition.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings
from src.queue_db import QueueDB

STALL_HOURS = 26  # allow a little slack beyond a 24h cadence


def _count_since(conn, hours: int) -> int:
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) FROM job_targets WHERE status='posted' AND posted_at > ?", (cutoff,)
    ).fetchone()
    return int(row[0])


def build_status(settings: Settings) -> dict:
    db = QueueDB(settings.db_path)
    with db.connect() as conn:
        last = conn.execute(
            """
            SELECT t.posted_at, t.group_id, j.property_id
            FROM job_targets t JOIN jobs j ON j.job_id = t.job_id
            WHERE t.status='posted' AND t.posted_at IS NOT NULL
            ORDER BY t.posted_at DESC LIMIT 1
            """
        ).fetchone()
        recent_failures = conn.execute(
            """
            SELECT t.status, t.last_error, j.property_id, j.updated_at
            FROM job_targets t JOIN jobs j ON j.job_id = t.job_id
            WHERE t.status IN ('failed','uncertain')
              AND j.updated_at > ?
            ORDER BY j.updated_at DESC LIMIT 10
            """,
            ((datetime.now(UTC) - timedelta(hours=48)).isoformat(),),
        ).fetchall()
        posts_24h = _count_since(conn, 24)
        posts_48h = _count_since(conn, 48)
        posts_7d = _count_since(conn, 24 * 7)

    last_posted_at = last["posted_at"] if last else None
    hours_since = None
    if last_posted_at:
        delta = datetime.now(UTC) - datetime.fromisoformat(last_posted_at)
        hours_since = round(delta.total_seconds() / 3600, 1)

    stalled = hours_since is None or hours_since > STALL_HOURS
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "healthy": not stalled,
        "stalled": stalled,
        "posts_24h": posts_24h,
        "posts_48h": posts_48h,
        "posts_7d": posts_7d,
        "last_post": {
            "property_id": last["property_id"] if last else None,
            "group_id": last["group_id"] if last else None,
            "posted_at": last_posted_at,
            "hours_since": hours_since,
        },
        "recent_failures": [
            {
                "property_id": r["property_id"],
                "status": r["status"],
                "error": r["last_error"],
                "at": r["updated_at"],
            }
            for r in recent_failures
        ],
    }


def main() -> int:
    settings = Settings.load()
    status = build_status(settings)

    out = Path("logs") / "monitor_status.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    verdict = "✅ HEALTHY" if status["healthy"] else "🚨 STALLED"
    print(f"{verdict}  posts: 24h={status['posts_24h']} 48h={status['posts_48h']} 7d={status['posts_7d']}")
    lp = status["last_post"]
    if lp["posted_at"]:
        print(f"last post: {lp['property_id']} @ {lp['posted_at']} ({lp['hours_since']}h ago)")
    else:
        print("last post: (none recorded)")
    if status["recent_failures"]:
        print(f"recent failures/uncertain (48h): {len(status['recent_failures'])}")
        for f in status["recent_failures"][:5]:
            print(f"  - {f['property_id']} {f['status']}: {f['error']}")
    print(f"status written: {out}")
    return 0 if status["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
