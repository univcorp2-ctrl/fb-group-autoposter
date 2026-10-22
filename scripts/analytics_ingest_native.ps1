# Windows Schannel transport for the private, user-owned EstateBoard analytics API.
# JSON arrives via stdin. Never place the token in command line arguments or logs.
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
try {
    $raw = [Console]::In.ReadToEnd()
    $inputObject = $raw | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace([string]$inputObject.token) -or [string]::IsNullOrWhiteSpace([string]$inputObject.payload.idempotency_key)) { throw 'INVALID_INPUT' }
    $headers = @{ 'Authorization' = 'Bearer ' + [string]$inputObject.token; 'Idempotency-Key' = [string]$inputObject.payload.idempotency_key }
    $json = ConvertTo-Json -InputObject $inputObject.payload -Depth 80 -Compress
    $response = Invoke-RestMethod -Uri 'https://estateboard.pages.dev/api/analytics/posts' -Method Post -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($json)) -TimeoutSec 25
    if (-not $response.ok) { throw 'API_REJECTED' }
    [Console]::Out.WriteLine('{"ok":true}')
    exit 0
} catch {
    $status = ''
    try { $status = [string][int]$_.Exception.Response.StatusCode } catch {}
    $typeName = $_.Exception.GetType().Name
    [Console]::Out.WriteLine((@{ok=$false; error_type=$typeName; http_status=$status} | ConvertTo-Json -Compress))
    exit 2
}
