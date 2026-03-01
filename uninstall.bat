@echo off
echo.
echo  LAN Remote - Uninstall
echo  ======================
echo.

REM ── Stop any running instance ──────────────────────────────────────────────
echo Stopping running server (if any)...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like '*lan-remote*server.py*' } | ForEach-Object { $_.Terminate() }"
echo Done.
echo.

REM ── Remove Task Scheduler entry ───────────────────────────────────────────
echo Removing startup task...
schtasks /delete /tn "LAN Remote" /f >nul 2>&1
if %errorlevel% equ 0 (
    echo        OK - LAN Remote will no longer start at login.
) else (
    echo        Task not found (already removed or never installed).
)

echo.
echo  Done. Python packages were NOT removed (shared with other tools).
echo  To also remove packages: pip uninstall fastapi uvicorn pynput pycaw comtypes zeroconf
echo.
pause
