from pathlib import Path

from scripts.run_draft_daemon import (
    DEFAULT_INTERVAL_MINUTES,
    MAX_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    _interval_minutes,
    _load_active_drafts,
    _select_focus_draft,
)


def test_interval_defaults_and_clamps(monkeypatch):
    monkeypatch.delenv("MESSENGER_DRAFT_INTERVAL_MINUTES", raising=False)
    assert _interval_minutes() == DEFAULT_INTERVAL_MINUTES
    monkeypatch.setenv("MESSENGER_DRAFT_INTERVAL_MINUTES", "1")
    assert _interval_minutes() == MIN_INTERVAL_MINUTES
    monkeypatch.setenv("MESSENGER_DRAFT_INTERVAL_MINUTES", "999")
    assert _interval_minutes() == MAX_INTERVAL_MINUTES
    monkeypatch.setenv("MESSENGER_DRAFT_INTERVAL_MINUTES", "not-a-number")
    assert _interval_minutes() == DEFAULT_INTERVAL_MINUTES


def test_select_focus_prefers_high_priority():
    rows = [
        {"thread_id": "1", "name": "normal", "url": "u1", "draft": "d1", "priority": "normal"},
        {"thread_id": "2", "name": "high", "url": "u2", "draft": "d2", "priority": "high"},
    ]
    assert _select_focus_draft(rows)["thread_id"] == "2"


def test_select_focus_uses_first_when_no_high_priority():
    rows = [
        {"thread_id": "1", "url": "u1", "draft": "d1"},
        {"thread_id": "2", "url": "u2", "draft": "d2"},
    ]
    assert _select_focus_draft(rows)["thread_id"] == "1"
    assert _select_focus_draft([]) is None


def test_load_active_drafts_filters_incomplete_rows(tmp_path: Path):
    data = tmp_path / "drafts.json"
    data.write_text(
        '{"drafts": ['
        '{"thread_id":"1","url":"u1","draft":"hello"},'
        '{"thread_id":"2","url":"","draft":"missing url"},'
        '{"thread_id":"3","url":"u3","draft":""}'
        ']}',
        encoding="utf-8",
    )
    rows = _load_active_drafts(tmp_path)
    assert [row["thread_id"] for row in rows] == ["1"]
