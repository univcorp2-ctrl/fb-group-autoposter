param(
  [string]$DriveArchive = 'G:\マイドライブ\0.物件資料_お客様紹介用\Estateboard',
  [string]$EstateBoardSource = 'G:\マイドライブ\AI_Agents\github\repos\EstateBoard\output\received\properties.json',
  [ValidateSet('existing','codex')][string]$PostTextProvider = 'existing'
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

Write-Host '[1/9] Create Drive-safe local runtime'
New-Item -ItemType Directory -Force -Path $RuntimeRoot,$AppRoot,$RuntimeProfile,$RuntimeData,$RuntimeLogs | Out-Null

Write-Host '[2/9] Remove Google Drive desktop.ini files from Git metadata'
$GitDir = Join-Path $RepoRoot '.git'
if (Test-Path $GitDir) {
  Get-ChildItem -Path $GitDir -Filter 'desktop.ini' -Recurse -Force -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
}

Write-Host '[3/9] Mirror application code outside Google Drive'
$excludeDirs = @('.git','.venv','profiles','logs','screenshots','__pycache__','.pytest_cache','.ruff_cache')
$excludeFiles = @('jobs.db','pipeline.lock','desktop.ini')
$roboArgs = @($RepoRoot,$AppRoot,'/MIR','/R:2','/W:2','/NFL','/NDL','/NJH','/NJS','/NP','/XD') + $excludeDirs + @('/XF') + $excludeFiles
& robocopy @roboArgs | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed: $LASTEXITCODE" }

Write-Host '[4/9] Preserve Facebook profile and SQLite history'
$OldProfile = Join-Path $RepoRoot 'profiles\main'
if ((Test-Path $OldProfile) -and -not (Test-Path (Join-Path $RuntimeProfile 'Default'))) {
  & robocopy $OldProfile $RuntimeProfile /E /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "profile copy failed: $LASTEXITCODE" }
}
$OldDb = Join-Path $RepoRoot 'data\jobs.db'
$NewDb = Join-Path $RuntimeData 'jobs.db'
if ((Test-Path $OldDb) -and -not (Test-Path $NewDb)) { Copy-Item $OldDb $NewDb -Force }

Write-Host '[5/9] Rebuild isolated Python environment'
if (!(Test-Path $Python)) {
  if (Get-Command py -ErrorAction SilentlyContinue) { & py -3.11 -m venv $VenvRoot }
  else { & python -m venv $VenvRoot }
}
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $AppRoot 'requirements.txt')

Write-Host '[6/9] Install the Chromium matching this venv'
& $Python -m playwright install chromium

Write-Host '[7/9] Optionally install Codex CLI'
if ($PostTextProvider -eq 'codex' -and -not (Get-Command codex -ErrorAction SilentlyContinue)) {
  if (Get-Command npm -ErrorAction SilentlyContinue) { & npm install -g '@openai/codex' }
  else { Write-Warning 'npm is unavailable. Codex provider will fall back to deterministic templates.' }
}

Write-Host '[8/9] Write runtime launcher'
$LauncherPath = Join-Path $RuntimeRoot 'run-task.ps1'
$provider = if ($PostTextProvider -eq 'codex') { 'codex' } else { '' }
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
$env:ESTATEBOARD_SOURCE = '__ESTATEBOARD_SOURCE__'
$env:STATUS_REPO_ROOT = '__REPO_ROOT__'
$env:RUNTIME_STATUS_WEB_PATH = Join-Path '__REPO_ROOT__' 'site\data\status.json'
$env:PUBLISH_STATUS_GIT = '1'
$env:POST_TEXT_PROVIDER = '__PROVIDER__'
Set-Location $AppRoot
& $Python $Script
exit $LASTEXITCODE
'@
$launcherText = $launcherText.Replace('__DRIVE_ARCHIVE__',$DriveArchive.Replace("'","''"))
$launcherText = $launcherText.Replace('__ESTATEBOARD_SOURCE__',$EstateBoardSource.Replace("'","''"))
$launcherText = $launcherText.Replace('__REPO_ROOT__',$RepoRoot.Replace("'","''"))
$launcherText = $launcherText.Replace('__PROVIDER__',$provider)
Set-Content -Path $LauncherPath -Value $launcherText -Encoding UTF8

Write-Host '[9/9] Register production scheduled tasks'
function Register-FBTask {
  param([string]$Name,[string]$Script,[string]$At,[int]$RandomDelayMin=0,[switch]$AtLogon)
  $args = "-NoProfile -ExecutionPolicy Bypass -File `"$LauncherPath`" -Script `"$Script`""
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $args -WorkingDirectory $AppRoot
  $daily = New-ScheduledTaskTrigger -Daily -At $At
  if ($RandomDelayMin -gt 0) { $daily.RandomDelay = "PT${RandomDelayMin}M" }
  $triggers = @($daily)
  if ($AtLogon) {
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $logon.Delay = 'PT4M'
    $triggers += $logon
  }
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
  Register-ScheduledTask -TaskName $Name -Action $action -Trigger $triggers -Settings $settings -Description 'Drive-safe Facebook property autoposter' -Force | Out-Null
}
Register-FBTask 'FBAutoposter-Keepalive' 'scripts\keepalive.py' '08:00' 20 -AtLogon
Register-FBTask 'FBAutoposter-Morning' 'scripts\run_daily_drive.py' '09:30' 45 -AtLogon
Register-FBTask 'FBAutoposter-Midday' 'scripts\run_daily_drive.py' '13:00' 30
Register-FBTask 'FBAutoposter-Afternoon' 'scripts\run_daily_drive.py' '16:30' 30
Register-FBTask 'FBAutoposter-Evening' 'scripts\run_daily_drive.py' '20:30' 45
Register-FBTask 'FBAutoposter-Verify' 'scripts\verify_posts.py' '11:30' 20
Register-FBTask 'FBAutoposter-Verify-PM' 'scripts\verify_posts.py' '21:30' 20
Register-FBTask 'FBAutoposter-Monitor-AM' 'scripts\monitor.py' '12:00'
Register-FBTask 'FBAutoposter-Monitor-PM' 'scripts\monitor.py' '23:00'

& $Python (Join-Path $AppRoot 'scripts\preflight_drive.py')
& $Python -m pytest -q (Join-Path $AppRoot 'tests\test_drive_assets.py') (Join-Path $AppRoot 'tests\test_runtime_status.py') (Join-Path $AppRoot 'tests\test_codex_provider.py')
Write-Host 'Repair completed.' -ForegroundColor Green
Write-Host "Runtime: $RuntimeRoot"
Write-Host "Launcher: $LauncherPath"
Write-Host "Dashboard source: $(Join-Path $RepoRoot 'site\data\status.json')"
