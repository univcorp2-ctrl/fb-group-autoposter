# Registers Windows Scheduled Tasks for safe Facebook posting.
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
        $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        $logon.Delay = 'PT4M'
        $triggers += $logon
    }
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -WakeToRun `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 10) `
        -MultipleInstances IgnoreNew `
        -Hidden `
        -ExecutionTimeLimit (New-TimeSpan -Hours $ExecutionHours)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $triggers -Settings $settings -Description $Desc -Force | Out-Null
}

# Conservative community growth runs before browser keepalive/posting. It uses
# a separate 30-minute ceiling and refuses to run while the posting pipeline
# lock belongs to a live process.
$communityAction = New-ScheduledTaskAction -Execute $TaskPython -Argument 'scripts\community_manager.py' -WorkingDirectory $Root
$communityTrigger = New-ScheduledTaskTrigger -Daily -At '06:20' -RandomDelay (New-TimeSpan -Minutes 20)
$communitySettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName 'FBAutoposter-CommunityManager' -Action $communityAction -Trigger $communityTrigger -Settings $communitySettings -Description 'Safely refresh/promote Facebook communities before posting' -Force | Out-Null

New-DailyRun -Name 'FBAutoposter-Keepalive' -Script 'keepalive.py' -At '08:00' -RandomDelayMin 20 -Desc 'Keep FB session alive + back up healthy profile (+ logon)' -AlsoAtLogon
New-DailyRun -Name 'FBAutoposter-Morning' -Script 'run_daily.py' -At '09:30' -RandomDelayMin 45 -Desc 'Post one fresh broker-OK property (morning + logon catch-up)' -AlsoAtLogon -ExecutionHours 8
New-DailyRun -Name 'FBAutoposter-Midday' -Script 'run_daily.py' -At '13:00' -RandomDelayMin 30 -Desc 'Posting fallback (only posts if morning missed)' -ExecutionHours 8
New-DailyRun -Name 'FBAutoposter-Afternoon' -Script 'run_daily.py' -At '16:30' -RandomDelayMin 30 -Desc 'Posting fallback (only posts if earlier runs missed)' -ExecutionHours 8
New-DailyRun -Name 'FBAutoposter-Evening' -Script 'run_daily.py' -At '20:30' -RandomDelayMin 45 -Desc 'Posting fallback (only posts if earlier runs missed)' -ExecutionHours 8
New-DailyRun -Name 'FBAutoposter-Monitor-AM' -Script 'monitor.py' -At '12:00' -RandomDelayMin 0 -Desc 'Posting health check (after morning run)'
New-DailyRun -Name 'FBAutoposter-Monitor-PM' -Script 'monitor.py' -At '23:00' -RandomDelayMin 0 -Desc 'Posting health check (after evening run)'
New-DailyRun -Name 'FBAutoposter-StatusDB' -Script 'build_status_db.py' -At '09:15' -RandomDelayMin 10 -Desc 'Rebuild posting-status Excel/CSV (投稿済/未投稿 一覧)' -AlsoAtLogon
New-DailyRun -Name 'FBAutoposter-Discover' -Script 'discover_groups.py' -At '07:00' -RandomDelayMin 30 -Desc 'Discover candidate FB groups (review list only, no auto-join)'
New-DailyRun -Name 'FBAutoposter-Verify' -Script 'verify_posts.py' -At '11:30' -RandomDelayMin 20 -Desc 'Re-verify posts live by permalink; promote approved posts'
New-DailyRun -Name 'FBAutoposter-Verify-PM' -Script 'verify_posts.py' -At '21:30' -RandomDelayMin 20 -Desc 'Re-verify posts live by permalink (evening); promote approved posts'
New-DailyRun -Name 'FBAutoposter-Engagement' -Script 'monitor_engagement.py' -At '12:30' -RandomDelayMin 20 -Desc 'Monitor reactions/comments on posts; report to Telegram'
New-DailyRun -Name 'FBAutoposter-Engagement-PM' -Script 'monitor_engagement.py' -At '22:30' -RandomDelayMin 20 -Desc 'Monitor reactions/comments on posts (evening); report to Telegram'
New-DailyRun -Name 'FBAutoposter-Notifications' -Script 'monitor_notifications.py' -At '10:00' -RandomDelayMin 20 -Desc 'Summarize FB notifications about our posts (filter noise) -> Telegram'
New-DailyRun -Name 'FBAutoposter-Notifications-PM' -Script 'monitor_notifications.py' -At '20:00' -RandomDelayMin 20 -Desc 'Summarize FB notifications about our posts (evening) -> Telegram'
New-DailyRun -Name 'FBAutoposter-NotionSync' -Script 'sync_notion_engagement.py' -At '12:45' -RandomDelayMin 15 -Desc 'Record daily post engagement to Notion DB'
New-DailyRun -Name 'FBAutoposter-NotionSync-PM' -Script 'sync_notion_engagement.py' -At '22:45' -RandomDelayMin 15 -Desc 'Record daily post engagement to Notion DB (evening)'

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
        -Hidden `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger @($trigger, $logon) -Settings $settings -Description $Desc -Force | Out-Null
}
New-RepeatingRun -Name 'FBAutoposter-Renotify' -Script 'renotify_alerts.py' -EveryMinutes 30 -Desc 'Re-notify unacknowledged session/checkpoint alerts until operator confirms'
New-RepeatingRun -Name 'FBAutoposter-Bridge' -Script 'sync_estateboard_status.py' -EveryMinutes 120 -Desc 'Sync FB posting status to EstateBoard dashboard + deploy to Cloudflare (background)'

Write-Host 'Registered tasks:'
Get-ScheduledTask -TaskName 'FBAutoposter-*' | Select-Object TaskName, State | Format-Table -AutoSize
& $Python "scripts\schedule_status.py"
