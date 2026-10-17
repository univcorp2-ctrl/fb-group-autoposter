param(
  [string]$RuntimeRoot = (Join-Path $env:LOCALAPPDATA 'FBGroupAutoposter')
)
$ErrorActionPreference = 'Stop'
$AppRoot = Join-Path $RuntimeRoot 'app'
$LauncherPath = Join-Path $RuntimeRoot 'run-task.ps1'
if (!(Test-Path $LauncherPath)) { throw "launcher missing: $LauncherPath" }
if (!(Test-Path $AppRoot)) { throw "app missing: $AppRoot" }

function New-LocalDailyRun {
  param(
    [string]$Name,[string]$Script,[string]$At,[int]$RandomDelayMin=0,
    [int]$ExecutionMinutes=60,[switch]$AtLogon,[string]$Desc='Drive-safe Facebook autoposter'
  )
  $args = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$LauncherPath`" -Script `"$Script`""
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $args -WorkingDirectory $AppRoot
  $daily = New-ScheduledTaskTrigger -Daily -At $At
  if ($RandomDelayMin -gt 0) { $daily.RandomDelay = "PT${RandomDelayMin}M" }
  $triggers = @($daily)
  if ($AtLogon) {
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $logon.Delay = 'PT4M'
    $triggers += $logon
  }
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew -Hidden -ExecutionTimeLimit (New-TimeSpan -Minutes $ExecutionMinutes)
  Register-ScheduledTask -TaskName $Name -Action $action -Trigger $triggers -Settings $settings -Description $Desc -Force | Out-Null
}
New-LocalDailyRun 'FBAutoposter-Discover' 'scripts\discover_groups.py' '05:20' 20 60
New-LocalDailyRun 'FBAutoposter-CommunityManager' 'scripts\community_manager.py' '06:20' 20 30
New-LocalDailyRun 'FBAutoposter-Keepalive' 'scripts\keepalive.py' '08:00' 20 60 -AtLogon
New-LocalDailyRun 'FBAutoposter-StatusDB' 'scripts\build_status_db.py' '09:15' 10 60 -AtLogon
New-LocalDailyRun 'FBAutoposter-Morning' 'scripts\run_daily_drive.py' '09:30' 45 480 -AtLogon
New-LocalDailyRun 'FBAutoposter-Notifications' 'scripts\monitor_notifications.py' '10:00' 20 60
New-LocalDailyRun 'FBAutoposter-Verify' 'scripts\verify_posts.py' '11:30' 20 60
New-LocalDailyRun 'FBAutoposter-Monitor-AM' 'scripts\monitor.py' '12:00' 0 60
New-LocalDailyRun 'FBAutoposter-Engagement' 'scripts\monitor_engagement.py' '12:30' 20 60
New-LocalDailyRun 'FBAutoposter-NotionSync' 'scripts\sync_notion_engagement.py' '12:45' 15 60
New-LocalDailyRun 'FBAutoposter-Midday' 'scripts\run_daily_drive.py' '13:00' 30 480
New-LocalDailyRun 'FBAutoposter-Afternoon' 'scripts\run_daily_drive.py' '16:30' 30 480
New-LocalDailyRun 'FBAutoposter-Notifications-PM' 'scripts\monitor_notifications.py' '20:00' 20 60
New-LocalDailyRun 'FBAutoposter-Evening' 'scripts\run_daily_drive.py' '20:30' 45 480
New-LocalDailyRun 'FBAutoposter-Verify-PM' 'scripts\verify_posts.py' '21:30' 20 60
New-LocalDailyRun 'FBAutoposter-DailyGuarantee' 'scripts\ensure_daily_post.py' '22:10' 0 480
New-LocalDailyRun 'FBAutoposter-Engagement-PM' 'scripts\monitor_engagement.py' '22:30' 20 60
New-LocalDailyRun 'FBAutoposter-NotionSync-PM' 'scripts\sync_notion_engagement.py' '22:45' 15 60
New-LocalDailyRun 'FBAutoposter-Monitor-PM' 'scripts\monitor.py' '23:00' 0 60
New-LocalDailyRun 'FBAutoposter-WebSLO' 'scripts\verify_estateboard_web.py' '23:10' 0 60
function New-LocalRepeatingRun {
  param([string]$Name,[string]$Script,[int]$EveryMinutes,[string]$Desc)
  $args = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$LauncherPath`" -Script `"$Script`""
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $args -WorkingDirectory $AppRoot
  $daily = New-ScheduledTaskTrigger -Once -At '00:00' -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) -RepetitionDuration (New-TimeSpan -Hours 23 -Minutes 59)
  $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  $logon.Delay = 'PT2M'
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -Hidden -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
  Register-ScheduledTask -TaskName $Name -Action $action -Trigger @($daily,$logon) -Settings $settings -Description $Desc -Force | Out-Null
}

New-LocalRepeatingRun 'FBAutoposter-Renotify' 'scripts\renotify_alerts.py' 30 'Re-notify unacknowledged FB alerts'
New-LocalRepeatingRun 'FBAutoposter-Bridge' 'scripts\sync_estateboard_status.py' 120 'Sync confirmed FB posts to EstateBoard + Cloudflare'

Write-Output 'Local-runtime task registration complete.'
Get-ScheduledTask -TaskName 'FBAutoposter-*' | Select-Object TaskName,State | Sort-Object TaskName | Format-Table -AutoSize