# ============================================================
#  SupabaseTools — Build all standalone executables (Windows)
#  Prerequisites: pip install pyinstaller
#  Output:        dist\
# ============================================================

$tools = @(
    @{ Name = "supabase-functions-backup"; Script = "supabase-functions-backup\supabase-functions-backup.py" },
    @{ Name = "supabase-storage-copy";     Script = "supabase-storage-copy\supabase-storage-copy.py" },
    @{ Name = "supabase-auth-copy";        Script = "supabase-auth-copy\supabase-auth-copy.py" },
    @{ Name = "supabase-secrets-manager";  Script = "supabase-secrets-manager\supabase-secrets-manager.py" }
)

Write-Host ""
Write-Host " Building SupabaseTools executables..."
Write-Host " Output directory: dist\"
Write-Host ""

$i = 1
foreach ($tool in $tools) {
    Write-Host " [$i/$($tools.Count)] $($tool.Name)"

    pyinstaller --onefile --noconfirm --clean `
        --name $tool.Name `
        --distpath dist `
        $tool.Script

    if ($LASTEXITCODE -ne 0) {
        Write-Error " ERROR: Build failed for $($tool.Name)"
        exit 1
    }

    Write-Host ""
    $i++
}

Write-Host " All executables built successfully:"
Write-Host ""
Get-ChildItem dist\*.exe | ForEach-Object { Write-Host "   $($_.FullName)" }
Write-Host ""
