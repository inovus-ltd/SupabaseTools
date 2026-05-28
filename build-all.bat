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
echo  [1/4] supabase-functions-backup
pyinstaller --onefile --noconfirm --clean ^
  --name supabase-functions-backup ^
  --distpath dist ^
  supabase-functions-backup\supabase-functions-backup.py
if %errorlevel% neq 0 ( echo  ERROR: build failed & exit /b 1 )
echo.

REM -- supabase-storage-copy --------------------------------
echo  [2/4] supabase-storage-copy
pyinstaller --onefile --noconfirm --clean ^
  --name supabase-storage-copy ^
  --distpath dist ^
  supabase-storage-copy\supabase-storage-copy.py
if %errorlevel% neq 0 ( echo  ERROR: build failed & exit /b 1 )
echo.

REM -- supabase-auth-copy -----------------------------------
echo  [3/4] supabase-auth-copy
pyinstaller --onefile --noconfirm --clean ^
  --name supabase-auth-copy ^
  --distpath dist ^
  supabase-auth-copy\supabase-auth-copy.py
if %errorlevel% neq 0 ( echo  ERROR: build failed & exit /b 1 )
echo.

REM -- supabase-secrets-manager -----------------------------
echo  [4/4] supabase-secrets-manager
pyinstaller --onefile --noconfirm --clean ^
  --name supabase-secrets-manager ^
  --distpath dist ^
  supabase-secrets-manager\supabase-secrets-manager.py
if %errorlevel% neq 0 ( echo  ERROR: build failed & exit /b 1 )
echo.

echo  All executables built successfully:
echo.
for %%f in (dist\*.exe) do echo    %%f
echo.
