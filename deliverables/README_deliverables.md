# Deliverables SIGAP-NET — Panduan Penggunaan

Paket materi kompetisi/demonstrasi **SIGAP-NET** (Sistem Integritas Konfigurasi
dan Respons Gangguan Jaringan) — UKM Kartika Cyber, POLTEKAD.
Disusun dari hasil audit kode sumber tanggal 12 November 2026.

Lokasi folder: `deliverables/` (di root repositori).

---

## Isi paket

| Berkas | Keterangan | Status verifikasi |
|---|---|---|
| `SIGAP-NET_Dokumentasi.pdf` | Dokumentasi profesional (deskripsi, masalah, solusi, arsitektur, teknologi, instalasi, panduan, keamanan, batasan) — 14 halaman | ✅ Header `%PDF-1.4`, trailer `%%EOF` |
| `SIGAP-NET_Dokumentasi.html` | Sumber HTML dari PDF (bila ingin mengubah lalu mencetak ulang) | ✅ |
| `SIGAP-NET_Template_Presentasi.pptx` | Template presentasi video 12 slide, nuansa teknologi/cybersecurity/TNI AD, dengan slot screenshot | ✅ Dibuka ulang: 12 slide, 16:9 |
| `generate_presentasi.py` | Generator ulang PPTX (`python generate_presentasi.py`) | ✅ Lolos kompilasi |
| `Jalankan_Demo_Video.ps1` | Pintu masuk demo di Windows | ✅ Lolos parser PowerShell |
| `demo_video.py` | Orkestrator demo otomatis 8 tahap | ✅ Lolos kompilasi + **teruji end-to-end** |
| `demo-run/<waktu>/` | Hasil run demo: database demo terisolasi, `RUN_REPORT.txt` | ✅ Dihasilkan saat verifikasi |
| `demo-run/server.log` | Log server selama demo | ✅ Bersih dari rahasia |
| `AUDIT_SIGAP_NET.md` | Laporan audit TAHAP 1 (fakta kode, temuan, keterbatasan) | ✅ |
| `video-youtube/SIGAP-NET_Demo_Youtube.mp4` | Video demo YouTube 1080p (H.264, subtitle Indonesia ter-burn) | ✅ ffprobe: h264, 1920×1080, 30 fps |
| `video-youtube/SIGAP-NET_Demo_Youtube.srt` | Subtitle video (17 entri) | ✅ |
| `video-youtube/thumbnail.png` | Thumbnail YouTube 1280×720 | ✅ PIL |
| `buat_kartu_video.py` / `buat_video_youtube.py` / `rakit_video.py` | Pipeline produksi video (kartu → rekam → perakit) | ✅ Teruji end-to-end |

---

## 1. README PDF

PDF sudah jadi — buka langsung `SIGAP-NET_Dokumentasi.pdf`.

Untuk mengubah isi:
1. Edit `SIGAP-NET_Dokumentasi.html`.
2. Cetak ke PDF via browser (Ctrl+P → *Save as PDF*, ukuran A4, aktifkan
   *Background graphics*), **atau** via Edge headless:

```powershell
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new `
  --print-to-pdf="SIGAP-NET_Dokumentasi.pdf" --no-pdf-header-footer `
  "file:///D:/POLTEKAD/UKM/KARTIKA_CYBER/mikrotik-backup-main/deliverables/SIGAP-NET_Dokumentasi.html"
```

## 2. Template Presentasi (PPTX)

Buka `SIGAP-NET_Template_Presentasi.pptx`. Urutan 12 slide:

1. Opening & identitas proyek · 2. Latar belakang masalah · 3. Permasalahan
yang diselesaikan · 4. Solusi SIGAP-NET · 5. Arsitektur sistem ·
6. Demo dashboard · 7. Demo fitur utama · 8. Demo monitoring & integritas ·
9. Keamanan & audit trail · 10. Hasil pengujian · 11. Keunggulan & kontribusi ·
12. Kesimpulan.

Slot bertanda **"AREA SCREENSHOT"** (slide 6–8) dan petunjuk slide 9/11 untuk
disisipi tangkapan layar aktual saat editing video. Menghasilkan ulang:

```powershell
python deliverables\generate_presentasi.py
```

