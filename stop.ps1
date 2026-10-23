param([string]$Data = (Join-Path $env:LOCALAPPDATA "AesopStudio"))
$pidFile = Join-Path $Data "server.pid"
if (-not (Test-Path $pidFile)) { Write-Host "Aesop Studio is not running."; exit 0 }
$id = [int](Get-Content $pidFile)
$proc = Get-Process -Id $id -ErrorAction SilentlyContinue
if ($proc -and $proc.ProcessName -like "python*") { taskkill /PID $id /T /F | Out-Null; Write-Host "Stopped Aesop Studio (PID $id)." }
else { Write-Host "Recorded PID $id is not a running Studio server; nothing stopped." }
Remove-Item $pidFile, (Join-Path $Data "launch-link.txt") -ErrorAction SilentlyContinue
