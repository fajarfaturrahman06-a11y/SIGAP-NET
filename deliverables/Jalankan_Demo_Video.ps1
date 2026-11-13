<#
.SYNOPSIS
    SIGAP-NET — Pintu masuk demo video otomatis (Windows).

.DESCRIPTION
    Wrapper ini hanya memeriksa Python lalu menjalankan demo_video.py.
    Seluruh logika (cek dependensi, isolasi DB, skenario, rekaman,
    pemberhentian aman) ada di demo_video.py.

.PARAMETER InstallPlaywright
    Coba instal Playwright + Chromium (membutuhkan internet).

.PARAMETER SkipBrowser
    Lewati browser automation; gunakan mode HTTP saja.

.PARAMETER Port
    Informasional — demo saat ini memakai port 5000 (lihat demo_video.py).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Jalankan_Demo_Video.ps1
    powershell -ExecutionPolicy Bypass -File Jalankan_Demo_Video.ps1 -InstallPlaywright
#>
param(
    [switch]$InstallPlaywright,
    [switch]$SkipBrowser,
    [int]$Port = 5000
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " SIGAP-NET - Demo Video Otomatis (mode aman/terisolasi)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# --- Pemeriksaan Python (jangan diasumsikan) ---
$py = $null
foreach ($cand in @("python", "py")) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cand; break }
}
if (-not $py) {
    Write-Host "[ERR ] Python tidak ditemukan di PATH." -ForegroundColor Red
    Write-Host "       Instal Python 3.12+ dari https://python.org lalu ulangi." -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK  ] Python ditemukan: $py" -ForegroundColor Green

$orchestrator = Join-Path $here "demo_video.py"
if (-not (Test-Path $orchestrator)) {
    Write-Host "[ERR ] demo_video.py tidak ditemukan di $here" -ForegroundColor Red
    exit 1
}

# --- Susun argumen (demo_video.py memakai port default 5000) ---
$argList = @($orchestrator)
if ($InstallPlaywright) { $argList += "--install-playwright" }
if ($SkipBrowser)       { $argList += "--skip-browser" }

Write-Host "[INFO] Menjalankan: $py $($argList -join ' ')" -ForegroundColor Cyan
& $py @argList
$code = $LASTEXITCODE

if ($code -eq 0) {
    Write-Host "[OK  ] Demo selesai. Laporan ada di deliverables\demo-run\" -ForegroundColor Green
} else {
    Write-Host "[ERR ] Demo berhenti dengan kode $code - periksa pesan di atas." -ForegroundColor Red
}
exit $code
