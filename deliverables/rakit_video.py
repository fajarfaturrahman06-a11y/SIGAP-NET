# -*- coding: utf-8 -*-
"""SIGAP-NET — Perakit video YouTube (ffmpeg).

Alur perakitan:
  1. Membaca timeline.json hasil rekaman → membuat subtitle Indonesia (.srt)
  2. Kartu intro/outro → klip MP4 (fade in/out, 1920x1080, 30 fps)
  3. Rekaman demo → MP4 1920x1080 + subtitle di-burn (jelas untuk juri)
  4. Concat → SIGAP-NET_Demo_Youtube.mp4 (H.264 + faststart, siap YouTube)
  5. Verifikasi: ffprobe (durasi, resolusi, codec)

Pemakaian:  python rakit_video.py
Prasyarat:  ffmpeg (dicek otomatis, termasuk instalasi winget)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
YT = HERE / "video-youtube"

# Durasi kartu (detik)
DUR = {"kartu_1_masalah.png": 5.0, "kartu_2_solusi.png": 6.0,
       "kartu_3_validasi.png": 6.0, "kartu_outro.png": 6.0}
ORDER = ["kartu_1_masalah.png", "kartu_2_solusi.png",
         "kartu_3_validasi.png"]
OUTRO = "kartu_outro.png"
PRE_ROLL = 0.0          # mark() sudah dipanggil saat adegan mulai tampil
FINAL = "SIGAP-NET_Demo_Youtube.mp4"
SUBS = "SIGAP-NET_Demo_Youtube.srt"

SUB_STYLE = ("FontName=Segoe UI,FontSize=17,Bold=1,PrimaryColour=&H00FFFFFF,"
             "OutlineColour=&H90000000,BackColour=&H80000000,BorderStyle=1,"
             "Outline=2,Shadow=1,MarginV=30")


def say(tag: str, msg: str) -> None:
    print(f"[{tag}] {msg}", flush=True)


def find_ffmpeg() -> str | None:
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    found = shutil.which("ffmpeg")
    if found:
        return found
    # Cari di lokasi umum instalasi winget
    roots = [Path.home() / "AppData/Local/Microsoft/WinGet/Packages",
             Path(r"C:\ProgramData\chocolatey\bin")]
    for root in roots:
        if root.exists():
            for p in root.rglob(exe):
                return str(p)
    return None


def run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        say("err", " ".join(cmd[:6]) + " …")
        say("err", (p.stderr or "")[-1500:])
        sys.exit(1)


def fmt_ts(sec: float) -> str:
    if sec < 0:
        sec = 0
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(timeline: list[dict], intro_total: float, video_len: float,
              path: Path) -> int:
    """Subtitle: teks adegan dari timeline, digeser setelah intro."""
    entries = []
    for i, ev in enumerate(timeline):
        start = intro_total + max(ev["t"] - PRE_ROLL, 0)
        if i + 1 < len(timeline):
            end = intro_total + max(timeline[i + 1]["t"] - PRE_ROLL, 0)
        else:
            end = intro_total + video_len
        entries.append((start, end, ev["label"]))
    # Sisipkan teks kartu intro
    t = 0.0
    kartu_teks = {
        "kartu_1_masalah.png": "Masalah: satu perubahan konfigurasi bisa "
                               "mengganggu seluruh jaringan.",
        "kartu_2_solusi.png": "SIGAP-NET: baseline SHA-256, deteksi drift, "
                              "risiko, insiden, dan audit append-only.",
        "kartu_3_validasi.png": "Teruji 79 test lulus · RBAC tiga peran · "
                                "audit tak bisa diubah · mode simulasi aman.",
    }
    pre = []
    for name in ORDER:
        d = DUR[name]
        teks = kartu_teks[name]
        pre.append((t, t + d - 0.3, teks))
        t += d
    # Kartu outro ada di AKHIR video (sesudah demo), bukan di awal.
    outro_t = intro_total + video_len
    entries = pre + entries + [
        (outro_t, outro_t + DUR[OUTRO] - 0.3,
         "SIGAP-NET — Kendalikan konfigurasi, lindungi jaringan. "
         "UKM Kartika Cyber POLTEKAD.")]

    lines = []
    for i, (s, e, teks) in enumerate(entries, 1):
        lines += [str(i), f"{fmt_ts(s)} --> {fmt_ts(e)}", teks, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return len(entries)


def main() -> int:
    say("info", "=== PERAKITAN VIDEO YOUTUBE SIGAP-NET ===")
    ff = find_ffmpeg()
    if not ff:
        say("err", "ffmpeg tidak ditemukan. Instal dengan: "
                   "winget install Gyan.FFmpeg")
        return 1
    say("ok", f"ffmpeg: {ff}")
    # ffprobe: sibling dari ffmpeg (jangan replace string — nama folder ikut
    # mengandung 'ffmpeg'), dengan fallback which + pencarian WinGet.
    fp = shutil.which("ffprobe")
    if not fp:
        cand = Path(ff).parent / ("ffprobe.exe" if sys.platform == "win32"
                                  else "ffprobe")
        if cand.exists():
            fp = str(cand)
        else:
            for root in [Path.home() /
                         "AppData/Local/Microsoft/WinGet/Packages"]:
                if root.exists():
                    found = list(root.rglob(
                        "ffprobe.exe" if sys.platform == "win32"
                        else "ffprobe"))
                    if found:
                        fp = str(found[0])
                        break
    if not fp:
        say("err", "ffprobe tidak ditemukan")
        return 1

    raw = YT / "demo_mentah.webm"
    timeline_file = YT / "timeline.json"
    if not raw.exists() or not timeline_file.exists():
        say("err", "jalankan dulu: python buat_video_youtube.py")
        return 1

    for name in ORDER + [OUTRO]:
        if not (YT / name).exists():
            say("err", f"kartu hilang: {name} (jalankan buat_kartu_video.py)")
            return 1

    work = YT / "build"
    work.mkdir(exist_ok=True)

    # ── Durasi video mentah ──────────────────────────────────────────
    p = subprocess.run([fp, "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", str(raw)],
                       capture_output=True, text=True)
    video_len = float(p.stdout.strip() or 0)
    if video_len <= 0:
        say("err", "durasi video mentah tidak terbaca")
        return 1
    say("ok", f"video mentah: {video_len:.1f} detik")

    # ── SRT dari timeline ────────────────────────────────────────────
    timeline = json.loads(timeline_file.read_text(encoding="utf-8"))
    intro_total = sum(DUR[n] for n in ORDER)
    srt = YT / SUBS
    n = build_srt(timeline, intro_total, video_len, srt)
    say("ok", f"subtitle: {SUBS} ({n} entri)")

    # ── Kartu → klip MP4 ─────────────────────────────────────────────
    for i, name in enumerate(ORDER + [OUTRO], 1):
        d = DUR[name]
        out = work / f"kartu_{i}.mp4"
        run([ff, "-y", "-loop", "1", "-t", str(d), "-i", str(YT / name),
             "-vf",
             f"scale=1920:1080:force_original_aspect_ratio=decrease,"
             f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
             f"fade=t=in:st=0:d=0.5,fade=t=out:st={d - 0.5}:d=0.5,"
             "format=yuv420p",
             "-r", "30", "-c:v", "libx264", "-crf", "19", "-preset", "medium",
             str(out)])
        say("ok", f"klip kartu {i}/4 ({d:.0f}s)")

    # ── Demo → MP4 (tanpa subtitle dulu — subtitle dibakar di akhir ──
    #    pada video utuh, karena SRT memakai waktu global) ────────────
    demo_mp4 = work / "demo.mp4"
    run([ff, "-y", "-i", str(raw),
         "-vf", "scale=1920:1080:flags=lanczos,format=yuv420p",
         "-r", "30", "-c:v", "libx264", "-crf", "19", "-preset", "medium",
         "-an", str(demo_mp4)])
    say("ok", "klip demo siap")

    # ── Concat: intro (3 kartu) → demo → OUTRO ───────────────────────
    files = ([work / f"kartu_{i}.mp4" for i in range(1, 4)]
             + [demo_mp4, work / "kartu_4.mp4"])
    lst = work / "concat.txt"
    lst.write_text("\n".join(f"file '{f.as_posix()}'" for f in files),
                   encoding="utf-8")
    merged = work / "merged.mp4"
    run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", str(merged)])
    say("ok", "concat: intro + demo + outro")

    # ── Burn subtitle pada video utuh (waktu global SRT) ─────────────
    srt_arg = str(srt).replace("\\", "/").replace(":", "\\:")
    final = YT / FINAL
    run([ff, "-y", "-i", str(merged),
         "-vf",
         f"subtitles='{srt_arg}':force_style='{SUB_STYLE}',format=yuv420p",
         "-r", "30", "-c:v", "libx264", "-crf", "19", "-preset", "medium",
         "-an", "-movflags", "+faststart", str(final)])
    say("ok", f"hasil akhir: {FINAL} (+subtitle ter-burn)")

    # ── Verifikasi ───────────────────────────────────────────────────
    p = subprocess.run([fp, "-v", "error", "-show_entries",
                        "format=duration,size:stream=codec_name,width,height,"
                        "r_frame_rate", "-of", "json", str(final)],
                       capture_output=True, text=True)
    info = json.loads(p.stdout or "{}")
    fmt = info.get("format", {})
    st = (info.get("streams") or [{}])[0]
    say("info", f"codec={st.get('codec_name')} "
                f"resolusi={st.get('width')}x{st.get('height')} "
                f"fps={st.get('r_frame_rate')} "
                f"durasi={float(fmt.get('duration', 0)):.1f}s "
                f"ukuran={int(fmt.get('size', 0)) / 1_048_576:.1f} MB")
    say("ok", "SELESAI — video siap diunggah ke YouTube.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
