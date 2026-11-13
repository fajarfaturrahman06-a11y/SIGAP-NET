# -*- coding: utf-8 -*-
"""SIGAP-NET — Perakit narasi suara video walkthrough 50 detik (edge-tts).

Alur:
  1. Sintesis 6 segmen narasi (Bahasa Indonesia, suara neural id-ID-ArdiNeural)
  2. Setiap segmen dipaskan ke jendela waktunya (tempo atempo bila terlalu panjang)
  3. Segmen disusun di atas track senyap 50 detik (fade in/out per segmen)
  4. Mux ke MP4 → SIGAP-NET_Walkthrough_50s_Narasi.mp4 (H.264 tanpa render ulang)

Pemakaian:  python buat_narasi_walkthrough.py
Prasyarat:  edge-tts (pip install edge-tts), ffmpeg, numpy; koneksi internet.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
VIDEO = HERE / "SIGAP-NET_Walkthrough_50s.mp4"
OUT = HERE / "SIGAP-NET_Walkthrough_50s_Narasi.mp4"
WORK = Path(r"C:\Users\fajar\AppData\Local\Temp\opencode\narasi_walkthrough")

SR = 48000
DURATION = 50.0
VOICE = "id-ID-ArdiNeural"
GAP = 0.4                  # jeda minimum antar segmen (detik)
TEMPO_MAX = 1.18           # batas percepatan agar tetap natural

# ── Naskah narasi (awal segmen, teks) ─────────────────────────────────
SEGMENTS = [
    (0.4,
     "SIGAP-NET, Defensive Shield. Integritas konfigurasi jaringan, "
     "terdeteksi sebelum menjadi insiden."),
    (7.5,
     "Dashboard monitoring menampilkan perangkat, perubahan, risiko tinggi, "
     "dan insiden terbuka, dengan grafik tren 14 hari."),
    (15.5,
     "Langkah pertama, baseline konfigurasi. Tetapkan hash verifikasi aktif "
     "sebagai acuan untuk setiap perangkat jaringan."),
    (23.5,
     "Langkah kedua, deteksi perubahan. Setiap baris dipindai; perubahan "
     "ditandai dengan risiko rendah hijau, dan risiko tinggi amber."),
    (32.5,
     "Langkah ketiga, penilaian risiko. Mesin aturan menandai SSH "
     "diaktifkan kembali dan firewall dinonaktifkan, lalu insiden baru "
     "terbuka."),
    (41.5,
     "Langkah keempat, jejak audit yang tidak dapat diubah. SIGAP-NET, "
     "terdeteksi sebelum menjadi insiden."),
]


# ── Utilitas ───────────────────────────────────────────────────────────
def find_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    root = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    if root.exists():
        for p in root.rglob("ffmpeg.exe"):
            return str(p)
    raise SystemExit("ffmpeg tidak ditemukan")


FF: str = find_ffmpeg()
FP: str = str(Path(FF).with_name("ffprobe.exe"))
if not Path(FP).exists():
    FP = shutil.which("ffprobe") or FP


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        [FP, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def decode_mono(path: Path) -> np.ndarray:
    r = subprocess.run(
        [FF, "-v", "error", "-i", str(path), "-f", "f32le",
         "-ac", "1", "-ar", str(SR), "-"],
        capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.float32)


# ── TTS ────────────────────────────────────────────────────────────────
async def _synth(text: str, path: Path) -> None:
    import edge_tts
    last: Exception | None = None
    for attempt in range(4):
        try:
            comm = edge_tts.Communicate(text, VOICE, rate="+0%")
            await comm.save(str(path))
            if path.exists() and path.stat().st_size > 1500:
                return
            last = RuntimeError("file kosong")
        except Exception as e:  # noqa: BLE001
            last = e
            await asyncio.sleep(1.5 * (attempt + 1))
    raise SystemExit(f"TTS gagal: {last} | {text[:50]}…")


def synth_all() -> list[Path]:
    async def run():
        paths = []
        for i, (_, text) in enumerate(SEGMENTS, 1):
            p = WORK / f"seg_{i}.mp3"
            await _synth(text, p)
            paths.append(p)
            print(f"[tts] segmen {i} → {p.name} "
                  f"({p.stat().st_size // 1024} KB)")
        return paths
    return asyncio.run(run())


# ── Pasca-produksi audio ───────────────────────────────────────────────
def fit_segment(src: Path, budget: float, idx: int) -> tuple[np.ndarray, float]:
    dur = probe_duration(src)
    tempo = dur / budget if dur > budget else 1.0
    if tempo > TEMPO_MAX:
        tempo = TEMPO_MAX
        print(f"[warn] segmen {idx} melebihi jendela "
              f"({dur:.1f}s > {budget:.1f}s) → dipaksa tempo {tempo:.2f}")
    out = WORK / f"seg_{idx}_fit.wav"
    if tempo > 1.001:
        subprocess.run(
            [FF, "-y", "-v", "error", "-i", str(src),
             "-filter:a", f"atempo={tempo:.4f}",
             "-ar", str(SR), "-ac", "1", str(out)],
            check=True)
        print(f"[fit] segmen {idx}: {dur:.2f}s → {probe_duration(out):.2f}s "
              f"(tempo ×{tempo:.3f})")
    else:
        shutil.copyfile(src, out) if src.suffix == ".wav" else subprocess.run(
            [FF, "-y", "-v", "error", "-i", str(src),
             "-ar", str(SR), "-ac", "1", str(out)], check=True)
        print(f"[fit] segmen {idx}: {dur:.2f}s (pas)")
    return decode_mono(out), tempo


def build_track(clips: list[tuple[float, np.ndarray]],
                limits: list[float]) -> np.ndarray:
    """Gabungkan klip; klip dipangkas bila melewati batas segmen berikut."""
    total = int(DURATION * SR)
    buf = np.zeros(total, dtype=np.float32)
    fade_n = int(0.05 * SR)
    for (start, audio), limit in zip(clips, limits):
        max_n = int((limit - start) * SR)
        n = min(len(audio), max_n, total - int(start * SR))
        if n <= 0:
            continue
        seg = audio[:n].copy()
        if n < len(audio):          # terpotong → fade out cepat
            f = min(int(0.12 * SR), n // 2)
            seg[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
        f = min(fade_n, n // 2)
        if f > 0:
            ramp = np.linspace(0, 1, f, dtype=np.float32)
            seg[:f] *= ramp
            seg[-f:] *= ramp[::-1]
        i0 = int(start * SR)
        buf[i0:i0 + n] += seg
    peak = float(np.max(np.abs(buf))) or 1.0
    buf *= 0.9 / peak
    return buf


def write_wav(path: Path, buf: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(buf, -1, 1) * 32767).astype("<i2").tobytes())


# ── Main ───────────────────────────────────────────────────────────────
def main() -> int:
    if not VIDEO.exists():
        print(f"video belum ada: {VIDEO}", file=sys.stderr)
        return 1
    WORK.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print(f"[info] sintesis {len(SEGMENTS)} segmen · suara {VOICE}")
    mp3s = synth_all()

    clips: list[tuple[float, np.ndarray]] = []
    limits: list[float] = []
    report = []
    for i, ((start, _), src) in enumerate(zip(SEGMENTS, mp3s), 1):
        nxt = (SEGMENTS[i][0] if i < len(SEGMENTS)
               else DURATION - 0.5)
        budget = nxt - start - GAP
        audio, tempo = fit_segment(src, budget, i)
        end = start + len(audio) / SR
        if end > nxt - 0.1:
            print(f"[warn] segmen {i} berakhir {end:.1f}s "
                  f"(jendela s/d {nxt - 0.1:.1f}s)")
        clips.append((start, audio))
        limits.append(nxt - 0.1)
        report.append((i, start, len(audio) / SR, end, budget, tempo))

    print("[info] menyusun track 50 detik …")
    buf = build_track(clips, limits)
    wav = WORK / "narasi_50s.wav"
    write_wav(wav, buf)

    print("[info] mux ke MP4 (tanpa render ulang) …")
    subprocess.run(
        [FF, "-y", "-v", "error", "-i", str(VIDEO), "-i", str(wav),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-ac", "2", "-ar", str(SR),
         "-movflags", "+faststart", "-shortest", str(OUT)],
        check=True)

    print("\n=== Laporan narasi ===")
    print(f"{'seg':>3} {'mulai':>6} {'durasi':>7} {'selesai':>8} "
          f"{'jendela':>8} {'tempo':>6}")
    for i, s, d, e, b, tp in report:
        print(f"{i:>3} {s:>6.1f} {d:>7.2f} {e:>8.2f} {b:>8.1f} {tp:>6.2f}")

    r = subprocess.run(
        [FP, "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,duration:format=duration,size",
         "-of", "default=noprint_wrappers=1", str(OUT)],
        capture_output=True, text=True, check=True)
    print(f"\n[ok] {OUT.name} dalam {time.time() - t0:.0f}s\n{r.stdout.strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
