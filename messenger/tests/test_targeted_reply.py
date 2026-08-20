from __future__ import annotations

import pytest

from src.targeted_reply import (
    message_fingerprint,
    normalize_text,
    sanitize_draft,
    select_exact_draft,
)


def test_sanitize_draft_removes_internal_review_note() -> None:
    draft = "本文です。\n\n（※この返信は下書きです。送信前に内容をご確認ください）"

    assert sanitize_draft(draft) == "本文です。"


def test_normalize_text_collapses_whitespace() -> None:
    assert normalize_text(" a\n\t b  c ") == "a b c"


def test_select_exact_draft_requires_name_and_thread() -> None:
    payload = {
        "drafts": [
            {"name": "松井宏貴", "thread_id": "1", "draft": "a"},
            {"name": "松井宏貴", "thread_id": "2", "draft": "b"},
        ]
    }

    assert select_exact_draft(
        payload, target_name="松井宏貴", thread_id="2"
    )["draft"] == "b"


@pytest.mark.parametrize(
    "payload",
    [
        {"drafts": []},
        {"drafts": [{"name": "別人", "thread_id": "1"}]},
        {"drafts": [{"name": "松井宏貴", "thread_id": "1"}] * 2},
    ],
)
def test_select_exact_draft_rejects_missing_or_ambiguous(payload: dict) -> None:
    with pytest.raises(ValueError):
        select_exact_draft(payload, target_name="松井宏貴", thread_id="1")


def test_message_fingerprint_is_stable_sha256() -> None:
    value = "返信本文"

    assert message_fingerprint(value) == message_fingerprint(value)
    assert len(message_fingerprint(value)) == 64
