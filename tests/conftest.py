"""Never let synthetic test runs write production usage telemetry."""
import pytest


@pytest.fixture(autouse=True)
def private_usage_directory(monkeypatch, tmp_path):
    monkeypatch.setenv('AI_TASK_USAGE_DIR', str(tmp_path / 'usage'))
