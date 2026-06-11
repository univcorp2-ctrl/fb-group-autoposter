import asyncio
from pathlib import Path

from config import Settings
from src.orchestrator import run_cycle


def test_dry_run_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("groups.yaml").write_text(
        """
groups:
  - id: "g1"
    name: "Test Group"
    post_url: "https://www.facebook.com/groups/g1/"
    enabled: true
    tone: "丁寧"
    max_chars: 1000
    active_hours: [0, 24]
    allow_links: true
    allow_images: true
    signature: "署名"
    forbidden: ["保証"]
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "jobs.db"))
    monkeypatch.setenv("INBOX_DIR", str(tmp_path / "data" / "inbox"))
    monkeypatch.setenv("PROFILE_DIR", str(tmp_path / "profiles" / "main"))
    settings = Settings.load(env_file=tmp_path / ".env")
    summary = asyncio.run(run_cycle(settings, selftest=True))
    assert summary["created"] == 1
    assert summary["approved_processed"] == 1
    assert summary["statuses"][0]["status"] == "done"
