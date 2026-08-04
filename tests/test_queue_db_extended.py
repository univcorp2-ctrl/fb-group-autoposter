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


def test_duplicate_property_posted_ever_detects_old_success(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    old_job = db.create_job({"property_id": "p"}, [{"group_id": "g", "body": "old"}])
    db.update_target_status(old_job, "g", "posted")

    assert db.duplicate_property_posted_ever("p", "g") is True
    assert db.duplicate_property_posted_ever("p", "other") is False


def test_duplicate_property_posted_ever_treats_uncertain_as_duplicate(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    old_job = db.create_job({"property_id": "p"}, [{"group_id": "g", "body": "old"}])
    db.update_target_status(old_job, "g", "uncertain")

    assert db.duplicate_property_posted_ever("p", "g") is True


def test_posted_property_ids_includes_uncertain(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    posted_job = db.create_job({"property_id": "posted"}, [{"group_id": "g", "body": "old"}])
    uncertain_job = db.create_job({"property_id": "uncertain"}, [{"group_id": "g", "body": "old"}])
    failed_job = db.create_job({"property_id": "failed"}, [{"group_id": "g", "body": "old"}])
    db.update_target_status(posted_job, "g", "posted")
    db.update_target_status(uncertain_job, "g", "uncertain")
    db.update_target_status(failed_job, "g", "failed")

    assert db.posted_property_ids() == {"posted", "uncertain"}


def test_posted_same_group_recently_blocks_on_recent_post(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job = db.create_job({"property_id": "p"}, [{"group_id": "g", "body": "x"}])
    db.update_target_status(job, "g", "posted")

    assert db.posted_same_group_recently("g", 24) is True
    assert db.posted_same_group_recently("other", 24) is False


def test_posted_same_group_recently_counts_uncertain(tmp_path):
    # An uncertain post very likely published, so it must enforce the same-group
    # gap to avoid posting twice in a day (block-avoidance).
    db = QueueDB(tmp_path / "jobs.db")
    job = db.create_job({"property_id": "p"}, [{"group_id": "g", "body": "x"}])
    db.update_target_status(job, "g", "uncertain")

    assert db.posted_same_group_recently("g", 24) is True


def test_posted_same_group_today_counts_uncertain(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job = db.create_job({"property_id": "p"}, [{"group_id": "g", "body": "x"}])
    db.update_target_status(job, "g", "uncertain")

    assert db.posted_same_group_today("g") is True


def test_count_posts_today_counts_posted_and_uncertain(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    posted_job = db.create_job({"property_id": "a"}, [{"group_id": "g1", "body": "x"}])
    uncertain_job = db.create_job({"property_id": "b"}, [{"group_id": "g2", "body": "x"}])
    failed_job = db.create_job({"property_id": "c"}, [{"group_id": "g3", "body": "x"}])
    db.update_target_status(posted_job, "g1", "posted")
    db.update_target_status(uncertain_job, "g2", "uncertain")
    db.update_target_status(failed_job, "g3", "failed")

    assert db.count_posts_today() == 2


def test_uncertain_target_is_never_returned_for_automatic_resubmission(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "p"}, [{"group_id": "g", "body": "body"}])
    db.update_target_status(job_id, "g", "uncertain")

    assert db.unposted_targets(job_id) == []
