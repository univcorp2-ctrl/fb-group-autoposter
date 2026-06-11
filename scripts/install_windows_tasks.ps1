$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (!(Test-Path $Python)) { $Python = 'python' }

$ActionPipeline = New-ScheduledTaskAction -Execute $Python -Argument "scripts\run_pipeline.py" -WorkingDirectory $Root
$TriggerPipeline = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName 'FBGroupAutoposter-Pipeline' -Action $ActionPipeline -Trigger $TriggerPipeline -Description 'Run approved posting pipeline hourly' -Force

$ActionApproval = New-ScheduledTaskAction -Execute $Python -Argument "scripts\approval_listener.py" -WorkingDirectory $Root
$TriggerApproval = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName 'FBGroupAutoposter-ApprovalPoll' -Action $ActionApproval -Trigger $TriggerApproval -Description 'Poll Telegram approval callbacks every 5 minutes' -Force

$ActionHealth = New-ScheduledTaskAction -Execute $Python -Argument "scripts\healthcheck.py" -WorkingDirectory $Root
$TriggerHealth = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(10) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName 'FBGroupAutoposter-Healthcheck' -Action $ActionHealth -Trigger $TriggerHealth -Description 'Check orchestrator heartbeat' -Force

Write-Host 'Registered tasks:'
Get-ScheduledTask -TaskName 'FBGroupAutoposter-*' | Select-Object TaskName, State
