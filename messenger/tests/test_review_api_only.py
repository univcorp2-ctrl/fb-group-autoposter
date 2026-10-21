"""Regression: API-only Messenger review never invokes a local CLI."""
from types import SimpleNamespace
import sys
from src import review_pipeline as reviews


def _forbid_cli(*_args, **_kwargs):
    raise AssertionError("A CLI must not run in API-only review mode")


def test_api_only_without_api_key_fails_closed(monkeypatch):
    monkeypatch.setenv("MESSENGER_REVIEW_PROVIDER", "anthropic_api_only")
    monkeypatch.setattr(reviews.shutil, "which", _forbid_cli)
    monkeypatch.setattr(reviews.subprocess, "run", _forbid_cli)
    assert reviews._call_opus("safe test prompt", api_key="") is None


def test_api_only_api_error_does_not_fall_back_to_cli(monkeypatch):
    class DummyMessages:
        def create(self, **_kwargs):
            raise RuntimeError("simulated API failure")

    class DummyClient:
        def __init__(self, **_kwargs):
            self.messages = DummyMessages()

    monkeypatch.setenv("MESSENGER_REVIEW_PROVIDER", "api_only")
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=DummyClient))
    monkeypatch.setattr(reviews.shutil, "which", _forbid_cli)
    monkeypatch.setattr(reviews.subprocess, "run", _forbid_cli)
    assert reviews._call_opus("safe test prompt", api_key="fake-test-key") is None
