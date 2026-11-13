@echo off
setlocal enabledelayedexpansion

echo 🚀 MEMULAI DEMO VIDEO SIGAP-NET — MODE SIMULASI
echo =================================================
echo.

:: 1. Aktifkan virtual environment
echo [1/6] Mengaktifkan virtual environment...
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else (
    echo ❌ Virtual environment tidak ditemukan. Jalankan dulu:
    echo    python -m venv venv
    echo    pip install -r requirements.txt
    exit /b 1
)

echo.
:: 2. Pastikan database sudah diinisialisasi
echo [2/6] Memastikan database siap...
python -c "from app import db; from config import SQLALCHEMY_DATABASE_URI; print('DB URI:', SQLALCHEMY_DATABASE_URI)" >nul 2>&1 || (
    echo ❌ Gagal memuat konfigurasi. Pastikan config.py ada dan benar.
    exit /b 1
)

echo.
:: 3. Jalankan Flask dalam mode simulasi (background)
echo [3/6] Menjalankan SIGAP-NET dalam mode simulasi...
start "SIGAP-NET Server" cmd /c "set SIMULATION=1 && flask run --host=0.0.0.0:5000 --debug 2>&1 | findstr /C:\"Running on http:\" && pause"

echo.
echo ⏳ Tunggu 5 detik agar server siap...
TIMEOUT /T 5 /NOBREAK >nul

echo.
:: 4. Buka browser ke dashboard
echo [4/6] Membuka browser ke http://localhost:5000...
start http://localhost:5000

echo.
echo 🎥 INSTRUKSI REKAM VIDEO:
echo =================================================
echo • Setelah browser terbuka:
echo   → Login sebagai: sigapadmin / [password Anda]
echo   → Masuk ke Devices → Tambah Router → isi:
echo        Nama: LAB-EDGE-01, IP: 192.168.88.1, Mode: Simulasi
echo   → Klik 'Backup Sekarang'
echo   → Di riwayat backup, klik 🔍 Diff antara dua versi
echo   → Masuk ke Reports → Export PDF (simpan sebagai demo-report.pdf)
echo.
echo 💡 Tips: Gunakan Zoom di area form & diff view untuk fokus!
echo =================================================
echo.
pause
