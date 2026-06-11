from pathlib import Path

import pytest

from config import Settings, load_groups


def test_settings_validate_runtime_requires_external(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "jobs.db"))
    settings = Settings.load(env_file=tmp_path / ".env")
    with pytest.raises(RuntimeError):
        settings.validate_runtime(require_external=True)


def test_load_groups_validates_policy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("groups.yaml").write_text("groups:\n  - id: g1\n    enabled: true\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_groups()
