# -*- coding: utf-8 -*-
"""Generator template PPTX SIGAP-NET untuk video presentasi lomba.

Menyusun 12 slide sesuai alur yang diminta, dengan desain bernuansa
teknologi, cybersecurity, dan lingkungan TNI AD (navy/gold), serta
placeholder screenshot untuk diisi tangkapan layar aktual aplikasi.

Pemakaian:  python generate_presentasi.py
Output:     SIGAP-NET_Template_Presentasi.pptx (di folder yang sama)
"""
import os

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

# ── Palet warna (nuansa militer / kemanan siber) ─────────────────────
NAVY = RGBColor(0x0A, 0x25, 0x40)      # biru tua dominan
NAVY_DK = RGBColor(0x07, 0x1A, 0x30)   # lebih gelap untuk sampul
GOLD = RGBColor(0xC9, 0xA2, 0x27)      # emas TNI/akademik
GOLD_LT = RGBColor(0xE9, 0xCF, 0x7A)   # emas terang
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
SLATE = RGBColor(0xB9, 0xC9, 0xDC)     # teks sekunder di latar gelap
INK = RGBColor(0x1C, 0x24, 0x30)       # teks utama di latar terang
GRAY = RGBColor(0x5B, 0x6B, 0x7E)
LIGHT = RGBColor(0xF4, 0xF7, 0xFB)
STEEL = RGBColor(0x14, 0x40, 0x6B)
ALERT = RGBColor(0xB4, 0x53, 0x09)     # jingga peringatan
GREEN = RGBColor(0x15, 0x80, 0x3D)
PANEL = RGBColor(0x10, 0x33, 0x54)     # panel pada latar gelap

SW, SH = Inches(13.333), Inches(7.5)   # 16:9

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "SIGAP-NET_Template_Presentasi.pptx")


# ── Helper ───────────────────────────────────────────────────────────
def rect(slide, x, y, w, h, fill=None, line=None, shape=MSO_SHAPE.RECTANGLE):
    s = slide.shapes.add_shape(shape, x, y, w, h)
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(1)
    s.shadow.inherit = False
    return s


def textbox(slide, x, y, w, h, text, size=16, color=INK, bold=False,
            align=PP_ALIGN.LEFT, font="Segoe UI", spacing=1.0,
            anchor=MSO_ANCHOR.TOP, italic=False):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        r = p.add_run()
        r.text = ln
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.italic = italic
        r.font.color.rgb = color
        r.font.name = font
    return tb


def bullets(slide, x, y, w, h, items, size=17, color=INK, gap=10,
            marker_color=GOLD, spacing=1.15):
    """Items: list of (teks, tingkat) — tingkat 0 utama, 1 sub."""
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    first = True
    for text, lvl in items:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.space_after = Pt(gap)
        p.line_spacing = spacing
        p.level = min(lvl, 4)
        marker = "▪  " if lvl == 0 else "–  "
        r0 = p.add_run()
        r0.text = marker if lvl == 0 else "     " + marker
        r0.font.size = Pt(size if lvl == 0 else size - 2)
        r0.font.color.rgb = marker_color if lvl == 0 else GRAY
        r0.font.bold = True
        r0.font.name = "Segoe UI"
        r = p.add_run()
        r.text = text
        r.font.size = Pt(size if lvl == 0 else size - 2)
        r.font.color.rgb = color if lvl == 0 else GRAY
        r.font.name = "Segoe UI"
    return tb


def blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def header(slide, kicker, title, num, total=12):
    """Header standar untuk slide isi (latar terang)."""
    rect(slide, 0, 0, SW, Inches(1.12), fill=NAVY)
    rect(slide, 0, Inches(1.12), SW, Pt(3.5), fill=GOLD)
    textbox(slide, Inches(0.55), Inches(0.14), Inches(9.5), Inches(0.3),
            kicker.upper(), size=10.5, color=GOLD_LT, bold=True)
    textbox(slide, Inches(0.55), Inches(0.4), Inches(11.0), Inches(0.62),
            title, size=26, color=WHITE, bold=True)
    textbox(slide, Inches(11.9), Inches(0.36), Inches(1.0), Inches(0.5),
            f"{num:02d}/{total}", size=13, color=GOLD_LT, bold=True,
            align=PP_ALIGN.RIGHT)
    footer(slide)


def footer(slide):
    textbox(slide, Inches(0.55), Inches(7.12), Inches(9.0), Inches(0.3),
            "SIGAP-NET · Sistem Integritas Konfigurasi dan Respons Gangguan "
            "Jaringan · UKM Kartika Cyber POLTEKAD", size=8.5, color=GRAY)
    textbox(slide, Inches(11.4), Inches(7.12), Inches(1.4), Inches(0.3),
            "Kompetisi Keamanan Siber", size=8.5, color=GRAY,
            align=PP_ALIGN.RIGHT)


