# Native SAM build on Windows (no Docker required).
# Requires GNU make (winget install -e --id ezwinports.make).
#
# Template CodeUri is infra/sam/lambda_src (thin) so CustomMakeBuilder CopySource
# does not copy backend/.venv / .pytest_cache (Access Denied on Windows/OneDrive).
# BACKEND is set to an absolute path so the Makefile works from SAM's temp scratch.
#
# Usage:
#   .\infra\sam\build.ps1
#   cd infra\sam; .\build.ps1

$ErrorActionPreference = "Stop"
$SamDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $SamDir "..\..")
$Backend = Join-Path $RepoRoot "backend"

# Refresh PATH for packages installed in this session (e.g. ezwinports.make).
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
  [System.Environment]::GetEnvironmentVariable("Path", "User")

$make = Get-Command make.exe -ErrorAction SilentlyContinue
if (-not $make) {
  throw "make.exe not found. Install with: winget install -e --id ezwinports.make"
}

$env:BACKEND = $Backend
Set-Location $SamDir

# SAM deletes .aws-sam\build on enter; OneDrive/Windows often locks dist-info
# files and raises WinError 5. Pre-clean (or rename aside) so build can proceed.
$buildDir = Join-Path $SamDir ".aws-sam\build"
if (Test-Path $buildDir) {
  Write-Host "Cleaning $buildDir ..."
  Get-ChildItem -LiteralPath $buildDir -Recurse -Force -ErrorAction SilentlyContinue |
    ForEach-Object { try { $_.Attributes = "Normal" } catch {} }
  try {
    Remove-Item -LiteralPath $buildDir -Recurse -Force -ErrorAction Stop
  } catch {
    $stale = "build.stale.{0}" -f (Get-Date -Format "yyyyMMddHHmmss")
    Write-Host "Delete blocked ($($_.Exception.Message)) - renaming to $stale"
    Rename-Item -LiteralPath $buildDir -NewName $stale -Force
  }
}

Write-Host "Using make: $($make.Source)"
Write-Host "BACKEND=$env:BACKEND"
Write-Host "Running: sam build --no-use-container"
& sam build --no-use-container @args
exit $LASTEXITCODE
