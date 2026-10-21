"""A private sync never sends or exposes Messenger customer content."""
import json
from scripts.sync_private_crm import sync

def test_complete_private_sync(tmp_path):
    data=tmp_path/"live"
    private=tmp_path/"private"
    data.mkdir()
    (data/"auto_reply_ledger.json").write_text(json.dumps({
        "attempts":{"once":{"state":"blocked_or_uncertain_no_replay"}}}))
    (data/"draft_daemon_status.json").write_text(json.dumps({
        "scan":{"scanned":22,"need_reply":9}}))
    (data/"threads_state.json").write_text(json.dumps({
        "12345":{"message":"SECRET_INBOUND"}}))
    (data/"drafts.json").write_text(json.dumps({"drafts":[{
        "thread_id":"12345","one_to_one_verified":True,
        "participant_count":1,"is_group":False,
        "review_fingerprint":"x"*64,"name":"SECRET_NAME",
        "draft":"SECRET_DRAFT", "review_status":"needs_human"}]}))
    out=sync(data,private)
    assert out["history_rows"]==1
    assert out["observed_draft_events"]==1
    assert out["unresolved_sends"]==1
    assert out["outbound_actions"]==0
    assert sync(data,private)["observed_draft_events"]==1
    assert len(list(private.glob("*.sqlite")))==2
    snapshot=json.loads((private/"verified_messenger_snapshot_latest.json").read_text())
    assert snapshot["uncertain_send_count"]==1
    assert snapshot["estateboard_publication_confirmed"] is False
    assert "SECRET_NAME" not in json.dumps(snapshot)
    for path in private.glob("*.sqlite"):
        for secret in (b"12345",b"SECRET_INBOUND",b"SECRET_DRAFT",b"SECRET_NAME"):
            assert secret not in path.read_bytes()
