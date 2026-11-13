# SIGAP-NET — Defensive Shield

**Sistem Integritas Konfigurasi dan Respons Gangguan Jaringan**

> *Integritas konfigurasi jaringan, terdeteksi sebelum menjadi insiden.*

SIGAP-NET adalah aplikasi web berbasis Flask untuk memantau integritas konfigurasi
perangkat jaringan (MikroTik). Aplikasi membandingkan konfigurasi terkini dengan
**baseline SHA-256**, menilai risiko setiap perubahan secara otomatis lewat **rule
engine**, membuka tiket insiden, dan mencatat seluruh aktivitas dalam **jejak audit
append-only** yang tidak dapat diubah atau dihapus.

---

## Fitur Utama

- **Dashboard monitoring real-time** — kartu ringkasan (perangkat, perubahan, risiko
  tinggi, insiden terbuka), grafik tren perubahan 14 hari, dan distribusi tingkat risiko.
- **Manajemen perangkat** — daftar perangkat, uji koneksi SSH, kredensial tersimpan
  terenkripsi (Fernet).
- **Backup konfigurasi router** — backup manual, jadwal otomatis (APScheduler),
  riwayat, dan unduhan.
- **Configuration Baseline** — acuan SHA-256 per perangkat, dapat diaktifkan/diganti.
- **Change Detection** — pemindaian konfigurasi terhadap baseline → status
  `OK`/`CHANGED` dengan tingkat risiko `LOW`–`CRITICAL`.
- **Risk Assessment** — rule engine menandai perubahan kritis, contoh:
  `ssh.disabled: disabled → enabled` dan `firewall filter: enabled → disabled` (HIGH).
- **Incident Management** — tiket insiden otomatis (`INC-YYYYMMDD-####`) dengan alur
  status tervalidasi dan catatan respons.
- **Audit Trail append-only** — layanan audit menolak perubahan dan penghapusan
  (edit/delete diblokir), setiap aktivitas pengguna tercatat.
- **Multi-peran** — `admin`, `operator`, `auditor`; CSRF pada semua form, throttling
  login (5 percobaan / 5 menit), kebijakan password kuat.
- **Mode simulasi** — skenario demo (normal / firewall / ssh) untuk presentasi tanpa
  perangkat nyata.

---

## Alur Kerja Inti (4 Langkah)

```
┌─────────────────┐    ┌──────────────────┐    ┌───────────────────┐    ┌──────────────┐
│ 1. BASELINE     │ →  │ 2. DETEKSI       │ →  │ 3. RISIKO &       │ →  │ 4. AUDIT     │
│ Tetapkan acuan  │    │ Periksa          │    │ INSIDEN           │    │ Jejak tak    │
│ SHA-256         │    │ konfigurasi      │    │ Rule engine +     │    │ terhapus     │
│ (Baseline)      │    │ (Change Detect.) │    │ tiket otomatis    │    │ (Audit)      │
└─────────────────┘    └──────────────────┘    └───────────────────┘    └──────────────┘
```

---

## Persyaratan

- **Python 3.10+** (dikembangkan pada Python 3.13) **atau** Docker
- Koneksi internet hanya diperlukan saat instalasi dependensi
- Untuk perangkat nyata: router **MikroTik dengan SSH aktif**

---

## Instalasi — Mode Lokal (SQLite)

Mode ini langsung jalan tanpa konfigurasi apa pun; database disimpan di
`data/sigapnet.db`.

```bash
git clone https://github.com/fajarfaturrahman06-a11y/SIGAP-NET.git
cd SIGAP-NET

python -m venv venv

# Aktifkan virtual environment:
venv\Scripts\activate          # Windows
source venv/bin/activate       # Linux / macOS

pip install -r requirements.txt

# 1. Buat tabel database (tambahkan --seed-demo untuk data lab contoh)
python -m flask --app app init-db --seed-demo

# 2. Buat administrator — password diminta tersembunyi saat kirim
#    (kebijakan: min. 12 karakter, huruf besar/kecil, angka, simbol)
python -m flask --app app create-admin admin

# 3. Jalankan
python -m flask --app app run --debug
```

Buka **http://127.0.0.1:5000** lalu masuk dengan akun yang baru dibuat.

---

## Instalasi — Docker (MySQL)

Cocok untuk deployment. Kontainer `web` menjalankan Gunicorn di balik port **8500**;
migrasi skema, `init-db`, dan pembuatan admin berjalan otomatis saat startup.

```bash
git clone https://github.com/fajarfaturrahman06-a11y/SIGAP-NET.git
cd SIGAP-NET

cp .env.example .env
# Edit .env — wajib isi minimal:
#   MYSQL_PASSWORD / MYSQL_ROOT_PASSWORD  (password kuat)
#   DATABASE_URL                          (sesuaikan user/password di atas)
#   SECRET_KEY                            (python -c "import secrets; print(secrets.token_hex(32))")
#   ADMIN_PASSWORD                        (min. 12 karakter, campuran)

docker compose up -d
```

