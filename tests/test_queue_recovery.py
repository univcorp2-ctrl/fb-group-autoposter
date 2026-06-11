from src.queue_db import QueueDB


def test_reset_stale_posting_jobs_returns_to_approved(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "p"}, [{"group_id": "g", "body": "body"}])
    db.update_job_status(job_id, "posting")
    assert db.reset_stale_posting_jobs() == 1
    assert db.get_job(job_id)["status"] == "approved"


def test_group_circuit_breaker_suggests_disable_after_threshold(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    assert db.record_group_result("g", success=False, threshold=3) is False
    assert db.record_group_result("g", success=False, threshold=3) is False
    assert db.record_group_result("g", success=False, threshold=3) is True
    assert db.record_group_result("g", success=True, threshold=3) is False


def test_finalize_partial_failed_when_some_targets_posted(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job(
        {"property_id": "p"},
        [{"group_id": "g1", "body": "a"}, {"group_id": "g2", "body": "b"}],
    )
    db.update_target_status(job_id, "g1", "posted")
    db.update_target_status(job_id, "g2", "failed", error="x")
    assert db.finalize_job_from_targets(job_id) == "partial_failed"
