# Hidden Windows-native pump, no ChatGPT scheduler.
$ErrorActionPreference = 'Stop'
$App = Split-Path -Parent $PSScriptRoot
$Py = 'C:\Users\t0015\AppData\Local\FBGroupAutoposter\.venv\Scripts\pythonw.exe'
$Runner = Join-Path $App 'scripts\facebook_recovery_pump.py'
if (!(Test-Path -LiteralPath $Py)) { throw "pythonw unavailable: $Py" }
if (!(Test-Path -LiteralPath $Runner)) { throw "pump unavailable: $Runner" }
$name = 'FBAutoposter-RecoveryPump'
$action=New-ScheduledTaskAction -Execute $Py -Argument ('"{0}"' -f $Runner) -WorkingDirectory $App
$trigger=New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 8) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Output "Registered hidden Windows task $name, every 30 minutes, no overlap"
