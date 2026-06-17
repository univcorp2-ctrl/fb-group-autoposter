"""Write the next scheduled autoposter runs to logs/schedule_status.*."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
TASK_NAMES = [
    "FBAutoposter-Morning",
    "FBAutoposter-Evening",
    "FBAutoposter-Monitor-AM",
    "FBAutoposter-Monitor-PM",
    "FBAutoposter-Discover",
]


def _run_powershell(script: str) -> str:
    for executable in ("pwsh", "powershell"):
        try:
            completed = subprocess.run(
                [
                    executable,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=ROOT,
            )
            return completed.stdout
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    return "[]"


def get_task_statuses() -> list[dict[str, Any]]:
    quoted = ",".join(f"'{name}'" for name in TASK_NAMES)
    script = f"""
$names = @({quoted})
$items = foreach ($name in $names) {{
  $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  if ($null -eq $task) {{ continue }}
  $info = Get-ScheduledTaskInfo -TaskName $name
  [PSCustomObject]@{{
    task_name = $name
    state = [string]$task.State
    next_run_time = if ($info.NextRunTime) {{ $info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss') }} else {{ $null }}
    last_run_time = if ($info.LastRunTime) {{ $info.LastRunTime.ToString('yyyy-MM-dd HH:mm:ss') }} else {{ $null }}
    last_task_result = $info.LastTaskResult
  }}
}}
$items | ConvertTo-Json -Depth 3
"""
    raw = _run_powershell(script).strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [{"error": "failed to parse scheduled task status", "raw": raw}]
    if isinstance(data, dict):
        return [data]
    return data if isinstance(data, list) else []


def write_status() -> dict[str, Any]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    statuses = get_task_statuses()
    posting = [s for s in statuses if s.get("task_name") in {"FBAutoposter-Morning", "FBAutoposter-Evening"}]
    next_posting = min(
        (s for s in posting if s.get("next_run_time")),
        key=lambda s: str(s["next_run_time"]),
        default=None,
    )
    payload = {
        "generated_at": now,
        "timezone": "local machine time",
        "next_posting_run": next_posting,
        "tasks": statuses,
    }
    (LOG_DIR / "schedule_status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Facebook Autoposter Schedule Status",
        "",
        f"- generated_at: {now}",
        "- timezone: local machine time",
        f"- next_posting_run: {next_posting.get('next_run_time') if next_posting else 'not scheduled'}",
        "",
        "| Task | State | Next Run | Last Run | Last Result |",
        "|---|---:|---:|---:|---:|",
    ]
    for status in statuses:
        lines.append(
            "| {task_name} | {state} | {next_run_time} | {last_run_time} | {last_task_result} |".format(
                task_name=status.get("task_name", ""),
                state=status.get("state", ""),
                next_run_time=status.get("next_run_time") or "",
                last_run_time=status.get("last_run_time") or "",
                last_task_result=status.get("last_task_result", ""),
            )
        )
    (LOG_DIR / "schedule_status.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    payload = write_status()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
