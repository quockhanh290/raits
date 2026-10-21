@echo off
REM ---------------------------------------------------------------------------
REM monitor\autostart_ops.cmd - bring the scheduler back after the machine reboots.
REM
REM Why this exists, measured: on 2026-09-15 at 17:27 local a planned Windows
REM "Operating System: Upgrade" restart (System event 1074, TrustedInstaller)
REM killed run_scheduler. The machine booted again at 19:49 and NOTHING started
REM it - no scheduled task, no Startup shortcut, no Run key. It stayed dead
REM until an operator typed `ops up` by hand at 2026-09-17 06:54, which cost the
REM whole 2026-09-16 session plus that night's NKD window.
REM
REM `ops up` is the right command to run unattended: it replaces the scheduler
REM ONLY when --restart-scheduler is passed, so a healthy one is left alone, and
REM its process scan fails CLOSED - a scan it cannot complete refuses rather
REM than launching a second instance. Two schedulers sharing clientId=1 is how
REM this project lost six entry slots in a morning.
REM
REM Registered as a logon task (not a boot task) on purpose: IB Gateway is a GUI
REM application living in the user session, so there is nothing to connect to
REM before that session exists.
REM ---------------------------------------------------------------------------
setlocal
set RAITS_ROOT=D:\raits
set PY=C:\Users\quock\AppData\Local\Programs\Python\Python311\python.exe
set LOG=%RAITS_ROOT%\monitor\logs\autostart.log

cd /d "%RAITS_ROOT%" || exit /b 1

echo. >> "%LOG%"
echo ==== autostart %DATE% %TIME% ==== >> "%LOG%"

REM Same flags as the mode this route runs in; --yes because no terminal is
REM attached to answer a prompt. Without --yes an unattended run that finds a
REM live process refuses instead of asking, which would be a silent no-op.
"%PY%" -m monitor.ops up --track1-only-shadow --yes >> "%LOG%" 2>&1
set RC=%ERRORLEVEL%

echo ---- ops up exit=%RC% >> "%LOG%"
"%PY%" -m monitor.ops status >> "%LOG%" 2>&1

exit /b %RC%
