"""Tests for the posting-reliability hardening:

  - long bodies are not typed char-by-char (which timed out), only a short
    human-feel prefix is typed and the rest is inserted fast;
  - verify_post_visible reloads + scrolls the feed so a freshly published post
    is confirmed instead of being wrongly marked "uncertain".
"""

import asyncio

from src.poster import HUMAN_TYPED_PREFIX_CHARS, FacebookPoster
from src.verifier import verify_post_visible


# --------------------------------------------------------------------------- #
# body splitting
# --------------------------------------------------------------------------- #
def test_split_body_keeps_short_prefix_and_rest():
    body = "あ" * 500
    prefix, rest = FacebookPoster._split_body_for_typing(body)
    assert len(prefix) == HUMAN_TYPED_PREFIX_CHARS
    assert prefix + rest == body
    # The slow char-by-char part is bounded so typing can never hit the timeout.
    assert len(prefix) <= 20


def test_split_body_handles_body_shorter_than_prefix():
    body = "短い"
    prefix, rest = FacebookPoster._split_body_for_typing(body)
    assert prefix == body
    assert rest == ""


# --------------------------------------------------------------------------- #
# verification with a fake page
# --------------------------------------------------------------------------- #
class _Locator:
    def __init__(self, count_value):
        self._count = count_value

    async def count(self):
        return self._count


class _Mouse:
    async def wheel(self, _x, _y):
        return None


class FakePage:
    def __init__(self, *, html_sequence, dialog_counts=(0,)):
        self._html_sequence = list(html_sequence)
        self._content_calls = 0
        self._dialog_counts = list(dialog_counts)
        self._dialog_calls = 0
        self.mouse = _Mouse()
        self.reloads = 0

    async def wait_for_timeout(self, _ms):
        return None

    def locator(self, _selector):
        idx = min(self._dialog_calls, len(self._dialog_counts) - 1)
        self._dialog_calls += 1
        return _Locator(self._dialog_counts[idx])

    async def content(self):
        idx = min(self._content_calls, len(self._html_sequence) - 1)
        self._content_calls += 1
        return self._html_sequence[idx]

    async def reload(self, **_kwargs):
        self.reloads += 1


def test_verify_confirms_post_after_reload():
    body = "こんにちは。収益物件のご紹介です。"
    page = FakePage(
        html_sequence=["<div>関係ないフィード</div>", f"<div>{body}</div>"],
        dialog_counts=[0],
    )
    ok = asyncio.run(verify_post_visible(page, body))
    assert ok is True
    assert page.reloads >= 1  # it reloaded to surface the lazy-loaded post


def test_verify_returns_false_when_post_never_appears():
    body = "確認できない本文テキスト"
    page = FakePage(html_sequence=["<div>無関係</div>"], dialog_counts=[0])
    ok = asyncio.run(verify_post_visible(page, body))
    assert ok is False


def test_verify_confirms_immediately_without_reload():
    body = "すぐ見つかる本文です"
    page = FakePage(html_sequence=[f"<article>{body}</article>"], dialog_counts=[0])
    ok = asyncio.run(verify_post_visible(page, body))
    assert ok is True
    assert page.reloads == 0


def test_verify_empty_body_is_false():
    page = FakePage(html_sequence=["<div></div>"], dialog_counts=[0])
    assert asyncio.run(verify_post_visible(page, "   ")) is False
