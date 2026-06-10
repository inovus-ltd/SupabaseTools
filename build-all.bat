@echo off
REM ============================================================
REM  SupabaseTools — Build all standalone executables (Windows)
REM  Prerequisites: pip install pyinstaller
REM  Output:        dist\
REM ============================================================

echo.
echo  Building SupabaseTools executables...
echo  Output directory: dist\
echo.

REM -- supabase-functions-backup ----------------------------
echo  [1/6] supabase-functions-backup
pyinstaller --onefile --noconfirm --clean ^
  --name supabase-functions-backup ^
  --distpath dist ^
  supabase-functions-backup\supabase-functions-backup.py
if %errorlevel% neq 0 ( echo  ERROR: build failed & exit /b 1 )
echo.

REM -- supabase-storage-copy --------------------------------
echo  [2/6] supabase-storage-copy
pyinstaller --onefile --noconfirm --clean ^
  --name supabase-storage-copy ^
  --distpath dist ^
  supabase-storage-copy\supabase-storage-copy.py
if %errorlevel% neq 0 ( echo  ERROR: build failed & exit /b 1 )
echo.

REM -- supabase-auth-copy -----------------------------------
echo  [3/6] supabase-auth-copy
pyinstaller --onefile --noconfirm --clean ^
  --name supabase-auth-copy ^
  --distpath dist ^
  supabase-auth-copy\supabase-auth-copy.py
if %errorlevel% neq 0 ( echo  ERROR: build failed & exit /b 1 )
echo.

REM -- supabase-secrets-manager -----------------------------
echo  [4/6] supabase-secrets-manager
pyinstaller --onefile --noconfirm --clean ^
  --name supabase-secrets-manager ^
  --distpath dist ^
  supabase-secrets-manager\supabase-secrets-manager.py
if %errorlevel% neq 0 ( echo  ERROR: build failed & exit /b 1 )
echo.

REM -- supabase-database-compare -----------------------------
echo  [5/6] supabase-database-compare
pyinstaller --onefile --noconfirm --clean ^
  --name supabase-database-compare ^
  --distpath dist ^
  supabase-database-compare\supabase-database-compare.py
if %errorlevel% neq 0 ( echo  ERROR: build failed & exit /b 1 )
echo.

echo  [6/6] supabase-database-sync
pyinstaller --onefile --noconfirm --clean ^
  --name supabase-database-sync ^
  --distpath dist ^
  supabase-database-sync\supabase-database-sync.py
if %errorlevel% neq 0 ( echo  ERROR: build failed & exit /b 1 )
echo.

echo  All executables built successfully:
echo.
for %%f in (dist\*.exe) do echo    %%f
echo.
