@echo off
REM Post-install self check for dsh-seekmemory.
REM
REM Runs the dsh CLI with --dump-config against an isolated DSH_HOME and then
REM asks node to verify that this plugin was really assembled into the profile.
REM
REM Why a .cmd: node spawning the exe with piped stdio hits EPERM under the
REM Windows sandbox, so the exe is invoked by the shell and node only reads
REM the dump file.
REM
REM Windows-only helper. On other platforms run the two steps manually:
REM   1) dsh --dump-config --profile <p>  (with DSH_HOME set) > dump.yml
REM   2) node scripts/check-installed.mjs --dump dump.yml --expect dsh-seekmemory
REM
REM Usage:
REM   set DSH_EXE_OVERRIDE=C:\path\to\DeepSeek Harness.exe
REM   postinstall-check.cmd [profile] [dsh_home]
REM Defaults: profile=web  dsh_home=%~dp0..\.tmp\check-home
REM Exit codes: 0 assembled, 1 not assembled / skipped, 2 setup problem.

setlocal enableextensions

set "PROFILE=%~1"
if "%PROFILE%"=="" set "PROFILE=web"

set "HOME_DIR=%~2"
if "%HOME_DIR%"=="" set "HOME_DIR=%~dp0..\.tmp\check-home"

REM No hard-coded install path: the caller supplies the DSH executable.
set "DSH_EXE=%DSH_EXE_OVERRIDE%"
if not defined DSH_EXE (
  echo FAIL  DSH executable not supplied.
  echo       set DSH_EXE_OVERRIDE=C:\path\to\DeepSeek Harness.exe
  exit /b 2
)
if not exist "%DSH_EXE%" (
  echo FAIL  dsh executable not found: %DSH_EXE%
  exit /b 2
)

REM CLI entry defaults to a sibling of the executable; override when it lives elsewhere.
set "DSH_CLI=%DSH_CLI_OVERRIDE%"
if not defined DSH_CLI (
  for %%I in ("%DSH_EXE%") do set "DSH_CLI=%%~dpIresources\app.asar\dsh\node_modules\@deepseek-ai\dsh\lib\bin.js"
)
if not exist "%DSH_CLI%" (
  echo FAIL  dsh CLI entry not found: %DSH_CLI%
  echo       set DSH_CLI_OVERRIDE to point at app.asar\dsh\node_modules\@deepseek-ai\dsh\lib\bin.js
  exit /b 2
)

if not exist "%HOME_DIR%" mkdir "%HOME_DIR%" >nul 2>nul
set "DUMP=%HOME_DIR%\postinstall-dump.yml"

echo [1/2] dump-config  profile=%PROFILE%  home=%HOME_DIR%
set "ELECTRON_RUN_AS_NODE=1"
set "DSH_HOME=%HOME_DIR%"
"%DSH_EXE%" "%DSH_CLI%" --dump-config --profile %PROFILE% > "%DUMP%" 2>"%HOME_DIR%\postinstall-dump.err"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo FAIL  dump-config exited %RC%
  type "%HOME_DIR%\postinstall-dump.err"
  exit /b 2
)

echo [2/2] verify composed tree
node "%~dp0check-installed.mjs" --dump "%DUMP%" --expect dsh-seekmemory
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
  echo.
  echo OK: dsh-seekmemory is assembled in profile "%PROFILE%".
) else (
  echo.
  echo NOT OK: see message above. Dump kept at:
  echo   %DUMP%
)
exit /b %RC%
