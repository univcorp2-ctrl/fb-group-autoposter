# Repository-owned Windows scheduling; never uses ChatGPT Tasks/Automations.
$ErrorActionPreference = 'Stop'
$RuntimeRoot = Join-Path $env:LOCALAPPDATA 'FBGroupAutoposter'
$AppRoot = Join-Path $RuntimeRoot 'app'
$Launcher = Join-Path $RuntimeRoot 'run-task.ps1'
if (!(Test-Path $Launcher)) { throw "Windows autoposter launcher missing: $Launcher" }

$jobs = @(
  @{ Name='FBAutoposter-AnalyticsSync'; Script='scripts\sync_analytics_incremental.py' },
  @{ Name='FBAutoposter-Post10Monitor'; Script='scripts\verify_post10_estateboard.py' }
)
foreach ($job in $jobs) {
    $command = 'powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Script "{1}"' -f $Launcher, $job.Script
    & schtasks.exe /Create /TN $job.Name /TR $command /SC HOURLY /MO 1 /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Unable to register $($job.Name): $LASTEXITCODE" }
    Write-Output "Registered Windows hourly schedule: $($job.Name)"
}
