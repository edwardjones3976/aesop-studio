param([int]$Port = 8765, [string]$Data = (Join-Path $env:LOCALAPPDATA "AesopStudio"))
# One-click open + sign-in. If Studio is running, ask it (via a file only this Windows user can write) for a fresh
# one-time sign-in link and open it; otherwise start Studio, which opens its own link.
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "scripts\studio-common.ps1")
$link = Join-Path $Data "launch-link.txt"
# Running = the port Studio recorded answers as Studio (netstat and the pid file alone are not trustworthy).
$state = Get-StudioState $Data
if (-not $state.Running) { & (Join-Path $PSScriptRoot "start.ps1") -Port $Port -Data $Data; exit $LASTEXITCODE }
$before = if (Test-Path $link) { Get-Content $link -Raw } else { "" }
New-Item -ItemType File -Force (Join-Path $Data "relogin.request") | Out-Null
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 250
  $now = if (Test-Path $link) { Get-Content $link -Raw } else { "" }
  if ($now -and $now -ne $before) { Start-Process $now.Trim(); exit 0 }
}
Write-Error "Studio is running but did not issue a new sign-in link; try stop.ps1 then start.ps1."
