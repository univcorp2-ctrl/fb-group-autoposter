from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("reason", "expected_exit", "expected_outcome"),
    [
        ("telegram_disabled", 0, "no_action"),
        ("telegram_polled", 0, "no_action"),
        ("telegram_webhook_owns_callbacks", 0, "no_action"),
        ("telegram_webhook_state_unknown", 20, "preflight_blocked"),
        ("telegram_poll_failed", 0, "no_action"),
    ],
)
def test_listener_main_returns_canonical_exit_for_each_safe_callback_mode(tmp_path, reason, expected_exit, expected_outcome):
    code = f'''
from pathlib import Path
from types import SimpleNamespace
from scripts.approval_listener import main
from src.run_result import RunResultStore

class Approval:
    def poll_once(self):
        self.last_poll_reason = {reason!r}
        return 0

settings = SimpleNamespace(db_path=Path({str(tmp_path / 'jobs.db')!r}))
raise SystemExit(main(settings=settings, approval=Approval(), store=RunResultStore(Path({str(tmp_path / 'results')!r}))))
'''
    completed = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)

    assert completed.returncode == expected_exit
    result = next((tmp_path / "results").glob("*.json"))
    text = result.read_text(encoding="utf-8")
    assert f'"outcome": "{expected_outcome}"' in text
    assert f'"reason": "{reason}"' in text
