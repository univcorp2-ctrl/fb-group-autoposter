"""Incremental SQLite -> existing EstateBoard Pages analytics D1 sync.

Designed for Windows Task Scheduler, not ChatGPT schedules.
Only changed/new rows are sent; never invent posted status or permalink.
An on-disk SHA256 checkpoint is written atomically after successful API writes.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analytics_export import (
    AnalyticsClient,
    build_post_payload,
    load_config,
    load_group_catalog,
    read_posting_history,
    validate_config,
)


def fingerprint(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def atomic_state(path: Path, state: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    config = load_config(ROOT / ".env")
    validate_config(config)
    path = Path(os.getenv("ANALYTICS_SYNC_CHECKPOINT", str(config.db_path.parent / "analytics_sync_checkpoint.json")))
    state: dict[str, str] = {}
    if path.exists():
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise RuntimeError("analytics checkpoint not a JSON object")
        state = {str(k): str(v) for k, v in parsed.items()}

    client = AnalyticsClient(config)
    catalog = load_group_catalog(config.groups_path)
    rows = read_posting_history(config.db_path)
    summary = {"total": len(rows), "sent": 0, "unchanged": 0, "failed": 0}
    for row in rows:
        payload = build_post_payload(row, catalog)
        key = payload["idempotency_key"]
        digest = fingerprint(payload)
        if state.get(key) == digest:
            summary["unchanged"] += 1
            continue
        try:
            client.send_post(payload)
        except Exception:
            summary["failed"] += 1
            continue
        state[key] = digest
        summary["sent"] += 1
        if summary["sent"] % 25 == 0:
            atomic_state(path, state)
    atomic_state(path, state)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if not summary["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
