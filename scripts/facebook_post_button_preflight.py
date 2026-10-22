"""No-send Facebook composer gate: prove a new-thread Post button becomes enabled.

Used by the Windows recovery pump after the correct extension version loads.
Never requests a real publication or bypasses the comment/reply safeguards.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STATUS=ROOT/"data"/"recovery_layout_gate.json"
EXT=ROOT/"extension"/"content.js"
PROBE_TTL_SECONDS=145
VALID_SECONDS=86400


def source_digest()->str:
    return hashlib.sha256(EXT.read_bytes()).hexdigest()


def cached_passed(version:str, group_id:str, now:float|None=None)->bool:
    if now is None: now=time.time()
    if not STATUS.exists():return False
    try:
        data=json.loads(STATUS.read_text(encoding="utf-8"))
        return (
            data.get("status")=="passed"
            and data.get("version")==version
            and data.get("group_id")==group_id
            and data.get("source_digest")==source_digest()
            and (now - float(data.get("passed_at_epoch",0))) <= VALID_SECONDS
        )
    except (OSError,ValueError,TypeError):return False


def atomic(path:Path, data:dict)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+".tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(tmp,path)


def ensure_layout_gate(group:dict, version:str, timeout:int=130)->dict:
    group_id=str(group.get("id") or "")
    group_url=str(group.get("post_url") or "")
    if not group_id.isdigit() or "www.facebook.com/groups/" not in group_url:
        return {"status":"blocked","reason":"invalid_configured_group"}
    if cached_passed(version,group_id):
        return {"status":"passed","reason":"cached_recent_no_send_success"}
    taskid="recovery-layout-"+uuid.uuid4().hex[:12]
    path=ROOT/"data"/"extension_tasks"/f"{taskid}.json"
    now=time.time()
    body="【安全な新規投稿欄の入力テスト】\nこの文字列は公開しません。\n投稿ボタンの有効化だけ確認します。"
    task={
        "task_id":taskid,
        "status":"pending",
        "created_at_epoch":now,
        "expires_at_epoch":now+PROBE_TTL_SECONDS,
        "group_id":group_id,
        "group_url":group_url,
        "body":body,
        "images":[],
        "image_root":"",
        "allow_images":False,
        "action":"layout_check",
    }
    if os.getenv('FB_POST_TRANSPORT') == 'authenticated_cdp':
        import asyncio
        from src.authenticated_post_transport import run_authenticated_task
        task['status'] = 'leased'
        atomic(path,task)
        asyncio.run(run_authenticated_task(task,path,timeout=timeout))
    else:
        atomic(path,task)
    deadline=now+min(timeout,PROBE_TTL_SECONDS-5)
    while time.time()<deadline:
        time.sleep(1.5)
        try: data=json.loads(path.read_text(encoding="utf-8"))
        except (ValueError,OSError):continue
        if data.get("status")!="finished":continue
        result=data.get("result") or {}
        details=str(result.get("error") or "")
        passed=(result.get("status")=="layout_ok" and
                "enabled=true" in details and "lines=3/3" in details)
        report={
            "status":"passed" if passed else "blocked",
            "reason":"no_send_composer_ready" if passed else "post_button_or_layout_not_confirmed",
            "version":version,"group_id":group_id,"task_id":taskid,
            "result_status":result.get("status"),
            "result_detail":details[:600],
            "source_digest":source_digest(),
            "passed_at_epoch":time.time() if passed else None,
        }
        atomic(STATUS,report)
        return report
    report={
        "status":"blocked","reason":"layout_probe_timeout_no_replay",
        "version":version,"group_id":group_id,"task_id":taskid,
        "source_digest":source_digest(),
    }
    atomic(STATUS,report)
    return report
