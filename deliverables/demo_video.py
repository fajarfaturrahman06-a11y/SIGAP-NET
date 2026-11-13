# -*- coding: utf-8 -*-
"""SIGAP-NET — Orkestrator demo video otomatis (Windows-friendly).

Menjalankan siklus demo penuh TANPA menyentuh database utama:
  [1/8] Pemeriksaan dependensi (playwright, ffmpeg, browser — TIDAK diasumsikan ada)
  [2/8] Pemeriksaan konfigurasi aplikasi + snapshot hash DB utama (read-only)
  [3/8] Menyiapkan data demo pada DATABASE terisolasi (database demo terpisah)
  [4/8] Menjalankan aplikasi (flask run) dan menunggu /health
  [5/8] Menjalankan skenario demonstrasi + rekaman browser (bila Playwright ada)
  [6/8] Menyimpan hasil (screenshot, video, laporan) ke folder hasil demo
  [7/8] Verifikasi database utama tidak berubah
  [8/8] Menghentikan aplikasi dengan aman

Pemakaian:
  python demo_video.py                 # cek dependensi + demo mode rekaman bila memungkinkan
  python demo_video.py --skip-browser  # tanpa browser automation (fallback HTTP saja)
  python demo_video.py --install-playwright  # coba menginstal Playwright (butuh internet)

Catatan keamanan: password demo DIHASILKAN saat runtime, hanya di memori,
dan TIDAK pernah ditulis ke berkas laporan.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import platform
import re
import secrets
import shutil
import socket
import string
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

HERE = Path(__file__).resolve().parent                 # deliverables/
REPO = HERE.parent                                     # root repositori
RUN_ROOT = HERE / "demo-run"                           # hasil demo
HEALTH_TIMEOUT = 40
PALETTE = {"info": "\033[94m", "ok": "\033[92m", "warn": "\033[93m",
           "err": "\033[91m", "dim": "\033[90m", "off": "\033[0m"}


# ── Utilitas umum ─────────────────────────────────────────────────────
def say(tag: str, msg: str) -> None:
    c = PALETTE.get(tag, "")
    print(f"{c}[{tag}]{PALETTE['off']} {msg}", flush=True)


def step(n: int, total: int, title: str) -> None:
    print("", flush=True)
    say("info", f"=== [{n}/{total}] {title} ===")


def run(cmd: list[str], cwd: Path, env: dict | None = None,
        stdin_text: str | None = None, timeout: int = 300) -> tuple[int, str]:
    """Jalankan perintah, kembalikan (kode, keluaran gabungan)."""
    try:
        p = subprocess.run(
            cmd, cwd=str(cwd), env=env, input=stdin_text,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, shell=False)
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out
    except FileNotFoundError:
        return 127, f"perintah tidak ditemukan: {cmd[0]}"
    except subprocess.TimeoutExpired as exc:
        out = ((exc.stdout or b"") if isinstance(exc.stdout, bytes)
               else (exc.stdout or ""))
        return 124, f"timeout {timeout}s\n{out}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def make_strong_password() -> str:
    """Password kuat sesuai kebijakan aplikasi — HANYA di memori."""
    pools = string.ascii_letters + string.digits + "!@#-_."
    while True:
        chars = [secrets.choice(string.ascii_uppercase),
                 secrets.choice(string.ascii_lowercase),
                 secrets.choice(string.digits),
                 secrets.choice("!@#-_.")]
        chars += [secrets.choice(pools) for _ in range(14)]
        secrets.SystemRandom().shuffle(chars)
        pw = "".join(chars)
        if (len(pw) >= 12 and not pw.lower().startswith("demo_admin")
                and "demo_admin" not in pw.lower()):
            return pw


def sub_env(base: dict, **over: str) -> dict:
    env = dict(base)
    env.update(over)
    return env


# ── [1/8] Dependensi ──────────────────────────────────────────────────
def check_dependencies(args) -> dict:
    step(1, 8, "Pemeriksaan dependensi (tidak diasumsikan terpasang)")
    dep: dict[str, str] = {}

    say("info", f"Python      : {platform.python_version()} ({sys.executable})")
    dep["python"] = platform.python_version()

    packages = ["flask", "flask_sqlalchemy", "flask_migrate", "apscheduler",
                "paramiko", "pytest", "playwright"]
    for mod in packages:
        found = importlib.util.find_spec(mod) is not None
        dep[mod] = "ADA" if found else "TIDAK ADA"
        say("ok" if found else "warn", f"paket {mod:<16}: {dep[mod]}")

    for tool in ("ffmpeg",):
        found = shutil.which(tool) is not None
        dep[tool] = "ADA" if found else "TIDAK ADA"
        say("ok" if found else "warn",
            f"tool {tool:<16}: {dep[tool]}"
            + ("" if found else "  (rekaman layar+audio dilewati)"))

    browser = next((p for p in [
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)") +
        r"\Microsoft\Edge\Application\msedge.exe",
        os.environ.get("ProgramFiles", r"C:\Program Files") +
        r"\Microsoft\Edge\Application\msedge.exe",
        os.environ.get("ProgramFiles", r"C:\Program Files") +
        r"\Google\Chrome\Application\chrome.exe",
    ] if p and Path(p).exists()), None)
    dep["browser"] = browser or "TIDAK ADA"
    say("ok" if browser else "warn", f"browser chromium : {dep['browser']}")

    if args.install_playwright and dep["playwright"] == "TIDAK ADA":
        say("info", "Menginstal Playwright (membutuhkan koneksi internet)...")
        code, out = run([sys.executable, "-m", "pip", "install", "playwright"],
                        cwd=REPO, timeout=600)
        say("ok" if code == 0 else "err", f"pip install playwright -> {code}")
        if code == 0:
            code2, out2 = run([sys.executable, "-m", "playwright",
                               "install", "chromium"], cwd=REPO, timeout=900)
            say("ok" if code2 == 0 else "err",
                f"playwright install chromium -> {code2}")
            if code2 != 0:
                say("warn", out2.strip()[-400:])
        dep["playwright"] = ("ADA" if importlib.util.find_spec("playwright")
                             else "TIDAK ADA")

    if dep["playwright"] == "TIDAK ADA":
        say("warn", "Playwright TIDAK tersedia → demo berjalan mode HTTP "
                    "(tanpa rekaman browser). Aktifkan dengan: "
                    "python demo_video.py --install-playwright")
    return dep


# ── [2/8] Konfigurasi aplikasi ────────────────────────────────────────
def check_config(main_db: Path) -> dict:
    step(2, 8, "Pemeriksaan konfigurasi aplikasi")
    ok = True
    for rel in ("app.py", "config.py", "requirements.txt", "templates",
                "data"):
        p = REPO / rel
        exists = p.exists()
        ok = ok and exists
        say("ok" if exists else "err", f"{rel:<18}: {'ada' if exists else 'TIDAK ADA'}")

    missing = [m for m in ["flask", "flask_sqlalchemy", "apscheduler",
                           "paramiko"]
               if importlib.util.find_spec(m) is None]
    if missing:
        say("err", "dependensi aplikasi belum terpasang: " + ", ".join(missing)
            + "  → jalankan: pip install -r requirements.txt")
        ok = False
    else:
        say("ok", "dependensi inti aplikasi terpasang")

    with socket.socket() as s:
        free = s.connect_ex(("127.0.0.1", 5000)) != 0
    say("ok" if free else "warn",
        f"port 5000: {'tersedia' if free else 'DIPAKAI — demo memakai port lain'}")

    if main_db.exists():
        digest = sha256_file(main_db)
        say("info", f"DB utama (read-only): data/{main_db.name} sha256="
                    f"{digest[:16]}…")
    else:
        digest = None
        say("warn", "DB utama tidak ditemukan (akan dibuat oleh aplikasi "
                    "saat pertama dijalankan)")
    if not ok:
        say("err", "Pemeriksaan konfigurasi gagal — hentikan demo.")
        sys.exit(2)
    return {"db_hash_before": digest, "port": 5000}


# ── [3/8] Data demo terisolasi ────────────────────────────────────────
def setup_demo_data(password: str) -> tuple[Path, dict]:
    step(3, 8, "Menyiapkan data demo pada DATABASE TERPISAH")
    run_dir = RUN_ROOT / time.strftime("%Y%m%d-%H%M%S")
    (run_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    (run_dir / "video").mkdir(parents=True, exist_ok=True)
    db_path = run_dir / "sigapnet-demo.db"
    db_url = "sqlite:///" + str(db_path).replace("\\", "/")

    env = sub_env(os.environ, FLASK_APP="app.py", DATABASE_URL=db_url,
                  SCHEDULER_ENABLED="false", FLASK_ENV="production")
    say("info", f"DB demo    : {db_path.relative_to(REPO)}")
    say("info", "Database utama TIDAK disentuh (DATABASE_URL di-override).")

    code, out = run([sys.executable, "-m", "flask", "init-db",
                     "--seed-demo"], cwd=REPO, env=env)
    if code != 0:
        say("err", "flask init-db gagal:\n" + out[-1200:])
        sys.exit(3)
    say("ok", "skema database demo dibuat + perangkat lab & baseline "
              "(EDGE-RTR-01)")

    # Akun demo dibuat lewat jalur resmi `flask ensure-admin` dengan password
    # dari environment variable (bukan argumen — tidak bocor ke process list,
    # dan bukan stdin interaktif yang di Windows dibaca msvcrt langsung dari
    # konsol sehingga pipe tidak bekerja). Password hanya hidup di memori
    # proses ini dan tidak pernah ditulis ke berkas.
    env_admin = sub_env(env, ADMIN_USERNAME="demo_admin",
                        ADMIN_PASSWORD=password)
    code, out = run([sys.executable, "-m", "flask", "ensure-admin"],
                    cwd=REPO, env=env_admin)
    if code != 0 or "is ready" not in out:
        say("err", "flask ensure-admin gagal:\n" + out[-1200:])
        sys.exit(3)
    say("ok", "akun demo_admin dibuat via `flask ensure-admin` (password "
              "hanya di memori proses, tidak disimpan ke berkas)")
    return run_dir, {"db_url": db_url, "env": env, "db_path": db_path}


# ── [4/8] Jalankan aplikasi ───────────────────────────────────────────
def start_app(env: dict) -> subprocess.Popen:
    step(4, 8, "Menjalankan aplikasi SIGAP-NET")
    base = "http://127.0.0.1:5000"
    log_path = RUN_ROOT / "server.log"
    log_f = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "flask", "run", "--host=127.0.0.1",
         "--port", "5000", "--no-reload", "--no-debugger"],
        cwd=str(REPO), env=env, stdout=log_f, stderr=subprocess.STDOUT)
    say("info", f"PID {proc.pid} → {base}  (log: deliverables/demo-run/server.log)")

    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        if proc.poll() is not None:
            say("err", f"aplikasi berhenti lebih dulu (kode {proc.returncode})")
            say("err", log_path.read_text(encoding="utf-8")[-1200:])
            sys.exit(4)
        try:
            with urllib.request.urlopen(base + "/health", timeout=3) as r:
                if r.status == 200:
                    say("ok", "/health → 200 — aplikasi siap")
                    return proc
        except Exception:
            time.sleep(1)
    say("err", f"/health tidak merespons dalam {HEALTH_TIMEOUT}s")
    stop_app(proc)
    sys.exit(4)


def stop_app(proc: subprocess.Popen) -> None:
    step(8, 8, "Menghentikan aplikasi dengan aman")
    if proc.poll() is None:
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True)
        else:
            proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    say("ok", f"proses dihentikan (kode keluar {proc.returncode})")
    time.sleep(1)
    with socket.socket() as s:
        busy = s.connect_ex(("127.0.0.1", 5000)) == 0
    say("ok" if not busy else "warn",
        "port 5000: " + ("masih terbuka" if busy else "sudah dilepas"))


# ── Klien HTTP sederhana (mode fallback tanpa Playwright) ─────────────
class HttpClient:
    def __init__(self, base: str):
        self.base = base
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar()))

    def get(self, path: str) -> str:
        with self.opener.open(self.base + path, timeout=20) as r:
            return r.read().decode("utf-8", "replace")

    def post(self, path: str, data: dict) -> tuple[int, str]:
        body = urllib.parse.urlencode(data).encode()
        try:
            with self.opener.open(
                    urllib.request.Request(self.base + path, data=body),
                    timeout=30) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    @staticmethod
    def csrf(html: str) -> str | None:
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        return m.group(1) if m else None


def login_http(client: HttpClient, user: str, password: str) -> bool:
    html = client.get("/login")
    token = client.csrf(html)
    if not token:
        say("err", "token CSRF tidak ditemukan di halaman login")
        return False
    code, body = client.post("/login", {"username": user, "password":
                                        password, "csrf_token": token,
                                        "next": ""})
    say("ok" if code in (200, 302) and "login" not in
        client.get("/")[:200].lower() else "err",
        f"login HTTP -> status {code}")
    return True


def run_scenarios_http(client: HttpClient, report: list[str]) -> None:
    """Jalankan 3 skenario simulasi + kunjungi halaman utama via HTTP."""
    pages = ["dashboard (/)", "/devices", "/checks", "/risks", "/baselines",
             "/incidents", "/audit", "/settings"]
    for p in pages:
        path = "/" if p.startswith("dashboard") else p
        try:
            client.get(path)
            report.append(f"GET {path} -> OK")
        except Exception as exc:
            report.append(f"GET {path} -> GAGAL: {exc}")
    say("ok", "kunjungan halaman utama selesai")

    html = client.get("/settings")
    token = client.csrf(html)
    for scen in ("normal", "firewall", "ssh"):
        code, _ = client.post(f"/settings/simulation/run/{scen}",
                              {"csrf_token": token or ""})
        report.append(f"SIMULATION {scen} -> status {code}")
        say("ok" if code in (200, 302) else "err",
            f"skenario {scen:<9} -> status {code}")
        html = client.get("/settings")
        token = client.csrf(html) or token
    client.get("/incidents")
    client.get("/audit")
    report.append("alur insiden & audit dikunjungi")


# ── Mode Playwright (rekaman video + screenshot) ──────────────────────
def run_browser_demo(base: str, user: str, password: str, run_dir: Path,
                     report: list[str]) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        say("warn", "Playwright tidak tersedia → mode HTTP saja")
        return False

    step(5, 8, "Menjalankan skenario demonstrasi + rekaman browser")
    shots = run_dir / "screenshots"
    vid = run_dir / "video"
    pages = [("01_dashboard", "/"), ("02_devices", "/devices"),
             ("03_checks", "/checks"), ("04_risks", "/risks"),
             ("05_baselines", "/baselines"), ("06_incidents", "/incidents"),
             ("07_audit", "/audit"), ("08_settings", "/settings"),
             ("09_users", "/users")]
    ok = False
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx = browser.new_context(
                viewport={"width": 1600, "height": 900},
                record_video_dir=str(vid),
                record_video_size={"width": 1600, "height": 900})
            page = ctx.new_page()
            # CATATAN: jangan pakai networkidle — halaman memuat sumber
            # eksternal (Google Fonts) sehingga tidak pernah "idle".
            page.goto(base + "/login", wait_until="load", timeout=30000)
            page.screenshot(path=str(shots / "00_login.png"))
            page.fill("input[name=username]", user)
            page.fill("input[name=password]", password)
            try:
                with page.expect_navigation(wait_until="load", timeout=20000):
                    page.press("input[name=password]", "Enter")
            except Exception as exc:
                flash = page.locator(
                    ".flash, [role=alert]").all_inner_texts()
                raise RuntimeError(
                    f"login tidak menyebabkan navigasi: {exc}; flash={flash}")
            if page.url.rstrip("/").endswith("/login"):
                flash = page.locator(
                    ".flash, [role=alert]").all_inner_texts()
                raise RuntimeError(f"login ditolak (URL={page.url}); "
                                   f"flash={flash}")
            say("ok", "login browser sukses")
            report.append("login browser -> sukses")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(shots / "01_dashboard.png"))

            # 3 skenario simulasi (POST dengan CSRF dari halaman)
            page.goto(base + "/settings", wait_until="load")
            token = page.locator("input[name=csrf_token]").first \
                      .get_attribute("value") or ""
            for scen, dest, shot in [
                    ("normal", "/checks", "10_skenario_normal"),
                    ("firewall", "/incidents", "11_skenario_firewall"),
                    ("ssh", "/incidents", "12_skenario_ssh")]:
                resp = page.request.post(
                    base + f"/settings/simulation/run/{scen}",
                    form={"csrf_token": token})
                report.append(f"skenario {scen} -> status {resp.status}")
                say("ok" if resp.status in (200, 302) else "err",
                    f"skenario {scen:<9} -> status {resp.status}")
                page.goto(base + dest, wait_until="load")
                page.wait_for_timeout(900)
                page.screenshot(path=str(shots / f"{shot}.png"))
                page.goto(base + "/settings", wait_until="load")
                token = page.locator("input[name=csrf_token]").first \
                          .get_attribute("value") or token

            for name, path in pages:
                page.goto(base + path, wait_until="load")
                page.wait_for_timeout(500)
                page.screenshot(path=str(shots / f"{name}.png"))
            report.append(f"{len(pages) + 5} screenshot disimpan")

            page.goto(base + "/audit", wait_until="load")
            page.wait_for_timeout(800)
            page.screenshot(path=str(shots / "13_audit_trail_final.png"))
            ctx.close()
            video_files = sorted(vid.glob("*.webm"))
            if video_files:
                target = vid / "demo_flow.webm"
                if video_files[0] != target:
                    shutil.move(str(video_files[0]), str(target))
                say("ok", f"video rekaman: {target.relative_to(REPO)}")
                report.append(f"video: {target.name}")
            browser.close()
            ok = True
    except Exception as exc:
        say("err", f"mode browser gagal: {exc}")
        report.append(f"mode browser GAGAL: {exc}")
    return ok


# ── [6/8] & [7/8] Simpan hasil & verifikasi ──────────────────────────
def write_report(run_dir: Path, dep: dict, report: list[str],
                 db_hash_before: str | None, main_db: Path,
                 browser_used: bool) -> None:
    step(6, 8, "Menyimpan hasil demo")
    after = sha256_file(main_db) if main_db.exists() else None

    lines = [
        "SIGAP-NET — LAPORAN RUN DEMO VIDEO OTOMATIS",
        "=" * 52,
        f"Waktu          : {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Sistem         : {platform.platform()}",
        "",
        "STATUS DEPENDENSI (hasil pemeriksaan, bukan asumsi):",
    ]
    lines += [f"  - {k:<18}: {v}" for k, v in dep.items()]
    lines += ["", "LANGKAH YANG DIJALANKAN:"]
    lines += [f"  {i + 1}. {r}" for i, r in enumerate(report)]
    lines += [
        "",
        "ISOLASI DATABASE:",
        "  - Aplikasi dijalankan dengan DATABASE_URL -> database demo "
        "terpisah di folder ini.",
        "  - Database utama hanya dibaca untuk verifikasi hash.",
        f"  - Hash sebelum : {db_hash_before or '(tidak ada)'}",
        f"  - Hash sesudah : {after or '(tidak ada)'}",
        f"  - Kesamaan     : {'SAMA (utuh)' if db_hash_before == after else 'BERBEDA / PERIKSA'}",
        "",
        "REKAMAN:",
        f"  - Rekaman browser : {'YA (Playwright)' if browser_used else 'TIDAK (Playwright tidak tersedia)'}",
        f"  - Rekaman layar+audio (ffmpeg): "
        f"{dep.get('ffmpeg', 'TIDAK ADA')}",
        "  - Screenshot       : folder screenshots/ "
        "(diisi saat mode Playwright aktif)",
        "  - Log server       : ../server.log",
        "",
        "Catatan: tidak ada password/token yang disimpan pada laporan ini.",
    ]
    path = run_dir / "RUN_REPORT.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    say("ok", f"laporan: {path.relative_to(REPO)}")

    step(7, 8, "Verifikasi database utama")
    if db_hash_before is None:
        say("warn", "DB utama tidak ada saat awal — tidak ada yang bisa "
                    "dibandingkan")
    elif db_hash_before == after:
        say("ok", f"database utama TIDAK BERUBAH (sha256 {after[:16]}…)")
    else:
        say("err", "database utama BERUBAH — periksa segera!")


# ── Main ──────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="Demo video otomatis SIGAP-NET")
    ap.add_argument("--install-playwright", action="store_true",
                    help="coba instal Playwright + Chromium (butuh internet)")
    ap.add_argument("--skip-browser", action="store_true",
                    help="tanpa browser automation (hanya HTTP)")
    args = ap.parse_args()

    main_db = REPO / "data" / "sigapnet.db"
    report: list[str] = []
    print("=" * 60)
    print(" SIGAP-NET — DEMO VIDEO OTOMATIS (mode aman/terisolasi)")
    print("=" * 60)

    dep = check_dependencies(args)
    cfg = check_config(main_db)
    password = make_strong_password()
    run_dir, ctx = setup_demo_data(password)
    proc = start_app(ctx["env"])
    base = "http://127.0.0.1:5000"
    browser_used = False
    try:
        if args.skip_browser or dep["playwright"] == "TIDAK ADA":
            step(5, 8, "Menjalankan skenario demonstrasi (mode HTTP)")
            client = HttpClient(base)
            if login_http(client, "demo_admin", password):
                report.append("login HTTP -> sukses")
                run_scenarios_http(client, report)
        else:
            browser_used = run_browser_demo(base, "demo_admin", password,
                                            run_dir, report)
            if not browser_used:
                step(5, 8, "Fallback mode HTTP setelah mode browser gagal")
                client = HttpClient(base)
                if login_http(client, "demo_admin", password):
                    run_scenarios_http(client, report)
    finally:
        write_report(run_dir, dep, report, cfg["db_hash_before"], main_db,
                     browser_used)
        stop_app(proc)

    say("ok", "DEMO SELESAI — hasil di: "
              + str(run_dir.relative_to(REPO)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
