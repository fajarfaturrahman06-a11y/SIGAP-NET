# SIGAP-NET — Catatan Handoff

Status per **11 November 2026**. Dokumen ini merangkum kondisi repo, pekerjaan yang
sudah selesai, dan hal yang perlu ditindaklanjuti. Belum ada yang di-commit.

---

## 1. Kondisi database

| Item | Nilai |
|---|---|
| DB aktif | `D:\POLTEKAD\UKM\KARTIKA_CYBER\mikrotik-backup-main\data\sigapnet.db` |
| Sumber path | `config.py:14` — fallback default, `DATABASE_URL` tidak diset |
| Jumlah user | **0** (tabel `users` kosong) |
| Skema | Lengkap, 15 tabel |
| `audit_log` | Kosong |

**Belum ada akun admin.** Untuk membuat yang pertama:

```powershell
$env:FLASK_APP="app.py"; $env:SCHEDULER_ENABLED="false"
flask init-db          # hanya jika tabel belum ada
flask create-admin admin
```

Password akan diminta interaktif (lihat bagian 3).

### Catatan: DB produksi pernah terkontaminasi data test

`devices` berisi 6 baris bernama `test-device`, `test-dashboard`, `test-monitoring`,
`test-incident`, `test-response`, `integration-test` (semuanya `is_demo=0`), plus
`incidents=2`, `config_checks=3`, `baselines=6`, dan 1 `login_attempts` gagal.

Penyebabnya `test_dashboard.py` di **root repo** — file itu melakukan `from app import app`
tanpa override `DATABASE_URL`, jadi menulis ke DB asli. Berbeda dengan `tests/conftest.py:8`
yang mengarahkan ke direktori temp dan aman.

**Tindak lanjut:** pindahkan `test_dashboard.py` ke `tests/` atau hapus, lalu bersihkan
baris `test-*` dari `devices` bila tidak terpakai.

---

## 2. Bug yang sudah diperbaiki: 403 saat tambah user

**Gejala:** POST ke `/users/new` mengembalikan 403 meski sudah login sebagai admin.

**Akar masalah:** bukan RBAC, tapi CSRF. `templates/_macros.html:37` mendefinisikan macro
`csrf_field()` yang membaca variabel `csrf_token` dari context processor (`app.py:184`).
Di Jinja2, `{% from '...' import x %}` mengimpor **tanpa context**, sehingga `csrf_token`
kosong, form merender `value=""`, dan `validate_csrf_token("")` menolak request.

Login tetap berfungsi karena `templates/login.html:59` menulis `{{ csrf_token }}` langsung,
tidak lewat macro.

**Perbaikan:** menambahkan `with context` pada 9 template yang mengimpor `csrf_field`:

```jinja
{% from '_macros.html' import csrf_field with context %}
```

File terdampak: `user_form.html`, `device_form.html`, `baseline_form.html`,
`baseline_detail.html`, `check_form.html`, `device_detail.html`, `incident_detail.html`,
`dashboard.html`, `settings.html`.

**Verifikasi:** dengan login admin asli pada DB temp — `GET /users/new` → 200, token
ter-render 64 karakter, `POST /users/new` → 302, user terbuat.

**Kenapa test tidak menangkap ini:** `tests/conftest.py:44` menyetel `WTF_CSRF_ENABLED=False`
dan fixture `csrf` mengambil token dari `session_transaction()`, bukan dari HTML hasil render.
Jalur macro tidak pernah diuji. **Layak ditambahkan test yang mem-POST token hasil render.**

---

## 3. Perubahan `create-admin` (keamanan)

Sebelumnya password dikirim sebagai argumen posisi — bocor ke shell history dan process list.

Sekarang (`app.py`):

```python
@app.cli.command("create-admin")
@click.argument("username")
@click.option("--role", default="admin", type=click.Choice(["admin", "operator", "auditor"]))
@click.option("--email", default=None)
def create_admin(username, role, email):
    with app.app_context():
        if User.query.filter_by(username=username).first():
            print("User already exists.")
            return
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
```

Pengecekan duplikat sengaja ditaruh **sebelum** prompt. Validasi password, hashing
PBKDF2-SHA256, pembatasan role, dan `audit.record('USER_CREATED')` tetap jalan karena
tetap memanggil `bootstrap.create_user()` yang sama.

`tests/test_app.py` disesuaikan memakai `input='...\n...\n'`.

