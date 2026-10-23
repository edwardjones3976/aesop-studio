# Fast offline test suite (no live CLI probes). Same env as tests/__init__.py.
$ErrorActionPreference = "Stop"
$env:AESOP_PROBE_OFFLINE = "1"
$env:AESOP_SIMULATED_ROUTE = "1"
Set-Location (Split-Path $PSScriptRoot -Parent)
python -W ignore -m unittest discover -s tests -p "test_*.py" -v @args
exit $LASTEXITCODE
