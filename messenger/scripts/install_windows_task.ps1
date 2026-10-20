# Register Messenger reply-draft daemon using the LIVE app runtime, not the stale Google Drive copy.
# Safety: the daemon NEVER sends Facebook messages. It only scans, drafts,
# and may write unsent text into the Messenger composer in the central Chrome.
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

# The daemon owns the 30-minute loop. Logon starts it; the daily trigger is a
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
    -Description 'Persistent Messenger reply-draft assistant: periodic scan, draft generation, composer placement, never sends' `
    -Force | Out-Null

# A separate, idempotent 30-minute watchdog ensures the authenticated Chrome
# profile is running. It never closes tabs or creates another profile.
$ChromeWatchScript = Join-Path $PSScriptRoot 'ensure_chrome_profile.ps1'
$ChromeTaskCommand = 'powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $ChromeWatchScript + '"'
& schtasks.exe /Create /TN 'FBAutoposter-MessengerChrome' /TR $ChromeTaskCommand /SC MINUTE /MO 30 /F | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Messenger Chrome watchdog registration failed: $LASTEXITCODE" }

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