---

## 4. ⚠️ Belum selesai: regresi di `db.py` (uncommitted)

`db.py` berisi perubahan yang **bukan** dari sesi ini dan punya dua masalah nyata:

### a. Properti `latest_check` dihapus tapi masih dipakai

`templates/device_detail.html:30` masih memanggil `device.latest_check`. Karena properti
itu dihapus, Jinja mengembalikan `Undefined` (falsy) — tidak crash, tapi kolom
"Snapshot Terakhir" **selalu menampilkan `—` dan "belum diperiksa"**, walau datanya ada.

### b. Nilai `integrity_state` berubah tanpa menyesuaikan pemanggil

Versi lama mengembalikan `NO_BASELINE` / `NOT_CHECKED` / `INTACT` / `DRIFT`.
Versi baru hanya `UNKNOWN` / `INTACT` / `DRIFT`. Akibatnya:

- `app.py:393` — `not_checked = sum(... == 'NOT_CHECKED')` **selalu 0**, statistik dashboard salah.
- `app.py:295-296` — mapping warna `NOT_CHECKED` dan `NO_BASELINE` jadi dead code;
  `UNKNOWN` tidak ada di map sehingga jatuh ke fallback abu-abu.

### c. Catatan tambahan

- `Device.open_incidents` juga dihapus; sejauh penelusuran tidak ada yang memakainya
  (`app.py:403` dan `dashboard.html:40` memakai key dict, bukan properti). Aman.
- `activate_baseline()` dan `Baseline.save()` yang baru memanggil `db.session.commit()`
  di dalam model. Ini memecah transaksi dan bisa meng-commit perubahan lain yang masih
  pending. Pertimbangkan pindahkan commit ke layer route/service.

**Keputusan yang perlu diambil:** kembalikan `latest_check`, atau perbarui
`device_detail.html` + `app.py:393` + mapping warna agar konsisten dengan `UNKNOWN`.

---

## 5. Status file

```
Modified (belum di-commit):
  app.py                    # create-admin interaktif
  tests/test_app.py         # menyesuaikan 2 test CLI
  templates/*.html (9 file) # perbaikan CSRF with context
  db.py                     # BUKAN dari sesi ini — lihat bagian 4

Untracked:
  test_dashboard.py              # mencemari DB produksi, pindahkan/hapus
  tests/test_baselines.py
  tests/test_migration.py
  SIGAP-NET_Presentation.pptx    # materi presentasi juri, 6 slide
  ~$SIGAP-NET_Presentation.pptx  # file lock PowerPoint, aman dihapus
```

**Test:** `python -m pytest tests -q` → **79 passed**.

---

## 6. Langkah berikutnya (urut prioritas)

1. Putuskan nasib perubahan `db.py` — perbaiki regresi `latest_check` dan `integrity_state`.
2. Buat akun admin pertama lewat `flask create-admin admin`.
3. Restart Flask dan uji `/users/new` di browser (hard refresh Ctrl+Shift+R agar HTML
   lama bertoken kosong tidak terpakai dari cache).
4. Pindahkan `test_dashboard.py` ke `tests/`; bersihkan baris `test-*` di `devices`.
5. Tambahkan test CSRF yang mem-POST token hasil render HTML.
6. Commit dalam potongan terpisah: perbaikan CSRF, perubahan CLI, lalu `db.py`.

---

## 7. Konteks berguna

- Kebijakan password: `security.py:176` — min 12 karakter, huruf besar + kecil + angka +
  simbol, bukan kata umum, tidak memuat username.
- Hashing: `werkzeug.security.generate_password_hash` (PBKDF2-SHA256).
- Reset password akun yang sudah ada: **hanya via UI** `/users/<id>/edit`
  (`routes/users.py:90`). Jalur ini menaikkan `session_version` sehingga sesi lama
  langsung invalid (`authz.py:18`). **Tidak ada CLI reset-password** — pertimbangkan
  menambah `flask set-password` dengan pola prompt yang sama seperti `create-admin`.
- `ensure-admin` / `create-admin` **tidak** mereset password akun yang sudah ada;
  keduanya berhenti bila username sudah terpakai.
- Jangan pakai `ADMIN_PASSWORD` di `.env` sebagai cara reset — tidak berlaku untuk akun
  yang sudah ada, dan menyimpan password plaintext di disk. Saat ini hanya ada `.env-example`.
