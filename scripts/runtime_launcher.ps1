param([Parameter(Mandatory=$true)][string]$Script)
$ErrorActionPreference = 'Stop'
$RuntimeRoot = Join-Path $env:LOCALAPPDATA 'FBGroupAutoposter'
$AppRoot = Join-Path $RuntimeRoot 'app'
$Python = Join-Path $RuntimeRoot '.venv\Scripts\python.exe'
$env:PROFILE_DIR = Join-Path $RuntimeRoot 'profiles\main'
$env:DB_PATH = Join-Path $RuntimeRoot 'data\jobs.db'
$env:INBOX_DIR = Join-Path $RuntimeRoot 'data\inbox'
$env:ESTATEBOARD_DRIVE_ROOT = 'G:\マイドライブ\0.物件資料_お客様紹介用\Estateboard'
# The EstateBoard daily pipeline writes the authoritative fresh source here.
$env:ESTATEBOARD_SOURCE = 'C:\AI-Agent\EstateBoard\output\received\properties.json'
$env:STATUS_REPO_ROOT = 'G:\マイドライブ\AI_Agents\github\repos\fb-group-autoposter'
$env:RUNTIME_STATUS_WEB_PATH = Join-Path $env:STATUS_REPO_ROOT 'site\data\status.json'
$env:PUBLISH_STATUS_GIT = '1'
# Codex failures produced unbound generation without approval fingerprints, so
# use the deterministic source-bound generator until the Codex integration is fixed.
$env:POST_TEXT_PROVIDER = 'template'
if (!(Test-Path -LiteralPath $env:ESTATEBOARD_SOURCE)) { throw "EstateBoard source missing: $env:ESTATEBOARD_SOURCE" }
Set-Location $AppRoot
& $Python $Script
exit $LASTEXITCODE
