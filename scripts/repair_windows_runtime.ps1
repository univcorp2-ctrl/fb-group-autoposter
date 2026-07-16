param(
    [string]$DriveArchive = 'G:\マイドライブ\0.物件資料_お客様紹介用\Estateboard'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$RuntimeRoot = Join-Path $env:LOCALAPPDATA 'FBGroupAutoposter'
$AppRoot = Join-Path $RuntimeRoot 'app'
$VenvRoot = Join-Path $RuntimeRoot '.venv'
$Python = Join-Path $VenvRoot 'Scripts\python.exe'
$RuntimeProfile = Join-Path $RuntimeRoot 'profiles\main'
$RuntimeData = Join-Path $RuntimeRoot 'data'
$RuntimeLogs = Join-Path $RuntimeRoot 'logs'

Write-Host "[1/8] Runtime root: $RuntimeRoot"
New-Item -ItemType Directory -Force -Path $RuntimeRoot, $AppRoot, $RuntimeProfile, $RuntimeData, $RuntimeLogs | Out-Null

Write-Host '[2/8] Removing Google Drive desktop.ini files from Git metadata'
$GitDir = Join-Path $RepoRoot '.git'
if (Test-Path $GitDir) {
    Get-ChildItem -Path $GitDir -Filter 'desktop.ini' -Recurse -Force -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

Write-Host '[3/8] Mirroring application code outside Google Drive'
$excludeDirs = @('.git', '.venv', 'profiles', 'logs', 'screenshots', '__pycache__', '.pytest_cache', '.ruff_cache')
$excludeFiles = @('jobs.db', 'pipeline.lock', 'desktop.ini')
$roboArgs = @($RepoRoot, $AppRoot, '/MIR', '/R:2', '/W:2', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/XD') + $excludeDirs + @('/XF') + $excludeFiles
& robocopy @roboArgs | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }

Write-Host '[4/8] Preserving existing Facebook profile and SQLite history'
$OldProfile = Join-Path $RepoRoot 'profiles\main'
if ((Test-Path $OldProfile) -and -not (Test-Path (Join-Path $RuntimeProfile 'Default'))) {
    & robocopy $OldProfile $RuntimeProfile /E /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "profile copy failed with exit code $LASTEXITCODE" }
}
$OldDb = Join-Path $RepoRoot 'data\jobs.db'
$NewDb = Join-Path $RuntimeData 'jobs.db'
if ((Test-Path $OldDb) -and -not (Test-Path $NewDb)) {
    Copy-Item $OldDb $NewDb -Force
}

Write-Host '[5/8] Creating isolated Python environment'
$Launcher = Get-Command py -ErrorAction SilentlyContinue
if ($Launcher) {
    & py -3.11 -m venv $VenvRoot
} else {
    & python -m venv $VenvRoot
}
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $AppRoot 'requirements.txt')

Write-Host '[6/8] Installing the Playwright Chromium required by this exact venv'
& $Python -m playwright install chromium

Write-Host '[7/8] Writing runtime launcher and environment'
$LauncherPath = Join-Path $RuntimeRoot 'run-task.ps1'
$launcherText = @'
param([Parameter(Mandatory=$true)][string]$Script)
$ErrorActionPreference = 'Stop'
$RuntimeRoot = Join-Path $env:LOCALAPPDATA 'FBGroupAutoposter'
$AppRoot = Join-Path $RuntimeRoot 'app'
$Python = Join-Path $RuntimeRoot '.venv\Scripts\python.exe'
$env:PROFILE_DIR = Join-Path $RuntimeRoot 'profiles\main'
$env:DB_PATH = Join-Path $RuntimeRoot 'data\jobs.db'
$env:INBOX_DIR = Join-Path $RuntimeRoot 'data\inbox'
$env:ESTATEBOARD_DRIVE_ROOT = '__DRIVE_ARCHIVE__'
Set-Location $AppRoot
& $Python $Script
exit $LASTEXITCODE
'@
$launcherText = $launcherText.Replace('__DRIVE_ARCHIVE__', $DriveArchive.Replace("'", "''"))
Set-Content -Path $LauncherPath -Value $launcherText -Encoding UTF8

Write-Host '[8/8] Registering repaired scheduled tasks'
function Register-FBTask {
    param([string]$Name, [string]$Script, [string]$At, [int]$RandomDelayMin = 0, [switch]$AtLogon)
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$LauncherPath`" -Script `"$Script`""
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $AppRoot
    $daily = New-ScheduledTaskTrigger -Daily -At $At
    if ($RandomDelayMin -gt 0) { $daily.RandomDelay = "PT${RandomDelayMin}M" }
    $triggers = @($daily)
    if ($AtLogon) {
        $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        $logon.Delay = 'PT4M'
        $triggers += $logon
    }
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $triggers -Settings $settings -Force | Out-Null
}

Register-FBTask -Name 'FBAutoposter-Keepalive' -Script 'scripts\keepalive.py' -At '08:00' -RandomDelayMin 20 -AtLogon
Register-FBTask -Name 'FBAutoposter-Morning' -Script 'scripts\run_daily_drive.py' -At '09:30' -RandomDelayMin 45 -AtLogon
Register-FBTask -Name 'FBAutoposter-Midday' -Script 'scripts\run_daily_drive.py' -At '13:00' -RandomDelayMin 30
Register-FBTask -Name 'FBAutoposter-Afternoon' -Script 'scripts\run_daily_drive.py' -At '16:30' -RandomDelayMin 30
Register-FBTask -Name 'FBAutoposter-Evening' -Script 'scripts\run_daily_drive.py' -At '20:30' -RandomDelayMin 45
Register-FBTask -Name 'FBAutoposter-Monitor-AM' -Script 'scripts\monitor.py' -At '12:00'
Register-FBTask -Name 'FBAutoposter-Monitor-PM' -Script 'scripts\monitor.py' -At '23:00'
Register-FBTask -Name 'FBAutoposter-StatusDB' -Script 'scripts\build_status_db.py' -At '09:15' -RandomDelayMin 10 -AtLogon
Register-FBTask -Name 'FBAutoposter-Verify' -Script 'scripts\verify_posts.py' -At '11:30' -RandomDelayMin 20
Register-FBTask -Name 'FBAutoposter-Verify-PM' -Script 'scripts\verify_posts.py' -At '21:30' -RandomDelayMin 20

Write-Host ''
Write-Host 'Repair completed.' -ForegroundColor Green
Write-Host "Runtime app: $AppRoot"
Write-Host "Profile:     $RuntimeProfile"
Write-Host "Database:    $NewDb"
Write-Host "Drive input: $DriveArchive"
Write-Host ''
Write-Host 'Run this dry diagnostic first:'
Write-Host "powershell -NoProfile -ExecutionPolicy Bypass -File `"$LauncherPath`" -Script scripts\preflight_drive.py"
Write-Host 'Then run one posting cycle:'
Write-Host "powershell -NoProfile -ExecutionPolicy Bypass -File `"$LauncherPath`" -Script scripts\run_daily_drive.py"
