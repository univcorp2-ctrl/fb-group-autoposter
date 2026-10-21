"""A private Messenger CRM event is never proof of an actual inbound or send."""
import json
from scripts.ingest_live_draft_crm import ingest, parse_observed_drafts
from src.messenger_crm.repository import MessengerCRMRepository

def fixture(tmp_path, reviewed=True):
    source=tmp_path/"drafts.json"
    source.write_text(json.dumps({"drafts":[{
        "thread_id":"123456789",
        "one_to_one_verified":reviewed,
        "participant_count":1,
        "is_group":False,
        "name":"SECRET_CUSTOMER",
        "last_message":"SECRET_INBOUND",
        "draft":"SECRET_DRAFT",
        "review_status":"needs_human",
        "review_model":"",
        "review_fingerprint":"a"*64,
        "material":{"approved":False,"file_path":"SECRET_PDF"}
    }]}),encoding="utf-8")
    return source

def test_private_observation_is_idempotent_and_redacted(tmp_path):
    source=fixture(tmp_path)
    db=tmp_path/"crm.sqlite"
    result=ingest(source,db)
    assert result["processed_this_run"]==1
    assert result["stored_event_count"]==1
    assert result["messages_sent"]==0
    again=ingest(source,db)
    assert again["stored_event_count"]==1
    events=MessengerCRMRepository(db).list_events()
    assert len(events)==1
    assert events[0].event_type=="messenger_draft_observed"
    assert events[0].payload["observation"]=="draft_only_not_delivery"
    raw=db.read_bytes()
    for token in (b"123456789",b"SECRET_CUSTOMER",
                  b"SECRET_INBOUND",b"SECRET_DRAFT",b"SECRET_PDF"):
        assert token not in raw

def test_unverified_one_to_one_is_not_ingested(tmp_path):
    source=fixture(tmp_path,reviewed=False)
    assert parse_observed_drafts(source)==[]

def test_same_draft_events_keep_stable_identity(tmp_path):
    source=fixture(tmp_path)
    first=parse_observed_drafts(source)[0].event_id
    second=parse_observed_drafts(source)[0].event_id
    assert first==second
