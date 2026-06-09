@echo off
title Reset Database
color 0C

echo.
echo  ============================================
echo    CRM — Reset Database (Clean Slate)
echo  ============================================
echo.
echo  WARNING: This will DROP all CRM tables and re-create them.
echo  All data will be lost.
echo.
set /p CONFIRM=Type YES to continue: 
if /i not "%CONFIRM%"=="YES" (
    echo  Cancelled.
    pause
    exit /b 0
)

cd /d "%~dp0"
call venv\Scripts\activate.bat

echo.
echo  [1/3] Dropping all tables...
python -c "
import psycopg2, sys, os
sys.path.insert(0, '.')
from app.config import settings
dsn = settings.DATABASE_URL.replace('postgresql+psycopg2','postgresql')
conn = psycopg2.connect(dsn)
conn.autocommit = True
cur = conn.cursor()
tables = ['activity_logs','login_logs','password_reset_tokens','refresh_tokens','users','tenants','alembic_version']
for t in tables:
    cur.execute(f'DROP TABLE IF EXISTS {t} CASCADE;')
    print(f'  Dropped {t}')
cur.execute('DROP TYPE IF EXISTS userrole CASCADE;')
cur.execute('DROP TYPE IF EXISTS userstatus CASCADE;')
cur.execute('DROP TYPE IF EXISTS tenantstatus CASCADE;')
cur.execute('DROP TYPE IF EXISTS authprovider CASCADE;')
print('  Dropped enum types')
cur.close(); conn.close()
print('  Done.')
"

echo.
echo  [2/3] Running fresh migration...
python migrate.py

echo.
echo  [3/3] Seeding demo data...
if exist ".seed_done" del ".seed_done"
python seed.py
if not errorlevel 1 (
    echo 1 > ".seed_done"
    echo  [OK] Demo data seeded.
)

echo.
echo  ============================================
echo    Database reset complete!
echo    Run start.bat to launch the server.
echo  ============================================
echo.
pause
