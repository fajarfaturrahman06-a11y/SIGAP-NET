# -*- coding: utf-8 -*-
"""SIGAP-NET — Perekam video demo untuk YouTube.

Merekam alur demo yang "menjual": login → dashboard → 3 skenario simulasi
(klik tombol nyata, bukan API) → tur halaman → audit trail.

Menghasilkan:
  - video mentah .webm (Playwright, 1600x900)
  - timeline.json  → dasar pembuatan subtitle Indonesia (SRT)

Database terisolasi (DATABASE_URL di-override) — database utama tidak
disentuh. Password demo hanya di memori.

Pemakaian:  python buat_video_youtube.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import demo_video as dv  # noqa: E402  (helper orkestrator yang sudah teruji)

OUT_DIR = HERE / "video-youtube"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Bersihkan sisa perekaman sebelumnya agar tidak tertukar
    raw_dir = OUT_DIR / "raw"
    if raw_dir.exists():
        for old in raw_dir.glob("*.webm"):
            old.unlink(missing_ok=True)
    print("=" * 60)
    print(" SIGAP-NET — Perekaman video demo (YouTube)")
    print("=" * 60)

    main_db = dv.REPO / "data" / "sigapnet.db"

    class _Args:
        install_playwright = False

    dv.check_dependencies(_Args())
    cfg = dv.check_config(main_db)
    password = dv.make_strong_password()
    run_dir, ctx = dv.setup_demo_data(password)
    proc = dv.start_app(ctx["env"])
    base = "http://127.0.0.1:5000"
    timeline: list[dict] = []
    video_path: Path | None = None

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(
                viewport={"width": 1600, "height": 900},
                record_video_dir=str(OUT_DIR / "raw"),
                record_video_size={"width": 1600, "height": 900})
            page = context.new_page()
            page.on("dialog", lambda d: d.accept())  # handler data-confirm
            t0 = time.time()

            def mark(label: str, hold: float = 0.0) -> None:
                """Catat waktu mulai tampilan sebuah adegan + jeda hold."""
                timeline.append({"t": round(time.time() - t0, 2),
                                 "label": label})
                dv.say("ok", f"[{timeline[-1]['t']:6.1f}s] {label}")
                if hold:
                    page.wait_for_timeout(int(hold * 1000))

            # ── ADEGAN 1: Login ──────────────────────────────────────
            page.goto(base + "/login", wait_until="load", timeout=30000)
            mark("Halaman login — autentikasi dengan kebijakan password "
                 "kuat (min 12 karakter, 4 jenis karakter)", 2.0)
            page.fill("input[name=username]", "demo_admin")
            page.fill("input[name=password]", password)
            with page.expect_navigation(wait_until="load", timeout=20000):
                page.press("input[name=password]", "Enter")
            if page.url.rstrip("/").endswith("/login"):
                raise RuntimeError(f"login gagal: {page.url}")
            # ── ADEGAN 2: Dashboard ──────────────────────────────────
            # CATATAN: mark() SELALU dipanggil tepat saat adegan mulai
            # tampil (sebelum hold) supaya subtitle sinkron dengan visual.
            mark("Dashboard Monitoring SIGAP-NET — ringkasan integritas "
                 "jaringan secara real-time", 4.0)
            page.mouse.move(700, 220)        # sorot kartu statistik
            page.wait_for_timeout(1500)
            page.mouse.move(1300, 330)       # sorot tombol skenario
            page.wait_for_timeout(1500)

            # ── ADEGAN 3: Skenario 1 (risiko normal) ─────────────────
            with page.expect_navigation(wait_until="load", timeout=20000):
                page.locator("button:has-text('Skenario 1')").first.click()
            mark("Skenario 1 — perubahan normal terdeteksi: risiko LOW, "
                 "tidak ada insiden (perubahan administratif wajar)", 3.5)

            # ── ADEGAN 4: Skenario 2 (firewall) ──────────────────────
            page.goto(base + "/", wait_until="load")
            page.wait_for_timeout(1500)
            with page.expect_navigation(wait_until="load", timeout=20000):
                page.locator("button:has-text('Skenario 2')").first.click()
            mark("Skenario 2 — firewall dinonaktifkan: risiko HIGH, "
                 "insiden dibuat otomatis oleh sistem", 3.5)
            page.goto(base + "/incidents", wait_until="load")
            mark("Incident Management — insiden terbuka tampil dengan "
                 "status, risiko, dan keterkaitan konfigurasi", 3.0)

            # ── ADEGAN 5: Skenario 3 (SSH) ───────────────────────────
            page.goto(base + "/", wait_until="load")
            page.wait_for_timeout(1500)
            with page.expect_navigation(wait_until="load", timeout=20000):
                page.locator("button:has-text('Skenario 3')").first.click()
            mark("Skenario 3 — SSH diaktifkan tanpa izin: risiko HIGH; "
                 "operator dapat mengajukan pemulihan berpersetujuan", 3.5)

            # ── ADEGAN 6: Tur halaman fitur ──────────────────────────
            for path, label, hold in [
                ("/devices", "Manajemen perangkat — status, monitoring, "
                             "dan cek integritas per perangkat", 2.2),
                ("/checks", "Change Detection — riwayat pemeriksaan dengan "
                            "hash SHA-256 dan diff konfigurasi", 2.4),
                ("/risks", "Risk Assessment — klasifikasi perubahan per "
                           "tingkat risiko (LOW s/d CRITICAL)", 2.2),
                ("/baselines", "Configuration Baseline — acuan resmi "
                               "ber-versi dengan checksum SHA-256", 2.4),
                ("/users", "User Management — RBAC: admin, operator, "
                           "auditor (segregation of duties)", 2.2),
                ("/audit", "Audit Trail — append-only: setiap aksi "
                           "tercatat permanen (tak bisa diubah/dihapus)",
                 3.0),
            ]:
                page.goto(base + path, wait_until="load")
                mark(label, hold)

            # ── ADEGAN 7: Penutup di dashboard ───────────────────────
            page.goto(base + "/", wait_until="load")
            mark("Siklus penuh: baseline → deteksi → risiko → insiden → "
                 "respons → audit. SIGAP-NET siap diandalkan.", 3.5)

            context.close()      # finalisasi file video
            vids = sorted((OUT_DIR / "raw").glob("*.webm"))
            if vids:
                video_path = OUT_DIR / "demo_mentah.webm"
                video_path.unlink(missing_ok=True)   # ganti hasil lama
                vids[0].rename(video_path)
                dv.say("ok", f"video mentah: {video_path.name}")
            browser.close()
    except Exception as exc:
        dv.say("err", f"rekaman gagal: {exc}")
        return 1
    finally:
        (OUT_DIR / "timeline.json").write_text(
            json.dumps(timeline, ensure_ascii=False, indent=2),
            encoding="utf-8")
        dv.say("info", f"{len(timeline)} adegan tercatat di timeline.json")
        dv.write_report(run_dir, {}, [f"video YouTube: {len(timeline)} "
                                      "adegan"], cfg["db_hash_before"],
                        main_db, browser_used=True)
        dv.stop_app(proc)

    if video_path is None:
        dv.say("err", "file video tidak ditemukan")
        return 1
    dv.say("ok", f"SELESAI — {video_path.relative_to(dv.HERE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
