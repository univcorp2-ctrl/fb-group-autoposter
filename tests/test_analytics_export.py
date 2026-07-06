from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from src.analytics_export import AnalyticsConfig, build_post_payload, read_posting_history, sync_history


class FakeClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def send_post(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {"ok": True}


def make_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE jobs(job_id TEXT PRIMARY KEY,property_id TEXT,status TEXT,created_at TEXT,updated_at TEXT,payload_json TEXT);
            CREATE TABLE job_targets(id INTEGER PRIMARY KEY,job_id TEXT,group_id TEXT,body TEXT,status TEXT,attempts INTEGER,last_error TEXT,posted_at TEXT,permalink TEXT);
            """
        )
        conn.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?)",
            ("job-1", "eb-42", "done", "2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00", json.dumps({"title": "新宿一棟ビル", "url": "https://example.test/42"})),
        )
        conn.execute(
            "INSERT INTO job_targets VALUES(?,?,?,?,?,?,?,?,?)",
            (1, "job-1", "group-1", "本文", "posted", 1, None, "2026-01-01T01:00:00+00:00", "https://facebook.test/post/1"),
        )


def test_read_and_build_payload(tmp_path: Path) -> None:
    db = tmp_path / "jobs.db"
    make_db(db)
    row = read_posting_history(db)[0]
    payload = build_post_payload(row, {"group-1": {"name": "投資家グループ", "post_url": "https://facebook.test/group/1"}})
    assert payload["idempotency_key"] == "post:job-1:group-1"
    assert payload["property"]["title"] == "新宿一棟ビル"
    assert payload["group"]["name"] == "投資家グループ"
    assert payload["post_url"] == "https://facebook.test/post/1"


def test_sync_history_backfills_all_rows(tmp_path: Path) -> None:
    db = tmp_path / "jobs.db"
    make_db(db)
    groups = tmp_path / "groups.yaml"
    groups.write_text("groups:\n  - id: group-1\n    name: Test Group\n", encoding="utf-8")
    config = AnalyticsConfig(True, "https://estateboard.test", "secret", db, groups)
    client = FakeClient()
    result = sync_history(config, client=client)
    assert result == {"total": 1, "sent": 1, "failed": 0}
    assert len(client.payloads) == 1


def test_sync_script_runs_from_repo_root_without_import_error() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/sync_analytics.py"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "ModuleNotFoundError" not in result.stderr
    assert "ANALYTICS_SYNC_ENABLED=false" in result.stdout
