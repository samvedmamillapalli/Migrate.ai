# Run API + UI locally (one process). From repo root:
#   .\dev.ps1
# Optional:
#   $env:DEV_PORT=8001; .\dev.ps1
#   .\dev.ps1 --port 8001

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$py = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  $py = "python"
}

& $py (Join-Path $Root "scripts\dev.py") @args
exit $LASTEXITCODE