Buka **http://localhost:8500**.

```bash
docker compose logs -f web       # pantau proses boot
docker compose exec web flask create-admin admin   # tambah admin manual bila perlu
docker compose down              # berhenti (data tetap di volume)
```

---

## Peran Pengguna

| Peran | Ringkasan akses |
|---|---|
| `admin` | Penuh — manajemen pengguna, pengaturan/simulasi, seluruh modul |
| `operator` | Operasional harian — perangkat, backup, pemeriksaan, respons insiden |
| `auditor` | Baca-saja — pemantauan, riwayat, dan jejak audit |

Buat akun tambahan lewat menu **User Management** (khusus admin) atau CLI
`flask create-admin <username> --role operator`.

---

## Panduan Penggunaan

Menu di sidebar mengikuti alur berikut (urut dari atas ke bawah).

### 1. Dashboard
Ringkasan integritas jaringan: kartu **Perangkat / Perubahan / Risiko Tinggi /
Insiden Terbuka**, grafik tren 14 hari, dan donat distribusi risiko. Tombol
**Skenario 1/2/3** dan **Reset Demo** menjalankan simulasi perubahan konfigurasi
(mode demo, lihat bagian *Mode Simulasi*).

### 2. Perangkat (Pemantauan)
- **Tambah Perangkat** — isi nama, host/IP, port SSH (default 22), dan kredensial.
- **Uji Koneksi** — verifikasi kredensial SSH sebelum dipakai.
- Kredensial disimpan terenkripsi; jangan hapus file `data/.encryption_key`.

### 3. Backup Router (Routers · Schedules · Backup History)
- **Routers** — daftar router terdaftar, edit/hapus, dan tombol backup manual.
- **Schedules** — jadwalkan backup berkala, aktifkan/nonaktifkan per jadwal.
- **Backup History** — unduh atau hapus hasil backup konfigurasi.

### 4. Configuration Baseline (Konfigurasi)
Buat baseline acuan dari konfigurasi perangkat, lalu **aktifkan** baseline tersebut.
Baseline aktif menjadi pembanding untuk deteksi perubahan; hash SHA-256-nya
ditampilkan pada detail baseline.

### 5. Change Detection (Pemantauan)
Klik **Periksa Konfigurasi** (atau jalankan pemeriksaan dari halaman perangkat).
Setiap baris menampilkan status `CHANGED`/`OK`, sumber perubahan, dan tingkat risiko
(`LOW` hijau, `MEDIUM`, `HIGH` amber, `CRITICAL` merah). Rinci perubahan (diff,
hash, metadata) ada di halaman detail pemeriksaan.

### 6. Risk Assessment (Pemantauan)
Penilaian risiko berjalan otomatis dari hasil pemeriksaan. Perubahan yang cocok
dengan aturan kritis (mis. `ssh.disabled: disabled → enabled`, firewall dinonaktifkan)
ditandai **HIGH/CRITICAL** di sini.

### 7. Incident Management (Respons)
Perubahan berisiko membuka tiket insiden otomatis dengan kode
`INC-YYYYMMDD-####`. Dari halaman detail Anda dapat:
- memindahkan status insiden (transisi tervalidasi oleh sistem),
- menambahkan catatan respons,
- menyaring daftar berdasarkan status, severity, atau perangkat.

### 8. Audit Trail (Tata Kelola)
Seluruh aktivitas (login, perubahan data, pemeriksaan, aksi insiden) tercatat di
sini. Sifatnya **append-only**: upaya edit dan hapus ditolak oleh layanan audit.
Setiap entri menyimpan aktor, aksi, objek, detail, dan waktu UTC.

### 9. Settings / Simulation (Sistem)
Pengaturan aplikasi dan pusat mode simulasi (skenario demo, reset data simulasi).

### 10. User Management (Tata Kelola)
Kelola pengguna dan peran (khusus `admin`).

---

## Mode Simulasi (Demo)

Untuk presentasi tanpa perangkat nyata:

1. Jalankan `python -m flask --app app init-db --seed-demo` (membuat perangkat lab
   dan baseline contoh), atau `flask seed-demo` kapan pun (idempoten).
2. Masuk ke Dashboard, klik **Skenario 1/2/3** — masing-masing mensimulasikan
   perubahan konfigurasi (normal, firewall, ssh) lengkap dengan pemeriksaan, risiko,
   dan insiden.
3. **Reset Demo** mengembalikan data simulasi ke kondisi awal.

Akun demo peran tidak dibuat otomatis; gunakan `flask seed-demo-users` dan isi
password yang diminta untuk masing-masing peran.

---

## Perintah CLI

Semua perintah dijalankan dari root repo dengan prefiks
`python -m flask --app app`:

