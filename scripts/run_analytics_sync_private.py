"""Scheduled, bounded analytics recovery for the existing approved EstateBoard ingest.

Reads private token from Google Drive, never from Git, and exports only local
posting history. It never creates Facebook posts or sends customer messages.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT.parents[2] / "Private"
RUNTIME = Path(os.environ.get("LOCALAPPDATA", "")) / "FBGroupAutoposter" / "data" / "jobs.db"
SECRETS = PRIVATE / "estateboard_analytics_tokens.json"
STATE = PRIVATE / "FBGroupAutoposter" / "analytics_sync_checkpoint.json"
RESULT = PRIVATE / "FBGroupAutoposter" / "analytics_sync_last_result.json"
MAX_BATCH = 50

sys.path.insert(0, str(ROOT))
from src.analytics_export import (
    AnalyticsClient, build_post_payload, load_config,
    load_group_catalog, read_posting_history, validate_config,
)

def write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)

def run(check_only: bool = False) -> int:
    if not SECRETS.is_file() or not RUNTIME.is_file():
        raise RuntimeError("Required private analytics token file or runtime database missing")
    token = json.loads(SECRETS.read_text(encoding="utf-8")).get("ANALYTICS_INGEST_TOKEN", "")
    if not isinstance(token, str) or len(token) < 16:
        raise RuntimeError("Private analytics ingest token missing")
    os.environ["ANALYTICS_SYNC_ENABLED"] = "true"
    os.environ["ANALYTICS_INGEST_TOKEN"] = token
    os.environ["DB_PATH"] = str(RUNTIME)
    os.environ["GROUPS_PATH"] = str(ROOT / "groups.yaml")
    os.environ["ANALYTICS_BASE_URL"] = "https://estateboard.pages.dev"
    config = load_config(ROOT / ".env")
    validate_config(config)
    if Path(config.db_path).resolve() != RUNTIME.resolve():
        raise RuntimeError("Wrong source database")
    records = read_posting_history(config.db_path)
    published = [x for x in records if x.get("status") == "posted" and x.get("permalink")]
    other = [x for x in records if x not in published]
    status = {"checked_at": datetime.now(timezone.utc).isoformat(), "checked": len(records),
              "posted_rows": len(published), "sent": 0, "unchanged": 0,
              "failed": 0, "batch_limit": MAX_BATCH, "mode": "check" if check_only else "sync"}
    if check_only:
        write_atomic(RESULT, status)
        print(json.dumps(status, ensure_ascii=False))
        return 0
    checkpoint = json.loads(STATE.read_text(encoding="utf-8")) if STATE.is_file() else {}
    if not isinstance(checkpoint, dict):
        raise RuntimeError("Invalid checkpoint; refusing to overwrite")
    client = AnalyticsClient(config)
    catalog = load_group_catalog(config.groups_path)
    try:
        for row in published + other:
            payload = build_post_payload(row, catalog)
            key = payload["idempotency_key"]
            digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":")).encode("utf-8")).hexdigest()
            if checkpoint.get(key) == digest:
                status["unchanged"] += 1
                continue
            if status["sent"] >= MAX_BATCH:
                break
            try:
                client.send_post(payload)
            except Exception as exc:
                status["failed"] += 1
                status["error_type"] = type(exc).__name__
                break   # fail closed: do not storm APIs on 401 / 429 / network problems
            checkpoint[key] = digest
            status["sent"] += 1
            if status["sent"] % 10 == 0:
                write_atomic(STATE, checkpoint)
    finally:
        write_atomic(STATE, checkpoint)
        write_atomic(RESULT, status)
    print(json.dumps(status, ensure_ascii=False))
    return 0 if not status["failed"] else 2

if __name__ == "__main__":
    try:
        raise SystemExit(run("--check" in sys.argv))
    except Exception as exc:
        # Do not disclose credentials, URLs with auth tokens, or full server errors.
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}, ensure_ascii=False))
        raise SystemExit(2)
