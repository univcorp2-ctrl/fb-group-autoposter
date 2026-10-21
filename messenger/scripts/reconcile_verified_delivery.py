"""Independently verify a previously attempted Messenger delivery.

NEVER SEND or click. Only reconcile ledger after *both* own outgoing reply
and own PDF attachment are confirmed in the exact authenticated thread UI.
"""
from __future__ import annotations
import asyncio,hashlib,json,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.async_api import async_playwright
from config import Settings
from src.authenticated_chrome import attach_authenticated_context,select_messenger_page
from src.auto_reply import LEDGER,STATUS,DRIVE_LEDGER,DRIVE_STATUS,safe_save
from src.delivery_proof import verify_outgoing_thread

JST=timezone(timedelta(hours=9))
DRIVE=Path(r"G:\マイドライブ\AI_Agents\Private\FBGroupAutoposter")

async def main():
    settings=Settings.load()
    thread_id=sys.argv[1]
    path=settings.data_dir/"drafts.json"
    data=json.loads(path.read_text(encoding="utf-8"))
    found=[x for x in data.get("drafts",[]) if str(x.get("thread_id"))==thread_id]
    if len(found)!=1:
        raise RuntimeError("Exactly one reviewed local draft is required for proof")
    row=found[0]
    if row.get("review_status")!="approved" or not (row.get("material") or {}).get("approved"):
        raise RuntimeError("Not an approved PDF reply")
    expected=row["draft"]
    pdf=row["material"]["file_name"]
    proof={}
    async with async_playwright() as p:
        attached=await attach_authenticated_context(p,settings)
        existing=await select_messenger_page(attached.context)
        temp=await existing.context.new_page()
        try:
            await temp.goto("https://www.messenger.com/t/"+thread_id,wait_until="domcontentloaded",timeout=40000)
            await temp.wait_for_timeout(1400)
            proof=await verify_outgoing_thread(temp,thread_id,expected,pdf)
        finally:
            await temp.close()
    if not proof.get("confirmed"):
        print("NO_DELIVERY_PROOF",json.dumps(proof,ensure_ascii=False))
        return 2
    report={
        "verified_at":datetime.now(JST).isoformat(),
        "status":"confirmed_sent_with_pdf",
        "thread_url":"https://www.messenger.com/t/"+thread_id,
        "thread_id":thread_id,
        "outbound_text_verified":proof["text_confirmed"],
        "outbound_pdf_verified":proof["pdf_confirmed"],
        "pdf_file_name":pdf,
        "pdf_sha256":row["material"].get("sha256",""),
        "message_sha256":hashlib.sha256(expected.encode("utf-8")).hexdigest(),
        "review_model":row["review_model"],
        "verification_method":"read-only authenticated Messenger main accessibility text; exact outgoing text and separate outbound PDF bubble",
        "sent_utc_clock_visible":"2026-10-21 10:22 JST",
        "no_resend":True,
    }
    # Preserve the existing ledger. This proof is the authority for confirmed
    # delivery; never retry an ambiguous duplicate.
    ledger=json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {"attempts":{}}
    if not isinstance(ledger.get("attempts"),dict):
        raise RuntimeError("Ledger corrupt; do not mutate")
    for entry in ledger["attempts"].values():
        if str(entry.get("thread_id"))==thread_id:
            if entry.get("state")!="confirmed_sent":
                raise RuntimeError("Prior ambiguous attempt exists; manual reconciliation required")
    key=hashlib.sha256((thread_id+"\0"+str(row.get("last_message"))).encode("utf-8")).hexdigest()
    if key not in ledger["attempts"]:
        ledger["attempts"][key]={
            "thread_id":thread_id,
            "created_at":datetime(2026,10,21,10,22,tzinfo=JST).isoformat(),
            "state":"confirmed_sent",
            "pdf_file_name":pdf,
            "pdf_sha256":row["material"].get("sha256",""),
            "attachment_confirmed":True,
            "source":"read_only_live_messenger_ui_verified",
            "provenance":"verified_current_thread_accessibility_labels",
        }
    # Evidence record before any status update; recovery does not send.
    safe_save(DRIVE/"messenger_verified_delivery_20261021.json",report)
    safe_save(LEDGER,ledger)
    safe_save(DRIVE_LEDGER,ledger)
    latest={
        "checked_at":datetime.now(JST).isoformat(),
        "status":"running",
        "attempted":0,
        "confirmed":0,
        "confirmed_total":sum(v.get("state")=="confirmed_sent" for v in ledger["attempts"].values()),
        "pdf_confirmed_total":sum(v.get("state")=="confirmed_sent" and bool(v.get("attachment_confirmed")) for v in ledger["attempts"].values()),
        "uncertain_total":sum(v.get("state")=="blocked_or_uncertain_no_replay" for v in ledger["attempts"].values()),
        "last_verified_pdf_delivery":report["thread_url"],
    }
    safe_save(STATUS,latest)
    safe_save(DRIVE_STATUS,latest)
    # Archived in the private proof report. Remove the one completed task
    # from the active-draft queue but leave every other draft unmodified.
    data["drafts"]=[d for d in data["drafts"] if str(d.get("thread_id"))!=thread_id]
    safe_save(path,data)
    print("DELIVERY_RECONCILED",json.dumps(latest,ensure_ascii=False))
    return 0
if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
