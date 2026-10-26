param([int]$Port = 0, [string]$Data = (Join-Path $env:LOCALAPPDATA "AesopStudio"))
# Stops the Studio server that owns this data directory, using the pid the server recorded itself.
# -Port is accepted for older callers and ignored: the server records its own port.
. (Join-Path $PSScriptRoot "scripts\studio-common.ps1")
$files = "server.pid", "server.port", "launch-link.txt" | ForEach-Object { Join-Path $Data $_ }
$state = Get-StudioState $Data
$srv = if ($state.Pid) { Get-CimInstance Win32_Process -Filter "ProcessId=$($state.Pid)" -ErrorAction SilentlyContinue }
if (-not $srv -or $srv.CommandLine -notmatch 'aesop_studio') {
  if ($state.Running) {
    Write-Host "A Studio answers on port $($state.Port) but its recorded pid ($($state.Pid)) is not it; nothing stopped."
    exit 1
  }
  Write-Host "Aesop Studio is not running."
  Remove-Item $files -ErrorAction SilentlyContinue
  exit 0
}
# Stop the launcher parent too when it is the same Studio command (Windows Store python launcher pattern).
$parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($srv.ParentProcessId)" -ErrorAction SilentlyContinue
$target = if ($parent -and $parent.CommandLine -match 'aesop_studio') { $parent.ProcessId } else { $srv.ProcessId }
taskkill /PID $target /T /F | Out-Null
Write-Host "Stopped Aesop Studio (PID $target)."
Remove-Item $files -ErrorAction SilentlyContinue
