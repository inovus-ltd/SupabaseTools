# ============================================================
#  SupabaseTools Installer (Windows PowerShell)
#  Downloads the latest release binaries from GitHub and
#  installs them to C:\Windows\System32 so they are
#  available from any terminal without any PATH changes.
#
#  Usage (run as Administrator):
#    irm https://raw.githubusercontent.com/inovus-ltd/SupabaseTools/master/install.ps1 | iex
#
#  Or if you have the file locally:
#    .\install.ps1
# ============================================================

$ErrorActionPreference = "Stop"

$repo    = "inovus-ltd/SupabaseTools"
$installDir = "C:\Windows\System32"

$tools = @(
    "supabase-functions-backup",
    "supabase-storage-copy",
    "supabase-auth-copy",
    "supabase-secrets-manager"
)

Write-Host ""
Write-Host " SupabaseTools Installer" -ForegroundColor Cyan
Write-Host " ─────────────────────────────────────────" -ForegroundColor Cyan

# -- Resolve latest release tag -------------------------------------------
Write-Host ""
Write-Host " Fetching latest release info..." -NoNewline
$apiUrl  = "https://api.github.com/repos/$repo/releases/latest"
try {
    $release = Invoke-RestMethod -Uri $apiUrl -Headers @{ "User-Agent" = "SupabaseTools-Installer" } -TimeoutSec 15
} catch {
    Write-Host " FAILED" -ForegroundColor Red
    Write-Host " Could not reach GitHub API: $_" -ForegroundColor Red
    Write-Host " Check your internet connection and try again." -ForegroundColor Yellow
    exit 1
}
$tag = $release.tag_name
Write-Host " $tag" -ForegroundColor Green

# -- Check for admin ----------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltinRole]::Administrator
)
if (-not $isAdmin) {
    Write-Host ""
    Write-Host " ERROR: This installer must be run as Administrator." -ForegroundColor Red
    Write-Host "        Right-click PowerShell and choose 'Run as administrator', then re-run." -ForegroundColor Yellow
    exit 1
}

# -- Download helper with live progress dots ----------------------------------
function Download-File {
    param([string]$Url, [string]$Dest)
    # Reason: HttpClient with manual streaming lets us print a dot every ~512KB
    # so the user sees activity rather than a silent hang during large downloads.
    $http = [System.Net.Http.HttpClient]::new()
    $http.DefaultRequestHeaders.Add("User-Agent", "SupabaseTools-Installer")
    try {
        $response = $http.GetAsync($Url, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        $response.EnsureSuccessStatusCode() | Out-Null
        $total = $response.Content.Headers.ContentLength
        $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $outStream = [System.IO.File]::Create($Dest)
        $buf = New-Object byte[] 524288  # 512 KB chunks
        $downloaded = 0
        try {
            while ($true) {
                $read = $stream.Read($buf, 0, $buf.Length)
                if ($read -le 0) { break }
                $outStream.Write($buf, 0, $read)
                $downloaded += $read
                Write-Host "." -NoNewline
            }
        } finally {
            $outStream.Close()
            $stream.Close()
        }
        $sizeMB = [math]::Round($downloaded / 1MB, 1)
        Write-Host " ${sizeMB} MB" -ForegroundColor Green
    } finally {
        $http.Dispose()
    }
}

# -- Download and install each tool ------------------------------------------
Write-Host " Installing to: $installDir"
Write-Host " Note: each executable is ~15-20 MB — dots show download progress."
Write-Host ""

foreach ($tool in $tools) {
    $filename = "$tool-windows.exe"
    $destName = "$tool.exe"
    $url      = "https://github.com/$repo/releases/download/$tag/$filename"
    $dest     = Join-Path $installDir $destName

    Write-Host " $tool  " -NoNewline
    try {
        Download-File -Url $url -Dest $dest
    } catch {
        Write-Host " FAILED" -ForegroundColor Red
        Write-Host "   URL: $url" -ForegroundColor DarkGray
        Write-Host "   Error: $_" -ForegroundColor DarkGray
    }
}

# -- Verify ------------------------------------------------------------------
Write-Host ""
Write-Host " Installed tools:" -ForegroundColor Cyan
foreach ($tool in $tools) {
    $dest = Join-Path $installDir "$tool.exe"
    if (Test-Path $dest) {
        Write-Host "   $tool" -ForegroundColor Green
    } else {
        Write-Host "   $tool  (MISSING — install may have failed)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host " Installation complete! Open a new terminal and run:" -ForegroundColor Cyan
Write-Host "   supabase-functions-backup list --project-ref <ref> --token <token>"
Write-Host "   supabase-storage-copy list --project-ref <ref> --token <token> --service-key <key>"
Write-Host "   supabase-auth-copy list --project-ref <ref> --token <token>"
Write-Host "   supabase-secrets-manager list --project-ref <ref> --token <token>"
Write-Host ""
