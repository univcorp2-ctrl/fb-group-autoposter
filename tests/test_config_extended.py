import pytest

from config import Settings


def test_int_env_rejects_non_numeric(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RETRY_MAX", "three")
    with pytest.raises(ValueError, match="RETRY_MAX.*must be an integer"):
        Settings.load(env_file=tmp_path / ".env")


def test_int_env_accepts_valid_number(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RETRY_MAX", "5")
    settings = Settings.load(env_file=tmp_path / ".env")
    assert settings.retry_max == 5


def test_settings_defaults_are_failsafe(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    settings = Settings.load(env_file=tmp_path / ".env")
    assert settings.dry_run is True
    assert settings.auto_approve is False
    assert settings.browser_backend == "playwright"


def test_validate_runtime_rejects_invalid_backend(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROWSER_BACKEND", "selenium")
    settings = Settings.load(env_file=tmp_path / ".env")
    with pytest.raises(ValueError, match="BROWSER_BACKEND"):
        settings.validate_runtime(require_external=False)


def test_validate_runtime_rejects_zero_positive_values(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAX_POSTS_PER_DAY", "0")
    settings = Settings.load(env_file=tmp_path / ".env")
    with pytest.raises(ValueError, match="MAX_POSTS_PER_DAY"):
        settings.validate_runtime(require_external=False)