def shot(slide, x, y, w, h, caption, hint):
    """Placeholder screenshot: bingkai + petunjuk isi."""
    rect(slide, x, y, w, h, fill=LIGHT, line=RGBColor(0xC8, 0xD2, 0xDE))
    rect(slide, x, y, w, Inches(0.34), fill=STEEL)
    textbox(slide, x + Inches(0.12), y + Inches(0.045), w - Inches(0.24),
            Inches(0.28), caption, size=11, color=WHITE, bold=True)
    textbox(slide, x + Inches(0.25), y + Inches(0.55), w - Inches(0.5),
            h - Inches(1.0), "◻  AREA SCREENSHOT\n\n" + hint, size=12,
            color=GRAY, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    rect(slide, x, y, w, h, fill=None, line=RGBColor(0xC8, 0xD2, 0xDE))


def kpi(slide, x, y, w, h, value, label, value_color=NAVY, bar=GOLD):
    rect(slide, x, y, w, h, fill=WHITE, line=RGBColor(0xC8, 0xD2, 0xDE))
    rect(slide, x, y, Pt(4), h, fill=bar)
    textbox(slide, x + Inches(0.18), y + Inches(0.12), w - Inches(0.3),
            Inches(0.55), value, size=25, color=value_color, bold=True)
    textbox(slide, x + Inches(0.18), y + Inches(0.68), w - Inches(0.3),
            h - Inches(0.75), label, size=10.5, color=GRAY)


def note(slide, x, y, w, text, color=STEEL, bg=LIGHT):
    h = Inches(0.78)
    rect(slide, x, y, w, h, fill=bg)
    rect(slide, x, y, Pt(4), h, fill=color)
    textbox(slide, x + Inches(0.18), y + Inches(0.09), w - Inches(0.35),
            h - Inches(0.18), text, size=11.5, color=INK,
            anchor=MSO_ANCHOR.MIDDLE)
    return h


# ── Deck ─────────────────────────────────────────────────────────────
prs = Presentation()
prs.slide_width, prs.slide_height = SW, SH
TOTAL = 12

# ── 1. Opening & identitas proyek ────────────────────────────────────
s = blank(prs)
rect(s, 0, 0, SW, SH, fill=NAVY_DK)
rect(s, Inches(0.0), 0, Pt(7), SH, fill=GOLD)
# ornamen: ring sirkuit sederhana
ring = rect(s, Inches(9.6), Inches(1.35), Inches(3.3), Inches(3.3),
            fill=None, line=RGBColor(0x24, 0x4A, 0x77), shape=MSO_SHAPE.OVAL)
rect(s, Inches(10.25), Inches(2.0), Inches(2.0), Inches(2.0), fill=None,
     line=RGBColor(0x33, 0x5E, 0x94), shape=MSO_SHAPE.OVAL)
rect(s, Inches(10.98), Inches(2.73), Inches(0.55), Inches(0.55), fill=GOLD,
     shape=MSO_SHAPE.OVAL)

textbox(s, Inches(0.75), Inches(0.6), Inches(7.5), Inches(0.4),
        "IDENTITAS PROYEK · SLIDE 1 DARI 12", size=11, color=GOLD_LT,
        bold=True)
textbox(s, Inches(0.72), Inches(1.75), Inches(9.0), Inches(1.5),
        "SIGAP-NET", size=72, color=WHITE, bold=True)
rect(s, Inches(0.78), Inches(3.05), Inches(2.6), Pt(3), fill=GOLD)
textbox(s, Inches(0.75), Inches(3.3), Inches(8.6), Inches(1.2),
        "Sistem Integritas Konfigurasi dan Respons Gangguan Jaringan",
        size=21, color=GOLD_LT)
textbox(s, Inches(0.75), Inches(4.15), Inches(8.8), Inches(1.1),
        "Platform manajemen backup konfigurasi router MikroTik dengan baseline "
        "integritas SHA-256, deteksi drift, penilaian risiko, penanganan insiden, "
        "dan audit trail append-only.", size=13.5, color=SLATE, spacing=1.25)

for i, (k, v) in enumerate([("UNIT", "UKM Kartika Cyber"),
                            ("INSTITUSI", "POLTEKAD"),
                            ("VERSI", "1.0.0"),
                            ("STACK", "Python · Flask")]):
    x = Inches(0.75 + i * 2.35)
    rect(s, x, Inches(5.75), Inches(2.15), Inches(0.95), fill=PANEL)
    textbox(s, x + Inches(0.15), Inches(5.85), Inches(1.9), Inches(0.3),
            k, size=9, color=GOLD_LT, bold=True)
    textbox(s, x + Inches(0.15), Inches(6.16), Inches(1.9), Inches(0.45),
            v, size=13.5, color=WHITE, bold=True)
textbox(s, Inches(0.75), Inches(6.95), Inches(9.0), Inches(0.35),
        "→ Narator: sapaan pembuka + satu kalimat identitas proyek (± 15 detik)",
        size=10.5, color=SLATE, italic=True)

# ── 2. Latar belakang masalah ────────────────────────────────────────
s = blank(prs)
header(s, "Latar Belakang", "Mengapa Jaringan Butuh Kendali Konfigurasi?", 2)
rows = [
    ("Backup manual & tersebar", "Konfigurasi router tersimpan di lokal "
     "masing-masing admin — sulit dipulihkan saat perangkat rusak."),
    ("Tidak ada baseline resmi", "Perubahan konfigurasi tak punya acuan "
     "perbandingan, sehingga manipulasi tidak terdeteksi."),
    ("Perubahan berisiko tanpa analisis", "Firewall dimatikan / SSH dibuka "
     "bisa lolos tanpa penilaian risiko maupun insiden."),
    ("Pemulihan tanpa persetujuan", "Rollback sembarangan dapat memperburuk "
     "keadaan; tak ada pemisahan kewenangan."),
    ("Audit trail mudah dimanipulasi", "Log yang bisa diedit tidak bernilai "
     "bukti saat investigasi insiden."),
]
y = Inches(1.55)
for i, (t, d) in enumerate(rows, 1):
    rect(s, Inches(0.55), y, Inches(12.2), Inches(0.85), fill=LIGHT)
    rect(s, Inches(0.55), y, Pt(4), Inches(0.85), fill=ALERT)
    rect(s, Inches(0.75), y + Inches(0.15), Inches(0.55), Inches(0.55),
         fill=NAVY)
    textbox(s, Inches(0.75), y + Inches(0.22), Inches(0.55), Inches(0.4),
            str(i), size=16, color=GOLD_LT, bold=True, align=PP_ALIGN.CENTER)
    textbox(s, Inches(1.5), y + Inches(0.08), Inches(3.6), Inches(0.7),
            t, size=14.5, color=NAVY, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    textbox(s, Inches(5.2), y + Inches(0.08), Inches(7.4), Inches(0.7),
            d, size=12.5, color=INK, anchor=MSO_ANCHOR.MIDDLE, spacing=1.05)
    y += Inches(0.93)
note(s, Inches(0.55), Inches(6.3), Inches(12.2),
     "Konteks: kebutuhan kendali perubahan konfigurasi di lingkungan lab/"
     "pendidikan jaringan — deteksi dini perubahan tak sah menjadi syarat "
     "demonstrasi pertahanan siber defensif.")

# ── 3. Permasalahan yang diselesaikan ────────────────────────────────
s = blank(prs)
header(s, "Rumusan Masalah", "Permasalahan yang Diselesaikan SIGAP-NET", 3)
items = [
    ("Bagaimana mendeteksi perubahan konfigurasi tak sah secara otomatis "
     "dalam hitungan detik?", 0),
    ("Bagaimana menetapkan acuan (baseline) konfigurasi yang sah dan "
     "terverifikasi?", 1),
    ("Bagaimana membedakan perubahan normal dari perubahan berbahaya?", 1),
    ("Bagaimana mengendalikan respons pemulihan agar tidak sembarangan?", 0),
    ("Siapa yang mengusul, menyetujui, dan mengeksekusi restore?", 1),
    ("Bagaimana membuktikan siapa melakukan apa dan kapan?", 0),
    ("Jejak audit harus utuh, tidak dapat diubah maupun dihapus.", 1),
    ("Bagaimana membatasi akses sesuai tanggung jawab pengguna?", 0),
    ("Pisahkan kewenangan admin, operator, dan auditor (segregation of "
     "duties).", 1),
]
bullets(s, Inches(0.6), Inches(1.55), Inches(7.6), Inches(4.7), items,
        size=15.5, gap=11)

# panel kanan: lingkup
rect(s, Inches(8.5), Inches(1.55), Inches(4.3), Inches(4.7), fill=NAVY)
rect(s, Inches(8.5), Inches(1.55), Inches(4.3), Pt(3.5), fill=GOLD)
textbox(s, Inches(8.75), Inches(1.75), Inches(3.9), Inches(0.4),
        "LINGKUP PENYELESAIAN", size=12, color=GOLD_LT, bold=True)
bullets(s, Inches(8.75), Inches(2.25), Inches(3.85), Inches(3.9), [
    ("Backup konfigurasi terpusat & terjadwal", 0),
    ("Baseline + hash SHA-256 per perangkat", 0),
    ("Deteksi drift & penilaian risiko", 0),
    ("Siklus insiden & alur persetujuan", 0),
    ("Audit trail append-only", 0),
    ("RBAC tiga peran", 0),
], size=13, color=WHITE, marker_color=GOLD, gap=13)
note(s, Inches(0.6), Inches(6.32), Inches(12.2),
     "Semua pertanyaan di atas dijawab oleh alur: baseline → pemeriksaan → "
     "risiko → insiden → respons berpersetujuan → audit trail.", color=GREEN)

# ── 4. Solusi SIGAP-NET ──────────────────────────────────────────────
s = blank(prs)
header(s, "Solusi", "SIGAP-NET: Satu Platform, Lima Kapabilitas Inti", 4)
caps = [
    ("01", "BACKUP", "Backup & jadwal cron",
     "Simpan konfigurasi router (SSH ketat), riwayat, dan penjadwalan otomatis."),
    ("02", "INTEGRITAS", "Baseline & SHA-256",
     "Baseline berversi, hash semantik stabil, diff per blok konfigurasi."),
    ("03", "RISIKO", "Penilaian otomatis",
     "LOW/MEDIUM/HIGH/CRITICAL — firewall mati & SSH aktif = HIGH."),
    ("04", "RESPONS", "Insiden & persetujuan",
     "Request → approve → execute → rollback; self-approval risiko tinggi "
     "diblokir."),
    ("05", "AUDIT", "Jejak tak terhapus",
     "Append-only via event database; aktor, peran, IP, waktu, hasil."),
]
x = Inches(0.5)
for num, tag, t, d in caps:
    rect(s, x, Inches(1.6), Inches(2.42), Inches(3.55), fill=WHITE,
         line=RGBColor(0xC8, 0xD2, 0xDE))
    rect(s, x, Inches(1.6), Inches(2.42), Inches(0.85), fill=NAVY)
    textbox(s, x + Inches(0.15), Inches(1.68), Inches(2.1), Inches(0.4),
            num, size=20, color=GOLD, bold=True)
    textbox(s, x + Inches(0.15), Inches(2.1), Inches(2.1), Inches(0.3),
            tag, size=9.5, color=GOLD_LT, bold=True)
    textbox(s, x + Inches(0.15), Inches(2.62), Inches(2.12), Inches(0.75),
            t, size=13.5, color=NAVY, bold=True, spacing=1.0)
    textbox(s, x + Inches(0.15), Inches(3.4), Inches(2.12), Inches(1.6),
            d, size=10.5, color=GRAY, spacing=1.1)
    x += Inches(2.53)

rect(s, Inches(0.5), Inches(5.3), Inches(12.33), Inches(0.95), fill=NAVY)
textbox(s, Inches(0.75), Inches(5.4), Inches(11.9), Inches(0.75),
        "Mode simulasi bawaan: 3 skenario aman (perubahan normal LOW · "
        "firewall dinonaktifkan HIGH · SSH diaktifkan HIGH) — demo tanpa "
        "menyentuh perangkat produksi.", size=13, color=WHITE,
        anchor=MSO_ANCHOR.MIDDLE, spacing=1.1)
note(s, Inches(0.5), Inches(6.32), Inches(12.33),
     "Restore ke perangkat nyata sengaja diblokir pada prototipe — hanya "
     "simulasi pemulihan yang tersedia (transparansi batasan sistem).",
     color=ALERT, bg=RGBColor(0xFD, 0xF6, 0xF0))

# ── 5. Arsitektur sistem ─────────────────────────────────────────────
s = blank(prs)
header(s, "Arsitektur", "Arsitektur Sistem SIGAP-NET", 5)
layers = [
    ("PRESENTATION", "Template Jinja2 · Dashboard, Devices, Checks, Risks, "
     "Baselines, Incidents, Audit, Users, Settings", STEEL),
    ("APPLICATION", "Flask 3.1 · 55 route · 7 blueprint · authz.py (RBAC) · "
     "csrf.py · ratelimit.py · security.py", NAVY),
    ("SERVICES", "integrity · risk · monitoring · response · simulation · "
     "audit (append-only) · adapters", RGBColor(0x0E, 0x5A, 0x3A)),
    ("DATA", "SQLAlchemy / Flask-Migrate · 15 tabel · SQLite (default) atau "
     "MySQL 8.0 · backups/ · logs/", RGBColor(0x5B, 0x3A, 0x0E)),
]
y = Inches(1.6)
for tag, desc, col in layers:
    rect(s, Inches(0.55), y, Inches(8.4), Inches(0.92), fill=col)
    textbox(s, Inches(0.75), y + Inches(0.12), Inches(2.2), Inches(0.35),
            tag, size=12, color=GOLD_LT, bold=True)
    textbox(s, Inches(0.75), y + Inches(0.45), Inches(8.0), Inches(0.42),
            desc, size=11.5, color=WHITE)
    y += Inches(1.04)
    if tag != "DATA":
        tri = rect(s, Inches(4.55), y - Inches(0.14), Inches(0.4),
                   Inches(0.16), fill=GOLD,
                   shape=MSO_SHAPE.ISOSCELES_TRIANGLE)
        tri.rotation = 180

# Kolom kanan: integrasi & scheduler
rect(s, Inches(9.25), Inches(1.6), Inches(3.55), Inches(2.05), fill=LIGHT,
     line=RGBColor(0xC8, 0xD2, 0xDE))
textbox(s, Inches(9.45), Inches(1.72), Inches(3.2), Inches(0.35),
        "INTEGRASI PERANGKAT", size=11, color=NAVY, bold=True)
bullets(s, Inches(9.45), Inches(2.1), Inches(3.2), Inches(1.5), [
    ("SSH paramiko → Router MikroTik", 0),
    ("RejectPolicy: host key tak dikenal = tolak", 0),
    ("Verifikasi known_hosts wajib", 0),
    ("Adapter simulation sebagai default", 0),
], size=10.5, gap=6)
rect(s, Inches(9.25), Inches(3.8), Inches(3.55), Inches(1.35), fill=LIGHT,
     line=RGBColor(0xC8, 0xD2, 0xDE))
textbox(s, Inches(9.45), Inches(3.92), Inches(3.2), Inches(0.35),
        "SCHEDULER (APScheduler)", size=11, color=NAVY, bold=True)
bullets(s, Inches(9.45), Inches(4.28), Inches(3.2), Inches(0.9), [
    ("CronTrigger per jadwal backup", 0),
    ("Leadership lock + watchdog", 0),
], size=10.5, gap=6)

# Alur deteksi
rect(s, Inches(0.55), Inches(5.85), Inches(12.25), Inches(0.85), fill=NAVY)
flow = "Konfigurasi  →  SHA-256 semantik  →  Diff vs baseline  →  Skor risiko  →  Insiden  →  Persetujuan  →  Audit"
textbox(s, Inches(0.75), Inches(5.95), Inches(11.9), Inches(0.65),
        "ALUR DETEKSI:  " + flow, size=12.5, color=WHITE, bold=True,
        anchor=MSO_ANCHOR.MIDDLE)

# ── 6. Demonstrasi dashboard ─────────────────────────────────────────
s = blank(prs)
header(s, "Demo · Bagian 1", "Demonstrasi: Dashboard & Login", 6)
shot(s, Inches(0.55), Inches(1.55), Inches(8.1), Inches(4.7),
     "SCREENSHOT 1 — HALAMAN LOGIN & DASHBOARD",
     "Isi dengan tangkapan layar aktual:\n"
     "login.html → dashboard.html\n"
     "(statistik integritas, grafik 14 hari, aktivitas audit)")
# checklist di kanan
rect(s, Inches(8.95), Inches(1.55), Inches(3.85), Inches(4.7), fill=NAVY)
rect(s, Inches(8.95), Inches(1.55), Inches(3.85), Pt(3.5), fill=GOLD)
textbox(s, Inches(9.2), Inches(1.75), Inches(3.4), Inches(0.4),
        "POIN NARASI", size=12, color=GOLD_LT, bold=True)
bullets(s, Inches(9.2), Inches(2.2), Inches(3.45), Inches(3.9), [
    ("Login autentikasi + kebijakan password kuat", 0),
    ("Dashboard: jumlah perangkat & monitoring", 0),
    ("Rasio integritas INTACT / DRIFT", 0),
    ("Grafik perubahan 14 hari terakhir", 0),
    ("Distribusi risiko per level", 0),
    ("Aktivitas audit terbaru (siapa-apa-kapan)", 0),
    ("3 tombol skenario simulasi siap dijalankan", 0),
], size=11.5, color=WHITE, gap=12)
note(s, Inches(0.55), Inches(6.32), Inches(12.25),
     "Timestamp demo: tampilkan jam berjalan pada rekaman agar terlihat "
     "responsif; lakukan zoom pada statistik dashboard.", color=STEEL)

# ── 7. Demonstrasi fitur utama ───────────────────────────────────────
s = blank(prs)
header(s, "Demo · Bagian 2", "Demonstrasi: Fitur Utama (Baseline → Insiden "
        "→ Respons)", 7)
shot(s, Inches(0.55), Inches(1.55), Inches(6.05), Inches(2.25),
     "SCREENSHOT 2 — BASELINE & CEK INTEGRITAS",
     "baselines.html · check_detail.html (diff + hash SHA-256)")
shot(s, Inches(6.75), Inches(1.55), Inches(6.05), Inches(2.25),
     "SCREENSHOT 3 — INSIDEN & ALUR RESPONS",
     "incident_detail.html (ajukan → setujui → eksekusi)")
steps = [
    ("Jalankan 3 skenario simulasi dari Dashboard/Settings", GREEN),
    ("Skenario 1 (normal) → risiko LOW, tanpa insiden", STEEL),
    ("Skenario 2 (firewall mati) → HIGH, insiden otomatis", ALERT),
    ("Skenario 3 (SSH aktif) → HIGH, insiden + ajukan restore", ALERT),
    ("Persetujuan & eksekusi → status insiden selesai", GREEN),
    ("Bersihkan data demo bila perlu (audit tetap tersimpan)", GRAY),
]
y = Inches(4.0)
for i, (t, c) in enumerate(steps, 1):
    rect(s, Inches(0.55), y, Inches(12.25), Inches(0.42), fill=LIGHT)
    rect(s, Inches(0.55), y, Pt(4), Inches(0.42), fill=c)
    textbox(s, Inches(0.75), y + Inches(0.06), Inches(0.4), Inches(0.3),
            str(i), size=11.5, color=c, bold=True)
    textbox(s, Inches(1.2), y + Inches(0.06), Inches(11.4), Inches(0.3),
            t, size=11.5, color=INK)
    y += Inches(0.48)

# ── 8. Monitoring & integritas ───────────────────────────────────────
s = blank(prs)
header(s, "Demo · Bagian 3", "Demonstrasi: Monitoring & Integritas Jaringan", 8)
shot(s, Inches(0.55), Inches(1.55), Inches(7.4), Inches(3.4),
     "SCREENSHOT 4 — MONITORING PERANGKAT & RIWAYAT CHECK",
     "devices.html · device_detail.html · checks.html")
# kolom kanan: detail teknis
rect(s, Inches(8.2), Inches(1.55), Inches(4.6), Inches(3.4), fill=LIGHT,
     line=RGBColor(0xC8, 0xD2, 0xDE))
textbox(s, Inches(8.4), Inches(1.68), Inches(4.2), Inches(0.4),
        "YANG DITAMPILKAN DI LAYAR", size=11.5, color=NAVY, bold=True)
bullets(s, Inches(8.4), Inches(2.1), Inches(4.25), Inches(2.7), [
    ("Status perangkat & toggle monitoring", 0),
    ("Hash SHA-256 baseline vs snapshot", 0),
    ("Diff per blok: nilai lama → baru", 0),
    ("Label risiko tiap perubahan", 0),
    ("Riwayat check 14 hari (grafik)", 0),
    ("Kode & status insiden terkait", 0),
], size=11.5, gap=10)
# baris bawah: 3 skenario
labels = [("SKENARIO 1 · NORMAL", "Risiko LOW — perubahan administratif "
           "terdeteksi, tanpa insiden", GREEN),
          ("SKENARIO 2 · FIREWALL", "Risiko HIGH — firewall dinonaktifkan, "
           "insiden dibuat otomatis", ALERT),
          ("SKENARIO 3 · AKSES SSH", "Risiko HIGH — SSH diaktifkan, alur "
           "pemulihan dijalankan", ALERT)]
x = Inches(0.55)
for t, d, c in labels:
    rect(s, x, Inches(5.1), Inches(4.03), Inches(1.05), fill=WHITE,
         line=RGBColor(0xC8, 0xD2, 0xDE))
    rect(s, x, Inches(5.1), Inches(4.03), Pt(4), fill=c)
    textbox(s, x + Inches(0.15), Inches(5.22), Inches(3.75), Inches(0.32),
            t, size=10.5, color=c, bold=True)
    textbox(s, x + Inches(0.15), Inches(5.53), Inches(3.75), Inches(0.56),
            d, size=10.5, color=INK, spacing=1.05)
    x += Inches(4.11)
note(s, Inches(0.55), Inches(6.3), Inches(12.25),
     "Catatan jujur untuk juri: statistik 'belum diperiksa' pada dashboard "
     "masih 0 akibat regresi nilai integrity_state (didokumentasikan di "
     "HANDOFF.md) — sebutkan jika ditanyakan.", color=ALERT,
     bg=RGBColor(0xFD, 0xF6, 0xF0))

# ── 9. Keamanan & audit trail ────────────────────────────────────────
s = blank(prs)
header(s, "Keamanan", "Keamanan, RBAC & Audit Trail", 9)
cards = [
    ("AUTENTIKASI", ["Sesi HttpOnly · SameSite=Lax · 8 jam",
                     "Invalidasi sesi lama saat ganti password",
                     "Throttling login 5x/300 detik (DB, fails-closed)"]),
    ("KEBIJAKAN PASSWORD", ["Min 12 karakter: besar+kecil+angka+simbol",
                            "Daftar password lemah & tanpa username",
                            "Hash PBKDF2-SHA256 (Werkzeug)"]),
    ("KONTROL AKSES (RBAC)", ["admin · operator · auditor",
                              "Ditegakkan di backend, bukan hanya UI",
                              "Auditor read-only; self-approve HIGH diblokir"]),
    ("PERLINDUNGAN TAMBAHAN", ["CSRF token untuk semua aksi ubah",
                               "Anti path-traversal & sanitasi filename",
                               "SSH RejectPolicy + known_hosts"]),
]
x, y = Inches(0.55), Inches(1.55)
for i, (t, its) in enumerate(cards):
    cx = x + (Inches(6.28) if i % 2 else 0)
    cy = y + (Inches(1.85) if i >= 2 else 0)
    rect(s, cx, cy, Inches(6.05), Inches(1.7), fill=WHITE,
         line=RGBColor(0xC8, 0xD2, 0xDE))
    rect(s, cx, cy, Inches(6.05), Inches(0.42), fill=NAVY)
    textbox(s, cx + Inches(0.15), cy + Inches(0.07), Inches(5.7),
            Inches(0.3), t, size=11, color=GOLD_LT, bold=True)
    bullets(s, cx + Inches(0.15), cy + Inches(0.52), Inches(5.75),
            Inches(1.1), [(v, 0) for v in its], size=10.5, gap=4)

rect(s, Inches(0.55), Inches(5.25), Inches(12.25), Inches(1.0), fill=NAVY)
textbox(s, Inches(0.8), Inches(5.35), Inches(11.8), Inches(0.8),
        "AUDIT TRAIL APPEND-ONLY — event database memblokir UPDATE & DELETE "
        "pada tabel audit_log. Setiap aksi tercatat: aktor, peran, IP, waktu, "
        "objek, detail, hasil.", size=13, color=WHITE, bold=True,
        anchor=MSO_ANCHOR.MIDDLE, spacing=1.1)
note(s, Inches(0.55), Inches(6.32), Inches(12.25),
     "→ Sisipkan tangkapan layar halaman Audit (/audit) di sini saat editing "
     "video — slot kosong tersedia di bawah blok audit.", color=STEEL)

# ── 10. Hasil pengujian ──────────────────────────────────────────────
s = blank(prs)
header(s, "Validasi", "Hasil Pengujian & Verifikasi", 10)
kpi(s, Inches(0.55), Inches(1.6), Inches(2.9), Inches(1.5), "79",
    "Test pytest — SELURUHNYA LULUS", value_color=GREEN, bar=GREEN)
kpi(s, Inches(3.6), Inches(1.6), Inches(2.9), Inches(1.5), "15",
    "Tabel database terinisialisasi", bar=STEEL)
kpi(s, Inches(6.65), Inches(1.6), Inches(2.9), Inches(1.5), "55",
    "Route terdaftar (7 blueprint + utama)", bar=STEEL)
kpi(s, Inches(9.7), Inches(1.6), Inches(3.1), Inches(1.5), "3",
    "Skenario simulasi terotomasi", bar=GOLD)

textbox(s, Inches(0.55), Inches(3.35), Inches(12.2), Inches(0.4),
        "CAKUPAN PENGUJIAN (berkas tests/)", size=13, color=NAVY, bold=True)
cov = [
    ("test_app.py", "Password policy, login, RBAC matrix, CSRF, render "
     "seluruh template, CLI"),
    ("test_integrity.py", "Parser konfigurasi, hash SHA-256 semantik & "
     "stabil, diff, skor risiko"),
    ("test_simulation.py", "3 skenario, insiden + audit, reset demo, audit "
     "imutable, blokir restore nyata"),
    ("test_stage2b.py", "Siklus insiden, baseline, respons/rollback, "
     "antipath-XSS, timestamp UTC"),
    ("test_stage2b_security.py", "Self-approval diblokir, RBAC, rate-limit "
     "fails-closed, header keamanan"),
    ("test_baselines.py / test_migration.py", "Versi baseline unik, "
     "aktivasi, integritas, inisialisasi skema"),
]
y = Inches(3.72)
for i, (f, d) in enumerate(cov):
    rect(s, Inches(0.55), y, Inches(12.25), Inches(0.39),
         fill=LIGHT if i % 2 == 0 else WHITE,
         line=RGBColor(0xE2, 0xE9, 0xF1))
    textbox(s, Inches(0.7), y + Inches(0.055), Inches(3.4), Inches(0.3),
            f, size=10.5, color=NAVY, bold=True)
    textbox(s, Inches(4.2), y + Inches(0.055), Inches(8.4), Inches(0.3),
            d, size=10.5, color=INK)
    y += Inches(0.43)
note(s, Inches(0.55), Inches(6.32), Inches(12.25),
     "Perintah reproduksi: pip install -r requirements-dev.txt && python -m "
     "pytest -q   (test terisolasi pada database sementara)", color=GREEN)

# ── 11. Keunggulan & kontribusi ──────────────────────────────────────
s = blank(prs)
header(s, "Diferensiasi", "Keunggulan & Kontribusi", 11)
left = [
    ("End-to-end dalam satu platform", "Backup, baseline, deteksi, risiko, "
     "insiden, respons, dan audit dalam satu aplikasi web."),
    ("Integritas kriptografis", "SHA-256 semantik: stabil terhadap spasi & "
     "formatir, namun peka terhadap perubahan nilai nyata."),
    ("Kendali perubahan berjenjang", "Penilaian risiko otomatis per blok "
     "konfigurasi (firewall/SSH → HIGH)."),
    ("Pemulihan berpersetujuan", "Alur request→approve→execute→rollback "
     "dengan row-lock dan blokir self-approval."),
    ("Bukti audit yang sah", "Append-only di level database — log tidak "
     "bisa diubah/dihapus siapa pun."),
    ("Transparansi batasan", "Restore perangkat nyata diblokir; mode "
     "simulasi aman untuk demonstrasi."),
]
y = Inches(1.55)
for t, d in left:
    rect(s, Inches(0.55), y, Inches(7.5), Inches(0.75), fill=LIGHT)
    rect(s, Inches(0.55), y, Pt(4), Inches(0.75), fill=GOLD)
    textbox(s, Inches(0.75), y + Inches(0.05), Inches(7.15), Inches(0.28),
            t, size=12.5, color=NAVY, bold=True)
    textbox(s, Inches(0.75), y + Inches(0.33), Inches(7.2), Inches(0.4),
            d, size=10.5, color=INK, spacing=1.0)
    y += Inches(0.78)

rect(s, Inches(8.3), Inches(1.55), Inches(4.5), Inches(4.5), fill=NAVY)
rect(s, Inches(8.3), Inches(1.55), Inches(4.5), Pt(3.5), fill=GOLD)
textbox(s, Inches(8.55), Inches(1.75), Inches(4.0), Inches(0.4),
        "KONTRIBUSI PENGEMBANGAN", size=12, color=GOLD_LT, bold=True)
bullets(s, Inches(8.55), Inches(2.2), Inches(4.1), Inches(3.7), [
    ("Kode bersih & teruji (pytest + ruff)", 0),
    ("Migrasi skema versioned (Alembic)", 0),
    ("Dokumentasi README & HANDOFF teknis", 0),
    ("Keamanan by-default: tanpa akun/secret bawaan", 0),
    ("Arsitektur adapter — siap integrasi perangkat lain", 0),
    ("Docker & systemd untuk penyebaran", 0),
    ("Cocok sebagai platform edukasi pertahanan siber", 0),
], size=11.5, color=WHITE, gap=11)
note(s, Inches(0.55), Inches(6.32), Inches(12.25),
     "→ Ganti poin 'kontribusi' dengan pencapaian tim bila ada data resmi "
     "kompetisi (jangan tampilkan angka statistik yang belum diverifikasi).",
     color=ALERT, bg=RGBColor(0xFD, 0xF6, 0xF0))

# ── 12. Kesimpulan ───────────────────────────────────────────────────
s = blank(prs)
rect(s, 0, 0, SW, SH, fill=NAVY_DK)
rect(s, 0, 0, Pt(7), SH, fill=GOLD)
textbox(s, Inches(0.75), Inches(0.6), Inches(8.0), Inches(0.4),
        "PENUTUP · SLIDE 12 DARI 12", size=11, color=GOLD_LT, bold=True)
textbox(s, Inches(0.72), Inches(1.15), Inches(9.5), Inches(0.9),
        "Kesimpulan", size=44, color=WHITE, bold=True)
rect(s, Inches(0.78), Inches(2.1), Inches(2.6), Pt(3), fill=GOLD)
bullets(s, Inches(0.75), Inches(2.45), Inches(8.4), Inches(3.4), [
    ("SIGAP-NET menjawab kendali perubahan konfigurasi jaringan: dari backup "
     "manual menjadi siklus penuh — baseline, deteksi, risiko, respons, audit.", 0),
    ("Diuji 79 test lulus, termasuk aspek keamanan: RBAC, CSRF, throttling, "
     "audit imutable, dan blokir restore perangkat nyata.", 0),
    ("Transparan atas batasan: mode simulasi menjadi jalur demonstrasi resmi; "
     "regresi dashboard terdokumentasi untuk perbaikan lanjutan.", 0),
    ("Selanjutnya: perbaiki statistik dashboard, perluas adapter perangkat, "
     "dan integrasi laporan ekspor.", 0),
], size=15, color=WHITE, marker_color=GOLD, gap=14, spacing=1.15)

rect(s, Inches(9.6), Inches(2.45), Inches(3.15), Inches(3.1), fill=PANEL)
textbox(s, Inches(9.85), Inches(2.65), Inches(2.7), Inches(0.4),
        "IDENTITAS", size=11, color=GOLD_LT, bold=True)
for i, (k, v) in enumerate([("Proyek", "SIGAP-NET v1.0.0"),
                            ("Unit", "UKM Kartika Cyber"),
                            ("Institusi", "POLTEKAD"),
                            ("Fokus", "Keamanan Jaringan Defensif")]):
    yy = Inches(3.1 + i * 0.6)
    textbox(s, Inches(9.85), yy, Inches(2.7), Inches(0.25), k, size=9,
            color=SLATE)
    textbox(s, Inches(9.85), yy + Inches(0.2), Inches(2.7), Inches(0.32),
            v, size=12, color=WHITE, bold=True)

textbox(s, Inches(0.75), Inches(6.35), Inches(9.0), Inches(0.5),
        "Terima Kasih — Siap untuk sesi tanya jawab juri.", size=17,
        color=GOLD_LT, bold=True)
textbox(s, Inches(0.75), Inches(6.9), Inches(11.5), Inches(0.4),
        "→ Narator: rangkuman 10 detik + undangan tanya jawab · "
        "Akhir video", size=10.5, color=SLATE, italic=True)

prs.save(OUT)
print(f"OK: {OUT} ({len(prs.slides.__iter__.__self__._sldIdLst)} slide)")
