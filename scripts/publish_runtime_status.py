"""Export SQLite posting history to the public status dashboard."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings
from src.runtime_status import write_runtime_status


def _run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=check,
        timeout=90,
    )


def publish_runtime_status(*, push: bool = False) -> dict:
    settings = Settings.load()
    repo = Path(os.getenv("STATUS_REPO_ROOT", str(ROOT)))
    output = Path(
        os.getenv("RUNTIME_STATUS_WEB_PATH", str(repo / "site" / "data" / "status.json"))
    )
    status = write_runtime_status(settings.db_path, output)
    if not push:
        return status
    relative = output.resolve().relative_to(repo.resolve())
    _run_git(repo, "add", str(relative))
    changed = _run_git(repo, "diff", "--cached", "--quiet", check=False).returncode != 0
    if not changed:
        return status
    _run_git(repo, "commit", "-m", "Update Facebook autoposter runtime status")
    _run_git(repo, "push", "origin", "main")
    return status


if __name__ == "__main__":
    publish_runtime_status(push="--push" in sys.argv)
