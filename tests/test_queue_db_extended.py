import pytest

from src.queue_db import QueueDB


def test_update_target_with_increment_attempts(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "p"}, [{"group_id": "g", "body": "body"}])
    db.update_target_status(job_id, "g", "failed", error="timeout", increment_attempts=True)
    targets = db.get_targets(job_id)
    assert targets[0]["attempts"] == 1
    assert targets[0]["last_error"] == "timeout"


def test_update_target_without_increment_keeps_attempts(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "p"}, [{"group_id": "g", "body": "body"}])
    db.update_target_status(job_id, "g", "failed", error="timeout", increment_attempts=True)
    db.update_target_status(job_id, "g", "posted")
    targets = db.get_targets(job_id)
    assert targets[0]["attempts"] == 1
    assert targets[0]["status"] == "posted"


def test_heartbeat_roundtrip(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    db.mark_heartbeat("test-component")
    age = db.heartbeat_age_minutes("test-component")
    assert age is not None
    assert age < 1.0


def test_heartbeat_age_returns_none_for_unknown(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    assert db.heartbeat_age_minutes("unknown") is None


def test_reject_job_skips_pending_targets(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job(
        {"property_id": "p"},
        [{"group_id": "g1", "body": "a"}, {"group_id": "g2", "body": "b"}],
    )
    db.reject_job(job_id, "not suitable")
    assert db.get_job(job_id)["status"] == "rejected"
    for t in db.get_targets(job_id):
        assert t["status"] == "skipped"


def test_invalid_target_status_raises(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    with pytest.raises(ValueError, match="invalid target status"):
        db.update_target_status("j", "g", "bad_status")


def test_count_posts_today_zero_initially(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    assert db.count_posts_today() == 0
