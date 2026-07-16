from types import SimpleNamespace

from src.poster import FacebookPoster
from src.queue_db import QueueDB


def settings(**overrides):
    base = dict(
        dry_run=True,
        max_posts_per_day=10,
        min_same_group_hours=20,
        max_groups_per_browser=5,
        group_fail_threshold=3,
        min_interval_min=0,
        max_interval_min=0,
        profile_dir="profiles/main",
        page_hard_timeout=1,
        browser_backend="playwright",
        humanize=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def group(**overrides):
    base = {"id": "g1", "active_hours": [0, 24], "post_url": "https://www.facebook.com/groups/g1/"}
    base.update(overrides)
    return base


def test_preflight_blocks_daily_limit(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    poster = FacebookPoster(settings(max_posts_per_day=0), db, [group()])
    reason = poster._preflight_target({"property_id": "p"}, {"group_id": "g1"}, group())
    assert reason == "daily_limit"


def test_preflight_blocks_outside_group_active_hours(tmp_path, monkeypatch):
    db = QueueDB(tmp_path / "jobs.db")
    poster = FacebookPoster(settings(), db, [group()])
    monkeypatch.setattr(poster, "_group_allowed_now", lambda _group: False)

    reason = poster._preflight_target({"property_id": "p"}, {"group_id": "g1"}, group())

    assert reason == "outside_active_hours"


def test_preflight_blocks_duplicate_recent_property(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "p"}, [{"group_id": "g1", "body": "body"}])
    db.update_target_status(job_id, "g1", "posted")
    poster = FacebookPoster(settings(), db, [group()])
    reason = poster._preflight_target({"property_id": "p"}, {"group_id": "g1"}, group())
    assert reason in {"same_group_interval", "duplicate_property_guard"}


def test_dry_run_marks_targets_posted_without_playwright(tmp_path):
    import asyncio

    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "p"}, [{"group_id": "g1", "body": "body"}])
    db.approve_job(job_id)
    poster = FacebookPoster(settings(), db, [group()])
    status = asyncio.run(poster.post_job(db.get_job(job_id)))
    assert status == "done"


def test_has_more_targets_only_between_targets():
    assert FacebookPoster._has_more_targets(0, 2) is True
    assert FacebookPoster._has_more_targets(0, 1) is False
    assert FacebookPoster._has_more_targets(1, 2) is False
