from pathlib import Path

from src.queue_db import QueueDB
<<<<<<< HEAD
from src.runtime_status import _safe_error, build_runtime_status, write_runtime_status
=======
from src.runtime_status import build_runtime_status, write_runtime_status
>>>>>>> origin/main


def test_missing_db_is_not_initialized(tmp_path: Path) -> None:
    result = build_runtime_status(tmp_path / "missing.db")
    assert result["health"] == "not_initialized"


<<<<<<< HEAD
def test_posted_row_is_exported_without_private_paths(tmp_path: Path) -> None:
=======
def test_posted_row_is_exported(tmp_path: Path) -> None:
>>>>>>> origin/main
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
<<<<<<< HEAD
    assert "screenshot" not in result["recent"][0]
    assert output.exists()


def test_error_redaction() -> None:
    assert _safe_error("API_KEY=very-secret failure") == "API_KEY=[REDACTED] failure"
=======
    assert output.exists()
>>>>>>> origin/main
