@echo off
REM Minimal make shim for `sam build --no-use-container` on Windows.
REM SAM invokes: make build-<FunctionLogicalId>
REM ARTIFACTS_DIR is set by the SAM CLI.

setlocal EnableExtensions
set "TARGET=%~1"

if "%TARGET%"=="" (
  echo make.cmd: missing target 1>&2
  exit /b 2
)

if "%ARTIFACTS_DIR%"=="" (
  echo make.cmd: ARTIFACTS_DIR is not set 1>&2
  exit /b 2
)

REM Resolve backend/ from this shim: tools\windows\make.cmd -> repo\backend
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "BACKEND=%REPO_ROOT%\backend"
set "PY=%BACKEND%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo make.cmd: %TARGET% -> %ARTIFACTS_DIR%
"%PY%" "%BACKEND%\scripts\package_lambda_for_sam.py" "%ARTIFACTS_DIR%"
exit /b %ERRORLEVEL%
