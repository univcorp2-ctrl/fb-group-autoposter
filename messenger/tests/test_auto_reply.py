from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import json

from src import auto_reply


def candidate(**other):
    return {"thread_id":"123456789", "name":"物件問い合わせ", "url":"https://www.messenger.com/t/123456789",
            "one_to_one_verified":True, "participant_count":1,"is_group":False,
            "last_message":"この物件の資料をください","time_text":"2分前", **other}


def test_eligible_only_recent_direct_property():
    assert auto_reply.eligible_message(candidate())
    assert not auto_reply.eligible_message(candidate(is_group=True))
    assert not auto_reply.eligible_message(candidate(one_to_one_verified=False))
    assert not auto_reply.eligible_message(candidate(time_text="昨日"))
    assert not auto_reply.eligible_message(candidate(last_message="了解しました"))


def test_initial_arm_never_sends_history(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_reply,"LEDGER",tmp_path/"ledger.json")
    monkeypatch.setattr(auto_reply,"STATUS",tmp_path/"status.json")
    monkeypatch.setattr(auto_reply,"DRIVE_STATUS",tmp_path/"drive.json")
    monkeypatch.setattr(auto_reply,"BASELINE_INBOX",tmp_path/"baseline.json")
    (tmp_path/"baseline.json").write_text('{"previews":{}}',encoding="utf-8")
    monkeypatch.setenv("MESSENGER_AUTO_SEND","true")
    from unittest.mock import Mock
    runner=Mock(side_effect=AssertionError("historical send forbidden"))
    monkeypatch.setattr(auto_reply.subprocess,"run",runner)
    s=SimpleNamespace(data_dir=tmp_path)
    out=auto_reply.run_pending(s)
    assert out["status"]=="baseline_saved_no_historical_send"
    assert runner.call_count==0
    (tmp_path/"drafts.json").write_text(json.dumps({"drafts":[candidate()]},ensure_ascii=False),encoding="utf-8")
    (tmp_path/"drafts_archive.jsonl").write_text(json.dumps({"checked_at":"2020-01-01 01:00 JST",**candidate()},ensure_ascii=False),encoding="utf-8")
    out=auto_reply.run_pending(s)
    assert out["attempted"]==0 and runner.call_count==0


def test_fresh_inbound_send_at_most_once(tmp_path,monkeypatch):
    monkeypatch.setattr(auto_reply,"LEDGER",tmp_path/"ledger.json")
    monkeypatch.setattr(auto_reply,"STATUS",tmp_path/"status.json")
    monkeypatch.setattr(auto_reply,"DRIVE_STATUS",tmp_path/"drive.json")
    monkeypatch.setattr(auto_reply,"BASELINE_INBOX",tmp_path/"baseline.json")
    (tmp_path/"baseline.json").write_text('{"previews":{}}',encoding="utf-8")
    monkeypatch.setenv("MESSENGER_AUTO_SEND","true")
    s=SimpleNamespace(data_dir=tmp_path)
    _=auto_reply.run_pending(s)
    # The archive timestamp is a minute later than the arming baseline.
    t=(datetime.now(auto_reply.JST)+timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M JST")
    import hashlib
    proof=hashlib.sha256(("物件問い合わせ"+"\0"+"この物件の資料をください").encode("utf-8")).hexdigest()
    row=candidate(review_status="approved",review_model="claude-opus-4-6",
                  review_message_sha256=proof,
                  draft="お問い合わせの物件について資料を確認し、改めてご案内いたします。")
    (tmp_path/"drafts.json").write_text(json.dumps({"drafts":[row]},ensure_ascii=False),encoding="utf-8")
    (tmp_path/"drafts_archive.jsonl").write_text(json.dumps({"checked_at":t,**row},ensure_ascii=False),encoding="utf-8")
    class Done: returncode=0;stdout='{"ok":true,"sent":true}\n';stderr=''
    calls=[]
    def send(argv,**kwargs):
        calls.append(argv)
        assert "--send" in argv and "123456789" in argv
        return Done()
    monkeypatch.setattr(auto_reply.subprocess,"run",send)
    assert auto_reply.run_pending(s)["confirmed"]==1
    assert auto_reply.run_pending(s)["attempted"]==0
    assert len(calls)==1


def test_inbox_snapshot_blocks_preexisting_message(tmp_path, monkeypatch):
    import hashlib
    from unittest.mock import Mock
    monkeypatch.setattr(auto_reply,"LEDGER",tmp_path/"ledger.json")
    monkeypatch.setattr(auto_reply,"STATUS",tmp_path/"status.json")
    monkeypatch.setattr(auto_reply,"DRIVE_STATUS",tmp_path/"drive.json")
    monkeypatch.setattr(auto_reply,"BASELINE_INBOX",tmp_path/"baseline.json")
    monkeypatch.setenv("MESSENGER_AUTO_SEND","true")
    s=SimpleNamespace(data_dir=tmp_path)
    assert auto_reply.run_pending(s)["attempted"]==0
    inbound="この物件の資料をください"
    snapshot=hashlib.sha256(inbound.encode("utf-8")).hexdigest()
    (tmp_path/"baseline.json").write_text(
        json.dumps({"previews":{"123456789":snapshot}},ensure_ascii=False),encoding="utf-8"
    )
    approval=hashlib.sha256(("物件問い合わせ"+"\0"+inbound).encode("utf-8")).hexdigest()
    row=candidate(review_status="approved",review_model="gpt-5.6-terra/high",
                  review_message_sha256=approval, draft="資料の共有条件を確認してご案内いたします。")
    (tmp_path/"drafts.json").write_text(json.dumps({"drafts":[row]},ensure_ascii=False),encoding="utf-8")
    stamp=(datetime.now(auto_reply.JST)+timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M JST")
    (tmp_path/"drafts_archive.jsonl").write_text(
        json.dumps({"checked_at":stamp,**row},ensure_ascii=False),encoding="utf-8"
    )
    sender=Mock(side_effect=AssertionError("Never send preexisting Messenger preview"))
    monkeypatch.setattr(auto_reply.subprocess,"run",sender)
    result=auto_reply.run_pending(s)
    assert result["attempted"]==0 and result["confirmed"]==0
    sender.assert_not_called()
