"""Silent, idempotent watchdog for the Messenger 1:1 document-reply daemon.

Runs under pythonw.exe from Windows Task Scheduler. Never opens a browser
or sends a message. Starts only a stopped READY task, leaves running jobs
untouched, and reports stale-running conditions without unsafe force-kills.
"""
from __future__ import annotations
import json
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "data" / "messenger_watchdog_status.json"
DRIVE = Path(r"G:\マイドライブ\AI_Agents\Private\FBGroupAutoposter\messenger_watchdog_status.json")
DAEMON_STATUS = ROOT / "data" / "draft_daemon_status.json"
TASK = "FBAutoposter-MessengerDrafts"
JST = timezone(timedelta(hours=9))

def save_atomic(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)

def query_state() -> str:
    command = (
        f"$task=Get-ScheduledTask -TaskName '{TASK}' -ErrorAction Stop;"
        "[string]$task.State"
    )
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
         "-Command", command],
        text=True, capture_output=True, timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode:
        raise RuntimeError("scheduled_task_query_failed")
    return proc.stdout.strip().splitlines()[-1]

def start_task() -> None:
    proc = subprocess.run(
        ["schtasks.exe", "/Run", "/TN", TASK],
        text=True, capture_output=True, timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode:
        raise RuntimeError("scheduled_task_restart_failed")

def last_success_seconds() -> int | None:
    if not DAEMON_STATUS.is_file():
        return None
    try:
        state = json.loads(DAEMON_STATUS.read_text(encoding="utf-8"))
        raw = str(state.get("last_success_at") or "")
        stamp = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S JST").replace(tzinfo=JST)
        return max(0, int((datetime.now(JST) - stamp).total_seconds()))
    except (ValueError, OSError):
        return None

def decide(task_state: str, last_success_age: int | None) -> str:
    if task_state == "Running":
        if last_success_age is not None and last_success_age > 15 * 60:
            return "stale_running_investigate_without_kill"
        return "healthy_running"
    if task_state == "Ready":
        return "start_stopped_daemon"
    return "blocked_" + task_state.lower().replace(" ", "_")

def main() -> int:
    state={"checked_at": datetime.now(JST).isoformat(), "task": TASK,
           "browser_popup_requested": False, "message_send_requested": False}
    try:
        state["task_state_before"] = query_state()
        state["last_success_age_seconds"] = last_success_seconds()
        decision = decide(state["task_state_before"], state["last_success_age_seconds"])
        state["decision"] = decision
        if decision == "start_stopped_daemon":
            start_task()
            state["task_state_after"] = query_state()
            state["decision"] = "restarted" if state["task_state_after"] == "Running" else "restart_unverified"
    except Exception as error:
        state["decision"] = "watchdog_error"
        state["error_type"] = type(error).__name__
    save_atomic(STATUS, state)
    try:
        save_atomic(DRIVE, state)
    except OSError:
        state["drive_status_written"] = False
    print(json.dumps(state, ensure_ascii=False))
    return 0 if state["decision"] in {"healthy_running","restarted","stale_running_investigate_without_kill"} else 2

if __name__ == "__main__":
    raise SystemExit(main())
