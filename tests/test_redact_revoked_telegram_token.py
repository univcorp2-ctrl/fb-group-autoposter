from __future__ import annotations

import io
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


TOKEN = "123456:ABCdef-ghI_jklMNopQRstuVWXyz"


def test_redacts_exact_token_and_telegram_url_token_atomically(tmp_path):
    from scripts.redact_revoked_telegram_token import redact_paths

    path = tmp_path / "logs" / "worker.log"
    path.parent.mkdir()
    path.write_text(f"token={TOKEN}\nhttps://api.telegram.org/bot{TOKEN}/getUpdates\n", encoding="utf-8")

    report = redact_paths(tmp_path, ["logs/worker.log"], token_stream=io.StringIO(TOKEN + "\n"))

    assert report == [("logs/worker.log", 2)]
    text = path.read_text(encoding="utf-8")
    assert TOKEN not in text
    assert text.count("[REDACTED_TELEGRAM_TOKEN]") == 2


@pytest.mark.parametrize("path", ["../outside.log", ".env", "data/jobs.db", "src/approval.py"])
def test_refuses_unsafe_or_source_paths(tmp_path, path):
    from scripts.redact_revoked_telegram_token import redact_paths

    (tmp_path / ".env").write_text(TOKEN, encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "approval.py").write_text(TOKEN, encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "jobs.db").write_text(TOKEN, encoding="utf-8")

    with pytest.raises(ValueError):
        redact_paths(tmp_path, [path], token_stream=io.StringIO(TOKEN + "\n"))


def test_refuses_empty_token_without_writing(tmp_path):
    from scripts.redact_revoked_telegram_token import redact_paths

    path = tmp_path / "logs" / "worker.log"
    path.parent.mkdir()
    path.write_text(TOKEN, encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        redact_paths(tmp_path, ["logs/worker.log"], token_stream=io.StringIO("\n"))
    assert path.read_text(encoding="utf-8") == TOKEN


def test_refuses_disallowed_extension_and_reparse_component(tmp_path, monkeypatch):
    from scripts import redact_revoked_telegram_token as redactor

    path = tmp_path / "logs" / "worker.csv"
    path.parent.mkdir()
    path.write_text(TOKEN, encoding="utf-8")
    with pytest.raises(ValueError, match="extension"):
        redactor.redact_paths(tmp_path, ["logs/worker.csv"], token_stream=io.StringIO(TOKEN + "\n"))

    log_path = tmp_path / "logs" / "worker.log"
    log_path.write_text(TOKEN, encoding="utf-8")
    original_lstat = os.lstat

    def reparse_logs(path):
        stat = original_lstat(path)
        if Path(path) == tmp_path / "logs":
            return SimpleNamespace(st_file_attributes=0x400)
        return stat

    monkeypatch.setattr(redactor.os, "lstat", reparse_logs)
    with pytest.raises(ValueError, match="reparse"):
        redactor.redact_paths(tmp_path, ["logs/worker.log"], token_stream=io.StringIO(TOKEN + "\n"))


def test_refuses_symlink_even_when_target_stays_in_logs(tmp_path):
    from scripts.redact_revoked_telegram_token import redact_paths

    logs = tmp_path / "logs"
    logs.mkdir()
    target = logs / "actual.log"
    target.write_text(TOKEN, encoding="utf-8")
    link = logs / "linked.log"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(ValueError, match="reparse"):
        redact_paths(tmp_path, ["logs/linked.log"], token_stream=io.StringIO(TOKEN + "\n"))
    assert target.read_text(encoding="utf-8") == TOKEN
