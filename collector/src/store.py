"""Persist collected properties into a SQLite database + JSON mirror (役割3).

Idempotent: each property gets a content signature (source group + a hash of the
post text); re-collecting the same post UPDATES the row instead of duplicating it.
No dependency on the other roles.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS collected_properties (
    signature      TEXT PRIMARY KEY,
    group_id       TEXT,
    group_name     TEXT,
    permalink      TEXT,
    author         TEXT,
    posted_at      TEXT,
    price_yen      INTEGER,
    yield_pct      REAL,
    prefecture     TEXT,
    location       TEXT,
    property_type  TEXT,
    station_access TEXT,
    year_built     TEXT,
    areas_json     TEXT,
    raw_text       TEXT,
    collected_at   TEXT
);
"""


def signature(group_id: str, raw_text: str) -> str:
    digest = hashlib.sha256(raw_text.strip().encode("utf-8")).hexdigest()[:20]
    return f"{group_id}:{digest}"


class PropertyStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert(self, record: dict[str, Any], *, collected_at: str) -> str:
        """Insert or update one collected property. Returns 'created' or 'updated'."""
        sig = signature(str(record.get("group_id", "")), str(record.get("raw_text", "")))
        row = {
            "signature": sig,
            "group_id": str(record.get("group_id", "")),
            "group_name": str(record.get("group_name", "")),
            "permalink": record.get("permalink") or "",
            "author": str(record.get("author", "")),
            "posted_at": str(record.get("posted_at", "")),
            "price_yen": record.get("price_yen"),
            "yield_pct": record.get("yield_pct"),
            "prefecture": record.get("prefecture"),
            "location": record.get("location"),
            "property_type": record.get("property_type"),
            "station_access": record.get("station_access"),
            "year_built": record.get("year_built"),
            "areas_json": json.dumps(record.get("areas", {}), ensure_ascii=False),
            "raw_text": str(record.get("raw_text", ""))[:4000],
            "collected_at": collected_at,
        }
        with self._conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM collected_properties WHERE signature = ?", (sig,)
            ).fetchone()
            cols = ", ".join(row.keys())
            placeholders = ", ".join(f":{k}" for k in row)
            conn.execute(
                f"INSERT OR REPLACE INTO collected_properties ({cols}) VALUES ({placeholders})", row
            )
        return "updated" if exists else "created"

    def count(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM collected_properties").fetchone()[0])

    def export_json(self, path: str | Path) -> int:
        with self._conn() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM collected_properties ORDER BY collected_at DESC")]
        Path(path).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(rows)
