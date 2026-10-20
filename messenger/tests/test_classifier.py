"""Only reply to positively verified 1:1 Messenger threads."""
from src.classifier import classify_thread, select_threads_needing_reply
from src.scraper import _parse_row

def verified(**extra):
    return {"name":"山田太郎","preview":"物件について質問です","is_unread":True,
            "is_group":False,"one_to_one_verified":True,"participant_count":1,**extra}

def test_inbound_high():
    x=classify_thread(verified());assert x.needs_reply and x.priority=="high"

def test_inbound_read():
    assert classify_thread(verified(is_unread=False)).priority=="normal"

def test_unverified_fails_closed():
    assert classify_thread({"name":"Unknown","preview":"質問"}).reason=="ambiguous_thread_type"
    assert not classify_thread(verified(one_to_one_verified=False)).needs_reply

def test_skip_self():
    assert classify_thread(verified(preview="あなた: 返答")).reason=="already_replied"
    assert not classify_thread(verified(last_from_me=True)).needs_reply

def test_skip_group():
    assert classify_thread(verified(is_group=True)).reason=="group_thread"
    assert classify_thread(verified(participant_count=3)).reason=="group_thread"

def test_skip_automation():
    assert classify_thread(verified(name="Facebook")).reason=="automated_thread"

def test_skip_system_and_blank():
    assert classify_thread(verified(preview="エンドツーエンド暗号化")).reason=="no_message"
    assert classify_thread(verified(preview="")).reason=="empty_preview_no_draft"

def test_skip_ack_not_question():
    assert classify_thread(verified(preview="承知いたしました。")).reason=="closing_ack"
    assert classify_thread(verified(preview="承知しました。価格はいくらですか？")).needs_reply

def test_priority():
    rows=[verified(name="A",is_unread=False),verified(name="B"),verified(name="C",is_group=True)]
    assert [v["name"] for v in select_threads_needing_reply(rows)]==["B","A"]

def test_inbox_positive_signal():
    dm=_parse_row({"id":"12345","spans":["山田","物件に興味あり","1分"],"imgCount":1,"aria":""})
    assert dm["one_to_one_verified"] and dm["participant_count"]==1
    group=_parse_row({"id":"8888","spans":["グループ","やあ","1分"],"imgCount":2,"aria":"グループチャット"})
    assert group["is_group"] and not group["one_to_one_verified"]
    ambiguous=_parse_row({"id":"abc","spans":["不明","やあ","1分"],"imgCount":0,"aria":""})
    assert not ambiguous["one_to_one_verified"] and ambiguous["participant_count"] is None
