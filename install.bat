@echo off
setlocal EnableDelayedExpansion

echo.
echo  LAN Remote - Setup
echo  ==================
echo.

REM ── Check Python ──────────────────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found in PATH.
    echo         Download from: https://python.org
    echo         Make sure to check "Add Python to PATH" during install.
    pause & exit /b 1
)
for /f "tokens=*" %%V in ('python --version 2^>^&1') do echo         Found: %%V
echo.

REM ── Install pip packages ──────────────────────────────────────────────────
echo [1/2] Installing Python dependencies...
pip install -r "%~dp0requirements.txt"
if %errorlevel% neq 0 (
    echo [ERROR] pip install failed. See errors above.
    pause & exit /b 1
)
echo        OK.
echo.

REM ── Find pythonw.exe (runs without a console window) ─────────────────────
for /f "delims=" %%P in ('python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYTHONW=%%P"
if not exist "!PYTHONW!" (
    REM Fallback: use python.exe (a brief console window may flash at startup)
    for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)"') do set "PYTHONW=%%P"
)

set "SCRIPT=%~dp0server.py"

REM ── Register Task Scheduler: run at logon, silently, auto-restart ─────────
echo [2/2] Registering startup task (runs at Windows login)...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$exe  = '!PYTHONW:\=\\!'; " ^
  "$args = '\"!SCRIPT:\=\\!\"'; " ^
  "$wd   = '!~dp0'; if ($wd.EndsWith('\')) { $wd = $wd.TrimEnd('\') }; $wd = $wd -replace '\\\\','\\'; " ^
  "$a = New-ScheduledTaskAction -Execute $exe -Argument $args -WorkingDirectory '%~dp0'; " ^
  "$t = New-ScheduledTaskTrigger -AtLogon -User $env:USERNAME; " ^
  "$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable $true; " ^
  "$p = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest -LogonType Interactive; " ^
  "Register-ScheduledTask -TaskName 'LAN Remote' -Action $a -Trigger $t -Settings $s -Principal $p -Force | Out-Null; " ^
  "Write-Host '       OK - will auto-start at next login.'"

if %errorlevel% neq 0 (
    echo.
    echo [WARN] Task Scheduler registration failed.
    echo        Right-click install.bat and choose "Run as administrator", then retry.
    echo.
    echo        You can still run the server manually with:
    echo          python "%~dp0server.py"
)

echo.
echo  ============================================================
echo   Setup complete!
echo  ============================================================
echo.
echo   LAN Remote will start automatically every time you log in.
echo.
echo   To start it RIGHT NOW without rebooting, press Y below.
echo.
set /p START="  Start server now? [Y/N]: "
if /i "!START!"=="Y" (
    echo.
    echo   Starting in background...
    start "" "!PYTHONW!" "%~dp0server.py"
    echo   Started. Check lan-remote.log for the connection URL.
    echo   (or open Task Manager to verify pythonw.exe is running)
)
echo.
pause
