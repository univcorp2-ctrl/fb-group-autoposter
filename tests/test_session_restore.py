"""Tests for session backup/restore fallback (src/session.py)."""
import inspect
from pathlib import Path
from types import SimpleNamespace

from src.session import backup_profile, latest_backup, restore_profile, restore_session_boundary


def test_backup_is_retained_but_legacy_restore_fails_closed_without_live_mutation(tmp_path):
    profile = tmp_path / "profiles" / "main"
    profile.mkdir(parents=True)
    (profile / "cookies.txt").write_text("session=GOOD", encoding="utf-8")
    (profile / "SingletonLock").write_text("lock", encoding="utf-8")  # volatile, must be skipped

    backup = backup_profile(profile, keep=3)
    assert backup is not None
    assert (backup / "cookies.txt").read_text(encoding="utf-8") == "session=GOOD"
    assert not (backup / "SingletonLock").exists()  # volatile file not copied

    # A scheduler-reachable expiry must never overwrite the live profile.
    (profile / "cookies.txt").write_text("EXPIRED", encoding="utf-8")
    used = restore_profile(profile)
    assert used is None
    assert (profile / "cookies.txt").read_text(encoding="utf-8") == "EXPIRED"


def test_latest_backup_and_restore_none_when_absent(tmp_path):
    profile = tmp_path / "profiles" / "main"
    profile.mkdir(parents=True)
    assert latest_backup(profile) is None
    assert restore_profile(profile) is None


def test_ordinary_expiry_boundary_requires_manual_profile_recovery(tmp_path):
    profile = tmp_path / "profiles" / "main"
    profile.mkdir(parents=True)

    result = restore_session_boundary(profile, run_id="expiry-001")

    assert (result.reason, result.circuit_open, result.submission_allowed) == (
        "manual_profile_recovery_required",
        True,
        False,
    )


def test_supplied_candidate_probe_is_never_runtime_clearance(tmp_path, monkeypatch):
    import src.browser_runtime as runtime

    profile = tmp_path / "profiles" / "main"
    profile.mkdir(parents=True)
    (profile / "Preferences").write_text("safe", encoding="utf-8")
    monkeypatch.setattr(runtime, "discover_chrome", lambda: Path("C:/Chrome/chrome.exe"))
    contract = SimpleNamespace(profile_dir=profile, browser_user_agent="configured-stable-user-agent")

    result = restore_session_boundary(
        profile,
        run_id="expiry-001",
        contract=contract,
        probe_callable=lambda context: {
            "authenticated": True,
            "user_agent": "configured-stable-user-agent",
            "context_binding": context.binding,
        },
    )

    assert (result.reason, result.healthy, result.circuit_open, result.submission_allowed) == (
        "candidate_probe_healthy_manual_recovery_required",
        False,
        True,
        False,
    )


def test_daily_manual_recovery_stop_states_keep_session_dead_alert_active():
    from scripts import run_daily

    assert run_daily._requires_session_dead_alert("manual_profile_recovery_required") is True
    assert run_daily._requires_session_dead_alert("candidate_probe_healthy_manual_recovery_required") is True
    assert run_daily._requires_session_dead_alert("completed") is False


def test_daily_scheduler_does_not_call_legacy_live_profile_restore():
    from scripts import run_daily

    assert "restore_profile(" not in inspect.getsource(run_daily.main)


def test_restore_boundary_refuses_challenge_without_touching_live_profile(tmp_path):
    profile = tmp_path / "profiles" / "main"
    profile.mkdir(parents=True)
    (profile / "Preferences").write_text("live", encoding="utf-8")

    result = restore_session_boundary(profile, run_id="challenge-001", challenge="checkpoint")

    assert (result.reason, result.circuit_open, result.submission_allowed) == (
        "checkpoint",
        True,
        False,
    )
    assert (profile / "Preferences").read_text(encoding="utf-8") == "live"
    assert not (tmp_path / "profiles" / "backups" / "challenge-001").exists()
