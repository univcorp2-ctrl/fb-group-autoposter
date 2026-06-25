"""Unit tests for build_notion_properties (pure function — no network)."""

from scripts.sync_notion_engagement import (
    PROP_COMMENTS,
    PROP_DATE,
    PROP_GROUP,
    PROP_PERMALINK,
    PROP_PROPERTY_ID,
    PROP_REACTIONS,
    PROP_SCORE,
    PROP_SHARES,
    PROP_TITLE,
    build_notion_properties,
)

SAMPLE_POST = {
    "property_id": "eb-10901",
    "group_id": "792499964217824",
    "group": "不動産投資 物件情報シェア",
    "permalink": "https://www.facebook.com/groups/792499964217824/posts/3866805296787260",
    "reactions": 4,
    "comments": 2,
    "shares": 1,
    "score": 11,
}
DATE_JST = "2026-06-25"
CHECKED_AT = "2026-06-25T02:44:41.358869+00:00"


def _props():
    return build_notion_properties(SAMPLE_POST, DATE_JST, CHECKED_AT)


def test_title_combines_property_id_and_group():
    props = _props()
    title = props[PROP_TITLE]["title"]
    assert title[0]["text"]["content"] == "eb-10901 / 不動産投資 物件情報シェア"


def test_date_is_date_property_with_given_value():
    props = _props()
    assert props[PROP_DATE] == {"date": {"start": DATE_JST}}


def test_number_properties_carry_right_ints():
    props = _props()
    assert props[PROP_REACTIONS] == {"number": 4}
    assert props[PROP_COMMENTS] == {"number": 2}
    assert props[PROP_SHARES] == {"number": 1}
    assert props[PROP_SCORE] == {"number": 11}
    assert isinstance(props[PROP_REACTIONS]["number"], int)
    assert isinstance(props[PROP_SCORE]["number"], int)


def test_permalink_is_url_property():
    props = _props()
    assert props[PROP_PERMALINK] == {"url": SAMPLE_POST["permalink"]}


def test_rich_text_property_ids_and_group():
    props = _props()
    assert props[PROP_PROPERTY_ID]["rich_text"][0]["text"]["content"] == "eb-10901"
    assert props[PROP_GROUP]["rich_text"][0]["text"]["content"] == "不動産投資 物件情報シェア"


def test_missing_numbers_default_to_zero():
    props = build_notion_properties(
        {"property_id": "eb-1", "group": "g"}, DATE_JST, CHECKED_AT
    )
    assert props[PROP_REACTIONS] == {"number": 0}
    assert props[PROP_PERMALINK] == {"url": None}
