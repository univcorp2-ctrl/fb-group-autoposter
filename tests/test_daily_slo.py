from pathlib import Path

from scripts.ensure_daily_post import MAX_PRESUBMIT_ATTEMPTS, _live_pipeline_owner
from scripts.verify_estateboard_web import missing_permalinks


def test_daily_guarantee_attempts_are_bounded() -> None:
    assert MAX_PRESUBMIT_ATTEMPTS == 2


def test_live_pipeline_owner_blocks_and_dead_owner_does_not(
    tmp_path, monkeypatch
) -> None:
    lock = tmp_path / "pipeline.lock"
    lock.write_text("1234", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.ensure_daily_post._pid_is_running", lambda pid: pid == 1234
    )
    assert _live_pipeline_owner(lock) == 1234
    monkeypatch.setattr(
        "scripts.ensure_daily_post._pid_is_running", lambda _pid: False
    )
    assert _live_pipeline_owner(lock) is None


def test_web_reflection_requires_every_permalink() -> None:
    urls = ["https://facebook.example/a", "https://facebook.example/b"]
    public = '{"url":"https://facebook.example/a"}'
    assert missing_permalinks(public, urls) == ["https://facebook.example/b"]
    assert missing_permalinks(public + " https://facebook.example/b", urls) == []


def test_slo_task_registration_contract() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "register_slo_tasks.ps1"
    ).read_text(encoding="utf-8")
    assert "FBAutoposter-CommunityManager" in source
    assert "FBAutoposter-DailyGuarantee" in source
    assert "FBAutoposter-WebSLO" in source
    assert "-At '06:20'" in source
    assert "-At '22:10'" in source
    assert "-At '23:10'" in source
    assert "New-TimeSpan -Minutes 15" in source
    assert "-MultipleInstances IgnoreNew" in source
    assert "-Hidden" in source
