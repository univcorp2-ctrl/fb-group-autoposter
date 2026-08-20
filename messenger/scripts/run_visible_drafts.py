"""Scan Messenger and place saved reply drafts into the regular logged-in work Chrome.

Facebook messages are NEVER sent. The existing scan generates/saves local drafts;
then a PowerShell helper opens each target thread in Chrome Profile 1 and places
only the unsent text into the composer for human review.
"""
from __future__ import annotations
import asyncio
import json
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from config import Settings  # noqa: E402
from scripts.run_once import _scan  # noqa: E402
HELPER=ROOT/'scripts'/'place_work_profile_drafts.ps1'
async def main_async()->dict:
    settings=Settings.load()
    scan=await _scan(settings,use_telegram=True)
    powershell=Path(r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe')
    proc=subprocess.run([str(powershell),'-NoProfile','-STA','-WindowStyle','Hidden','-ExecutionPolicy','Bypass','-File',str(HELPER)],cwd=str(ROOT.parent),capture_output=True,text=True,timeout=5*60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=False)
    result={'scan':scan,'work_profile_drafts':{'returncode':proc.returncode,'ok':proc.returncode==0}}
    print(json.dumps(result,ensure_ascii=False))
    return result
if __name__=='__main__': asyncio.run(main_async())
