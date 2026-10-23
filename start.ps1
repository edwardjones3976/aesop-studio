param(
  [int]$Port = 8765,
  [string]$Data = (Join-Path $env:LOCALAPPDATA "AesopStudio"),
  [switch]$NoBrowser
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
New-Item -ItemType Directory -Force $Data | Out-Null
$pidFile = Join-Path $Data "server.pid"
if (Test-Path $pidFile) {
  $old = Get-Content $pidFile
  if (Get-Process -Id $old -ErrorAction SilentlyContinue) { Write-Host "Aesop Studio already running (PID $old)."; exit 0 }
}
$link = Join-Path $Data "launch-link.txt"
Remove-Item $link -ErrorAction SilentlyContinue
$log = Join-Path $Data "server.log"
$p = Start-Process -FilePath "python" -ArgumentList @("-m", "aesop_studio", "--port", $Port, "--data", "`"$Data`"") `
  -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru
Set-Content $pidFile $p.Id
for ($i = 0; $i -lt 50 -and -not (Test-Path $link); $i++) { Start-Sleep -Milliseconds 200 }
if (-not (Test-Path $link)) { Write-Error "Server did not start; see $log.err" }
Write-Host "Aesop Studio running on http://127.0.0.1:$Port (PID $($p.Id))"
if (-not $NoBrowser) { Start-Process (Get-Content $link) }
