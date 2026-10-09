"""Read-only Facebook delivery evidence audit (no posting or scheduling)."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

db = Path(os.getenv("LOCALAPPDATA", "")) / "FBGroupAutoposter" / "data" / "jobs.db"
if not db.is_file():
    raise SystemExit("Runtime SQLite DB not found")
uri = db.resolve().as_uri() + "?mode=ro"
with sqlite3.connect(uri, uri=True) as con:
    tables = [row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    report = []
    for table in tables:
        cols = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
        if not any(word in table.lower() for word in ("post", "deliver", "job", "attempt")):
            continue
        count = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        entry = {"table": table, "rows": count, "columns": cols}
        status_col = next((c for c in cols if c.lower() in ("status","post_status","delivery_status")), None)
        if status_col:
            try:
                entry["status_counts"] = [
                    {"status": str(status)[:90], "count": total}
                    for status, total in con.execute(
                        f'SELECT "{status_col}",COUNT(*) FROM "{table}" GROUP BY "{status_col}"')
                ]
            except sqlite3.Error as exc:
                entry["status_error"] = type(exc).__name__
        report.append(entry)
    recent = con.execute("SELECT posted_at, permalink FROM job_targets WHERE status = ? ORDER BY posted_at DESC LIMIT 5", ("posted",)).fetchall()
    new_post_count = con.execute("SELECT COUNT(*) FROM job_targets WHERE status = ? AND posted_at >= ?", ("posted", "2026-10-04")).fetchone()[0]
    attempt_states = con.execute("SELECT state, COUNT(*) FROM submission_attempts GROUP BY state").fetchall()
    print(json.dumps({"db_found": True, "table_count": len(tables),
                      "delivery_tables": report, "new_posts_since_oct_4": new_post_count,
                      "last_five_posted": [{"at": date, "has_permalink": bool(url)} for date, url in recent],
                      "attempt_states": dict(attempt_states)}, ensure_ascii=False, indent=2))