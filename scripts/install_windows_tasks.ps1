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
$TaskPython = Join-Path $Root '.venv\Scripts\pythonw.exe'
if (!(Test-Path $TaskPython)) { $TaskPython = $Python }

function New-DailyRun {
    param(
        [string]$Name, [string]$Script, [string]$At, [int]$RandomDelayMin, [string]$Desc,
        [switch]$AlsoAtLogon, [int]$ExecutionHours = 1
    )
    $action = New-ScheduledTaskAction -Execute $TaskPython -Argument "scripts\$Script" -WorkingDirectory $Root
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
    # Resilience so a daily run is not silently skipped. Posting runs need up to
    # several hours because the anti-abuse cadence deliberately sleeps 15-35
    # minutes between groups; ordinary tasks keep the 1h default.
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -WakeToRun `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 10) `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours $ExecutionHours)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $triggers -Settings $settings -Description $Desc -Force | Out-Null
}

# --- Session keepalive: keep the FB login warm + snapshot a healthy profile ---
New-DailyRun -Name 'FBAutoposter-Keepalive' -Script 'keepalive.py' -At '08:00' -RandomDelayMin 20 -Desc 'Keep FB session alive + back up healthy profile (+ logon)' -AlsoAtLogon

# --- Posting: morning + several fallbacks + evening ---
# Each run is idempotent (one post per group per JST day). The extra midday and
# afternoon runs are FALLBACKS: they only post if an earlier run failed.
New-DailyRun -Name 'FBAutoposter-Morning' -Script 'run_daily.py' -At '09:30' -RandomDelayMin 45 -Desc 'Post one fresh broker-OK property (morning + logon catch-up)' -AlsoAtLogon -ExecutionHours 8
New-DailyRun -Name 'FBAutoposter-Midday' -Script 'run_daily.py' -At '13:00' -RandomDelayMin 30 -Desc 'Posting fallback (only posts if morning missed)' -ExecutionHours 8
New-DailyRun -Name 'FBAutoposter-Afternoon' -Script 'run_daily.py' -At '16:30' -RandomDelayMin 30 -Desc 'Posting fallback (only posts if earlier runs missed)' -ExecutionHours 8
New-DailyRun -Name 'FBAutoposter-Evening' -Script 'run_daily.py' -At '20:30' -RandomDelayMin 45 -Desc 'Posting fallback (only posts if earlier runs missed)' -ExecutionHours 8

# --- Monitoring: after each posting window ---
New-DailyRun -Name 'FBAutoposter-Monitor-AM' -Script 'monitor.py' -At '12:00' -RandomDelayMin 0 -Desc 'Posting health check (after morning run)'
New-DailyRun -Name 'FBAutoposter-Monitor-PM' -Script 'monitor.py' -At '23:00' -RandomDelayMin 0 -Desc 'Posting health check (after evening run)'

# --- Posting-status DB: rebuild the at-a-glance Excel/CSV (投稿済/未投稿 一覧) ---
New-DailyRun -Name 'FBAutoposter-StatusDB' -Script 'build_status_db.py' -At '09:15' -RandomDelayMin 10 -Desc 'Rebuild posting-status Excel/CSV (投稿済/未投稿 一覧)' -AlsoAtLogon

# --- Group discovery: refresh candidate real-estate / investor groups daily ---
New-DailyRun -Name 'FBAutoposter-Discover' -Script 'discover_groups.py' -At '07:00' -RandomDelayMin 30 -Desc 'Discover candidate FB groups (review list only, no auto-join)'

# --- Post verification: re-check live that posts are public; promote approved ---
New-DailyRun -Name 'FBAutoposter-Verify' -Script 'verify_posts.py' -At '11:30' -RandomDelayMin 20 -Desc 'Re-verify posts live by permalink; promote approved posts'
New-DailyRun -Name 'FBAutoposter-Verify-PM' -Script 'verify_posts.py' -At '21:30' -RandomDelayMin 20 -Desc 'Re-verify posts live by permalink (evening); promote approved posts'

# --- Engagement monitor: reactions/comments on published posts -> Telegram ---
New-DailyRun -Name 'FBAutoposter-Engagement' -Script 'monitor_engagement.py' -At '12:30' -RandomDelayMin 20 -Desc 'Monitor reactions/comments on posts; report to Telegram'
New-DailyRun -Name 'FBAutoposter-Engagement-PM' -Script 'monitor_engagement.py' -At '22:30' -RandomDelayMin 20 -Desc 'Monitor reactions/comments on posts (evening); report to Telegram'

# --- FB notifications: keep only reactions/comments on OUR posts -> Telegram ---
New-DailyRun -Name 'FBAutoposter-Notifications' -Script 'monitor_notifications.py' -At '10:00' -RandomDelayMin 20 -Desc 'Summarize FB notifications about our posts (filter noise) -> Telegram'
New-DailyRun -Name 'FBAutoposter-Notifications-PM' -Script 'monitor_notifications.py' -At '20:00' -RandomDelayMin 20 -Desc 'Summarize FB notifications about our posts (evening) -> Telegram'

# --- Notion sync: record daily engagement to Notion DB (needs NOTION_TOKEN) ---
New-DailyRun -Name 'FBAutoposter-NotionSync' -Script 'sync_notion_engagement.py' -At '12:45' -RandomDelayMin 15 -Desc 'Record daily post engagement to Notion DB'
New-DailyRun -Name 'FBAutoposter-NotionSync-PM' -Script 'sync_notion_engagement.py' -At '22:45' -RandomDelayMin 15 -Desc 'Record daily post engagement to Notion DB (evening)'

# --- Alert re-notifier: keep pinging Telegram until the operator acknowledges ---
function New-RepeatingRun {
    param([string]$Name, [string]$Script, [int]$EveryMinutes, [string]$Desc)
    $action = New-ScheduledTaskAction -Execute $TaskPython -Argument "scripts\$Script" -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -Daily -At '00:00'
    $rep = New-ScheduledTaskTrigger -Once -At '00:00' `
        -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
        -RepetitionDuration (New-TimeSpan -Hours 23 -Minutes 59)
    $trigger.Repetition = $rep.Repetition
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $logon.Delay = 'PT2M'
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger @($trigger, $logon) -Settings $settings -Description $Desc -Force | Out-Null
}
New-RepeatingRun -Name 'FBAutoposter-Renotify' -Script 'renotify_alerts.py' -EveryMinutes 30 -Desc 'Re-notify unacknowledged session/checkpoint alerts until operator confirms'

# --- EstateBoard bridge: sync posting status -> data.json -> Cloudflare Pages ---
New-RepeatingRun -Name 'FBAutoposter-Bridge' -Script 'sync_estateboard_status.py' -EveryMinutes 120 -Desc 'Sync FB posting status to EstateBoard dashboard + deploy to Cloudflare (background)'

Write-Host 'Registered tasks:'
Get-ScheduledTask -TaskName 'FBAutoposter-*' | Select-Object TaskName, State | Format-Table -AutoSize

& $Python "scripts\schedule_status.py"
