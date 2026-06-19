"""Tests for session backup/restore fallback (src/session.py)."""
from src.session import backup_profile, latest_backup, restore_profile


def test_backup_then_restore_recovers_cookies(tmp_path):
    profile = tmp_path / "profiles" / "main"
    profile.mkdir(parents=True)
    (profile / "cookies.txt").write_text("session=GOOD", encoding="utf-8")
    (profile / "SingletonLock").write_text("lock", encoding="utf-8")  # volatile, must be skipped

    backup = backup_profile(profile, keep=3)
    assert backup is not None
    assert (backup / "cookies.txt").read_text(encoding="utf-8") == "session=GOOD"
    assert not (backup / "SingletonLock").exists()  # volatile file not copied

    # Simulate an expired/corrupted live session, then restore.
    (profile / "cookies.txt").write_text("EXPIRED", encoding="utf-8")
    used = restore_profile(profile)
    assert used == backup
    assert (profile / "cookies.txt").read_text(encoding="utf-8") == "session=GOOD"


def test_latest_backup_and_restore_none_when_absent(tmp_path):
    profile = tmp_path / "profiles" / "main"
    profile.mkdir(parents=True)
    assert latest_backup(profile) is None
    assert restore_profile(profile) is None
