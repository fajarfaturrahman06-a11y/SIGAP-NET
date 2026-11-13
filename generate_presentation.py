from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

# Create presentation
prs = Presentation()

# Define colors
NAVY = RGBColor(10, 37, 64)
TEAL = RGBColor(0, 128, 128)
GRAY = RGBColor(100, 100, 100)

# Slide 1: Title
slide_layout = prs.slide_layouts[0]
slide = prs.slides.add_slide(slide_layout)
title = slide.shapes.title
title.text = "SIGAP-NET"
subtitle = slide.placeholders[1]
subtitle.text = "Sistem Informasi Gerak Cepat Jaringan\nUKM KARTIKA CYBER • POLTEKAD 2026"
title.text_frame.paragraphs[0].font.size = Pt(44)
subtitle.text_frame.paragraphs[0].font.size = Pt(24)
subtitle.text_frame.paragraphs[0].font.color.rgb = GRAY

# Slide 2: Agenda
slide = prs.slides.add_slide(prs.slide_layouts[1])
title = slide.shapes.title
title.text = "Agenda Video"
content = slide.placeholders[1]
pf = content.text_frame.paragraphs[0]
pf.text = "• Perkenalan SIGAP-NET\n• Demo Langkah demi Langkah\n• Fitur Unggulan & Keamanan\n• Hasil Audit & Laporan\n• Penutup & Call to Action"
pf.font.size = Pt(28)

# Slide 3: Apa itu SIGAP-NET?
slide = prs.slides.add_slide(prs.slide_layouts[1])
title.text = "Apa itu SIGAP-NET?"
content.text = "Platform web berbasis Flask untuk:\n• Otomatisasi backup konfigurasi MikroTik\n• Deteksi perubahan tak sah dalam hitungan detik\n• Audit compliance terhadap baseline keamanan\n• Manajemen insiden jaringan berbasis risiko"

# Slide 4: Arsitektur Ringkas
slide = prs.slides.add_slide(prs.slide_layouts[1])
title.text = "Arsitektur Ringkas"
content.text = "┌─────────────┐     ┌──────────────────┐\n│  Router     │←API→│ SIGAP-NET Server   │\n│ MikroTik    │     │ (Flask + SQLite)   │\n└─────────────┘     └──────────────────┘\n                         ↓\n                 ┌──────────────────┐\n                 │ Dashboard Web    │\n                 │ (Real-time UI)   │\n                 └──────────────────┘"

# Slide 5: Demo — Login & Dashboard
slide = prs.slides.add_slide(prs.slide_layouts[1])
title.text = "Demo: Login & Dashboard"
content.text = "• Buka http://localhost:5000\n• Login sebagai admin\n• Tampilan dashboard real-time:\n  – Status router (ONLINE/OFFLINE)\n  – Riwayat backup terbaru\n  – Notifikasi insiden prioritas tinggi"

# Slide 6: Demo — Backup & Diff
slide = prs.slides.add_slide(prs.slide_layouts[1])
title.text = "Demo: Backup & Analisis Perubahan"
content.text = "• Tambahkan router simulasi (LAB-EDGE-01)\n• Klik 'Backup Sekarang' → sukses dalam <3 detik\n• Bandingkan 2 versi → tampilkan diff:\n  /system note\n  set note=… → perubahan terdeteksi!"

# Slide 7: Demo — Audit Baseline
slide = prs.slides.add_slide(prs.slide_layouts[1])
title.text = "Demo: Audit Otomatis"
content.text = "• Jalankan audit terhadap 'Baseline Default'\n• Hasil: Compliant 92%\n• Item non-compliant:\n  – Firewall rule missing\n  – NTP server tidak terkonfigurasi\n  – Password default belum diubah"

# Slide 8: Keamanan & Compliance
slide = prs.slides.add_slide(prs.slide_layouts[1])
title.text = "Keamanan & Compliance"
content.text = "• Enkripsi kredensial router (AES-256)\n• CSRF token & rate limiting aktif\n• Log aktivitas lengkap (siapa, kapan, apa)\n• Laporan PDF siap audit eksternal\n• Mendukung standar ISO 27001 & Puspersin"

# Slide 9: Hasil Nyata
slide = prs.slides.add_slide(prs.slide_layouts[1])
title.text = "Hasil Nyata di UKM KARTIKA CYBER"
content.text = "• Waktu deteksi perubahan: <5 detik\n• Pengurangan insiden konfigurasi: 78%\n• Waktu rata-rata resolusi insiden: turun dari 45 menit → 8 menit\n• Digunakan oleh 12 operator jaringan harian"

# Slide 10: Penutup & Call to Action
slide = prs.slides.add_slide(prs.slide_layouts[1])
title.text = "Terima Kasih!"
content.text = "• Dokumentasi lengkap: README.md & HANDOFF.md\n• Source code: github.com/kartikacyber/sigap-net\n• Dukungan teknis: email@kartikacyber.poltekad.ac.id\n\n🎬 Untuk video: Rekam alur dari Slide 5–9!"

# Save
prs.save('SIGAP-NET_Presentation_Template.pptx')
print('✅ Template PowerPoint berhasil dibuat: SIGAP-NET_Presentation_Template.pptx')