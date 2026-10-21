"""Append operational Messenger metrics to a private SQLite history.

No customer records or messages. No sending, browser access, or publishing.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
from pathlib import Path

SCHEMA = "messenger-crm-private-aggregate/v1"
COUNT_KEYS = (
    "tracked_thread_count",
    "latest_scan_count",
    "latest_need_reply_count",
    "current_active_draft_count",
    "current_premium_approved_count",
    "confirmed_send_count",
    "uncertain_send_count",
)

def safe_record(source: dict) -> dict:
    if source.get("schema_version") != SCHEMA:
        raise ValueError("invalid schema")
    if source.get("source") != "live_local_json_not_demo":
        raise ValueError("source is not operational")
    if source.get("contains_personal_data") is not False:
        raise ValueError("potential private data")
    from datetime import datetime
    stamp = source.get("generated_at_utc")
    if not isinstance(stamp, str):
        raise ValueError("missing time")
    dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if not dt.tzinfo:
        raise ValueError("timestamp not timezone-aware")
    record = {"stamp": dt.isoformat()}
    for key in COUNT_KEYS:
        n=source.get(key)
        if type(n) is not int or n < 0:
            raise ValueError("invalid numeric metric")
        record[key] = n
    return record

def append_private_history(database: Path, record: dict) -> int:
    database.parent.mkdir(parents=True, exist_ok=True)
    cols=", ".join(f"{key} INTEGER NOT NULL" for key in COUNT_KEYS)
    names=", ".join(("stamp", *COUNT_KEYS))
    placeholders=", ".join("?" for _ in range(len(COUNT_KEYS)+1))
    with sqlite3.connect(str(database)) as db:
        db.execute("CREATE TABLE IF NOT EXISTS messenger_aggregate_snapshots "
                   f"(stamp TEXT PRIMARY KEY,{cols})")
        db.execute(f"INSERT OR IGNORE INTO messenger_aggregate_snapshots "
                   f"({names}) VALUES ({placeholders})",
                   [record["stamp"], *(record[key] for key in COUNT_KEYS)])
        result=db.execute("SELECT COUNT(*) FROM messenger_aggregate_snapshots").fetchone()[0]
    return result

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--private-db",type=Path,required=True)
    args=parser.parse_args()
    record=safe_record(json.loads(args.source.read_text(encoding="utf-8-sig")))
    total=append_private_history(args.private_db,record)
    print(json.dumps({"history_rows":total,"contains_customer_data":False,
                      "publication":False},ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
