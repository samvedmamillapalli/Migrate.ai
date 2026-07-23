# Fresh restart: stop whatever is on DEV_PORT, clear stale env, start API + UI.
# From repo root:
#   .\restart.ps1
# Optional:
#   $env:DEV_PORT=8001; .\restart.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$py = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  $py = "python"
}

& $py (Join-Path $Root "scripts\dev.py") restart @args
exit $LASTEXITCODE
