# Repair the Windows runtime used by fb-group-autoposter.
# Run from PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\repair_windows_runtime.ps1

[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipTaskRegistration
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Write-Step([string]$Message) {
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Set-DotEnvValue([string]$Path, [string]$Name, [string]$Value) {
    $lines = @()
    if (Test-Path $Path) {
        $lines = @(Get-Content -LiteralPath $Path -Encoding UTF8)
    }
    $escaped = [Regex]::Escape($Name)
    $replacement = "$Name=$Value"
    $found = $false
    $updated = foreach ($line in $lines) {
        if ($line -match "^$escaped=") {
            $found = $true
            $replacement
        } else {
            $line
        }
    }
    if (-not $found) {
        $updated += $replacement
    }
    Set-Content -LiteralPath $Path -Value $updated -Encoding UTF8
}

Write-Step 'Validate repository and remove Google Drive desktop.ini Git refs'
if (-not (Test-Path (Join-Path $Root '.git'))) {
    throw "Git repository not found: $Root"
}
Get-ChildItem -LiteralPath (Join-Path $Root '.git\refs') -Filter 'desktop.ini' -Recurse -Force -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
$packedRefs = Join-Path $Root '.git\packed-refs'
if (Test-Path $packedRefs) {
    $clean = Get-Content -LiteralPath $packedRefs | Where-Object { $_ -notmatch 'desktop\.ini' }
    Set-Content -LiteralPath $packedRefs -Value $clean -Encoding ASCII
}
& git fsck --no-reflogs
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'git fsck reported problems. Posting repair will continue; reclone may still be required.'
}

Write-Step 'Create or repair Python virtual environment'
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    & py -3.11 -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) {
        & python -m venv (Join-Path $Root '.venv')
    }
}
if (-not (Test-Path $VenvPython)) {
    throw 'Unable to create .venv. Install Python 3.11 or newer.'
}
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt

Write-Step 'Install the exact Playwright Chromium required by this virtual environment'
& $VenvPython -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    throw 'Playwright Chromium installation failed.'
}

Write-Step 'Move the persistent browser profile outside Google Drive sync'
$LocalBase = Join-Path $env:LOCALAPPDATA 'fb-group-autoposter'
$LocalProfile = Join-Path $LocalBase 'profile'
New-Item -ItemType Directory -Force -Path $LocalProfile | Out-Null
$OldProfile = Join-Path $Root 'profiles\main'
if ((Test-Path $OldProfile) -and -not (Test-Path (Join-Path $LocalProfile 'Default'))) {
    Write-Host "Copying existing Facebook session profile to $LocalProfile"
    & robocopy $OldProfile $LocalProfile /E /COPY:DAT /R:2 /W:2 /XD Cache Code` Cache GPUCache DawnCache GrShaderCache /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) {
        throw "Profile copy failed (robocopy exit code $LASTEXITCODE)."
    }
}
$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) {
    Copy-Item (Join-Path $Root '.env.example') $EnvPath
}
Set-DotEnvValue -Path $EnvPath -Name 'PROFILE_DIR' -Value $LocalProfile
Set-DotEnvValue -Path $EnvPath -Name 'ESTATEBOARD_SOURCE' -Value 'G:\マイドライブ\AI_Agents\github\repos\EstateBoard\output\received\properties.json'
Set-DotEnvValue -Path $EnvPath -Name 'ESTATEBOARD_DRIVE_ROOT' -Value 'G:\マイドライブ\0.物件資料_お客様紹介用\Estateboard'

Write-Step 'Run runtime preflight'
& $VenvPython scripts\runtime_preflight.py
if ($LASTEXITCODE -ne 0) {
    throw 'Runtime preflight failed. Review the messages above.'
}

if (-not $SkipTests) {
    Write-Step 'Run safe tests (no Facebook post)'
    & $VenvPython -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw 'Tests failed; scheduled posting was not re-registered.'
    }
    & $VenvPython scripts\run_pipeline.py --selftest
    if ($LASTEXITCODE -ne 0) {
        throw 'Dry-run selftest failed; scheduled posting was not re-registered.'
    }
}

if (-not $SkipTaskRegistration) {
    Write-Step 'Re-register Windows scheduled tasks with repaired Python runtime'
    & powershell -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1
    if ($LASTEXITCODE -ne 0) {
        throw 'Windows task registration failed.'
    }
}

Write-Step 'Repair completed'
Write-Host "Profile: $LocalProfile"
Write-Host 'Next verification commands:'
Write-Host "  & '$VenvPython' scripts\keepalive.py"
Write-Host "  & '$VenvPython' scripts\run_daily.py"
Write-Host 'If Facebook requests login/checkpoint, run scripts\login_once.py once in the interactive session.'
