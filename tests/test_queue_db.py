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


def test_posted_property_ids_for_group_is_per_group(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    # Two jobs, each targeting both groups, but only some targets posted.
    job_a = db.create_job(
        {"property_id": "pA", "title": "A"},
        [{"group_id": "g1", "body": "b1"}, {"group_id": "g2", "body": "b2"}],
    )
    job_b = db.create_job(
        {"property_id": "pB", "title": "B"},
        [{"group_id": "g1", "body": "b3"}, {"group_id": "g2", "body": "b4"}],
    )
    # g1 posted pA; g2 posted pB (uncertain still counts).
    db.update_target_status(job_a, "g1", "posted")
    db.update_target_status(job_b, "g2", "uncertain")

    assert db.posted_property_ids_for_group("g1") == {"pA"}
    assert db.posted_property_ids_for_group("g2") == {"pB"}
    # A group with nothing posted yet returns an empty set.
    assert db.posted_property_ids_for_group("g3") == set()
    # The global view still unions both.
    assert db.posted_property_ids() == {"pA", "pB"}


def test_invalid_status_rejected(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    try:
        db.update_job_status("missing", "bad")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid status should fail")
