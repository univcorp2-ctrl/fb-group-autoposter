import os
import time

import pytest

from src.orchestrator import pipeline_lock


def test_pipeline_lock_recovers_stale_pid(tmp_path, monkeypatch):
    lock_path = tmp_path / "pipeline.lock"
    lock_path.write_text("99999999", encoding="utf-8")
    monkeypatch.setattr("src.orchestrator._pid_is_running", lambda pid: False)

    with pipeline_lock(lock_path):
        assert lock_path.exists()

    assert not lock_path.exists()


def test_pipeline_lock_blocks_live_other_pid(tmp_path, monkeypatch):
    lock_path = tmp_path / "pipeline.lock"
    lock_path.write_text("99999999", encoding="utf-8")
    monkeypatch.setattr("src.orchestrator._pid_is_running", lambda pid: True)

    with pytest.raises(RuntimeError, match="pipeline lock exists"):
        with pipeline_lock(lock_path):
            pass


def test_pipeline_lock_never_reclaims_old_live_owner(tmp_path, monkeypatch):
    lock_path = tmp_path / "pipeline.lock"
    lock_path.write_text("99999999", encoding="utf-8")
    old = time.time() - (9 * 60 * 60)
    os.utime(lock_path, (old, old))
    monkeypatch.setattr("src.orchestrator._pid_is_running", lambda pid: True)

    with pytest.raises(RuntimeError, match="pipeline lock exists"):
        with pipeline_lock(lock_path):
            pass

    assert lock_path.exists()
