# Laporan Audit SIGAP-NET — TAHAP 1

Audit kode sumber: **12 November 2026**
Repo: `D:\POLTEKAD\UKM\KARTIKA_CYBER\mikrotik-backup-main`
Metode: pembacaan langsung README.md, HANDOFF.md, dan kode sumber (app.py,
db.py, routes/, services/, templates/, tests/) + pemeriksaan database SQLite
(read-only) + pemeriksaan lingkungan eksekusi. **Tanpa mengarang fitur.**

---

## 1. Identitas & dokumentasi

- README.md (176 baris) menyebut aplikasi "MikroTik Backup Dashboard" dengan
  blok **SIGAP-NET**: baseline konfigurasi, pemeriksaan integritas SHA-256,
  deteksi drift, analisis risiko, insiden, audit trail, persetujuan respons,
  simulasi aman, RBAC, CSRF, password policy, login throttling.
- `config.py:66-69`: `APP_NAME='SIGAP-NET'`,
  `APP_LONG_NAME='Sistem Integritas Konfigurasi dan Respons Gangguan Jaringan'`,
  `APP_VERSION='1.0.0'`.
- `HANDOFF.md` (status 11 Nov 2026) berisi riwayat perbaikan bug CSRF (macro
  `csrf_field` tanpa `with context`), perubahan CLI `create-admin`
  interaktif, serta daftar regresi `db.py` yang belum selesai.

## 2. Struktur direktori

| Kelompok | Isi |
|---|---|
| Root | `app.py` (916 baris), `config.py`, `db.py` (406), `authz.py`, `security.py`, `csrf.py`, `ratelimit.py`, `bootstrap.py`, `mikrotik.py`, `scheduler.py` |
| `routes/` | 7 blueprint: devices, baselines, checks, incidents, audittrail, users, simulation |
| `services/` | integrity (273), risk (212), monitoring (236), response (238), simulation (103), audit (49), demo_data (68), adapters (54) |
| `templates/` | 29 template Jinja2 |
| `tests/` | 8 berkas test → **79 test** |
| `migrations/` | Alembic + `001_add_sigapnet_tables.py` |
| Deployment | `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`, `mikrobackup.service` |
| Data | `data/sigapnet.db` (SQLite), `backups/`, `logs/` |
| Lain | `README.md`, `HANDOFF.md`, `demo-flow.bat`, `generate_presentation.py`, `test_dashboard.py` (root) |

## 3. Route (55 total, terverifikasi via grep)

- Utama (`app.py`): `/login`, `/logout`, `/`, `/routers*` (5), `/api/routers/*`
  (4), `/schedules*` (4), `/history`, `/backups/*` (2), `/settings`,
  `/api/events`, `/api/routers/status`, `/health`.
- `devices`: 9 route (`/devices`, baru/detail/edit/delete, `check`, `status`,
  `toggle-monitoring`, `config`).
- `baselines`: 5 · `checks`: 5 (termasuk `/risks`) · `incidents`: 8
  (status, note, response request/approve/execute/rollback) · `users`: 4 ·
  `audittrail`: 1 · `simulation`: 2 (run per skenario, reset — admin saja).

## 4. Database (15 tabel, terverifikasi langsung)

`users, routers, backups, schedules, activity_log, devices, baselines,
config_checks, config_changes, incidents, incident_events, response_actions,
audit_log, app_settings, login_attempts`

Kondisi DB utama saat audit: **users=2, devices=6 (baris uji `test-*`),
baselines=6, config_checks=3, incidents=2, audit_log=3, routers=0,
backups=0**. (HANDOFF menyebut users=0 — sudah berubah sejak 11 Nov.)

## 5. Fitur yang BENAR-BENAR berjalan

