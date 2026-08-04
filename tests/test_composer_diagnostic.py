"""Synthetic, read-only coverage for the group-composer diagnostic."""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import sys

from src.composer_diagnostic import diagnose_composer


FIXTURES = Path(__file__).parent / "fixtures" / "facebook"


class _Locator:
    def __init__(self, count: int, *, visible: bool = True):
        self._count = count
        self._visible = visible

    @property
    def first(self):
        return self

    def nth(self, _index):
        return self

    async def count(self):
        return self._count

    async def is_visible(self):
        return self._visible


class _ReadOnlyPage:
    def __init__(self, html: str, *, url: str = "https://www.facebook.com/groups/example/"):
        self.html = html
        self.url = url
        self.writes: list[str] = []

    def locator(self, selector):
        if "投稿を作成" in selector and "投稿を作成" in self.html:
            return _Locator(1)
        return _Locator(0)

    async def content(self):
        return self.html

    def __getattr__(self, name):
        if name in {"click", "mouse", "keyboard", "goto", "screenshot", "set_input_files"}:
            raise AssertionError(f"diagnostic must not use {name}")
        raise AttributeError(name)


def test_ready_fixture_reports_only_sanitized_read_only_result():
    page = _ReadOnlyPage((FIXTURES / "group_feed_composer.html").read_text(encoding="utf-8"))

    result = asyncio.run(diagnose_composer(page))

    assert result["reason"] == "composer_ready"
    assert result["write_performed"] is False
    assert "html" not in result
    assert "cookie" not in repr(result).lower()


def test_missing_composer_stops_before_write():
    page = _ReadOnlyPage((FIXTURES / "group_feed_no_composer.html").read_text(encoding="utf-8"))

    result = asyncio.run(diagnose_composer(page))

    assert result["reason"] == "selector_missing"
    assert result["write_performed"] is False


def test_login_and_checkpoint_urls_have_stable_reasons():
    login = asyncio.run(diagnose_composer(_ReadOnlyPage("", url="https://www.facebook.com/login/")))
    checkpoint = asyncio.run(diagnose_composer(_ReadOnlyPage("", url="https://www.facebook.com/checkpoint/")))

    assert login["reason"] == "login_required"
    assert checkpoint["reason"] == "checkpoint_required"


def test_messenger_competitor_is_never_a_group_composer():
    page = _ReadOnlyPage(
        (FIXTURES / "group_feed_messenger_competitor.html").read_text(encoding="utf-8"),
        url="https://www.facebook.com/messages/t/123",
    )

    result = asyncio.run(diagnose_composer(page))

    assert result["reason"] == "selector_missing"


def test_diagnostic_script_runs_directly_from_repo_root_without_opening_browser():
    root = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [sys.executable, "scripts/diagnose_composer.py", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
