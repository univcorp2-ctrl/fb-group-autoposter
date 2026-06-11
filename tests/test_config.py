from pathlib import Path

import pytest

from config import Settings, load_groups


def test_load_groups_validates_enabled_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("groups.yaml").write_text(
        """
groups:
  - id: "ok"
    name: "OK"
    post_url: "https://www.facebook.com/groups/ok/"
    enabled: true
    tone: "丁寧"
    max_chars: 500
    active_hours: [9, 22]
    allow_links: true
    allow_images: true
    signature: ""
    forbidden: []
  - id: "bad"
    name: "BAD"
    post_url: "bad"
    enabled: false
    tone: "丁寧"
    max_chars: 1
    active_hours: [9, 22]
""",
        encoding="utf-8",
    )
    groups = load_groups()
    assert [g["id"] for g in groups] == ["ok"]


def test_settings_validate_runtime_rejects_bad_interval(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MIN_INTERVAL_MIN", "30")
    monkeypatch.setenv("MAX_INTERVAL_MIN", "10")
    settings = Settings.load(env_file=tmp_path / ".env")
    with pytest.raises(ValueError):
        settings.validate_runtime(require_external=False)


def test_settings_validate_runtime_rejects_missing_external(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    settings = Settings.load(env_file=tmp_path / ".env")
    with pytest.raises(RuntimeError):
        settings.validate_runtime(require_external=True)
