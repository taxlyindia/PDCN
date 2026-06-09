@echo off
title PDCN CRM — Startup
color 0B

echo.
echo  ============================================
echo    PDCN CRM — Local Server Startup
echo  ============================================
echo.

:: ─── Kill any process already using port 8000 ────────────
echo  [CLEANUP] Checking for processes on port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo  [CLEANUP] Killing PID %%a on port 8000...
    taskkill /PID %%a /F >nul 2>&1
)

:: ─── Kill any lingering uvicorn / python processes ────────
echo  [CLEANUP] Terminating any existing uvicorn processes...
taskkill /F /IM uvicorn.exe >nul 2>&1

:: Kill python processes running main:app or uvicorn
for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq python.exe" /NH 2^>nul ^| findstr /i "python"') do (
    wmic process where "ProcessId=%%a" get CommandLine /value 2>nul | findstr /i "uvicorn\|main:app" >nul 2>&1
    if not errorlevel 1 (
        echo  [CLEANUP] Killing python PID %%a (uvicorn worker^)...
        taskkill /PID %%a /F >nul 2>&1
    )
)

:: Small pause to let ports release
timeout /t 2 >nul

echo  [OK] Port 8000 is now free.
echo.

:: ─── Check Python ─────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python is not installed or not in PATH.
    echo  Download Python 3.10+ from https://python.org
    pause
    exit /b 1
)

:: ─── Navigate to backend ──────────────────────────────────
cd /d "%~dp0backend"

:: ─── Create venv if not present ───────────────────────────
if not exist "venv\Scripts\activate.bat" (
    echo  [SETUP] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo  [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo  [OK] Virtual environment created.
)

:: ─── Activate venv ────────────────────────────────────────
echo  [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

:: ─── Install dependencies ─────────────────────────────────
echo  [INFO] Installing/updating dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo  [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo  [OK] Dependencies ready.

:: ─── Check .env file ──────────────────────────────────────
if not exist ".env" (
    echo  [SETUP] .env not found. Copying from .env.example...
    copy ".env.example" ".env" >nul
    echo  [WARN] Edit backend\.env with your actual config before production.
)

:: ─── Run migrations ───────────────────────────────────────
echo  [INFO] Running database migrations...
python migrate.py
if errorlevel 1 (
    echo  [ERROR] Migration failed. Check your DATABASE_URL in .env
    pause
    exit /b 1
)

:: ─── Seed database (first run only) ──────────────────────
set SEED_FLAG=.seed_done
if not exist "%SEED_FLAG%" (
    echo  [SETUP] Seeding demo data...
    python seed.py
    if not errorlevel 1 (
        echo 1 > "%SEED_FLAG%"
        echo  [OK] Demo data seeded.
    ) else (
        echo  [WARN] Seed failed — check logs above.
    )
) else (
    echo  [INFO] Seed already done. Skipping.
)

:: ─── Start FastAPI Server ─────────────────────────────────
echo.
echo  ============================================
echo    Starting FastAPI Backend Server...
echo    URL:  http://localhost:8000
echo    Docs: http://localhost:8000/docs
echo  ============================================
echo.

:: Open browser after 3 seconds
start /b cmd /c "timeout /t 3 >nul && start http://localhost:8000"

:: Start Uvicorn (fresh)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

echo.
echo  [INFO] Server stopped.
pause
