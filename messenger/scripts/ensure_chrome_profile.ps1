# Own only the Messenger-dedicated, already-authorized Chrome Default profile.
# Never terminate another Chrome session or fall back to Guest/incognito.
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ProfileDir = 'C:\AI-Agent\chrome-profile-authenticated'
$Chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$Status = Join-Path $RepoRoot 'messenger\data\chrome_owner_status.json'
$DriveStatus = 'G:\マイドライブ\AI_Agents\Private\FBGroupAutoposter\messenger_chrome_status.json'
$state = [ordered]@{checked_at=(Get-Date).ToUniversalTime().ToString('o');profile='Default';running=$false;cdp_ready=$false;status='unknown'}
try {
    if (!(Test-Path -LiteralPath $ProfileDir)) {throw 'authenticated_profile_unavailable'}
    if (!(Test-Path -LiteralPath $Chrome)) {throw 'chrome_binary_missing'}
    $pattern = [regex]::Escape($ProfileDir)
    $existing = @(Get-CimInstance Win32_Process -Filter "name='chrome.exe'" | Where-Object {
      $_.CommandLine -match $pattern -and $_.CommandLine -notmatch '--type='
    })
    if ($existing.Count -eq 0) {
      Start-Process -FilePath $Chrome -ArgumentList @(
        "--user-data-dir=$ProfileDir",'--profile-directory=Default','--remote-debugging-port=0',
        '--no-first-run','--no-default-browser-check','https://www.messenger.com/'
      ) -WindowStyle Minimized
      $state.status = 'profile_started_minimized'
      Start-Sleep -Seconds 4
    } else {
      $state.status = 'profile_already_running'
    }
    $state.running = $true
    $portFile = Join-Path $ProfileDir 'DevToolsActivePort'
    if (Test-Path -LiteralPath $portFile) {
      $lines = @(Get-Content -LiteralPath $portFile -TotalCount 2)
      if ($lines.Count -ge 2 -and $lines[0] -match '^\d+$' -and $lines[1] -like '/devtools/browser/*') {
        try {
          $v = Invoke-RestMethod -Uri "http://127.0.0.1:$($lines[0])/json/version" -TimeoutSec 3
          $state.cdp_ready = ([string]$v.Browser -match 'Chrome')
        } catch { $state.status = 'browser_running_cdp_unreachable' }
      }
    }
    if ($state.cdp_ready) { $state.status = 'ready' }
} catch { $state.status = 'blocked'; $state.error = $_.Exception.Message }
$payload = $state | ConvertTo-Json -Depth 3
New-Item -ItemType Directory -Force -Path (Split-Path $Status) | Out-Null
[IO.File]::WriteAllText($Status, $payload, [Text.UTF8Encoding]::new($false))
try {
    New-Item -ItemType Directory -Force -Path (Split-Path $DriveStatus) | Out-Null
    [IO.File]::WriteAllText($DriveStatus, $payload, [Text.UTF8Encoding]::new($false))
} catch {}
Write-Output $payload
if (!$state.cdp_ready) {exit 2}
