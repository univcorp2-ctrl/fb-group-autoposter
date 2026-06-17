# Registers Windows Scheduled Tasks for safe twice-daily Facebook posting.
#
# Design:
#   - Two posting runs per day (morning + evening), each with a random delay.
#     MIN_SAME_GROUP_HOURS + MAX_POSTS_PER_DAY in .env
#     cap the cadence, so even if a run fires early nothing over-posts.
#   - A monitor run after each posting window writes logs/monitor_status.json and
#     flags if posting has stalled (no successful post in ~26h).
#
# NOTE: posting uses a *headed* browser (lower ban risk than headless), so these
# tasks run in the interactive user session — the PC must be logged in at the
# scheduled times. Times below are LOCAL machine time (set the PC to JST).

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (!(Test-Path $Python)) { $Python = 'python' }

function New-DailyRun {
    param([string]$Name, [string]$Script, [string]$At, [int]$RandomDelayMin, [string]$Desc)
    $action = New-ScheduledTaskAction -Execute $Python -Argument "scripts\$Script" -WorkingDirectory $Root
    if ($RandomDelayMin -gt 0) {
        $trigger = New-ScheduledTaskTrigger -Daily -At $At -RandomDelay (New-TimeSpan -Minutes $RandomDelayMin)
    } else {
        $trigger = New-ScheduledTaskTrigger -Daily -At $At
    }
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Description $Desc -Force | Out-Null
}

# --- Posting: morning + evening (random delay up to 45 min for naturalness) ---
New-DailyRun -Name 'FBAutoposter-Morning' -Script 'run_daily.py' -At '09:30' -RandomDelayMin 45 -Desc 'Post one fresh broker-OK property (morning)'
New-DailyRun -Name 'FBAutoposter-Evening' -Script 'run_daily.py' -At '20:30' -RandomDelayMin 45 -Desc 'Post one fresh broker-OK property (evening)'

# --- Monitoring: after each posting window ---
New-DailyRun -Name 'FBAutoposter-Monitor-AM' -Script 'monitor.py' -At '12:00' -RandomDelayMin 0 -Desc 'Posting health check (after morning run)'
New-DailyRun -Name 'FBAutoposter-Monitor-PM' -Script 'monitor.py' -At '23:00' -RandomDelayMin 0 -Desc 'Posting health check (after evening run)'

# --- Group discovery: refresh candidate real-estate / investor groups daily ---
New-DailyRun -Name 'FBAutoposter-Discover' -Script 'discover_groups.py' -At '07:00' -RandomDelayMin 30 -Desc 'Discover candidate FB groups (review list only, no auto-join)'

Write-Host 'Registered tasks:'
Get-ScheduledTask -TaskName 'FBAutoposter-*' | Select-Object TaskName, State | Format-Table -AutoSize

& $Python "scripts\schedule_status.py"
