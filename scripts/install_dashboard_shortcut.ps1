$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $RepoRoot "open-facebook-analytics.cmd"
if (-not (Test-Path $Launcher)) {
    throw "Launcher not found: $Launcher"
}

$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Facebook投稿分析.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Launcher
$Shortcut.WorkingDirectory = $RepoRoot
$Shortcut.Description = "EstateBoard Facebook投稿分析ダッシュボードを開く"
$Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,167"
$Shortcut.Save()

Write-Host "Created desktop shortcut: $ShortcutPath"
