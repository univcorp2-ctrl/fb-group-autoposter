"""Tests for the EstateBoard posting-status bridge (scripts/sync_estateboard_status.py)."""
import json
import sqlite3

import scripts.sync_estateboard_status as bridge
from scripts.sync_estateboard_status import (
    POSTED_COLUMN,
    POSTED_DATE_COLUMN,
    POSTED_LABEL,
    POSTED_TO_COLUMN,
    sync_estateboard_status,
)


def _make_jobs_db(path):
    """Tiny jobs.db with one posted property eb-2362 (group g1, screenshot s.png)."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE jobs (job_id TEXT PRIMARY KEY, property_id TEXT, status TEXT);
        CREATE TABLE job_targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, group_id TEXT,
            body TEXT, status TEXT, posted_at TEXT, screenshot TEXT, permalink TEXT
        );
        """
    )
    conn.execute("INSERT INTO jobs VALUES ('j1', 'eb-2362', 'done')")
    conn.execute(
        "INSERT INTO job_targets(job_id, group_id, body, status, posted_at, screenshot) "
        "VALUES ('j1', 'g1', 'b', 'posted', '2026-06-10T00:00:00+00:00', 'screenshots/s.png')"
    )
    conn.commit()
    conn.close()


def _make_master(path):
    """Master with a matching record (propertyId 2362 -> id 99) and a non-match."""
    records = [
        {"id": 99, "propertyId": 2362, "property.label": "投稿済物件"},
        {"id": 7, "propertyId": 1111, "property.label": "未投稿物件"},
    ]
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _make_data_json(path):
    payload = {
        "generated_at": "2026-06-20T00:00:00",
        "count": 2,
        "columns": ["チェック", "コメント", "ID", "物件名"],
        "items": [
            {"チェック": False, "コメント": "", "ID": 99, "物件名": "投稿済物件"},
            {"チェック": False, "コメント": "", "ID": 7, "物件名": "未投稿物件"},
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_sync_marks_master_and_data_json(tmp_path, monkeypatch):
    # Arrange: a temp EstateBoard tree + a temp jobs.db with one posted property.
    db_path = tmp_path / "jobs.db"
    _make_jobs_db(db_path)
    eb_root = tmp_path / "EstateBoard"
    received = eb_root / "output" / "received"
    docs = eb_root / "docs"
    received.mkdir(parents=True)
    docs.mkdir(parents=True)
    master = received / "master_properties.jsonl"
    data_json = docs / "data.json"
    _make_master(master)
    _make_data_json(data_json)

    # Resolve group_id g1 -> a human community NAME (not the raw id).
    monkeypatch.setattr(bridge, "_group_name_map", lambda: {"g1": "収益物件シェアグループ"})

    # Act
    summary = sync_estateboard_status(db_path, eb_root=eb_root)

    # Assert: master — matching record stamped with group NAMES; non-match untouched.
    by_id = {r["id"]: r for r in _read_jsonl(master)}
    assert by_id[99]["_posted_to_fb"] == "2026-06-10T00:00:00+00:00"
    assert by_id[99]["_posted_groups"] == ["収益物件シェアグループ"]  # NAME, not "g1"
    assert by_id[99]["_posted_screenshot"] == "screenshots/s.png"
    assert "_posted_to_fb" not in by_id[7]

    # Assert: data.json gains leading 投稿済 / 投稿先 / 投稿日 columns.
    data = json.loads(data_json.read_text(encoding="utf-8"))
    assert data["columns"][0] == POSTED_COLUMN
    assert data["columns"][1] == POSTED_TO_COLUMN  # 投稿先 right after 投稿済
    assert data["columns"][2] == POSTED_DATE_COLUMN
    items = {it["ID"]: it for it in data["items"]}
    assert list(data["items"][0].keys())[0] == POSTED_COLUMN  # 投稿済 is first key
    assert items[99][POSTED_COLUMN] == POSTED_LABEL
    assert items[99][POSTED_TO_COLUMN] == "収益物件シェアグループ"  # community NAME
    assert items[99][POSTED_DATE_COLUMN] == "2026-06-10"
    assert items[7][POSTED_COLUMN] == ""
    assert items[7][POSTED_TO_COLUMN] == ""

    assert summary["master_marked"] == 1
    assert summary["data_marked"] == 1


def test_sync_absent_repo_is_noop(tmp_path):
    db_path = tmp_path / "jobs.db"
    _make_jobs_db(db_path)
    summary = sync_estateboard_status(db_path, eb_root=tmp_path / "does_not_exist")
    assert summary["skipped"] is True
    assert summary["master_marked"] == 0
