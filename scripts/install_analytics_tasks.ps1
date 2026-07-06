$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

$SyncScript = Join-Path $RepoRoot "scripts\sync_analytics.py"
$MetricsScript = Join-Path $RepoRoot "scripts\collect_post_metrics.py"
$SyncCommand = '"{0}" "{1}"' -f $Python, $SyncScript
$MetricsCommand = '"{0}" "{1}"' -f $Python, $MetricsScript

schtasks.exe /Create /TN "FBGroupAutoposter-AnalyticsSync" /TR $SyncCommand /SC HOURLY /MO 1 /F | Out-Host
schtasks.exe /Create /TN "FBGroupAutoposter-MetricsCollect" /TR $MetricsCommand /SC DAILY /ST 00:30 /F | Out-Host

Write-Host "Registered: FBGroupAutoposter-AnalyticsSync (hourly)"
Write-Host "Registered: FBGroupAutoposter-MetricsCollect (daily 00:30 local time)"
