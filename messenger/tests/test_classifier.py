"""Tests for the needs-reply classifier."""

from src.classifier import classify_thread, select_threads_needing_reply


def test_inbound_1to1_unread_needs_high_priority_reply():
    thread = {"name": "山田太郎", "preview": "物件について質問です", "is_unread": True}
    classification = classify_thread(thread)
    assert classification.needs_reply is True
    assert classification.priority == "high"
    assert classification.reason == "inbound_1to1"


def test_inbound_1to1_read_needs_normal_priority_reply():
    thread = {"name": "佐藤花子", "preview": "ありがとうございます", "is_unread": False}
    classification = classify_thread(thread)
    assert classification.needs_reply is True
    assert classification.priority == "normal"


def test_skip_when_i_replied_last_via_preview_prefix():
    thread = {"name": "山田太郎", "preview": "あなた: 承知しました", "is_unread": False}
    classification = classify_thread(thread)
    assert classification.needs_reply is False
    assert classification.reason == "already_replied"


def test_skip_when_last_from_me_flag_set():
    thread = {"name": "山田太郎", "preview": "詳細はこちら", "last_from_me": True}
    assert classify_thread(thread).needs_reply is False


def test_skip_group_thread_by_flag():
    thread = {"name": "投資仲間グループ", "preview": "みなさんこんにちは", "is_group": True}
    assert classify_thread(thread).needs_reply is False


def test_skip_group_thread_by_participant_count():
    thread = {"name": "三人会話", "preview": "やあ", "participant_count": 3}
    classification = classify_thread(thread)
    assert classification.needs_reply is False
    assert classification.reason == "group_thread"


def test_skip_automated_thread():
    thread = {"name": "Facebook", "preview": "セキュリティ通知", "is_unread": True}
    classification = classify_thread(thread)
    assert classification.needs_reply is False
    assert classification.reason == "automated_thread"


def test_e2e_banner_preview_is_no_message():
    thread = {
        "name": "Seiya Aizaki",
        "preview": "メッセージと通話はエンドツーエンド暗号化で保護されています。",
        "is_group": False,
    }
    classification = classify_thread(thread)
    assert classification.needs_reply is False
    assert classification.reason == "no_message"


def test_system_event_preview_is_no_message():
    thread = {
        "name": "誰か",
        "preview": "Masayuki Watariさんが山崎 真さんをグループに追加しました。",
    }
    assert classify_thread(thread).reason in ("no_message", "group_thread")


def test_real_inbound_message_still_needs_reply():
    thread = {"name": "田中", "preview": "築古アパートを探しています", "is_unread": True}
    classification = classify_thread(thread)
    assert classification.needs_reply is True
    assert classification.reason == "inbound_1to1"


def test_empty_preview_flagged_for_review():
    thread = {"name": "新規の人", "preview": "", "is_unread": True}
    classification = classify_thread(thread)
    assert classification.needs_reply is True
    assert classification.reason == "needs_review_empty_preview"


def test_select_sorts_high_priority_first():
    threads = [
        {"name": "A", "preview": "後で見た既読", "is_unread": False},
        {"name": "B", "preview": "未読の新着", "is_unread": True},
        {"name": "自分グループ", "preview": "x", "is_group": True},
    ]
    selected = select_threads_needing_reply(threads)
    assert [thread["name"] for thread in selected] == ["B", "A"]
    assert all("classification" in thread for thread in selected)


def test_short_closing_ack_does_not_need_reply():
    thread = {"name": "作野 衣久江", "preview": "承知いたしました。", "is_unread": False}
    classification = classify_thread(thread)
    assert classification.needs_reply is False
    assert classification.reason == "closing_ack"


def test_ack_with_followup_question_still_needs_reply():
    thread = {
        "name": "作野 衣久江",
        "preview": "承知しました。価格はいくらですか？",
        "is_unread": True,
    }
    classification = classify_thread(thread)
    assert classification.needs_reply is True
    assert classification.reason == "inbound_1to1"
