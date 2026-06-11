import asyncio

from src.session import is_logged_in, login_required_message
from src.verifier import dry_run_screenshot_path


class FakePage:
    def __init__(self, url="https://www.facebook.com/", selectors=None):
        self.url = url
        self.selectors = set(selectors or [])

    async def query_selector(self, selector):
        return object() if selector in self.selectors else None


def test_is_logged_in_false_on_login_url():
    page = FakePage(url="https://www.facebook.com/login")
    assert asyncio.run(is_logged_in(page)) is False


def test_is_logged_in_true_with_marker():
    page = FakePage(selectors=['div[role="navigation"]'])
    assert asyncio.run(is_logged_in(page)) is True


def test_login_required_message_mentions_login_once():
    assert "login_once.py" in login_required_message()


def test_dry_run_screenshot_path_writes_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = dry_run_screenshot_path("job", "group")
    assert path.endswith(".txt")
    assert "DRY_RUN" in (tmp_path / path).read_text(encoding="utf-8")
