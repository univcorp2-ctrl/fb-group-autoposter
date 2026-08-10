# Repair only the four long-running Facebook posting tasks.
# Does not touch Renotify/Bridge/Monitor tasks, so it is safe to invoke from
# the currently-running Renotify task during one-shot production recovery.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $Root '.venv\Scripts\pythonw.exe'
if (!(Test-Path $Python)) {
    $Python = Join-Path $Root '.venv\Scripts\python.exe'
}
if (!(Test-Path $Python)) { throw "Python runtime not found under $Root\.venv\Scripts" }

function Register-PostingTask {
    param(
        [string]$Name,
        [string]$At,
        [int]$RandomDelayMin,
        [string]$Desc,
        [switch]$AlsoAtLogon
    )
    $action = New-ScheduledTaskAction -Execute $Python -Argument 'scripts\run_daily.py' -WorkingDirectory $Root
    $daily = New-ScheduledTaskTrigger -Daily -At $At
    if ($RandomDelayMin -gt 0) { $daily.RandomDelay = "PT${RandomDelayMin}M" }
    $triggers = @($daily)
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
        -ExecutionTimeLimit (New-TimeSpan -Hours 8)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $triggers -Settings $settings -Description $Desc -Force | Out-Null
}

Register-PostingTask -Name 'FBAutoposter-Morning' -At '09:30' -RandomDelayMin 45 -Desc 'Post one fresh broker-OK property (morning + logon catch-up)' -AlsoAtLogon
Register-PostingTask -Name 'FBAutoposter-Midday' -At '13:00' -RandomDelayMin 30 -Desc 'Posting fallback (only posts if morning missed)'
Register-PostingTask -Name 'FBAutoposter-Afternoon' -At '16:30' -RandomDelayMin 30 -Desc 'Posting fallback (only posts if earlier runs missed)'
Register-PostingTask -Name 'FBAutoposter-Evening' -At '20:30' -RandomDelayMin 45 -Desc 'Posting fallback (only posts if earlier runs missed)'

$names = @('FBAutoposter-Morning','FBAutoposter-Midday','FBAutoposter-Afternoon','FBAutoposter-Evening')
$rows = foreach ($name in $names) {
    $task = Get-ScheduledTask -TaskName $name
    $info = Get-ScheduledTaskInfo -TaskName $name
    [pscustomobject]@{
        TaskName = $name
        State = [string]$task.State
        ExecutionTimeLimit = [string]$task.Settings.ExecutionTimeLimit
        Execute = [string]$task.Actions[0].Execute
        Arguments = [string]$task.Actions[0].Arguments
        NextRunTime = if ($info.NextRunTime) { $info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss') } else { $null }
    }
}
$rows | ConvertTo-Json -Depth 3
