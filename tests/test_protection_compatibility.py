"""Offline characterization tests for the Claude account-protection baseline."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

from config import Settings
from src.browser_runtime import BrowserContract
from src.poster import FacebookPoster, PostNotVerified, PostingBlocked, SessionExpired


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
    assert settings.humanize is True
    assert (settings.min_interval_min, settings.max_interval_min) == (15, 35)
    assert settings.max_groups_per_browser == 5
    assert settings.cooldown_hours == 24
    assert settings.profile_dir == Path("profiles/main")
    assert settings.browser_user_agent.endswith("Chrome/126.0.0.0 Safari/537.36")


def test_production_example_keeps_stricter_posting_limits():
    source = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "MAX_POSTS_PER_DAY=2" in source
    assert "MIN_SAME_GROUP_HOURS=24" in source


def test_poster_keeps_navigation_and_human_pause_ranges():
    post_source = inspect.getsource(FacebookPoster._post_one)
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


def test_posting_block_records_failure_without_screenshot_evidence():
    source = inspect.getsource(FacebookPoster._post_job_real)
    blocked_branch = source.split("except PostingBlocked as exc:", 1)[1].split(
        "except Exception as exc:", 1
    )[0]

    assert 'update_target_status(job["job_id"], target["group_id"], "failed"' in blocked_branch
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


def test_uncertain_verifier_has_explicit_read_only_probe_mode():
    source = (ROOT / "scripts" / "verify_posts.py").read_text(encoding="utf-8")

    assert 'ap.add_argument("--probe", action="store_true"' in source
    assert "if probe:" in source
    assert "await ctx.close()\n            return summary\n\n        # Correct the DB against reality." in source
