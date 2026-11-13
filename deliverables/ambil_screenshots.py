"""Ambil screenshot aplikasi SIGAP-NET yang sedang berjalan untuk README.md.

Pemakaian:
    # start aplikasi dulu:  python -m flask --app app run --debug
    python deliverables/ambil_screenshots.py

Kredensial dibaca dari environment (tidak ditulis ke repo):
    SIGAP_USERNAME  default: sigapadmin
    SIGAP_PASSWORD  diminta interaktif bila tidak diset
    SIGAP_BASE      default: http://127.0.0.1:5000

Hasil: images/00_login.png .. images/09_users.png (10 file, 1600x900).
"""
import os
import sys

from playwright.sync_api import sync_playwright

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("SIGAP_BASE", "http://127.0.0.1:5000")
USERNAME = os.environ.get("SIGAP_USERNAME", "sigapadmin")
OUT = os.path.join(REPO, "images")

PAGES = [
    ("01_dashboard", "/"),
    ("02_devices", "/devices"),
    ("03_checks", "/checks"),
    ("04_risks", "/risks"),
    ("05_baselines", "/baselines"),
    ("06_incidents", "/incidents"),
    ("07_audit", "/audit"),
    ("08_settings", "/settings"),
    ("09_users", "/users"),
]


def main() -> int:
    password = os.environ.get("SIGAP_PASSWORD")
    if not password:
        import getpass
        password = getpass.getpass(f"Password {USERNAME}: ")
    if not password:
        print("Password kosong — batal.")
        return 1

    os.makedirs(OUT, exist_ok=True)
    taken = 0

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 900})

        # halaman login (sebelum autentikasi)
        page.goto(BASE + "/login", wait_until="networkidle")
        page.screenshot(path=os.path.join(OUT, "00_login.png"))
        print("shot 00_login")
        taken += 1

        # login
        page.fill("input[name=username]", USERNAME)
        page.fill("input[name=password]", password)
        page.click("button[type=submit], input[type=submit]")
        try:
            page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
        except Exception:
            print("LOGIN GAGAL — cek kredensial atau throttle login.", file=sys.stderr)
            browser.close()
            return 2
        page.wait_for_load_state("networkidle")

        for name, path in PAGES:
            page.goto(BASE + path, wait_until="networkidle")
            page.wait_for_timeout(400)  # biarkan chart/animasi selesai
            page.screenshot(path=os.path.join(OUT, f"{name}.png"))
            print(f"shot {name}")
            taken += 1

        browser.close()

    print(f"selesai — {taken} screenshot di {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
