# -*- coding: utf-8 -*-
"""SIGAP-NET — Generator kartu video & thumbnail YouTube (PIL).

Membuat (1920x1080 kecuali thumbnail 1280x720):
  kartu_1_masalah.png   — pembuka masalah (hook)
  kartu_2_solusi.png    — identitas SIGAP-NET + poin jual
  kartu_3_validasi.png  — bukti/test/keamanan
  kartu_outro.png       — penutup + CTA
  thumbnail.png         — thumbnail YouTube

Pemakaian: python buat_kartu_video.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "video-youtube"
OUT.mkdir(parents=True, exist_ok=True)

W, H = 1920, 1080
NAVY_TOP = (7, 26, 48)
NAVY_BOT = (16, 58, 99)
GOLD = (201, 162, 39)
GOLD_LT = (233, 207, 122)
WHITE = (255, 255, 255)
SLATE = (185, 201, 220)
STEEL = (20, 64, 107)
FONT = "segoeuib"          # Segoe UI Bold
FONT_R = "segoeui"         # Segoe UI


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def gradient_bg() -> Image.Image:
    img = Image.new("RGB", (W, H), NAVY_TOP)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        col = tuple(int(a + (b - a) * t) for a, b in zip(NAVY_TOP, NAVY_BOT))
        d.line([(0, y), (W, y)], fill=col)
    # ornamen grid tipis
    for x in range(0, W, 96):
        d.line([(x, 0), (x, H)], fill=(255, 255, 255), width=1)
    for y in range(0, H, 96):
        d.line([(0, y), (W, y)], fill=(255, 255, 255), width=1)
    overlay = Image.new("RGB", (W, H), NAVY_TOP)
    img = Image.blend(img, overlay, 0.93)
    d = ImageDraw.Draw(img)
    # bingkai emas
    d.rectangle([40, 40, W - 40, H - 40], outline=GOLD, width=3)
    d.rectangle([52, 52, W - 52, H - 52], outline=STEEL, width=1)
    return img


def badge(d: ImageDraw.ImageDraw, x: int, y: int, text: str,
          size: int = 30) -> int:
    f = font(FONT, size)
    tb = d.textbbox((0, 0), text, font=f)
    w, h = tb[2] - tb[0], tb[3] - tb[1]
    pad_x, pad_y = 26, 14
    d.rounded_rectangle([x, y, x + w + pad_x * 2, y + h + pad_y * 2],
                        radius=8, fill=GOLD)
    d.text((x + pad_x, y + pad_y - tb[1]), text, font=f, fill=(10, 30, 55))
    return x + w + pad_x * 2


def center_text(d: ImageDraw.ImageDraw, y: int, text: str, size: int,
                fill=WHITE, font_name: str = FONT, spacing: int = 18) -> int:
    f = font(font_name, size)
    lines = text.split("\n")
    for ln in lines:
        tb = d.textbbox((0, 0), ln, font=f)
        w = tb[2] - tb[0]
        d.text(((W - w) / 2, y), ln, font=f, fill=fill)
        y += (tb[3] - tb[1]) + spacing
    return y


def save(img: Image.Image, name: str) -> None:
    p = OUT / name
    img.save(p)
    print(f"OK: {p.name}")


# ── Kartu 1: Masalah (hook) ──────────────────────────────────────────
img = gradient_bg()
d = ImageDraw.Draw(img)
badge(d, 100, 110, "MASALAHNYA", 30)
y = center_text(d, 300,
                "SATU PERUBAHAN KONFIGURASI.\n"
                "SATU KESALAHAN.\n"
                "JARINGAN TERGANGGU.",
                92, spacing=34)
d.line([(660, y + 40), (1260, y + 40)], fill=GOLD, width=5)
center_text(d, y + 80,
            "Backup manual tersebar · tidak ada acuan perubahan sah ·\n"
            "log audit yang bisa diubah tidak bernilai bukti",
            42, fill=SLATE, font_name=FONT_R, spacing=26)
save(img, "kartu_1_masalah.png")

# ── Kartu 2: Solusi / identitas ──────────────────────────────────────
img = gradient_bg()
d = ImageDraw.Draw(img)
badge(d, 100, 110, "SOLUSI", 30)
center_text(d, 250, "SIGAP-NET", 150, spacing=10)
center_text(d, 445,
            "Sistem Integritas Konfigurasi dan Respons Gangguan Jaringan",
            46, fill=GOLD_LT, font_name=FONT_R)
d.line([(560, 545), (1360, 545)], fill=GOLD, width=4)
poin = ["Baseline SHA-256 + deteksi drift otomatis",
        "Penilaian risiko & insiden berbasis persetujuan",
        "Audit trail append-only — tak bisa diubah / dihapus"]
y = 620
for p in poin:
    d.ellipse([640, y + 14, 662, y + 36], fill=GOLD)
    center_text(d, y, p, 44, fill=WHITE, font_name=FONT_R)
    y += 90
center_text(d, y + 30, "UKM Kartika Cyber · POLTEKAD", 36,
            fill=SLATE, font_name=FONT_R)
save(img, "kartu_2_solusi.png")

# ── Kartu 3: Validasi / bukti ────────────────────────────────────────
img = gradient_bg()
d = ImageDraw.Draw(img)
badge(d, 100, 110, "TERUJI & TRANSAPARAN", 30)
kolom = [("79", "TEST LULUS", "parser, hash, diff, risiko,\ninsiden, RBAC, CSRF"),
         ("3", "PERAN RBAC", "admin · operator · auditor\nditegakkan di backend"),
         ("100%", "AUDIT UTUH", "append-only di level\ndatabase — tanpa edit/hapus")]
x = 150
for nilai, label, ket in kolom:
    d.rounded_rectangle([x, 330, x + 520, 760], radius=18, fill=STEEL)
    d.rounded_rectangle([x, 330, x + 520, 348], radius=8, fill=GOLD)
    tb = d.textbbox((0, 0), nilai, font=font(FONT, 120))
    d.text((x + (520 - (tb[2] - tb[0])) / 2, 390), nilai, font=font(FONT, 120),
           fill=GOLD_LT)
    tb = d.textbbox((0, 0), label, font=font(FONT, 40))
    d.text((x + (520 - (tb[2] - tb[0])) / 2, 555), label, font=font(FONT, 40),
           fill=WHITE)
    for i, ln in enumerate(ket.split("\n")):
        tb = d.textbbox((0, 0), ln, font=font(FONT_R, 30))
        d.text((x + (520 - (tb[2] - tb[0])) / 2, 630 + i * 44), ln,
               font=font(FONT_R, 30), fill=SLATE)
    x += 560
center_text(d, 850,
            "Restore perangkat nyata sengaja diblokir — demo memakai mode "
            "simulasi aman",
            38, fill=GOLD_LT, font_name=FONT_R)
save(img, "kartu_3_validasi.png")

# ── Kartu Outro: CTA ─────────────────────────────────────────────────
img = gradient_bg()
d = ImageDraw.Draw(img)
badge(d, 100, 110, "PENUTUP", 30)
center_text(d, 300, "KENDALIKAN KONFIGURASI.\nLINDUNGI JARINGAN.",
            96, spacing=36)
d.line([(660, 560), (1260, 560)], fill=GOLD, width=5)
center_text(d, 620,
            "SIGAP-NET v1.0.0 — backup, integritas, respons, audit\n"
            "dalam satu platform web.",
            46, fill=WHITE, font_name=FONT_R, spacing=30)
center_text(d, 810, "UKM Kartika Cyber · POLTEKAD · 2026", 40,
            fill=GOLD_LT, font_name=FONT_R)
center_text(d, 900, "Sumber kode & dokumentasi: repositori proyek SIGAP-NET",
            32, fill=SLATE, font_name=FONT_R)
save(img, "kartu_outro.png")

# ── Thumbnail YouTube (1280x720) ─────────────────────────────────────
tw, th = 1280, 720
img = Image.new("RGB", (tw, th), NAVY_TOP)
d = ImageDraw.Draw(img)
for yy in range(th):
    t = yy / th
    col = tuple(int(a + (b - a) * t) for a, b in zip(NAVY_TOP, NAVY_BOT))
    d.line([(0, yy), (tw, yy)], fill=col)
d.rectangle([18, 18, tw - 18, th - 18], outline=GOLD, width=3)
badge(d, 60, 55, "DEMO SISTEM", 26)
d.text((60, 160), "SIGAP-NET", font=font(FONT, 120), fill=WHITE)
d.text((64, 310), "Deteksi Perubahan Konfigurasi\nJaringan dalam Hitungan Detik",
       font=font(FONT, 46), fill=GOLD_LT, spacing=14)
d.line([(64, 470), (640, 470)], fill=GOLD, width=4)
for i, t in enumerate(["Baseline SHA-256", "Risiko & Insiden",
                       "Audit Append-Only"]):
    x0 = 64 + i * 390
    d.rounded_rectangle([x0, 520, x0 + 360, 610], radius=12, fill=STEEL)
    tb = d.textbbox((0, 0), t, font=font(FONT, 30))
    d.text((x0 + (360 - (tb[2] - tb[0])) / 2, 548), t, font=font(FONT, 30),
           fill=WHITE)
d.text((64, 645), "UKM Kartika Cyber · POLTEKAD", font=font(FONT_R, 30),
       fill=SLATE)
img.save(OUT / "thumbnail.png")
print("OK: thumbnail.png")
