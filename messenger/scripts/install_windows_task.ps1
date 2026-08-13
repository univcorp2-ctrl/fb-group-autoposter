# Register the Messenger reply-draft assistant as a conservative read-only task.
# It NEVER sends Facebook messages. messenger/.env must keep:
#   READ_ONLY=true
#   WRITE_DRAFT_TO_FB=false
#   HEADLESS=false
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Python = Join-Path $RepoRoot '.venv\Scripts\pythonw.exe'
if (!(Test-Path $Python)) {
    $Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
}
if (!(Test-Path $Python)) {
    throw "Python runtime not found: $Python"
}

$Action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument 'messenger\scripts\run_once.py' `
    -WorkingDirectory $RepoRoot

$Daily = New-ScheduledTaskTrigger -Daily -At '07:30'
$Repeat = New-ScheduledTaskTrigger -Once -At '07:30' `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Hours 16)
$Daily.Repetition = $Repeat.Repetition

$Logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Logon.Delay = 'PT5M'

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask `
    -TaskName 'FBAutoposter-MessengerDrafts' `
    -Action $Action `
    -Trigger @($Daily, $Logon) `
    -Settings $Settings `
    -Description 'Hourly read-only Facebook Messenger scan and reply-draft generation; never sends messages' `
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
