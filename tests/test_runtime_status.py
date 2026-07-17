from pathlib import Path

from src.queue_db import QueueDB
from src.runtime_status import build_runtime_status, write_runtime_status


def test_missing_db_is_not_initialized(tmp_path: Path) -> None:
    result = build_runtime_status(tmp_path / "missing.db")
    assert result["health"] == "not_initialized"


def test_posted_row_is_exported(tmp_path: Path) -> None:
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job(
        {"property_id": "eb-1"},
        [{"group_id": "g1", "body": "body"}],
    )
    db.update_target_status(job_id, "g1", "posted", permalink="https://example.test/post/1")
    output = tmp_path / "site" / "status.json"
    result = write_runtime_status(db.path, output)
    assert result["health"] == "healthy"
    assert result["counts"]["posted"] == 1
    assert result["recent"][0]["permalink"].endswith("/1")
    assert output.exists()
