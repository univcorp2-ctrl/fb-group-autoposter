"""Tests for the needs-reply classifier."""

from src.classifier import classify_thread, select_threads_needing_reply


def test_inbound_1to1_unread_needs_high_priority_reply():
    t = {"name": "山田太郎", "preview": "物件について質問です", "is_unread": True}
    c = classify_thread(t)
    assert c.needs_reply is True
    assert c.priority == "high"
    assert c.reason == "inbound_1to1"


def test_inbound_1to1_read_needs_normal_priority_reply():
    t = {"name": "佐藤花子", "preview": "ありがとうございます", "is_unread": False}
    c = classify_thread(t)
    assert c.needs_reply is True
    assert c.priority == "normal"


def test_skip_when_i_replied_last_via_preview_prefix():
    t = {"name": "山田太郎", "preview": "あなた: 承知しました", "is_unread": False}
    c = classify_thread(t)
    assert c.needs_reply is False
    assert c.reason == "already_replied"


def test_skip_when_last_from_me_flag_set():
    t = {"name": "山田太郎", "preview": "詳細はこちら", "last_from_me": True}
    assert classify_thread(t).needs_reply is False


def test_skip_group_thread_by_flag():
    t = {"name": "投資仲間グループ", "preview": "みなさんこんにちは", "is_group": True}
    assert classify_thread(t).needs_reply is False


def test_skip_group_thread_by_participant_count():
    t = {"name": "三人会話", "preview": "やあ", "participant_count": 3}
    c = classify_thread(t)
    assert c.needs_reply is False
    assert c.reason == "group_thread"


def test_skip_automated_thread():
    t = {"name": "Facebook", "preview": "セキュリティ通知", "is_unread": True}
    c = classify_thread(t)
    assert c.needs_reply is False
    assert c.reason == "automated_thread"


def test_e2e_banner_preview_is_no_message():
    """A 1:1 thread whose only preview is the encryption banner has nothing to
    reply to — it must NOT be flagged."""
    t = {"name": "Seiya Aizaki",
         "preview": "メッセージと通話はエンドツーエンド暗号化で保護されています。",
         "is_group": False}
    c = classify_thread(t)
    assert c.needs_reply is False
    assert c.reason == "no_message"


def test_system_event_preview_is_no_message():
    t = {"name": "誰か", "preview": "Masayuki Watariさんが山崎 真さんをグループに追加しました。"}
    assert classify_thread(t).reason in ("no_message", "group_thread")


def test_real_inbound_message_still_needs_reply():
    t = {"name": "田中", "preview": "築古アパートを探しています", "is_unread": True}
    c = classify_thread(t)
    assert c.needs_reply is True
    assert c.reason == "inbound_1to1"


def test_empty_preview_flagged_for_review():
    t = {"name": "新規の人", "preview": "", "is_unread": True}
    c = classify_thread(t)
    assert c.needs_reply is True
    assert c.reason == "needs_review_empty_preview"


def test_select_sorts_high_priority_first():
    threads = [
        {"name": "A", "preview": "後で見た既読", "is_unread": False},
        {"name": "B", "preview": "未読の新着", "is_unread": True},
        {"name": "自分グループ", "preview": "x", "is_group": True},
    ]
    selected = select_threads_needing_reply(threads)
    assert [t["name"] for t in selected] == ["B", "A"]
    assert all("classification" in t for t in selected)
