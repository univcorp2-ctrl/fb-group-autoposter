"""Tests for inbox row parsing (pure functions, no browser)."""

from src.scraper import _is_group, _parse_row


def test_parse_one_to_one_row():
    row = {"id": "111", "aria": "", "imgCount": 1,
           "spans": ["Seiya Aizaki", "中古物件ありますか？", "·", "2時間"]}
    t = _parse_row(row)
    assert t["thread_id"] == "111"
    assert t["name"] == "Seiya Aizaki"
    assert t["preview"] == "中古物件ありますか？"
    assert t["is_group"] is False
    assert t["participant_count"] == 1
    assert t["url"].endswith("/t/111")


def test_parse_group_row_by_aria():
    row = {"id": "222", "aria": "グループチャット: CGS見杉小委員会さん", "imgCount": 2,
           "spans": ["CGS見杉小委員会", "佐藤 大悟: パーティプランしてます", "·", "7分"]}
    t = _parse_row(row)
    assert t["is_group"] is True
    assert t["participant_count"] == 2


def test_is_group_by_avatar_count():
    assert _is_group("", 2) is True
    assert _is_group("", 1) is False


def test_is_group_by_aria_prefix_case_insensitive():
    assert _is_group("Group chat: Foo", 1) is True
    assert _is_group("グループチャット: 何か", 1) is True


def test_parse_row_missing_spans_is_safe():
    t = _parse_row({"id": "333", "aria": "", "imgCount": 1, "spans": []})
    assert t["name"] == "(名称不明)"
    assert t["preview"] == ""