| Perintah | Fungsi |
|---|---|
| `init-db [--seed-demo]` | Buat tabel + patch skema; `--seed-demo` menambah perangkat lab & baseline |
| `create-admin <user> [--role admin\|operator\|auditor]` | Buat pengguna; password diminta tersembunyi (tidak lewat command line) |
| `ensure-admin` | Buat admin dari env `ADMIN_USERNAME`/`ADMIN_PASSWORD` (dipakai Docker) |
| `seed-demo` | Tanam perangkat demo + baseline (idempoten) |
| `seed-demo-users` | Buat akun demo 3 peran (password per peran diminta) |
| `db migrate` / `db upgrade` | Flask-Migrate (dijalankan otomatis oleh entrypoint Docker) |
| `run --debug` | Server development Flask |

---

## Konfigurasi Lingkungan (`.env`)

Salin `.env-example` menjadi `.env`. Varian penting:

| Variabel | Default | Keterangan |
|---|---|---|
| `DATABASE_URL` | *(SQLite `data/sigapnet.db`)* | MySQL untuk Docker, mis. `mysql+pymysql://user:pass@db:3306/mikrobackup` |
| `SECRET_KEY` | *(auto → file `.secret_key`)* | Dihasilkan otomatis bila kosong — jangan commit file-nya |
| `ENCRYPTION_KEY` | *(auto → file `data/.encryption_key`)* | Kunci Fernet kredensial router; **wajib stabil lintas deploy** |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / *(kosong)* | Admin dibuat saat startup jika password kuat |
| `SESSION_COOKIE_SECURE` | `false` | `true` bila sudah di belakang HTTPS |
| `TRUST_PROXY_HEADERS` | `false` | `true` hanya di belakang reverse proxy tepercaya |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_WINDOW_SECONDS` | `5` / `300` | Throttling percobaan login |
| `SCHEDULER_ENABLED` | `true` | Penjadwal backup otomatis |
| `SSH_KNOWN_HOSTS_FILE` | *(kosong)* | Path known_hosts untuk verifikasi host key SSH (default `~/.ssh/known_hosts`) |
| `SIGAP_ALLOW_REAL_RESTORE` | `false` | Restore perangkat nyata sengaja dinonaktifkan untuk prototipe |
| `SIGAP_SHOW_DEMO_ACCOUNTS` | `false` | Tampilkan info akun demo di halaman login |

> Tanpa `.env`, mode lokal tetap berjalan penuh (SQLite + kunci otomatis).

---

## Endpoint Utilitas

| Endpoint | Fungsi |
|---|---|
| `/health` | Cek kesehatan aplikasi (untuk monitoring/uptime probe) |
| `/api/routers/status` | Status koneksi perangkat (JSON) |
| `/api/events` | Aliran event untuk pembaruan dashboard |

---

## Struktur Proyek

```
SIGAP-NET/
├── app.py               # Entry point: app factory, CLI, route inti
├── config.py            # Konfigurasi + kunci rahasia (auto-generate)
├── db.py                # SQLAlchemy, model, tipenya
├── bootstrap.py         # Inisialisasi database
├── authz.py / security.py / csrf.py / ratelimit.py   # Otorisasi, keamanan
├── scheduler.py         # Penjadwal backup (APScheduler)
├── mikrotik.py          # Klien SSH/router
├── routes/              # Blueprint: devices, checks, baselines, incidents,
│                        #   audittrail, users, simulation, dst.
├── services/            # Logika bisnis: monitoring, risk, audit, integrity,
│                        #   response, simulation, adapters
├── templates/           # Jinja2 (dashboard, modul, login, dst.)
├── static/              # CSS/JS/gambar
├── data/                # Database SQLite + kunci enkripsi (tidak di-commit)
├── backups/  logs/      # Hasil backup & log runtime (tidak di-commit)
├── Dockerfile  docker-compose.yml  entrypoint.sh   # Deploy Docker + MySQL
├── mikrobackup.service  # Unit systemd (opsional, Gunicorn)
└── requirements.txt     # Dependensi runtime
```

---

## Catatan Keamanan

- Password disimpan terenkripsi (Werkzeug hashing); kebijakan password kuat
  ditegakkan di CLI maupun UI.
- Semua form dilindungi **CSRF**; login dibatasi 5 percobaan per 5 menit.
- Kredensial router dienkripsi dengan **Fernet** — jangan hapus
  `data/.encryption_key` dan jangan ubah `ENCRYPTION_KEY` setelah perangkat tersimpan.
- Mode produksi: set `SESSION_COOKIE_SECURE=true` di belakang HTTPS dan
  `TRUST_PROXY_HEADERS=true` di belakang reverse proxy.
- Jejak audit **append-only** — tidak ada UI atau service method untuk mengubah
  atau menghapus entri.

---

## Kredit

Dikembangkan oleh **UKM KARTIKA CYBER — Politeknik Adisutjipto**, 2026.
