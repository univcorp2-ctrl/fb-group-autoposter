# Register Messenger reply-draft daemon using the LIVE app runtime, not the stale Google Drive copy.
# Safety: premium-reviewed 1:1 PDF requests may be sent automatically.
# Group chats and unverified documents fail closed; Chrome stays background-only.
#
# Optional interval override in messenger/.env or user environment:
#   MESSENGER_DRAFT_INTERVAL_MINUTES=30
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Python = Join-Path $env:LOCALAPPDATA 'FBGroupAutoposter\.venv\Scripts\pythonw.exe'
if (!(Test-Path $Python)) {
    throw "Windowless Python runtime not found: $Python"
}

$Action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument 'messenger\scripts\run_draft_daemon.py' `
    -WorkingDirectory $RepoRoot

# The daemon owns a 1-minute background polling loop. Logon starts it; the daily trigger is a
# self-healing fallback if the process was stopped while the PC stayed logged in.
$Logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Logon.Delay = 'PT2M'
$Daily = New-ScheduledTaskTrigger -Daily -At '07:30'

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName 'FBAutoposter-MessengerDrafts' `
    -Action $Action `
    -Trigger @($Logon, $Daily) `
    -Settings $Settings `
    -Description 'Quiet Messenger 1:1 property PDF reply daemon: premium-reviewed only, group threads prohibited' `
    -Force | Out-Null

# A separate, idempotent 30-minute watchdog ensures the authenticated Chrome
# profile is running. It never closes tabs or creates another profile.
$ChromeWatchScript = Join-Path $PSScriptRoot 'ensure_chrome_profile.ps1'
$ChromeTaskCommand = 'powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $ChromeWatchScript + '"'
& schtasks.exe /Create /TN 'FBAutoposter-MessengerChrome' /TR $ChromeTaskCommand /SC MINUTE /MO 30 /F | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Messenger Chrome watchdog registration failed: $LASTEXITCODE" }
# Task Scheduler must also hide the Chrome keepalive task itself, not only
# the PowerShell process launched by its -WindowStyle Hidden argument.
$ChromeExisting = Get-ScheduledTask -TaskName 'FBAutoposter-MessengerChrome'
$ChromeSettings = $ChromeExisting.Settings
$ChromeSettings.Hidden = $true
Set-ScheduledTask -TaskName 'FBAutoposter-MessengerChrome' -Settings $ChromeSettings | Out-Null

# Recover a stopped daemon every 5 minutes without visible windows.
# pythonw + an explicitly hidden Task Scheduler action; never open Chrome here.
$HealthAction = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument 'messenger\scripts\watch_messenger_daemon.py' `
    -WorkingDirectory $RepoRoot
$HealthTrigger = New-ScheduledTaskTrigger -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
$HealthSettings = New-ScheduledTaskSettingsSet `
    -Hidden -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
Register-ScheduledTask -TaskName 'FBAutoposter-MessengerWatchdog' `
    -Action $HealthAction -Trigger $HealthTrigger `
    -Settings $HealthSettings `
    -Description 'Silent restart of stopped Messenger 1:1 PDF-reply daemon only; never sends messages' `
    -Force | Out-Null

$Task = Get-ScheduledTask -TaskName 'FBAutoposter-MessengerDrafts'
$Info = Get-ScheduledTaskInfo -TaskName 'FBAutoposter-MessengerDrafts'
[pscustomobject]@{
    TaskName = $Task.TaskName
    State = [string]$Task.State
    NextRunTime = if ($Info.NextRunTime) { $Info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss') } else { $null }
    ExecutionTimeLimit = [string]$Task.Settings.ExecutionTimeLimit
    Hidden = [bool]$Task.Settings.Hidden
    Execute = [string]$Task.Actions[0].Execute
    Arguments = [string]$Task.Actions[0].Arguments
    WorkingDirectory = [string]$Task.Actions[0].WorkingDirectory
} | ConvertTo-Json -Compress