import pytest
from src.direct_thread_guard import direct_thread_evidence

def row(**kw):
    d={"name":"山田さん","is_group":False,"one_to_one_verified":True,"participant_count":1}
    d.update(kw)
    return d

def proof(**kw):
    d={"title":"スレッド: 山田さん","labels":["山田さんとのスレッドのメッセージ","送信"]}
    d.update(kw)
    return d

def test_exact_dm_passes():
    assert direct_thread_evidence(proof(),"山田さん",row())

@pytest.mark.parametrize("bad_row",[
    {"is_group":True},{"one_to_one_verified":False},
    {"participant_count":2},{"participant_count":None},{"participant_count":True},
    {"name":"別の人"}])
def test_ambiguous_or_group_inbox_never_sends(bad_row):
    assert not direct_thread_evidence(proof(),"山田さん",row(**bad_row))

def test_group_marker_blocks_even_if_avatar_single():
    assert not direct_thread_evidence(proof(labels=[
        "山田さんとのスレッドのメッセージ","グループチャット: 4人"
    ]),"山田さん",row())
    assert not direct_thread_evidence(proof(title="スレッド: グループ投資家"),"山田さん",row())
    assert not direct_thread_evidence(proof(labels=["山田さんとのスレッドのメッセージ",
        "Group members"]), "山田さん", row())

def test_positive_header_required():
    assert not direct_thread_evidence(proof(labels=["送信"]), "山田さん", row())
    assert not direct_thread_evidence(proof(title=""), "山田さん", row())
