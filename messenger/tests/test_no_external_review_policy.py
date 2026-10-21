"""Normal Chat only: never invoke paid model APIs or CLI reviewers.

This test never makes a network or subprocess call.
"""
from src import review_pipeline as review


def _forbidden(*args, **kwargs):
    raise AssertionError("External model or CLI invocation prohibited")


def test_codex_provider_must_not_call_cli(monkeypatch):
    monkeypatch.setenv("MESSENGER_REVIEW_PROVIDER", "codex")
    monkeypatch.setattr(review.shutil, "which", _forbidden)
    monkeypatch.setattr(review.subprocess, "run", _forbidden)
    assert review._call_opus("local synthetic draft", api_key="fake-nonsecret") is None


def test_api_provider_must_not_call_api_or_cli(monkeypatch):
    monkeypatch.setenv("MESSENGER_REVIEW_PROVIDER", "anthropic_api_only")
    monkeypatch.setattr(review.shutil, "which", _forbidden)
    monkeypatch.setattr(review.subprocess, "run", _forbidden)
    assert review._call_opus("local synthetic draft", api_key="fake-nonsecret") is None


def test_normal_chat_only_fails_closed(monkeypatch):
    monkeypatch.setenv("MESSENGER_REVIEW_PROVIDER", "normal_chat_only")
    monkeypatch.setattr(review.shutil, "which", _forbidden)
    monkeypatch.setattr(review.subprocess, "run", _forbidden)
    assert review._call_opus("local synthetic draft", api_key="") is None


def test_maintenance_marker_blocks_auto_send_even_when_env_on(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from src import auto_reply
    pause=tmp_path/"send_pause.lock"
    pause.write_text("user restricted send")
    monkeypatch.setattr(auto_reply,"SEND_PAUSE_FILE",pause)
    monkeypatch.setattr(auto_reply,"STATUS",tmp_path/"status.json")
    monkeypatch.setattr(auto_reply,"LEDGER",tmp_path/"ledger.json")
    monkeypatch.setenv("MESSENGER_AUTO_SEND","true")
    result=auto_reply.run_pending(SimpleNamespace(data_dir=tmp_path))
    assert result["status"]=="send_paused_fail_closed"
    assert result["attempted"]==0
    assert not (tmp_path/"ledger.json").exists()
