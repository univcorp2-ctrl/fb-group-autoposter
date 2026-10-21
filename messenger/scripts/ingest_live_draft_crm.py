"""Read existing Messenger drafts into a private, pseudonymous CRM event store.

No messages, PDFs, customer names, contacts, or real thread IDs are persisted.
Never generates a reply, sends a message, or writes to a public website.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from src.messenger_crm.models import CRMEvent, utc_now_iso
from src.messenger_crm.repository import MessengerCRMRepository

def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def parse_observed_drafts(path: Path) -> list[CRMEvent]:
    data=json.loads(path.read_text(encoding="utf-8"))
    rows=data.get("drafts")
    if not isinstance(rows,list):
        raise ValueError("invalid draft collection")
    unique={}
    for item in rows:
        if not isinstance(item,dict):
            continue
        thread=str(item.get("thread_id",""))
        fingerprint=str(item.get("review_fingerprint",""))
        if not (thread.isdecimal() and len(fingerprint)>=16
                and item.get("one_to_one_verified") is True
                and item.get("participant_count")==1
                and item.get("is_group") is False):
            continue
        opaque="t_"+digest(thread)
        event_id=digest("draft_observed:"+thread+":"+fingerprint)
        event=CRMEvent(
            event_id=event_id,
            event_type="messenger_draft_observed",
            customer_external_id=opaque,
            thread_id=opaque,
            draft_id="d_"+digest(fingerprint),
            occurred_at=utc_now_iso(),
            payload={"channel":"facebook_messenger",
                     "observation":"draft_only_not_delivery",
                     "review_status":str(item.get("review_status","unknown"))[:40],
                     "review_model":str(item.get("review_model",""))[:70],
                     "material_approved":bool((item.get("material") or {}).get("approved")),
                     "one_to_one_verified":True}
        )
        unique[event_id]=event
    return list(unique.values())

def ingest(source: Path, private_db: Path) -> dict:
    events=parse_observed_drafts(source)
    repo=MessengerCRMRepository(private_db)
    repo.record_events(events)
    count=repo.export_estateboard_payload()
    # Never export payload or private event identifiers, even to stdout.
    return {"processed_this_run":len(events),
            "stored_event_count":len(count.get("events",[])),
            "customer_details_published":False,
            "messages_sent":0}

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",type=Path,required=True)
    ap.add_argument("--private-db",type=Path,required=True)
    args=ap.parse_args()
    print(json.dumps(ingest(args.source,args.private_db),ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
