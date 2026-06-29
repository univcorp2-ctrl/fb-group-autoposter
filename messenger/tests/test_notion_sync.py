"""Tests for the Notion property mapping (pure, no network)."""

from src.notion_sync import (
    PROP_DRAFT,
    PROP_PRIORITY,
    PROP_STATUS,
    PROP_THREAD_ID,
    PROP_TITLE,
    PROP_URL,
    build_properties,
)


def _row():
    return {
        "thread_id": "1234567890",
        "url": "https://www.messenger.com/t/1234567890",
        "name": "山田太郎",
        "last_message": "物件について教えてください",
        "draft": "山田太郎さん、ありがとうございます。",
        "priority": "high",
    }


def test_build_properties_maps_core_fields():
    props = build_properties(_row(), "2026-06-29 10:00 JST")
    assert props[PROP_TITLE]["title"][0]["text"]["content"] == "山田太郎"
    assert props[PROP_THREAD_ID]["rich_text"][0]["text"]["content"] == "1234567890"
    assert props[PROP_URL]["url"].endswith("1234567890")
    assert props[PROP_STATUS]["select"]["name"] == "要返信"


def test_priority_label_translation():
    assert build_properties(_row(), "x")[PROP_PRIORITY]["select"]["name"] == "高"
    row = {**_row(), "priority": "normal"}
    assert build_properties(row, "x")[PROP_PRIORITY]["select"]["name"] == "中"


def test_draft_text_truncated_to_notion_limit():
    row = {**_row(), "draft": "あ" * 5000}
    content = build_properties(row, "x")[PROP_DRAFT]["rich_text"][0]["text"]["content"]
    assert len(content) <= 1900


def test_missing_url_becomes_none():
    row = {**_row(), "url": ""}
    assert build_properties(row, "x")[PROP_URL]["url"] is None
