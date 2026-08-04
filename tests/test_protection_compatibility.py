"""Offline characterization tests for the Claude account-protection baseline."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from config import Settings
from src.browser_runtime import BrowserContract
from src.ensure import ensure_posted_today
from src.poster import (
    CheckpointRequired,
    FacebookPoster,
    PostNotVerified,
    PostingBlocked,
    SessionExpired,
)
from src.queue_db import QueueDB


ROOT = Path(__file__).resolve().parents[1]


def _settings(**overrides):
    values = {
        "profile_dir": Path("profiles/main"),
        "browser_user_agent": "configured-stable-user-agent",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_browser_contract_preserves_existing_identity():
    settings = _settings()

    contract = BrowserContract.from_settings(settings)

    assert contract.headless is False
    assert contract.user_data_dir == Path("profiles/main")
    assert contract.user_agent == settings.browser_user_agent
    assert contract.viewport == {"width": 1366, "height": 900}


def test_browser_contract_viewport_cannot_be_mutated():
    contract = BrowserContract.from_settings(_settings())

    with pytest.raises(TypeError):
        contract.viewport["width"] = 1920


def test_settings_defaults_preserve_conservative_runtime_controls(monkeypatch, tmp_path):
    for name in (
        "AUTO_APPROVE",
        "HUMANIZE",
        "MIN_INTERVAL_MIN",
        "MAX_INTERVAL_MIN",
        "MAX_GROUPS_PER_BROWSER",
        "COOLDOWN_HOURS",
        "PROFILE_DIR",
        "BROWSER_USER_AGENT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings.load(tmp_path / "missing.env")

    assert settings.auto_approve is False
    assert settings.dry_run is True
    assert settings.humanize is True
    assert (settings.min_interval_min, settings.max_interval_min) == (15, 35)
    assert settings.max_groups_per_browser == 5
    assert settings.cooldown_hours == 24
    assert settings.profile_dir == Path("profiles/main")
    assert settings.browser_user_agent.endswith("Chrome/126.0.0.0 Safari/537.36")


def test_runtime_posting_gates_default_off_in_settings_defaults(monkeypatch, tmp_path):
    for name in ("DRY_RUN", "AUTO_APPROVE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings.load(tmp_path / "missing.env")

    assert settings.dry_run is True
    assert settings.auto_approve is False


def test_production_example_keeps_stricter_posting_limits():
    source = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "MAX_POSTS_PER_DAY=2" in source
    assert "MIN_SAME_GROUP_HOURS=24" in source


def test_poster_keeps_navigation_and_human_pause_ranges():
    post_source = inspect.getsource(FacebookPoster._post_one_attempt)
    pause_source = inspect.getsource(FacebookPoster._human_pause)

    assert "random.randint(1200, 3500)" in post_source
    assert "random.randint(800, 3200)" in pause_source
    assert pause_source.count("page.mouse.move") == 2
    assert "page.mouse.wheel(0, random.randint(100, 400))" in pause_source


def test_poster_keeps_interval_and_context_recycling_thresholds():
    interval_source = inspect.getsource(FacebookPoster._random_interval)
    posting_source = inspect.getsource(FacebookPoster._post_job_real)

    assert "self.settings.min_interval_min * 60" in interval_source
    assert "self.settings.max_interval_min * 60" in interval_source
    assert "posted_in_browser >= self.settings.max_groups_per_browser" in posting_source


def test_poster_retry_excludes_session_block_and_ambiguity():
    retry = FacebookPoster._post_one.retry.retry

    for exception in (SessionExpired("expired"), PostingBlocked("blocked"), PostNotVerified("uncertain")):
        outcome = SimpleNamespace(failed=True, exception=lambda exception=exception: exception)
        retry_state = SimpleNamespace(outcome=outcome)
        assert retry(retry_state) is False


def test_current_checkpoint_flow_restores_once_then_retries_before_stopping():
    calls = {"run": 0, "restore": 0}

    class FakeDB:
        @staticmethod
        def posted_same_group_today(_group_id):
            return False

    async def run_once():
        calls["run"] += 1
        raise CheckpointRequired("checkpoint", kind="checkpoint")

    def restore_session():
        calls["restore"] += 1
        return True

    async def no_sleep(_seconds):
        return None

    result = asyncio.run(
        ensure_posted_today(
            None,
            [{"id": "g", "active_hours": [0, 24]}],
            FakeDB(),
            run_once=run_once,
            restore_session=restore_session,
            sleeper=no_sleep,
            now_hour_fn=lambda: 12,
            time_fn=lambda: 0.0,
        )
    )

    assert calls == {"run": 2, "restore": 1}
    assert result["reason"] == "session_unrecoverable"
    assert result["challenge"] == "checkpoint"


def test_posting_block_records_failure_without_screenshot_evidence():
    source = inspect.getsource(FacebookPoster._post_job_real)
    blocked_branch = source.split("except PostingBlocked as exc:", 1)[1].split(
        "except Exception as exc:", 1
    )[0]

    assert 'update_target_status_with_outbox(' in blocked_branch
    assert '"failed"' in blocked_branch
    assert "save_screenshot" not in blocked_branch


def test_scheduler_keeps_randomized_posting_windows():
    source = (ROOT / "scripts" / "install_windows_tasks.ps1").read_text(encoding="utf-8")

    assert "FBAutoposter-Morning' -Script 'run_daily.py' -At '09:30' -RandomDelayMin 45" in source
    assert "FBAutoposter-Midday' -Script 'run_daily.py' -At '13:00' -RandomDelayMin 30" in source
    assert "FBAutoposter-Afternoon' -Script 'run_daily.py' -At '16:30' -RandomDelayMin 30" in source
    assert "FBAutoposter-Evening' -Script 'run_daily.py' -At '20:30' -RandomDelayMin 45" in source


def test_membership_check_is_report_only_without_explicit_enable_flag():
    source = (ROOT / "scripts" / "check_membership.py").read_text(encoding="utf-8")

    assert 'do_enable = "--enable" in sys.argv' in source
    assert "if do_enable and joined_disabled:" in source


def test_uncertain_verifier_probe_preserves_targets_but_may_initialize_schema(
    tmp_path, monkeypatch
):
    from playwright import async_api
    from scripts import verify_posts

    db_path = tmp_path / "jobs.db"
    db = QueueDB(db_path)
    job_id = db.create_job({"property_id": "p"}, [{"group_id": "g", "body": "body"}])
    db.update_target_status(job_id, "g", "uncertain", error="pending_approval")
    before = db.get_targets(job_id)
    with db.connect() as conn:
        conn.execute("DROP TABLE heartbeat")
        conn.execute("DROP TABLE group_circuit")

    settings = SimpleNamespace(
        db_path=db_path,
        profile_dir=tmp_path / "profile",
        browser_user_agent="configured-stable-user-agent",
    )
    monkeypatch.setattr(verify_posts.Settings, "load", lambda: settings)
    monkeypatch.setattr(
        verify_posts,
        "load_groups",
        lambda: [{"id": "g", "name": "Group", "post_url": "https://example.invalid/g"}],
    )

    class FakeContext:
        pages = [object()]

        async def close(self):
            return None

    class FakeChromium:
        async def launch_persistent_context(self, **_kwargs):
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightContextManager:
        async def __aenter__(self):
            return FakePlaywright()

        async def __aexit__(self, *_args):
            return None

    async def fake_cookie_user_id(_context):
        return "user-id"

    async def fake_collect_my_posts(*_args, **_kwargs):
        return [{"permalink": "https://example.invalid/post", "text": "body"}]

    monkeypatch.setattr(async_api, "async_playwright", FakePlaywrightContextManager)
    monkeypatch.setattr(verify_posts, "cookie_user_id", fake_cookie_user_id)
    monkeypatch.setattr(verify_posts, "collect_my_posts", fake_collect_my_posts)

    asyncio.run(verify_posts.run(headed=False, probe=True))

    after = QueueDB(db_path).get_targets(job_id)
    with db.connect() as conn:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert after == before
    assert {"heartbeat", "group_circuit"} <= tables
