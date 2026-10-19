"""Fail-closed Chrome MV3 extension heartbeat watchdog for the authorized Windows PC.

Does not create Facebook posts or replay ambiguous submissions.
Run every 5 minutes from the repository-owned Windows Task Scheduler.
A Chrome restart is allowed only when user input is idle, there is no
active Facebook submission lease and a six-hour restart cooldown has passed.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "data" / "extension_watchdog_state.json"
DRIVE_STATUS = Path(r"G:\マイドライブ\AI_Agents\Private\FBGroupAutoposter\extension_watchdog_status.json")
HEALTH_URL = "http://127.0.0.1:8766/health"
MIN_IDLE_SECONDS = 15 * 60
RESTART_COOLDOWN_SECONDS = 6 * 3600


def atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def bridge_health() -> dict:
    with urlopen(HEALTH_URL, timeout=4) as response:
        return json.load(response)


def desktop_idle_seconds() -> int:
    class LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
    value = LastInputInfo()
    value.cbSize = ctypes.sizeof(value)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(value)):
        raise OSError("GetLastInputInfo failed")
    current_tick = ctypes.windll.kernel32.GetTickCount()
    return ((current_tick - value.dwTime) & 0xFFFFFFFF) // 1000


def eligible_for_restart(health: dict, *, idle: int, last_restart: float, now: float) -> bool:
    return (
        not health.get("extension_polling", False)
        and not health.get("active_lease", False)
        and not health.get("posting_paused", False)
        and idle >= MIN_IDLE_SECONDS
        and now - last_restart >= RESTART_COOLDOWN_SECONDS
    )


def chrome_binary() -> Path:
    for program_dir in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)")):
        if program_dir:
            chrome = Path(program_dir) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if chrome.is_file():
                return chrome
    raise FileNotFoundError("Chrome executable not found")


def restart_default_chrome() -> None:
    # chrome://restart gracefully restores the Chrome Default session.
    # Never terminate Chrome with taskkill or modify profile/cookie files.
    subprocess.Popen(
        [str(chrome_binary()), "--profile-directory=Default", "chrome://restart"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    now = time.time()
    stamp = datetime.now(timezone.utc).isoformat()
    prior = {}
    if STATE_FILE.exists():
        try:
            prior = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    state = {
        "checked_at": stamp,
        "extension_polling": False,
        "result": "unverified",
        "restart_attempts_total": int(prior.get("restart_attempts_total", 0)),
        "last_restart_epoch": float(prior.get("last_restart_epoch", 0)),
    }
    try:
        health = bridge_health()
        state.update({
            "bridge_online": True,
            "extension_polling": bool(health.get("extension_polling", False)),
            "poll_age_seconds": health.get("extension_poll_age_seconds"),
            "active_lease": bool(health.get("active_lease", False)),
            "pending_tasks": int(health.get("pending_tasks") or 0),
            "posting_paused": bool(health.get("posting_paused", False)),
        })
        if state["extension_polling"]:
            state["result"] = "healthy"
        else:
            idle = desktop_idle_seconds()
            state["desktop_idle_seconds"] = idle
            if not eligible_for_restart(
                health, idle=idle, last_restart=state["last_restart_epoch"], now=now
            ):
                state["result"] = "stale_waiting_for_safe_idle_or_cooldown"
            elif args.check_only:
                state["result"] = "stale_restart_eligible_check_only"
            else:
                # Commit cooldown before triggering Chrome. Never restart in a tight loop.
                state["last_restart_epoch"] = now
                state["restart_attempts_total"] += 1
                state["result"] = "restart_requested"
                atomic_json(STATE_FILE, state)
                restart_default_chrome()
                time.sleep(20)
                new_health = bridge_health()
                state["extension_polling"] = bool(new_health.get("extension_polling", False))
                state["poll_age_seconds"] = new_health.get("extension_poll_age_seconds")
                state["result"] = "recovered" if state["extension_polling"] else "restart_did_not_restore_polling"
    except Exception as error:
        state["result"] = "watchdog_error"
        state["error"] = f"{type(error).__name__}: {error}"[:250]
    atomic_json(STATE_FILE, state)
    try:
        atomic_json(DRIVE_STATUS, state)
        state["drive_status_saved"] = True
    except OSError as error:
        state["drive_error"] = type(error).__name__
    print(json.dumps(state, ensure_ascii=False))
    return 0 if state["extension_polling"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
