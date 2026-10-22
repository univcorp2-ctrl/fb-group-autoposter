"""Schedule-owned Facebook posting recovery pump.

Runs only when Chrome's loaded unpacked extension matches the reviewed source,
the local bridge is polling, no submission lease/pause is active, and there are
no pending bridge tasks. Uses the existing run-task.ps1/posting pipeline and its
approval, duplicate, freshness and daily caps. Never replays uncertain tasks.
No browser windows or extra login profiles are launched by the pump.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/"data"/"recovery_pump_status.json"
DRIVE=Path(r"G:\マイドライブ\AI_Agents\Private\FBGroupAutoposter\recovery_pump_status.json")
WRAPPER=Path(r"C:\Users\t0015\AppData\Local\FBGroupAutoposter\run-task.ps1")
MAX_STARTS_PER_DAY=6

def save(data:dict)->None:
    for path in (STATE,DRIVE):
        try:
            path.parent.mkdir(parents=True,exist_ok=True)
            tmp=path.with_name(path.name+".tmp")
            tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
            os.replace(tmp,path)
        except OSError: pass

def safe_to_run(health:dict, expected:str)->tuple[bool,str]:
    if not health.get("ok"): return False,"bridge_unhealthy"
    if health.get("extension_version")!=expected: return False,"extension_version_not_loaded"
    if not health.get("extension_polling"): return False,"extension_not_polling"
    if health.get("posting_paused"): return False,"posting_paused"
    if health.get("active_lease"): return False,"active_submission_lease"
    if int(health.get("pending_tasks",0) or 0): return False,"existing_bridge_queue"
    return True,"ready"

def main()->int:
    now=datetime.now(timezone.utc)
    stamp=now.isoformat()
    day=now.astimezone().date().isoformat()
    prior={}
    if STATE.exists():
        try:prior=json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError,ValueError):pass
    starts=int(prior.get("starts_today",0)) if prior.get("day")==day else 0
    result={"day":day,"checked_at":stamp,"starts_today":starts,"status":"blocked","expected_version":None}
    try:
        expected=json.loads((ROOT/"extension"/"manifest.json").read_text(encoding="utf-8"))["version"]
        result["expected_version"]=expected
        with urlopen("http://127.0.0.1:8766/health",timeout=4) as res:health=json.load(res)
        result["loaded_version"]=health.get("extension_version")
        ok,reason=safe_to_run(health,expected)
        if not ok:
            result["reason"]=reason
        elif starts>=MAX_STARTS_PER_DAY:
            result["reason"]="daily_start_limit"
        elif not WRAPPER.is_file():
            result["reason"]="production_wrapper_missing"
        else:
            from config import load_groups
            from scripts.facebook_post_button_preflight import ensure_layout_gate
            groups=[g for g in load_groups() if g.get("enabled",True)]
            if not groups:
                result["reason"]="no_authorized_target_group"
                save(result)
                print(json.dumps(result,ensure_ascii=False))
                return 0
            layout=ensure_layout_gate(groups[0], expected)
            result["layout_gate"]=layout
            if layout.get("status")!="passed":
                result["reason"]="safe_new_thread_button_unverified"
                save(result)
                print(json.dumps(result,ensure_ascii=False))
                return 0
            result["status"]="running"
            result["starts_today"]=starts+1
            save(result)
            # launch the existing production entrypoint; never duplicate its
            # credentials, object model, or posting safety controls.
            args=[
                "powershell.exe","-NoProfile","-NonInteractive","-WindowStyle",
                "Hidden","-ExecutionPolicy","Bypass","-File",str(WRAPPER),
                "-Script",r"scripts\run_daily_drive.py",
            ]
            p=subprocess.run(
                args,cwd=str(ROOT),stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                encoding="utf-8",errors="replace",check=False,
                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),
            )
            result["returncode"]=p.returncode
            result["stdout_tail"]=(p.stdout or "")[-1600:]
            result["stderr_tail"]=(p.stderr or "")[-1600:]
            result["status"]="finished" if p.returncode==0 else "failed"
    except Exception as error:
        result["reason"]=type(error).__name__
        result["status"]="error"
    result["completed_at"]=datetime.now(timezone.utc).isoformat()
    save(result)
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result["status"] in ("blocked","finished") else 2

if __name__=="__main__":sys.exit(main())
