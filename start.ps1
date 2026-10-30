param(
  [int]$Port = 8765,
  [string]$Data = (Join-Path $env:LOCALAPPDATA "AesopStudio"),
  [switch]$NoBrowser,
  [switch]$Force
)
# $Port is the first port tried after preferred.port (the last port that actually served this data folder).
# preferred.port is not deleted: a new port is a new browser site and would hide the saved project list.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
. (Join-Path $root "scripts\studio-common.ps1")
New-Item -ItemType Directory -Force $Data | Out-Null
$state = Get-StudioState $Data
if ($state.Running) {
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($state.Pid)" -ErrorAction SilentlyContinue
  $started = if ($proc) { $proc.CreationDate } else { $null }
  $newest = Get-ChildItem (Join-Path $root "aesop_studio"), (Join-Path $root "static") -Recurse -File -Include *.py, *.js, *.html, *.css -ErrorAction SilentlyContinue |
    Measure-Object LastWriteTime -Maximum
  $stale = $started -and $newest.Maximum -and ($newest.Maximum - $started).TotalSeconds -gt 2
  if (-not $stale) {
    Write-Host "Aesop Studio is already running on port $($state.Port). Use open.ps1 (or the desktop shortcut) to sign in."
    exit 0
  }
  $health = Get-StudioHealth $state.Port
  if ($health -and $health.Busy) {
    $n = if ($health.Tasks -gt 0) { $health.Tasks } else { 1 }
    Write-Host "Studio is finishing $n tasks; retry in a minute"
    exit 0
  }
  if (-not $health -and -not $Force) {
    # Unknown is not idle: an older server without /api/health, a timeout or any probe error must never
    # become a forced kill of work in flight. The owner can override with -Force after checking the app.
    Write-Host "Could not confirm that the running Studio (port $($state.Port)) is idle; not stopping it. Re-run with -Force to replace it anyway."
    exit 1
  }
  Write-Host "Aesop Studio on port $($state.Port) is older than its files. Stopping that process."
  & (Join-Path $root "stop.ps1") -Data $Data
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$link = Join-Path $Data "launch-link.txt"
Remove-Item $link, (Join-Path $Data "server.port"), (Join-Path $Data "server.pid") -ErrorAction SilentlyContinue
$log = Join-Path $Data "server.log"
$p = Start-Process -FilePath "python" -ArgumentList @("-u", "-m", "aesop_studio", "--port", $Port, "--data", "`"$Data`"") `
  -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru
for ($i = 0; $i -lt 75 -and -not (Test-Path $link); $i++) {
  if ($p.HasExited) { break }
  Start-Sleep -Milliseconds 200
}
if (-not (Test-Path $link)) {
  $why = Get-Content "$log.err" -ErrorAction SilentlyContinue | Select-Object -Last 1
  Write-Error "Server did not start: $why (see $log.err)"
}
$state = Get-StudioState $Data  # server.pid is written by the server itself: the real process, not a launcher stub
Write-Host "Aesop Studio running on http://127.0.0.1:$($state.Port) (PID $($state.Pid))"
if (-not $NoBrowser) { Start-Process (Get-Content $link) }
