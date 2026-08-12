# Idempotently register the three reliability/safety tasks that complement the
# normal Morning/Midday/Afternoon/Evening Facebook posting schedule.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $Root '.venv\Scripts\pythonw.exe'
if (!(Test-Path $Python)) { $Python = Join-Path $Root '.venv\Scripts\python.exe' }
if (!(Test-Path $Python)) { throw "Python runtime not found: $Python" }

function Register-HiddenTask {
    param(
        [string]$Name,
        [string]$Script,
        $Trigger,
        [int]$ExecutionMinutes,
        [string]$Description
    )
    $action = New-ScheduledTaskAction -Execute $Python -Argument "scripts\$Script" -WorkingDirectory $Root
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -WakeToRun `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew `
        -Hidden `
        -ExecutionTimeLimit (New-TimeSpan -Minutes $ExecutionMinutes)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $Trigger -Settings $settings -Description $Description -Force | Out-Null
}

$community = New-ScheduledTaskTrigger -Daily -At '06:20' -RandomDelay (New-TimeSpan -Minutes 20)
Register-HiddenTask -Name 'FBAutoposter-CommunityManager' -Script 'community_manager.py' -Trigger $community -ExecutionMinutes 30 -Description 'Safely expand and validate Facebook communities'

$guarantee = New-ScheduledTaskTrigger -Daily -At '22:10'
$guaranteeRep = New-ScheduledTaskTrigger -Once -At '22:10' -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Minutes 45)
$guarantee.Repetition = $guaranteeRep.Repetition
Register-HiddenTask -Name 'FBAutoposter-DailyGuarantee' -Script 'ensure_daily_post.py' -Trigger $guarantee -ExecutionMinutes 25 -Description 'If today has zero confirmed posts, safely attempt one final post'

$web = New-ScheduledTaskTrigger -Daily -At '23:10'
$webRep = New-ScheduledTaskTrigger -Once -At '23:10' -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Minutes 60)
$web.Repetition = $webRep.Repetition
Register-HiddenTask -Name 'FBAutoposter-WebSLO' -Script 'verify_estateboard_web.py' -Trigger $web -ExecutionMinutes 15 -Description 'Verify confirmed Facebook permalinks are reflected on EstateBoard Pages'

$names = @('FBAutoposter-CommunityManager','FBAutoposter-DailyGuarantee','FBAutoposter-WebSLO')
$rows = foreach ($name in $names) {
    $task = Get-ScheduledTask -TaskName $name
    $info = Get-ScheduledTaskInfo -TaskName $name
    [pscustomobject]@{
        TaskName = $name
        State = [string]$task.State
        NextRunTime = if ($info.NextRunTime) { $info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss') } else { $null }
        ExecutionTimeLimit = [string]$task.Settings.ExecutionTimeLimit
        Hidden = [bool]$task.Settings.Hidden
        Execute = [string]$task.Actions[0].Execute
        Arguments = [string]$task.Actions[0].Arguments
        WorkingDirectory = [string]$task.Actions[0].WorkingDirectory
    }
}
$rows | ConvertTo-Json -Depth 3
