import asyncio

import pytest

from src.selectors import SELECTORS, SelectorAmbiguous, SelectorMissing, exactly_one_visible


def test_selector_groups_not_empty():
    required = ["logged_in_markers", "open_composer", "composer_textbox", "post_button", "file_input"]
    for key in required:
        assert key in SELECTORS
        assert len(SELECTORS[key]) >= 2


class _Locator:
    def __init__(self, matches):
        self.matches = matches

    def nth(self, index):
        return _Match(self.matches[index])

    async def count(self):
        return len(self.matches)


class _Match:
    def __init__(self, visible):
        self.visible = visible

    async def is_visible(self):
        return self.visible


class _Page:
    def __init__(self, matches): self.matches = matches
    def locator(self, selector):
        return _Locator([item for part in selector.split(", ") for item in self.matches.get(part, [])])


def test_exactly_one_visible_accepts_hidden_duplicates():
    selector = SELECTORS["open_composer"][0]
    page = _Page({selector: [False, True]})

    locator = asyncio.run(exactly_one_visible(page, "open_composer"))

    assert isinstance(locator, _Match)


def test_exactly_one_visible_rejects_multiple_visible_candidates():
    selector = SELECTORS["open_composer"][0]
    page = _Page({selector: [True, True]})

    with pytest.raises(SelectorAmbiguous):
        asyncio.run(exactly_one_visible(page, "open_composer"))


def test_exactly_one_visible_rejects_zero_visible_candidates():
    page = _Page({})

    with pytest.raises(SelectorMissing):
        asyncio.run(exactly_one_visible(page, "open_composer"))


def test_composer_textbox_selectors_never_match_feed_comment_boxes():
    """A write boundary must stay inside the create-post dialog.

    Facebook group feeds expose visible contenteditable comment boxes.  A
    page-wide textbox selector makes those indistinguishable from the post
    composer and turns a valid composer into an ambiguous write target.
    """
    assert 'div[role="textbox"][contenteditable="true"]' not in SELECTORS["composer_textbox"]
