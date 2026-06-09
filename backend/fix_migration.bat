@echo off
title Fix Migration
color 0A
cd /d "%~dp0"

echo.
echo  Fixing failed migration...
echo.

call venv\Scripts\activate.bat

echo  [1/3] Marking migration as NOT applied (stamp base)...
alembic stamp base

echo  [2/3] Dropping partial columns if they exist...
python -c "
from app.database.session import engine
from sqlalchemy import text
with engine.connect() as conn:
    conn.execution_options(isolation_level='AUTOCOMMIT')
    try:
        conn.execute(text('ALTER TABLE users DROP COLUMN IF EXISTS is_finance_team'))
        print('  Dropped is_finance_team')
    except Exception as e:
        print('  is_finance_team:', e)
    try:
        conn.execute(text('ALTER TABLE users DROP COLUMN IF EXISTS is_cfa_team'))
        print('  Dropped is_cfa_team')
    except Exception as e:
        print('  is_cfa_team:', e)
print('  Columns cleaned.')
"

echo  [3/3] Re-running migration...
alembic upgrade head

echo.
echo  Done! Now run start.bat normally.
pause
