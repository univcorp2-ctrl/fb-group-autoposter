from types import SimpleNamespace

from src.poster import FacebookPoster
from src.queue_db import QueueDB


def settings(tmp_path):
    return SimpleNamespace(
        dry_run=True,
        max_posts_per_day=1,
        min_same_group_hours=20,
        group_fail_threshold=3,
        profile_dir=tmp_path / "profile",
        page_hard_timeout=120,
        browser_backend="playwright",
        max_groups_per_browser=5,
        min_interval_min=0,
        max_interval_min=0,
        humanize=False,
    )


def test_preflight_daily_limit(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    s = settings(tmp_path)
    group = {"id": "g", "active_hours": [0, 24]}
    job_id = db.create_job({"property_id": "p", "title": "A"}, [{"group_id": "g", "body": "body"}])
    db.update_target_status(job_id, "g", "posted")
    poster = FacebookPoster(s, db, [group])
    reason = poster._preflight_target({"property_id": "p2"}, {"group_id": "g"}, group)
    assert reason == "daily_limit"
