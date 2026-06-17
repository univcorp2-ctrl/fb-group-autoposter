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


class FakePage:
    def __init__(self, *, dialog_counts, block_markers=()):
        # dialog_counts: sequence returned by locator(composer).count() across
        # polls; reaching 0 means the composer closed (submission accepted).
        self._dialog_counts = list(dialog_counts)
        self._dialog_calls = 0
        self._block_markers = set(block_markers)

    async def wait_for_timeout(self, _ms):
        return None

    def locator(self, _selector):
        idx = min(self._dialog_calls, len(self._dialog_counts) - 1)
        self._dialog_calls += 1
        return _Locator(self._dialog_counts[idx])

    async def query_selector(self, selector):
        return object() if selector in self._block_markers else None


def test_verify_true_when_composer_closes():
    # Composer open for two polls, then closes (count -> 0): submission accepted.
    page = FakePage(dialog_counts=[1, 1, 0])
    assert asyncio.run(verify_post_visible(page, "収益物件のご紹介です。")) is True


def test_verify_false_when_composer_never_closes():
    # Composer stays open every poll: the Post click did not submit.
    page = FakePage(dialog_counts=[1])
    assert asyncio.run(verify_post_visible(page, "本文", attempts=3, interval_ms=0)) is False


def test_verify_false_when_block_marker_present():
    # Composer closed but a posting-block marker is on screen -> not posted.
    from src.selectors import SELECTORS

    page = FakePage(dialog_counts=[0], block_markers={SELECTORS["posting_block_markers"][0]})
    assert asyncio.run(verify_post_visible(page, "本文")) is False


def test_verify_empty_body_is_false():
    page = FakePage(dialog_counts=[0])
    assert asyncio.run(verify_post_visible(page, "   ")) is False