| Fitur | Bukti |
|---|---|
| Backup & jadwal | `mikrotik.py` (paramiko, RejectPolicy, known_hosts), `scheduler.py` (APScheduler CronTrigger, leadership lock, watchdog) |
| Baseline berversi | `db.py:262` `UniqueConstraint(device_id, version)`, properti `active_baseline`, `save()`/`activate_baseline()` |
| Hash & diff | `services/integrity.py` (parser + SHA-256 semantik), diuji `test_integrity.py` |
| Penilaian risiko | `services/risk.py` `assess_change()` — 4 level RISK_LEVELS |
| Insiden | `services/monitoring.py` — `evaluate_configuration`, `create_incident_for_check` (insiden terbuka serupa dipakai ulang), siklus status |
| Respons berpersetujuan | `services/response.py` — request/approve/execute/rollback + row lock; test: self-approval HIGH diblokir, rollback saat konfigurasi menyimpang diblokir |
| Simulasi 3 skenario | `services/simulation.py` — normal=LOW, firewall=HIGH, ssh=HIGH; reset mempertahankan audit |
| Audit append-only | `services/audit.py:60-61` — event SQLAlchemy blokir update & delete; diuji `test_audit_log_is_immutable` |
| RBAC | `authz.py` — admin/operator/auditor, `roles_required`, invalidasi sesi via `session_version` |
| Password policy | `security.py:176` — min 12, besar+kecil+angka+simbol, daftar lemah, tanpa username; hashing PBKDF2-SHA256 (Werkzeug) |
| Login throttling | `ratelimit.py` + tabel `login_attempts`, default 5×/300 dtk, fails-closed |
| CSRF | `csrf.py` — token dari form/header/X-CSRF-Token, `validate_csrf_token` |
| Anti path-traversal | `security.py:147-166` — `sanitize_filename`, `safe_join_path`, `is_safe_path` |
| CLI | `init-db [--seed-demo]`, `create-admin` (interaktif), `ensure-admin`, `seed-demo-users`, `seed-demo` |

**Terbukti berjalan saat verifikasi end-to-end** (run demo terisolasi):
login → 3 skenario (LOW/HIGH/HIGH) → 2 insiden dibuat → 9 aksi audit tercatat
→ aplikasi berhenti bersih.

## 6. Fitur yang DINONAKTIFKAN / BELUM ADA (jangan diklaim)

1. **Restore perangkat nyata** — `ALLOW_REAL_RESTORE=false`; README: "belum
   diimplementasikan dan tetap diblokir"; diuji
   `test_real_device_restore_is_blocked`.
2. **Akun default otomatis** — tidak ada; harus lewat CLI eksplisit.
3. **Ekspor laporan PDF** — TIDAK ada route `/reports` dalam daftar 55 route.
4. **Enkripsi AES-256 kredensial, statistik "78% pengurangan insiden",
   "12 operator", "compliance 92%", "ISO 27001/Puspersin"** — muncul di
   `generate_presentation.py` lama **tanpa dasar di kode** → tidak boleh
   dipakai di materi baru.
5. **`demo-flow.bat`** merujuk menu "Reports → Export PDF" yang tidak ada →
   sudah usang.

## 7. Regresi & masalah yang DITEMUKAN (tidak diperbaiki — di luar kewenangan)

1. `db.py`: properti `Device.latest_check` dihapus tetapi
   `templates/device_detail.html:30` masih memanggilnya → kolom "Snapshot
   Terakhir" selalu `—` (sesuai HANDOFF bagian 4a).
2. `Device.integrity_state` hanya `UNKNOWN/INTACT/DRIFT` (`db.py:239`), tetapi
   `app.py:393` menghitung `NOT_CHECKED` → statistik "belum diperiksa" selalu
   0; `UNKNOWN` tidak ada di pemetaan warna `app.py:295-296` (4b).
3. `test_dashboard.py` di root menulis ke DB utama (tanpa override
   `DATABASE_URL`) — berbahaya; sumber kontaminasi baris `test-*`.
4. Tabel `devices` masih mengandung 6 baris uji (lihat bagian 4).

## 8. Cara menjalankan & pengujian

```powershell
pip install -r requirements.txt
flask init-db --seed-demo
flask ensure-admin            # dengan ADMIN_USERNAME/ADMIN_PASSWORD di env
flask run --host=127.0.0.1 --port=5000
python -m pytest tests -q     # 79 test lulus (HANDOFF) — terisolasi via conftest
```

Docker Compose tersedia tetapi **Docker tidak terpasang** di mesin audit.

## 9. Lingkungan eksekusi (pemeriksaan aktual, bukan asumsi)

| Komponen | Status |
|---|---|
| Python | 3.13.7 ✓ |
| flask / sqlalchemy / pytest / python-pptx / PIL | ADA ✓ |
| playwright | **TIDAK ADA** |
| ffmpeg | **TIDAK ADA** |
| pyautogui / reportlab / fpdf | **TIDAK ADA** |
| Edge + Chrome | ADA ✓ (dipakai untuk cetak PDF) |
| node / npx / git | ADA ✓ |
| Docker | **TIDAK ADA** |
| Virtualenv di repo | **TIDAK ADA** |

## 10. Kesimpulan audit

SIGAP-NET berfungsi sebagai platform backup + integritas konfigurasi +
respons insiden terverifikasi oleh 79 test dan uji end-to-end nyata.
Klaim harus dibatasi pada fitur terbukti; batasan (restore nyata, tanpa
ekspor PDF, regresi dashboard) wajib disampaikan transparan kepada juri.
