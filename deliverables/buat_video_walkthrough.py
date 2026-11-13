# -*- coding: utf-8 -*-
"""SIGAP-NET — Perakit video peluncuran + UI walkthrough (50 detik).

Pipeline: PIL/cv2 me-render frame per frame (kamera 3D halus, sorotan
teal/amber menyala, tipografi bergerak) → di-pipe ke ffmpeg → MP4 1920x1080.

Pemakaian:
    python buat_video_walkthrough.py            # render penuh 50 detik
    python buat_video_walkthrough.py --preview  # 8 frame contoh (cek visual)

Prasyarat: cv2, numpy, Pillow, ffmpeg.
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = HERE.parent
SHOTS = REPO / "deliverables" / "demo-run" / "20261112-194225" / "screenshots"
OUT = REPO / "deliverables" / "SIGAP-NET_Walkthrough_50s.mp4"
PREVIEW_DIR = Path(r"C:\Users\fajar\AppData\Local\Temp\opencode\preview_vid")

W, H, FPS = 1920, 1080, 30
UP = 3                      # faktor super-resolve sumber (1600x900 → 4800x2700)
TEAL = (145, 212, 45)       # BGR #2DD4BF (hijau toska)
TEAL_DIM = (110, 170, 40)
AMBER = (40, 165, 245)      # BGR #F5A524 (kuning amber)
GREEN = (60, 200, 150)      # BGR hijau badge LOW
RED = (60, 90, 245)         # BGR merah badge NEW
WHITE = (255, 255, 255)
GREY = (150, 165, 180)

F_BOLD = r"C:\Windows\Fonts\arialbd.ttf"
F_REG = r"C:\Windows\Fonts\arial.ttf"
F_MONO = r"C:\Windows\Fonts\consolab.ttf"

# ── Garis waktu (detik) ───────────────────────────────────────────────
T_LOGIN, T_DASH, T_BASE, T_CHECK = 0.0, 7.0, 15.0, 23.0
T_RISK, T_SLIDE, T_SLIDE_END, T_AUDIT = 32.0, 36.3, 37.1, 41.0
T_OUTRO, T_END = 46.8, 50.0
FADE = 0.55                 # durasi crossfade antar-adegan


# ── Utilitas easing ───────────────────────────────────────────────────
def clamp(v, a=0.0, b=1.0):
    return max(a, min(b, v))


def ease_io(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


def ease_out(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_out_quint(t):
    t = clamp(t)
    return 1 - (1 - t) ** 5


def lerp(a, b, t):
    return a + (b - a) * t


def seg(t, t0, t1):
    """Progres 0..1 dalam jendela [t0,t1]."""
    return clamp((t - t0) / (t1 - t0)) if t1 > t0 else 1.0


# ── Font & sprite teks ────────────────────────────────────────────────
_font_cache = {}


def font(path, size):
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]


def text_sprite(text, fpath, size, color, tracking=0):
    """Render teks → sprite RGBA (color BGR)."""
    f = font(fpath, size)
    # ukur
    tmp = Image.new("RGBA", (10, 10))
    d = ImageDraw.Draw(tmp)
    if tracking:
        w = sum(d.textlength(ch, font=f) + tracking for ch in text) - tracking
    else:
        w = d.textlength(text, font=f)
    asc, desc = f.getmetrics()
    w, h = int(w) + 8, asc + desc + 8
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r, g, b = color[2], color[1], color[0]
    if tracking:
        x = 4
        for ch in text:
            d.text((x, 2), ch, font=f, fill=(r, g, b, 255))
            x += d.textlength(ch, font=f) + tracking
    else:
        d.text((4, 2), text, font=f, fill=(r, g, b, 255))
    return np.asarray(img)


def paste_rgba(dst, sprite, x, y, alpha=1.0):
    """Composite sprite RGBA ke dst (BGR) di posisi (x,y) dengan alpha."""
    if alpha <= 0.003:
        return
    h, w = sprite.shape[:2]
    x0, y0 = int(x), int(y)
    x1, y1 = x0 + w, y0 + h
    sx0 = sy0 = 0
    if x0 < 0:
        sx0 = -x0
        x0 = 0
    if y0 < 0:
        sy0 = -y0
        y0 = 0
    x1 = min(x1, dst.shape[1])
    y1 = min(y1, dst.shape[0])
    if x1 <= x0 or y1 <= y0:
        return
    sp = sprite[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)].astype(np.float32)
    a = (sp[:, :, 3:4] / 255.0) * alpha
    region = dst[y0:y1, x0:x1].astype(np.float32)
    dst[y0:y1, x0:x1] = (region * (1 - a) + sp[:, :, :3] * a).astype(np.uint8)


# ── Latar belakang (grid + partikel + vignette) ──────────────────────
def build_bg_base():
    g = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    base = np.zeros((H, W, 3), np.float32)
    top = np.array([13, 17, 23], np.float32)     # #0D1117
    bot = np.array([7, 10, 14], np.float32)
    base[:] = top * (1 - g[:, :, None]) + bot * g[:, :, None]
    # vignette
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    vig = np.clip(1.05 - 0.42 * d ** 2, 0.42, 1.0)
    base *= vig[:, :, None]
    return base.astype(np.uint8)


RNG = np.random.default_rng(20261113)
PARTICLES = [
    (float(RNG.uniform(0, W)), float(RNG.uniform(0, H)),
     float(RNG.uniform(6, 22)), int(RNG.integers(1, 3)),
     float(RNG.uniform(0, 6.28)), int(RNG.integers(0, 2)))
    for _ in range(46)
]


def draw_bg(frame, t):
    """frame = salinan bg base; tambah grid bergerak + partikel."""
    ox = int((t * 14) % 80)
    oy = int((t * 8) % 80)
    grid = np.zeros((H, W), np.uint8)
    for x in range(-80, W + 80, 80):
        cv2.line(grid, (x + ox, 0), (x + ox, H), 255, 1)
    for y in range(-80, H + 80, 80):
        cv2.line(grid, (0, y + oy), (W, y + oy), 255, 1)
    g = cv2.GaussianBlur(grid, (0, 0), 0.6)
    frame[g > 0] = (frame[g > 0] * 0.90 +
                    np.array([10, 34, 32], np.float32) * 0.10).astype(np.uint8)
    for (px, py, spd, sz, ph, kind) in PARTICLES:
        y = (py - spd * t) % (H + 40) - 20
        x = px + 7 * math.sin(t * 0.6 + ph)
        col = TEAL if kind == 0 else AMBER
        cv2.circle(frame, (int(x), int(y)), sz, col, -1, cv2.LINE_AA)
        cv2.circle(frame, (int(x), int(y)), sz + 3,
                   tuple(int(c * 0.35) for c in col), -1, cv2.LINE_AA)


# ── Kamera 3D (perspektif yaw + pitch, zoom, fokus) ───────────────────
def camera_matrix(cx, cy, z, yaw_deg, pitch_deg=0.0, cx_screen=960, cy_screen=540):
    """Matriks 3x3 sumber(1600x900) → layar(1920x1080)."""
    th = math.radians(yaw_deg)
    ph = math.radians(pitch_deg)
    f = 2600.0
    T1 = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1]], np.float64)
    P = np.array([
        [math.cos(th), 0, 0],
        [0, math.cos(ph), 0],
        [math.sin(th) / f, math.sin(ph) / f, 1],
    ], np.float64)
    s = z * (W / 1600.0)
    S = np.array([[s, 0, 0], [0, s, 0], [0, 0, 1]], np.float64)
    T2 = np.array([[1, 0, cx_screen], [0, 1, cy_screen], [0, 0, 1]], np.float64)
    return T2 @ S @ P @ T1


def to_screen(Hm, pts):
    """pts: list (x,y) sumber → list float layar."""
    out = []
    for (x, y) in pts:
        v = Hm @ np.array([x, y, 1.0])
        out.append((v[0] / v[2], v[1] / v[2]))
    return out


# ── Gambar layar: bayangan + screenshot ──────────────────────────────
class Shot:
    """Screenshot tersuper-resolve + bayangan lembut."""

    def __init__(self, name):
        img = cv2.imread(str(SHOTS / name), cv2.IMREAD_COLOR)
        if img is None:
            raise SystemExit(f"screenshot hilang: {name}")
        self.small = img
        up = cv2.resize(img, (1600 * UP, 900 * UP), interpolation=cv2.INTER_LANCZOS4)
        # sudut membulat (radius dipanggang ke alpha)
        r = 18 * UP
        mask = np.zeros(up.shape[:2], np.uint8)
        cv2.rectangle(mask, (r, r), (up.shape[1] - r, up.shape[0] - r), 255, -1)
        cv2.rectangle(mask, (0, 0), (2 * r, 2 * r), 0, -1)
        cv2.rectangle(mask, (up.shape[1] - 2 * r, 0), (up.shape[1], 2 * r), 0, -1)
        cv2.rectangle(mask, (0, up.shape[0] - 2 * r), (2 * r, up.shape[0]), 0, -1)
        cv2.rectangle(mask, (0, 0), (2 * r, 2 * r), 0, -1)
        # sudut: gambar lingkaran terpotong
        for (cx, cy) in [(r, r), (up.shape[1] - r, r),
                         (r, up.shape[0] - r), (up.shape[1] - r, up.shape[0] - r)]:
            cv2.circle(mask, (cx, cy), r, 255, -1)
        cv2.rectangle(mask, (r, 0), (up.shape[1] - r, r), 255, -1)
        cv2.rectangle(mask, (r, up.shape[0] - r), (up.shape[1] - r, up.shape[0]), 255, -1)
        cv2.rectangle(mask, (0, r), (r, up.shape[0] - r), 255, -1)
        cv2.rectangle(mask, (up.shape[1] - r, r), (up.shape[1], up.shape[0] - r), 255, -1)
        self.bgra = np.dstack([up, mask])
        # bayangan: alpha di-blur lebar (sekali saja)
        self.shadow = cv2.GaussianBlur(mask, (0, 0), 26 * UP // 3)

    def draw(self, H_src, H_up, frame):
        """Warp screenshot + bayangan ke frame (BGR) sesuai kamera."""
        sh = cv2.warpPerspective(self.shadow, H_up, (W, H),
                                 flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        shf = (sh.astype(np.float32) / 255.0) * 0.55
        frame[:] = (frame.astype(np.float32) *
                    (1 - shf[:, :, None])).astype(np.uint8)
        warp = cv2.warpPerspective(self.bgra, H_up, (W, H),
                                   flags=cv2.INTER_LINEAR,
                                   borderMode=cv2.BORDER_CONSTANT,
                                   borderValue=(0, 0, 0, 0))
        a = warp[:, :, 3:4].astype(np.float32) / 255.0
        f = frame.astype(np.float32)
        frame[:] = (f * (1 - a) + warp[:, :, :3].astype(np.float32) * a).astype(np.uint8)


# ── Sorotan UI (kotak glow teal/amber yang menyala) ───────────────────
def draw_glow_rect(frame, Hm, rect, color, alpha, thickness=3, sigma=14,
                   fill=0.05):
    """rect = (x0,y0,x1,y1) koordinat sumber; digambar se-isi quad di layar."""
    if alpha <= 0.01:
        return
    x0, y0, x1, y1 = rect
    quad = np.array(to_screen(Hm, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]),
                    np.float32)
    xs, ys = quad[:, 0], quad[:, 1]
    pad = int(sigma * 3) + 8
    rx0 = int(max(0, xs.min() - pad))
    ry0 = int(max(0, ys.min() - pad))
    rx1 = int(min(W, xs.max() + pad))
    ry1 = int(min(H, ys.max() + pad))
    if rx1 <= rx0 or ry1 <= ry0:
        return
    roi = quad.copy()
    roi[:, 0] -= rx0
    roi[:, 1] -= ry0
    h, w = ry1 - ry0, rx1 - rx0
    mask = np.zeros((h, w), np.uint8)
    cv2.polylines(mask, [roi.astype(np.int32)], True, 255, thickness, cv2.LINE_AA)
    # isian tipis
    if fill > 0:
        fill_mask = np.zeros((h, w), np.uint8)
        cv2.fillConvexPoly(fill_mask, roi.astype(np.int32), 255, cv2.LINE_AA)
        fill_mask = cv2.GaussianBlur(fill_mask, (0, 0), 3)
        reg = frame[ry0:ry1, rx0:rx1].astype(np.float32)
        fa = (fill_mask.astype(np.float32) / 255.0) * fill * alpha
        reg = reg * (1 - fa[:, :, None]) + np.array(color, np.float32) * fa[:, :, None]
        frame[ry0:ry1, rx0:rx1] = reg.astype(np.uint8)
    glow = cv2.GaussianBlur(mask, (0, 0), sigma)
    ga = (glow.astype(np.float32) / 255.0) * 0.85 * alpha
    reg = frame[ry0:ry1, rx0:rx1].astype(np.float32)
    reg = reg * (1 - ga[:, :, None]) + np.array(color, np.float32) * ga[:, :, None]
    frame[ry0:ry1, rx0:rx1] = reg.astype(np.uint8)
    # inti garis
    cv2.polylines(frame[ry0:ry1, rx0:rx1], [roi.astype(np.int32)], True,
                  tuple(int(c * (0.35 + 0.65 * alpha)) for c in color),
                  thickness, cv2.LINE_AA)


def draw_glow_dot(frame, Hm, center, radius_src, color, alpha):
    if alpha <= 0.01:
        return
    (sx, sy) = to_screen(Hm, [center])[0]
    # radius ikut skala kamera
    (sx2, sy2) = to_screen(Hm, [(center[0] + radius_src, center[1])])[0]
    r = max(6.0, abs(sx2 - sx))
    layer = np.zeros((H, W), np.uint8)
    cv2.circle(layer, (int(sx), int(sy)), int(r), 255, -1, cv2.LINE_AA)
    glow = cv2.GaussianBlur(layer, (0, 0), r * 0.9)
    ga = (glow.astype(np.float32) / 255.0) * 0.8 * alpha
    f = frame.astype(np.float32)
    f = f * (1 - ga[:, :, None]) + np.array(color, np.float32) * ga[:, :, None]
    frame[:] = f.astype(np.uint8)
    cv2.circle(frame, (int(sx), int(sy)), int(r), color, 2, cv2.LINE_AA)


def pulse(t, start, period=1.6, lo=0.62, hi=1.0):
    """Alpha menyala berdenyut setelah `start`."""
    if t < start:
        return 0.0
    k = 0.5 + 0.5 * math.sin(2 * math.pi * (t - start) / period)
    return lo + (hi - lo) * k


# ── Caption (tipografi bergerak) ──────────────────────────────────────
def caption_sprites(line1, line2):
    s1 = text_sprite(line1, F_BOLD, 38, WHITE, tracking=3)
    s2 = text_sprite(line2, F_REG, 26, (200, 245, 240), tracking=0)
    return s1, s2


def draw_caption(frame, sprites, t_local, enter=0.35, hold=0.0, dur=8.0,
                 exit_at=None):
    s1, s2 = sprites
    if t_local < enter:
        return
    tin = ease_out_quint(seg(t_local, enter, enter + 0.65))
    a_in = clamp(seg(t_local, enter, enter + 0.45))
    a_out = 1.0
    if exit_at is not None:
        a_out = 1.0 - ease_io(seg(t_local, exit_at, exit_at + 0.45))
    a = a_in * a_out
    if a <= 0.01:
        return
    # scrim gelap-gradasi di pita bawah agar teks terbaca di atas layar terang
    h_scrim = 240
    ramp = np.linspace(0.0, 1.0, h_scrim, dtype=np.float32) ** 0.8
    alpha = (ramp * 0.72 * a).reshape(h_scrim, 1, 1)
    reg = frame[H - h_scrim:].astype(np.float32)
    frame[H - h_scrim:] = (reg * (1 - alpha)).astype(np.uint8)
    x = int(lerp(-70, 74, tin))
    # panel lower-third lembut di belakang blok teks
    pad = 20
    bx0 = int(max(-30, x - 10))
    bx1 = int(min(W - 4, x + 26 + max(s1.shape[1], s2.shape[1]) + pad))
    by0, by1 = 914, 1056
    if bx1 > bx0:
        panel = np.zeros((H, W), np.uint8)
        cv2.rectangle(panel, (bx0, by0), (bx1, by1), 255, -1, cv2.LINE_AA)
        panel = cv2.GaussianBlur(panel, (0, 0), 10)
        pa = (panel.astype(np.float32) / 255.0) * (0.60 * a)
        rf = frame.astype(np.float32)
        frame[:] = (rf * (1 - pa[:, :, None])).astype(np.uint8)
    y_bar = 934
    bar_h = int(92 * ease_out(seg(t_local, enter, enter + 0.55)))
    if bar_h > 2:
        cv2.rectangle(frame, (x, y_bar + (92 - bar_h) // 2),
                      (x + 6, y_bar + (92 + bar_h) // 2), TEAL, -1)
    paste_rgba(frame, s1, x + 24, 936, a)
    paste_rgba(frame, s2, x + 24, 986, a * 0.95)


# ── Progress bar ──────────────────────────────────────────────────────
def draw_progress(frame, t):
    y = H - 5
    frac = clamp(t / T_END)
    x = int(W * frac)
    cv2.rectangle(frame, (0, y), (W, H), (18, 26, 30), -1)
    cv2.rectangle(frame, (0, y), (x, H), TEAL, -1)
    if 0 < x < W:
        cv2.circle(frame, (x, y + 2), 6, AMBER, -1, cv2.LINE_AA)


# ── Render per adegan ─────────────────────────────────────────────────
CAP = {}


def init_caps():
    CAP["login"] = caption_sprites("PEMBUKA & LOGIN",
                                   "Integritas konfigurasi jaringan — sebelum menjadi insiden")
    CAP["dash"] = caption_sprites("DASHBOARD MONITORING",
                                  "Ringkasan integritas jaringan secara real-time")
    CAP["base"] = caption_sprites("LANGKAH 1 · BASELINE KONFIGURASI",
                                  "Acuan SHA-256 aktif untuk EDGE-RTR-01")
    CAP["check"] = caption_sprites("LANGKAH 2 · DETEKSI PERUBAHAN",
                                   "Status CHANGED · risiko LOW (hijau) & HIGH (amber)")
    CAP["risk"] = caption_sprites("LANGKAH 3 · PENILAIAN RISIKO",
                                  "Rule engine menandai perubahan tidak sah")
    CAP["inc"] = caption_sprites("LANGKAH 3 · INCIDENT MANAGEMENT",
                                 "Tiket insiden baru terbuka otomatis")
    CAP["audit"] = caption_sprites("LANGKAH 4 · AUDIT APPEND-ONLY",
                                   "Log SHA-256 yang tidak dapat diubah")


def scene_login(t, dur, bg):
    f = bg.copy()
    p = ease_io(t / dur)
    cx = lerp(800, 505, p)
    cy = lerp(455, 392, p)
    z = lerp(1.16, 1.74, p)
    yaw = lerp(2.6, -1.6, p)
    pitch = lerp(-1.0, 0.7, p)
    Hm = camera_matrix(cx, cy, z, yaw, pitch)
    draw_bg(f, t + 0.0)
    SHOTS_CACHE["00_login.png"].draw(Hm, Hm @ np.diag([1 / UP, 1 / UP, 1]), f)
    draw_glow_dot(f, Hm, (309, 272), 30, TEAL, pulse(t, 0.8, 1.7))
    draw_glow_rect(f, Hm, (275, 316, 714, 456), TEAL,
                   clamp(seg(t, 1.4, 2.1)) * pulse(t, 1.4, 1.9, 0.55, 0.95),
                   thickness=3, sigma=16, fill=0.05)
    draw_glow_rect(f, Hm, (841, 246, 1289, 664), TEAL,
                   clamp(seg(t, 3.6, 4.3)) * 0.75, thickness=2, sigma=13,
                   fill=0.025)
    draw_caption(f, CAP["login"], t, enter=0.9, exit_at=dur - 1.1)
    return f


CARDS = [
    (283, 160, 483, 260, TEAL), (500, 160, 699, 260, TEAL),
    (717, 160, 916, 260, AMBER), (934, 160, 1133, 260, AMBER),
]


def scene_dash(t, dur, bg):
    f = bg.copy()
    p1 = ease_io(seg(t, 0, 4.3))          # geser kartu kiri → kanan
    p2 = ease_io(seg(t, 4.0, dur))        # zoom ke grafik + donat
    if p2 <= 0:
        cx = lerp(430, 1245, p1)
        cy = 210
        z = 1.72
        yaw = lerp(2.4, -2.4, p1)
        pitch = -1.2
    else:
        cx = lerp(1245, 918, p2)
        cy = lerp(210, 566, p2)
        z = lerp(1.72, 1.78, p2)
        yaw = lerp(-2.4, 1.2, p2)
        pitch = lerp(-1.2, 0.8, p2)
    Hm = camera_matrix(cx, cy, z, yaw, pitch)
    draw_bg(f, t)
    SHOTS_CACHE["01_dashboard.png"].draw(Hm, Hm @ np.diag([1 / UP, 1 / UP, 1]), f)
    # kartu ringkasan menyala saat kamera melintas
    for i, (x0, y0, x1, y1, col) in enumerate(CARDS):
        st = 0.45 + i * 0.62
        draw_glow_rect(f, Hm, (x0, y0, x1, y1), col,
                       clamp(seg(t, st, st + 0.6)) * pulse(t, st, 1.7, 0.5, 0.9),
                       thickness=3, sigma=13, fill=0.045)
    draw_glow_rect(f, Hm, (283, 385, 1117, 757), TEAL,
                   clamp(seg(t, 4.7, 5.4)) * pulse(t, 4.7, 1.8, 0.5, 0.9),
                   thickness=3, sigma=16, fill=0.04)
    draw_glow_rect(f, Hm, (1160, 385, 1573, 757), AMBER,
                   clamp(seg(t, 5.6, 6.3)) * pulse(t, 5.6, 1.8, 0.5, 0.9),
                   thickness=3, sigma=16, fill=0.04)
    draw_caption(f, CAP["dash"], t, enter=0.4, exit_at=dur - 1.0)
    return f


def scene_base(t, dur, bg):
    f = bg.copy()
    p = ease_io(t / dur)
    cx = lerp(940, 742, p)
    cy = lerp(352, 344, p)
    z = lerp(1.42, 2.18, p)
    yaw = lerp(2.2, -1.8, p)
    pitch = lerp(-0.9, 0.6, p)
    Hm = camera_matrix(cx, cy, z, yaw, pitch)
    draw_bg(f, t)
    SHOTS_CACHE["05_baselines.png"].draw(Hm, Hm @ np.diag([1 / UP, 1 / UP, 1]), f)
    draw_glow_rect(f, Hm, (283, 316, 1573, 372), TEAL,
                   clamp(seg(t, 1.0, 1.7)) * pulse(t, 1.0, 1.7, 0.55, 0.95),
                   thickness=3, sigma=16, fill=0.05)
    draw_glow_rect(f, Hm, (832, 326, 1020, 362), TEAL,
                   clamp(seg(t, 3.3, 3.9)) * pulse(t, 3.3, 1.5, 0.7, 1.0),
                   thickness=4, sigma=15, fill=0.06)
    draw_glow_rect(f, Hm, (1030, 326, 1100, 362), GREEN,
                   clamp(seg(t, 5.2, 5.7)) * pulse(t, 5.2, 1.5, 0.6, 1.0),
                   thickness=3, sigma=13, fill=0.06)
    draw_caption(f, CAP["base"], t, enter=0.5, exit_at=dur - 1.0)
    return f


ROWS_CHECK = [
    (296, 325, 1560, 365, AMBER, 3.0),
    (296, 382, 1560, 420, AMBER, 3.9),
    (296, 439, 1560, 477, GREEN, 4.8),
]


def scene_check(t, dur, bg):
    f = bg.copy()
    p = ease_io(t / dur)
    cx = lerp(935, 862, p)
    cy = lerp(372, 402, p)
    z = lerp(1.52, 1.92, p)
    yaw = lerp(-2.0, 1.8, p)
    pitch = lerp(0.8, -0.6, p)
    Hm = camera_matrix(cx, cy, z, yaw, pitch)
    draw_bg(f, t)
    SHOTS_CACHE["03_checks.png"].draw(Hm, Hm @ np.diag([1 / UP, 1 / UP, 1]), f)

    # animasi pemindaian: garis menyapu tabel (1.2s → 5.2s)
    if 1.1 < t < 5.6:
        sp = ease_io(seg(t, 1.2, 5.2))
        yscan = lerp(300, 492, sp)
        xa, xb = 296, 1560
        # ekor
        for k, (off, al, th) in enumerate([(34, 0.16, 2), (22, 0.28, 2),
                                           (12, 0.45, 3)]):
            y = yscan - off
            pa, pb = to_screen(Hm, [(xa, y), (xb, y)])
            cv2.line(f, (int(pa[0]), int(pa[1])), (int(pb[0]), int(pb[1])),
                     tuple(int(c * al) for c in TEAL), th, cv2.LINE_AA)
        pa, pb = to_screen(Hm, [(xa, yscan), (xb, yscan)])
        layer = np.zeros((H, W), np.uint8)
        cv2.line(layer, (int(pa[0]), int(pa[1])), (int(pb[0]), int(pb[1])),
                 255, 4, cv2.LINE_AA)
        glow = cv2.GaussianBlur(layer, (0, 0), 12)
        ga = (glow.astype(np.float32) / 255.0) * 0.9
        ff = f.astype(np.float32)
        ff = ff * (1 - ga[:, :, None]) + np.array(TEAL, np.float32) * ga[:, :, None]
        f[:] = ff.astype(np.uint8)
        cv2.line(f, (int(pa[0]), int(pa[1])), (int(pb[0]), int(pb[1])),
                 WHITE, 2, cv2.LINE_AA)

    # sorotan baris: LOW hijau vs HIGH amber
    for (x0, y0, x1, y1, col, st) in ROWS_CHECK:
        a = clamp(seg(t, st, st + 0.55)) * pulse(t, st, 1.7, 0.5, 0.95)
        # kedipkan sekali saat baris disapu scan
        draw_glow_rect(f, Hm, (x0, y0, x1, y1), col, a,
                       thickness=3, sigma=15, fill=0.05)
    # badge CHANGED di setiap baris
    for i, st in enumerate([2.2, 3.1, 4.0]):
        y0 = 332 + i * 57
        draw_glow_rect(f, Hm, (682, y0, 766, y0 + 26), AMBER,
                       clamp(seg(t, st, st + 0.5)) * pulse(t, st, 1.5, 0.6, 1.0),
                       thickness=3, sigma=12, fill=0.08)
    draw_caption(f, CAP["check"], t, enter=0.5, exit_at=dur - 1.0)
    return f


def scene_risk(t, dur, bg):
    """Adegan risiko (0–4.3s) lalu geser ke insiden lewat slide_transition."""
    f = bg.copy()
    p = ease_io(t / dur)
    cx = lerp(1258, 1216, p)
    cy = lerp(384, 372, p)
    z = lerp(1.82, 2.12, p)
    yaw = lerp(2.2, -1.4, p)
    pitch = lerp(-0.8, 0.5, p)
    Hm = camera_matrix(cx, cy, z, yaw, pitch)
    draw_bg(f, t)
    SHOTS_CACHE["04_risks.png"].draw(Hm, Hm @ np.diag([1 / UP, 1 / UP, 1]), f)
    # dua baris perubahan HIGH di panel kanan
    draw_glow_rect(f, Hm, (950, 318, 1566, 370), AMBER,
                   clamp(seg(t, 0.6, 1.25)) * pulse(t, 0.6, 1.6, 0.55, 1.0),
                   thickness=3, sigma=15, fill=0.055)
    draw_glow_rect(f, Hm, (950, 380, 1566, 432), AMBER,
                   clamp(seg(t, 1.5, 2.15)) * pulse(t, 1.5, 1.6, 0.55, 1.0),
                   thickness=3, sigma=15, fill=0.055)
    # katalog aturan: firewall dinonaktifkan + SSH diaktifkan (HIGH)
    for i, st in enumerate([2.6, 3.1]):
        y0 = 417 + i * 47
        draw_glow_rect(f, Hm, (795, y0, 892, y0 + 30), AMBER,
                       clamp(seg(t, st, st + 0.5)) * pulse(t, st, 1.5, 0.5, 0.95),
                       thickness=3, sigma=12, fill=0.07)
    draw_caption(f, CAP["risk"], t, enter=0.4, exit_at=3.7)
    return f


def scene_inc(t, dur, bg):
    """t dihitung dari awal adegan insiden (setelah slide)."""
    f = bg.copy()
    p = ease_io(t / dur)
    cx = lerp(806, 796, p)
    cy = lerp(458, 470, p)
    z = lerp(1.58, 1.86, p)
    yaw = lerp(-1.8, 1.5, p)
    pitch = lerp(0.7, -0.5, p)
    Hm = camera_matrix(cx, cy, z, yaw, pitch)
    draw_bg(f, t)
    SHOTS_CACHE["06_incidents.png"].draw(Hm, Hm @ np.diag([1 / UP, 1 / UP, 1]), f)
    for i, st in enumerate([0.5, 1.25]):
        y0 = 421 + i * 49
        draw_glow_rect(f, Hm, (296, y0, 1560, y0 + 43), AMBER,
                       clamp(seg(t, st, st + 0.55)) * pulse(t, st, 1.6, 0.55, 1.0),
                       thickness=3, sigma=15, fill=0.05)
        draw_glow_rect(f, Hm, (908, y0 + 8, 964, y0 + 35), RED,
                       clamp(seg(t, st + 0.45, st + 0.9)) *
                       pulse(t, st + 0.45, 1.4, 0.7, 1.0),
                       thickness=3, sigma=12, fill=0.08)
    draw_caption(f, CAP["inc"], t, enter=0.35, exit_at=dur - 0.9)
    return f


AUDIT_PILLS = [
    (376, 400, TEAL, 0.8), (433, 457, TEAL, 1.4), (490, 514, AMBER, 2.0),
    (595, 619, TEAL, 2.6), (652, 676, TEAL, 3.2), (709, 733, AMBER, 3.8),
    (814, 838, TEAL, 4.4), (871, 895, AMBER, 5.2),
]


def scene_audit(t, dur, bg):
    f = bg.copy()
    p = ease_io(t / dur)
    cx = lerp(1035, 1010, p)
    cy = lerp(452, 690, p)
    z = lerp(1.66, 1.84, p)
    yaw = lerp(1.6, -1.4, p)
    pitch = lerp(-0.6, 0.5, p)
    Hm = camera_matrix(cx, cy, z, yaw, pitch)
    draw_bg(f, t)
    SHOTS_CACHE["13_audit_trail_final.png"].draw(
        Hm, Hm @ np.diag([1 / UP, 1 / UP, 1]), f)
    # detail hash SHA-256 disorot
    draw_glow_rect(f, Hm, (872, 474, 1352, 578), TEAL,
                   clamp(seg(t, 1.0, 1.7)) * pulse(t, 1.0, 1.7, 0.5, 0.9),
                   thickness=3, sigma=15, fill=0.04)
    # lencana SUCCESS (teal) & CHANGED (amber) menyala saat kamera melewati
    for (y0, y1, col, st) in AUDIT_PILLS:
        draw_glow_rect(f, Hm, (1376, y0, 1464, y1), col,
                       clamp(seg(t, st, st + 0.5)) * pulse(t, st, 1.5, 0.55, 1.0),
                       thickness=3, sigma=12, fill=0.08)
    draw_caption(f, CAP["audit"], t, enter=0.5, exit_at=dur - 1.4)
    return f


# ── Kartu penutup ─────────────────────────────────────────────────────
def shield_points(cx, cy, w, h):
    """Titik-titik perisai (koordinat layar)."""
    hw = w / 2
    top = cy - h / 2
    pts = [
        (cx - hw, top + h * 0.10),
        (cx - hw, top + h * 0.52),
        (cx - hw * 0.72, top + h * 0.78),
        (cx, top + h),
        (cx + hw * 0.72, top + h * 0.78),
        (cx + hw, top + h * 0.52),
        (cx + hw, top + h * 0.10),
        (cx, top),
    ]
    return np.array(pts, np.int32)


def scene_outro(t, dur, bg):
    f = bg.copy()
    draw_bg(f, t + 41.0)
    t1 = ease_out_quint(seg(t, 0.15, 1.3))     # perisai muncul
    t2 = ease_out_quint(seg(t, 0.45, 1.7))     # tracking judul
    t3 = ease_out(seg(t, 0.9, 1.9))            # slogan
    t4 = ease_out(seg(t, 1.3, 2.2))            # sub

    # perisai menyala
    if t1 > 0.01:
        sc = lerp(0.86, 1.0, t1)
        cx, cy, w, h = 960, 372, 132 * sc, 156 * sc
        pts = shield_points(cx, cy, w, h)
        layer = np.zeros((H, W), np.uint8)
        cv2.polylines(layer, [pts], True, 255, 4, cv2.LINE_AA)
        glow = cv2.GaussianBlur(layer, (0, 0), 16)
        ga = (glow.astype(np.float32) / 255.0) * 0.95 * t1
        ff = f.astype(np.float32)
        ff = ff * (1 - ga[:, :, None]) + np.array(TEAL, np.float32) * ga[:, :, None]
        f[:] = ff.astype(np.uint8)
        cv2.polylines(f, [pts], True,
                      tuple(int(c * t1) for c in TEAL), 4, cv2.LINE_AA)
        # centang di dalam perisai
        chk = np.array([[cx - 26, cy + 2], [cx - 6, cy + 24],
                        [cx + 30, cy - 22]], np.int32)
        chk = chk.astype(np.float32)
        chk[:, 0] = cx + (chk[:, 0] - cx) * sc
        chk[:, 1] = cy + (chk[:, 1] - cy) * sc
        alpha_ck = ease_out(seg(t, 0.8, 1.4))
        cv2.polylines(f, [chk.astype(np.int32)], False,
                      tuple(int(c * alpha_ck) for c in WHITE), 6, cv2.LINE_AA)

    # judul dengan tracking menyusut (tipografi bergerak)
    if t2 > 0.01:
        track = int(lerp(46, 14, t2))
        title = text_sprite("SIGAP-NET", F_BOLD, 96, WHITE, tracking=track)
        a = ease_out(seg(t, 0.45, 1.25))
        x = 960 - title.shape[1] // 2
        paste_rgba(f, title, x, 500, a)
        sub = text_sprite("DEFENSIVE SHIELD", F_BOLD, 26, TEAL, tracking=10)
        sa = ease_out(seg(t, 0.75, 1.55))
        paste_rgba(f, sub, 960 - sub.shape[1] // 2, 618, sa)

    # slogan + garis menyembur dari tengah
    if t3 > 0.01:
        slogan = text_sprite(
            "Integritas konfigurasi jaringan, terdeteksi sebelum menjadi insiden.",
            F_REG, 28, (235, 245, 245))
        paste_rgba(f, slogan, 960 - slogan.shape[1] // 2, 676, t3)
        half = int(330 * t3)
        y = 660
        cv2.line(f, (960 - half, y), (960 - 40, y), TEAL_DIM, 2, cv2.LINE_AA)
        cv2.line(f, (960 + 40, y), (960 + half, y), TEAL_DIM, 2, cv2.LINE_AA)
    if t4 > 0.01:
        sub2 = text_sprite(
            "UKM KARTIKA CYBER  ·  POLITEKNIK ADISUTJIPTO  ·  2026",
            F_REG, 21, GREY, tracking=2)
        paste_rgba(f, sub2, 960 - sub2.shape[1] // 2, 742, t4)
    return f


# ── Slide transition (geser) risiko → insiden ────────────────────────
def slide_transition(t, dur, bg, left_fn, right_fn):
    p = ease_io(t / dur)
    dx = int(W * p)
    fl = left_fn()
    fr = right_fn()
    out = bg.copy()
    # frame kiri bergeser keluar, frame kanan masuk dari kanan
    out[:, :W - dx] = fl[:, dx:]
    out[:, W - dx:] = fr[:, :dx]
    # garis pemisah menyala
    x = W - dx
    if 0 < x < W:
        layer = np.zeros((H, W), np.uint8)
        cv2.line(layer, (x, 0), (x, H), 255, 9, cv2.LINE_AA)
        glow = cv2.GaussianBlur(layer, (0, 0), 11)
        ga = np.clip(glow.astype(np.float32) / 255.0 * 2.2, 0, 1) * 0.9
        ff = out.astype(np.float32)
        ff = ff * (1 - ga[:, :, None]) + np.array(TEAL, np.float32) * ga[:, :, None]
        out[:] = ff.astype(np.uint8)
        cv2.line(out, (x, 0), (x, H), (240, 255, 255), 2, cv2.LINE_AA)
    return out


# ── Compositor utama ──────────────────────────────────────────────────
SHOTS_CACHE = {}


def init_shots():
    for n in ["00_login.png", "01_dashboard.png", "05_baselines.png",
              "03_checks.png", "04_risks.png", "06_incidents.png",
              "13_audit_trail_final.png"]:
        SHOTS_CACHE[n] = Shot(n)


def blend(a, b, alpha):
    if alpha <= 0.002:
        return a
    if alpha >= 0.998:
        return b
    return cv2.addWeighted(a, 1 - alpha, b, alpha, 0)


def frame_at(t, bg):
    # login → dash
    if T_DASH - FADE / 2 <= t < T_DASH + FADE / 2:
        a = scene_login(t, T_DASH, bg)
        b = scene_dash(max(0.0, t - T_DASH), 8.0, bg)
        return blend(a, b, ease_io(seg(t, T_DASH - FADE / 2, T_DASH + FADE / 2)))
    # dash → base
    if T_BASE - FADE / 2 <= t < T_BASE + FADE / 2:
        a = scene_dash(t - T_DASH, 8.0, bg)
        b = scene_base(max(0.0, t - T_BASE), 8.0, bg)
        return blend(a, b, ease_io(seg(t, T_BASE - FADE / 2, T_BASE + FADE / 2)))
    # base → checks
    if T_CHECK - FADE / 2 <= t < T_CHECK + FADE / 2:
        a = scene_base(t - T_BASE, 8.0, bg)
        b = scene_check(max(0.0, t - T_CHECK), 9.0, bg)
        return blend(a, b, ease_io(seg(t, T_CHECK - FADE / 2, T_CHECK + FADE / 2)))
    # checks → risk
    if T_RISK - FADE / 2 <= t < T_RISK + FADE / 2:
        a = scene_check(t - T_CHECK, 9.0, bg)
        b = scene_risk(max(0.0, t - T_RISK), 9.0, bg)
        return blend(a, b, ease_io(seg(t, T_RISK - FADE / 2, T_RISK + FADE / 2)))
    # slide risk → incident
    if T_SLIDE <= t < T_SLIDE_END:
        lt = t - T_RISK
        return slide_transition(
            t - T_SLIDE, T_SLIDE_END - T_SLIDE, bg,
            lambda: scene_risk(lt, 9.0, bg),
            lambda: scene_inc(0.0, 3.9, bg))
    # audit → risk (crossfade T_AUDIT)
    if T_AUDIT - FADE / 2 <= t < T_AUDIT + FADE / 2:
        a = scene_inc(t - (T_SLIDE_END), 3.9, bg)
        b = scene_audit(max(0.0, t - T_AUDIT), T_OUTRO - T_AUDIT, bg)
        return blend(a, b, ease_io(seg(t, T_AUDIT - FADE / 2, T_AUDIT + FADE / 2)))
    # audit → outro
    if T_OUTRO <= t < T_OUTRO + 0.7:
        a = scene_audit(t - T_AUDIT, T_OUTRO - T_AUDIT, bg)
        b = scene_outro(t - T_OUTRO, T_END - T_OUTRO, bg)
        return blend(a, b, ease_io(seg(t, T_OUTRO, T_OUTRO + 0.7)))

    if t < T_DASH:
        return scene_login(t, T_DASH, bg)
    if t < T_BASE:
        return scene_dash(t - T_DASH, 8.0, bg)
    if t < T_CHECK:
        return scene_base(t - T_BASE, 8.0, bg)
    if t < T_RISK:
        return scene_check(t - T_CHECK, 9.0, bg)
    if t < T_SLIDE:
        return scene_risk(t - T_RISK, 9.0, bg)
    if t < T_AUDIT:
        return scene_inc(t - T_SLIDE_END, 3.9, bg)
    if t < T_OUTRO:
        return scene_audit(t - T_AUDIT, T_OUTRO - T_AUDIT, bg)
    return scene_outro(t - T_OUTRO, T_END - T_OUTRO, bg)


def render_frame(t, bg):
    f = frame_at(t, bg)
    draw_progress(f, t)
    # fade dari/hitungam gelap di awal & akhir
    if t < 0.45:
        f = (f.astype(np.float32) * (t / 0.45)).astype(np.uint8)
    elif t > T_END - 0.5:
        f = (f.astype(np.float32) *
             clamp((T_END - t) / 0.5)).astype(np.uint8)
    return f


# ── Main ──────────────────────────────────────────────────────────────
def find_ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    root = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    if root.exists():
        for p in root.rglob("ffmpeg.exe"):
            return str(p)
    return None


def main():
    mode_preview = "--preview" in sys.argv
    ff = find_ffmpeg()
    if not ff:
        print("ffmpeg tidak ditemukan", file=sys.stderr)
        return 1
    print("[info] init aset …", flush=True)
    init_shots()
    init_caps()
    bg = build_bg_base()

    if mode_preview:
        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        stamps = [3.4, 11.0, 19.2, 27.6, 34.6, 38.6, 44.0, 48.7]
        for i, ts in enumerate(stamps, 1):
            t0 = time.time()
            f = render_frame(ts, bg)
            p = PREVIEW_DIR / f"prev_{i}_t{ts:04.1f}s.png"
            cv2.imwrite(str(p), f)
            print(f"[prev] {ts:5.1f}s → {p.name}  ({time.time()-t0:.1f}s)")
        print(f"[ok] preview di {PREVIEW_DIR}")
        return 0

    total = int(T_END * FPS)
    print(f"[info] render {total} frame @ {FPS}fps → {OUT.name}", flush=True)
    cmd = [ff, "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-c:v", "libx264", "-preset", "slow", "-crf", "18",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    t0 = time.time()
    for i in range(total):
        t = i / FPS
        frame = render_frame(t, bg)
        proc.stdin.write(frame.tobytes())
        if i % 150 == 0:
            el = time.time() - t0
            print(f"[render] frame {i:4d}/{total}  t={t:5.2f}s  "
                  f"({el:.0f}s terlewati)", flush=True)
    proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace")
    proc.wait()
    if proc.returncode != 0:
        print("[err] ffmpeg:", err[-1200:], file=sys.stderr)
        return 1
    print(f"[ok] selesai dalam {time.time()-t0:.0f}s → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
