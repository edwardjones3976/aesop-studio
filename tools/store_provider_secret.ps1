<#
.SYNOPSIS
  Store one provider API key in Studio's owner secret store (DPAPI, current Windows user only).

.DESCRIPTION
  Writes %USERPROFILE%\.codex\provider-mcp-secrets\<Name>.dpapi, the file Studio's metered routes read
  (openai.dpapi for the Codex API, xai.dpapi for the Grok API). The key is read from an interactive prompt
  (nothing echoed) or copied from a KEY=value line in an existing .env file. The value is never printed.

.EXAMPLE
  .\tools\store_provider_secret.ps1 -Name xai
  .\tools\store_provider_secret.ps1 -Name xai -FromEnvFile C:\Users\edwar\director-orchestrator\.env -Var XAI_API_KEY
#>
param(
  [Parameter(Mandatory)][ValidateSet("openai", "xai")][string]$Name,
  [string]$FromEnvFile,
  [string]$Var,
  [switch]$Force
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Security
$dir = Join-Path $env:USERPROFILE ".codex\provider-mcp-secrets"
$out = Join-Path $dir "$Name.dpapi"
if ((Test-Path $out) -and -not $Force) { throw "$out already exists; pass -Force to replace it" }
if ($FromEnvFile) {
  if (-not $Var) { throw "-Var is required with -FromEnvFile" }
  $line = Get-Content -LiteralPath $FromEnvFile | Where-Object { $_ -match "^$Var=\S+" } | Select-Object -First 1
  if (-not $line) { throw "no $Var= line in $FromEnvFile" }
  $key = ($line -replace "^$Var=", "").Trim().Trim('"')
} else {
  $sec = Read-Host -Prompt "Paste the $Name API key (hidden)" -AsSecureString
  $key = [Runtime.InteropServices.Marshal]::PtrToStringUni([Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($sec))
}
if (-not $key -or $key -match '\s') { throw "empty or malformed key" }
New-Item -ItemType Directory -Force $dir | Out-Null
$bytes = [Text.Encoding]::ASCII.GetBytes($key)
$enc = [Security.Cryptography.ProtectedData]::Protect($bytes, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
[IO.File]::WriteAllBytes($out, $enc)
$key = $null; $bytes = $null
Write-Host "Stored $Name key ($($enc.Length) encrypted bytes) at $out. Restart Studio (start.ps1) to pick it up."
