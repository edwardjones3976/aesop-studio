# Shared by start.ps1, open.ps1 and stop.ps1. The server writes server.port and server.pid (its own pid) once it has
# bound; these helpers trust those files plus an HTTP probe, not netstat, because Windows sometimes reports a
# listener's owner as PID 0 and the Store python alias is a launcher stub whose pid is not the server's.

function Get-StudioHealth([int]$Port) {
  try {
    $req = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:$Port/api/health")
    $req.Timeout = 2000
    $resp = $req.GetResponse()
    $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
    $body = $reader.ReadToEnd()
    $reader.Close()
    $resp.Close()
    $j = $body | ConvertFrom-Json
    # A reply without an explicit busy field is unknown, not idle: the caller must then refuse to force-stop.
    if ($null -eq $j -or -not ($j.busy -is [bool])) { return $null }  # only an explicit true/false is an answer
    return @{ Busy = [bool]$j.busy; Tasks = [int]$j.tasks }
  } catch { return $null }
}

function Test-StudioPort([int]$Port) {
  # Studio answers every request with "Server: AesopStudio" (a 401 for an unsigned /api call is fine).
  try {
    $req = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:$Port/api/ping")
    $req.Timeout = 2000
    try { $resp = $req.GetResponse() } catch [System.Net.WebException] { $resp = $_.Exception.Response }
    if (-not $resp) { return $false }
    $ok = [string]$resp.Headers["Server"] -match '^AesopStudio'
    $resp.Close()
    return $ok
  } catch { return $false }
}

function Get-StudioState([string]$Data) {
  # Returns @{ Running; Port; Pid } for the Studio that owns this data directory.
  $portFile = Join-Path $Data "server.port"
  $pidFile = Join-Path $Data "server.pid"
  $port = if (Test-Path $portFile) { [int](Get-Content $portFile -Raw).Trim() } else { 0 }
  $procId = if (Test-Path $pidFile) { [int](Get-Content $pidFile -Raw).Trim() } else { 0 }
  $running = $port -gt 0 -and (Test-StudioPort $port)
  return @{ Running = $running; Port = $port; Pid = $procId }
}
