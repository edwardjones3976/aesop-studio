param([int]$Port = 8765, [string]$Data = (Join-Path $env:LOCALAPPDATA "AesopStudio"))
# Stops the Studio server that is actually listening on its loopback port (the pid file can be stale).
$pidFile = Join-Path $Data "server.pid"
$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $listener) {
  Write-Host "Aesop Studio is not running."
  Remove-Item $pidFile, (Join-Path $Data "launch-link.txt") -ErrorAction SilentlyContinue
  exit 0
}
$srv = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
if (-not $srv -or $srv.CommandLine -notmatch 'aesop_studio') {
  Write-Host "Port $Port is held by another program (PID $($listener.OwningProcess)); nothing stopped."
  exit 1
}
# Stop the launcher parent too when it is the same Studio command (Windows Store python launcher pattern).
$parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($srv.ParentProcessId)" -ErrorAction SilentlyContinue
$target = if ($parent -and $parent.CommandLine -match 'aesop_studio') { $parent.ProcessId } else { $srv.ProcessId }
taskkill /PID $target /T /F | Out-Null
Write-Host "Stopped Aesop Studio (PID $target)."
Remove-Item $pidFile, (Join-Path $Data "launch-link.txt") -ErrorAction SilentlyContinue