**Aturan konten:** jangan menambahkan angka statistik/klaim yang belum
diverifikasi (contoh klaim lama yang tidak terbukti: "AES-256", "pengurangan
insiden 78%", "ISO 27001") — lihat `AUDIT_SIGAP_NET.md`.

## 3. Otomatisasi Video Demo

Jalankan dari root repositori (Windows):

```powershell
# Mode aman: cek dependensi → DB demo terisolasi → jalankan app →
# skenario → laporan → verifikasi DB utama → berhenti
powershell -ExecutionPolicy Bypass -File deliverables\Jalankan_Demo_Video.ps1

# Dengan rekaman video browser (butuh internet untuk instalasi pertama)
powershell -ExecutionPolicy Bypass -File deliverables\Jalankan_Demo_Video.ps1 -InstallPlaywright
```

Alur 8 tahap yang dijalankan `demo_video.py`:

| Tahap | Aksi |
|---|---|
| 1 | Cek dependensi **apa adanya** (Playwright/ffmpeg TIDAK diasumsikan ada) |
| 2 | Cek konfigurasi aplikasi + snapshot SHA-256 database utama (read-only) |
| 3 | Buat database demo **terpisah** (`demo-run/<waktu>/sigapnet-demo.db`), akun demo via `flask ensure-admin` |
| 4 | Jalankan aplikasi, tunggu `/health` |
| 5 | Login + 3 skenario simulasi + kunjungan halaman (browser bila Playwright ada, jika tidak → mode HTTP) |
| 6 | Simpan `RUN_REPORT.txt`, screenshot, video (bila tersedia) |
| 7 | **Buktikan** hash database utama tidak berubah |
| 8 | Hentikan aplikasi dengan aman (taskkill berpohon + cek port) |

Mode rekaman (status terkini: **Playwright & Chromium sudah terpasang**):

- **Playwright tersedia** → video `.webm` 1600×900 + screenshot tiap halaman.
  (Sudah terpasang di mesin ini sejak 12 Nov 2026 — diuji menghasilkan
  `demo_flow.webm` 4,37 MB + 14 screenshot.)
- **Playwright tidak tersedia** → mode HTTP otomatis; tanpa video/screenshot,
  tetap menjalankan seluruh skenario.
- **ffmpeg tersedia** → dapat dipakai untuk rekaman layar+audio eksternal;
  ffmpeg **sudah terpasang** (winget `Gyan.FFmpeg` 9.0.2) dan dipakai oleh
  pipeline video YouTube (bagian 4).

Password demo **dihasilkan saat runtime, hanya di memori**, dan tidak pernah
ditulis ke berkas laporan.

### Hasil run verifikasi (12 Nov 2026, 19:42 — mode rekaman penuh)

```
3 skenario  : normal→LOW, firewall→HIGH, ssh→HIGH (status 200)
insiden     : INC-20261112-0001, INC-20261112-0002
video       : demo-run/20261112-194225/video/demo_flow.webm (4,37 MB, EBML valid)
screenshot  : 14 PNG (login, dashboard, tiap halaman, 3 skenario, audit)
DB utama    : sha256 SAMA sebelum & sesudah (utuh)
port 5000   : dilepas bersih
```

---

## 4. Video YouTube siap upload

**Hasil akhir** — `deliverables/video-youtube/`:

| Berkas | Keterangan |
|---|---|
| `SIGAP-NET_Demo_Youtube.mp4` | Video final: **H.264 1920×1080, 30 fps, ±84 detik, ±5,6 MB**, `+faststart` (siap YouTube) |
| `SIGAP-NET_Demo_Youtube.srt` | 17 entri subtitle Indonesia (juga di-burn ke video agar jelas di ponsel) |
| `thumbnail.png` | Thumbnail 1280×720 |

**Struktur video (alur jual untuk juri):**

1. Kartu masalah (hook) → 2. Kartu solusi SIGAP-NET → 3. Kartu validasi
   (79 test, RBAC, audit utuh, mode simulasi aman) → **4. Demo browser
   penuh**: login → dashboard → 3 skenario (LOW/HIGH/HIGH) → tur 6 halaman
   fitur → penutup → 5. Kartu outro CTA.

**Produksi ulang (3 langkah):**

```powershell
python deliverables\buat_kartu_video.py     # kartu intro/outro + thumbnail (PIL)
python deliverables\buat_video_youtube.py   # rekam demo + timeline.json (Playwright)
python deliverables\rakit_video.py          # SRT + kartu + burn subtitle + concat (ffmpeg)
```

Catatan teknis teruji:
- Subtitle di-burn pada **video utuh** (bukan klip demo) — waktu SRT global,
  sinkron dengan visual (diverifikasi lewat ekstraksi frame).
- `mark()` pada perekam dipanggil **saat adegan mulai tampil**, bukan sesudah
  jeda — membuat teks subtitle tepat mengikuti halaman di layar.
- Rekaman memakai `wait_until="load"` (bukan `networkidle` — Google Fonts
  eksternal tidak pernah "idle").
- Database terisolasi per run; **database utama tidak berubah**
  (sha256 `2c5869b4…` sebelum & sesudah).

**Tips upload YouTube:** unggah MP4 apa adanya; judul saran
*"SIGAP-NET — Demo Sistem Integritas Konfigurasi Jaringan"*; unggah
`thumbnail.png` sebagai custom thumbnail; subtitle sudah menyala otomatis
karena sudah di-burn (file `.srt` bisa diunggah juga sebagai CC opsional);
musik latar bisa ditambahkan via YouTube Studio (Audio Library) tanpa
mengubah file.

---

## Batasan yang perlu diketahui

1. **ffmpeg kini terpasang** (winget `Gyan.FFmpeg` 9.0.2) — rekaman
   layar+audio eksternal dan pipeline video YouTube sudah bisa berjalan;
   rekaman browser via Playwright **sudah aktif**.
2. `flask create-admin` interaktif **tidak bisa** dipipe di Windows (click
   membaca konsol langsung via msvcrt); karenanya demo memakai jalur resmi
   `flask ensure-admin` + environment variable.
3. Jangan menjalankan `test_dashboard.py` (root repo) — menulis ke database
   utama. Gunakan `python -m pytest tests -q`.
4. Regresi dashboard yang sudah didokumentasikan (statistik "belum diperiksa"
   selalu 0; kolom "Snapshot Terakhir" selalu `—`) **tidak diperbaiki** —
   instruksi melarang mengubah fitur inti aplikasi.
5. Tabel `devices` di database utama masih berisi baris uji `test-*` dari
   pekerjaan sebelumnya (tercatat di audit, tidak dihapus).

## Prasyarat

- Python 3.12+ (teruji: 3.13.7) dengan dependensi `requirements.txt`
- Edge atau Chrome (untuk cetak PDF)
- `python-pptx` (untuk generator PPTX — terpasang)
- Opsional: Playwright + Chromium, ffmpeg
