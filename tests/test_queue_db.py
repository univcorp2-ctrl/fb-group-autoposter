from src.queue_db import QueueDB


def test_queue_lifecycle_and_unique(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    prop = {"property_id": "p1", "title": "A"}
    variants = [{"group_id": "g1", "body": "body"}, {"group_id": "g1", "body": "body duplicate"}]
    job_id = db.create_job(prop, variants)
    targets = db.get_targets(job_id)
    assert len(targets) == 1
    db.approve_job(job_id)
    assert db.get_job(job_id)["status"] == "approved"
    db.update_job_status(job_id, "posting")
    db.update_target_status(job_id, "g1", "posted")
    assert db.finalize_job_from_targets(job_id) == "done"
    assert db.duplicate_property_recently("p1", "g1") is True


def test_invalid_status_rejected(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    try:
        db.update_job_status("missing", "bad")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid status should fail")
