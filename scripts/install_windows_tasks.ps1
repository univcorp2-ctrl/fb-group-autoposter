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
    param(
        [string]$Name, [string]$Script, [string]$At, [int]$RandomDelayMin, [string]$Desc,
        [switch]$AlsoAtLogon
    )
    $action = New-ScheduledTaskAction -Execute $Python -Argument "scripts\$Script" -WorkingDirectory $Root
    if ($RandomDelayMin -gt 0) {
        $trigger = New-ScheduledTaskTrigger -Daily -At $At -RandomDelay (New-TimeSpan -Minutes $RandomDelayMin)
    } else {
        $trigger = New-ScheduledTaskTrigger -Daily -At $At
    }
    $triggers = @($trigger)
    if ($AlsoAtLogon) {
        # Catch-up: if the PC was off at the scheduled time, post shortly after the
        # next logon instead of skipping the whole day. The calendar-day guard
        # (one post per group per JST day) makes this safe — a logon after a run
        # already happened today just skips. Guarantees a post on any day the PC
        # is used within active hours.
        $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        $logon.Delay = 'PT4M'
        $triggers += $logon
    }
    # Resilience so a daily run is not silently skipped:
    #   - StartWhenAvailable: if the PC was off/asleep at the scheduled time,
    #     run as soon as it is available again (catch up a missed day).
    #   - WakeToRun: wake the PC from sleep to run.
    #   - Battery flags: still run on battery (laptops).
    #   - RestartCount/Interval: retry a few times if the run fails.
    #   - MultipleInstances IgnoreNew: never stack overlapping runs.
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -WakeToRun `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 10) `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $triggers -Settings $settings -Description $Desc -Force | Out-Null
}

# --- Session keepalive: keep the FB login warm + snapshot a healthy profile ---
# Runs before the morning post and on every logon so backups stay fresh and an
# expired session is detected early (auto-restored by the posting loop).
New-DailyRun -Name 'FBAutoposter-Keepalive' -Script 'keepalive.py' -At '08:00' -RandomDelayMin 20 -Desc 'Keep FB session alive + back up healthy profile (+ logon)' -AlsoAtLogon

# --- Posting: morning + several fallbacks + evening ---
# Each run is idempotent (one post per group per JST day). The extra midday and
# afternoon runs are FALLBACKS: they only post if an earlier run failed, so the
# day's post is never missed. Morning also runs ~4 min after logon as catch-up.
New-DailyRun -Name 'FBAutoposter-Morning' -Script 'run_daily.py' -At '09:30' -RandomDelayMin 45 -Desc 'Post one fresh broker-OK property (morning + logon catch-up)' -AlsoAtLogon
New-DailyRun -Name 'FBAutoposter-Midday' -Script 'run_daily.py' -At '13:00' -RandomDelayMin 30 -Desc 'Posting fallback (only posts if morning missed)'
New-DailyRun -Name 'FBAutoposter-Afternoon' -Script 'run_daily.py' -At '16:30' -RandomDelayMin 30 -Desc 'Posting fallback (only posts if earlier runs missed)'
New-DailyRun -Name 'FBAutoposter-Evening' -Script 'run_daily.py' -At '20:30' -RandomDelayMin 45 -Desc 'Posting fallback (only posts if earlier runs missed)'

# --- Monitoring: after each posting window ---
New-DailyRun -Name 'FBAutoposter-Monitor-AM' -Script 'monitor.py' -At '12:00' -RandomDelayMin 0 -Desc 'Posting health check (after morning run)'
New-DailyRun -Name 'FBAutoposter-Monitor-PM' -Script 'monitor.py' -At '23:00' -RandomDelayMin 0 -Desc 'Posting health check (after evening run)'

# --- Posting-status DB: rebuild the at-a-glance Excel/CSV (投稿済/未投稿 一覧) ---
# Runs after the 09:00 EstateBoard refresh so new listings appear, and at logon.
# run_daily also rebuilds it after every posting run, so the 投稿済 flag stays current.
New-DailyRun -Name 'FBAutoposter-StatusDB' -Script 'build_status_db.py' -At '09:15' -RandomDelayMin 10 -Desc 'Rebuild posting-status Excel/CSV (投稿済/未投稿 一覧)' -AlsoAtLogon

# --- Group discovery: refresh candidate real-estate / investor groups daily ---
New-DailyRun -Name 'FBAutoposter-Discover' -Script 'discover_groups.py' -At '07:00' -RandomDelayMin 30 -Desc 'Discover candidate FB groups (review list only, no auto-join)'

Write-Host 'Registered tasks:'
Get-ScheduledTask -TaskName 'FBAutoposter-*' | Select-Object TaskName, State | Format-Table -AutoSize

& $Python "scripts\schedule_status.py"
