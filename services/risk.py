"""Transparent, rule-based risk assessment engine.

Each rule is a small, readable predicate over a single configuration change.
The engine never claims an attack happened: it reports a detected change and a
risk level with an explanation, potential impact, and verification guidance.
"""
from dataclasses import dataclass

from db import RISK_LEVELS, RISK_ORDER


@dataclass(frozen=True)
class RiskRule:
    id: str
    severity: str
    title: str
    reason: str
    impact: str
    recommendation: str
    match: object


def _text(change) -> str:
    return f'{change.section} {change.param}'.lower()


def _new(change) -> str:
    return (change.new_value or '').lower()


def _old(change) -> str:
    return (change.old_value or '').lower()


def _is_firewall(change) -> bool:
    return 'firewall' in change.section


def _service_enabled(change, service: str) -> bool:
    return (change.section.startswith('ip service')
            and change.param.lower().startswith(f'{service}.')
            and change.param.lower().endswith(('disabled', 'enabled'))
            and _new(change) == 'enabled')


RULES = [
    RiskRule(
        'CRED_USER_GROUP', 'CRITICAL',
        'Perubahan pengguna / hak akses',
        'Pengguna, grup, atau kredensial perangkat berubah. Ini dapat menjadi '
        'indikasi penambahan akses tidak sah maupun perubahan administratif.',
        'Akses tidak sah, eskalasi hak istimewa, atau hilangnya akuntabilitas.',
        'Verifikasi apakah perubahan dilakukan oleh administrator berwenang, '
        'periksa daftar pengguna/grup aktif, dan tinjau log login perangkat.',
        lambda c: any(k in _text(c) for k in ('user', 'group', 'password', 'secret'))
        and c.change_type in ('ADDED', 'REMOVED', 'MODIFIED'),
    ),
    RiskRule(
        'SERVICE_TELNET', 'CRITICAL',
        'Layanan Telnet diaktifkan',
        'Telnet mengirim kredensial dalam teks polos dan sangat berisiko.',
        'Penyadapan kredensial administrator dan pengambilalihan perangkat.',
        'Nonaktifkan Telnet, gunakan SSH, dan audit siapa yang mengaktifkannya.',
        lambda c: _service_enabled(c, 'telnet'),
    ),
    RiskRule(
        'FIREWALL_DISABLED', 'HIGH',
        'Firewall dinonaktifkan',
        'Konfigurasi firewall berubah dari aktif menjadi nonaktif. Ini melemahkan '
        'kontrol akses jaringan secara langsung.',
        'Lalu lintas berbahaya dapat masuk, aturan filtering tidak lagi berlaku.',
        'Pastikan perubahan disetujui. Jika tidak, segera pulihkan baseline dan '
        'periksa koneksi masuk pada perangkat.',
        lambda c: ('firewall' in _text(c) and 'enable' in c.param.lower()
                   and _new(c) == 'disabled'),
    ),
    RiskRule(
        'SERVICE_SSH_ENABLED', 'HIGH',
        'Layanan SSH diaktifkan',
        'SSH yang sebelumnya nonaktif menjadi aktif. Akses manajemen jarak jauh '
        'terbuka dan dapat disalahgunakan.',
        'Percobaan brute force, akses administratif tidak sah, pergerakan lateral.',
        'Konfirmasi persetujuan perubahan, batasi sumber IP yang boleh SSH, '
        'terapkan kunci publik dan nonaktifkan login password bila tidak perlu.',
        lambda c: _service_enabled(c, 'ssh'),
    ),
    RiskRule(
        'SERVICE_INSECURE', 'HIGH',
        'Layanan manajemen tidak aman diaktifkan',
        'Layanan FTP atau HTTP (webfig) diaktifkan dan umumnya tidak terenkripsi.',
        'Kebocoran kredensial dan konfigurasi melalui jaringan.',
        'Nonaktifkan layanan tersebut atau ganti ke HTTPS/SSH dengan akses terbatas.',
        lambda c: (_service_enabled(c, 'ftp') or _service_enabled(c, 'www')
                   or _service_enabled(c, 'api')),
    ),
    RiskRule(
        'FIREWALL_RULE_REMOVED', 'HIGH',
        'Aturan firewall dihapus',
        'Satu atau lebih aturan firewall hilang dibandingkan baseline.',
        'Kontrol filtering berkurang dan port/alamat tertentu dapat terekspos.',
        'Tinjau aturan yang hilang dan pulihkan jika tidak ada tiket perubahan resmi.',
        lambda c: _is_firewall(c) and c.change_type == 'REMOVED',
    ),
    RiskRule(
        'FIREWALL_RULE_CHANGED', 'MEDIUM',
        'Aturan firewall berubah',
        'Parameter aturan firewall berubah. Perlu verifikasi apakah perubahan sah.',
        'Kebijakan filtering dapat menjadi lebih longgar dari yang direncanakan.',
        'Bandingkan dengan change request dan uji aturan pada perangkat lab.',
        lambda c: _is_firewall(c) and c.change_type in ('ADDED', 'MODIFIED'),
    ),
    RiskRule(
        'SSH_CONFIG_CHANGED', 'MEDIUM',
        'Konfigurasi SSH berubah',
        'Port atau parameter SSH berubah dan memengaruhi akses manajemen.',
        'Akses manajemen hilang atau terbuka pada port yang tidak diawasi.',
        'Verifikasi port yang diizinkan, aturan firewall, dan dokumentasi akses.',
        lambda c: 'ssh' in _text(c),
    ),
    RiskRule(
        'DNS_CHANGED', 'MEDIUM',
        'Konfigurasi DNS berubah',
        'Server DNS atau kebijakan DNS berubah. Perubahan DNS dapat mengalihkan '
        'resolusi nama ke server yang tidak tepercaya.',
        'DNS spoofing/poisoning, pengalihan lalu lintas, dan kegagalan resolusi.',
        'Pastikan server DNS baru resmi, periksa allow-remote-requests, dan uji '
        'resolusi dari perangkat.',
        lambda c: 'dns' in _text(c),
    ),
    RiskRule(
        'ROUTING_CHANGED', 'MEDIUM',
        'Konfigurasi routing berubah',
        'Gateway, rute statis, atau kebijakan routing berubah.',
        'Lalu lintas dapat dialihkan, terjadi loop, atau konektivitas terputus.',
        'Verifikasi gateway/rute baru terhadap topologi dan uji konektivitas.',
        lambda c: any(k in _text(c) for k in ('route', 'gateway', 'routing')),
    ),
    RiskRule(
        'NAT_CHANGED', 'MEDIUM',
        'Konfigurasi NAT berubah',
        'Aturan NAT ditambah, dihapus, atau diubah.',
        'Eksposur layanan internal atau hilangnya akses keluar.',
        'Pastikan aturan NAT sesuai desain dan tidak membuka layanan internal.',
        lambda c: 'nat' in _text(c),
    ),
    RiskRule(
        'LOGGING_CHANGED', 'MEDIUM',
        'Logging / NTP berubah',
        'Logging jarak jauh atau sinkronisasi waktu berubah.',
        'Berkurangnya bukti audit atau timestamp insiden menjadi tidak akurat.',
        'Pastikan logging tetap aktif dan waktu perangkat tersinkron.',
        lambda c: any(k in _text(c) for k in ('logging', 'ntp', 'log')),
    ),
    RiskRule(
        'ACCESS_SERVICE_CHANGED', 'MEDIUM',
        'Layanan manajemen berubah',
        'Konfigurasi layanan manajemen (port/alamat) berubah.',
        'Akses dapat terbuka lebih luas atau justru hilang.',
        'Verifikasi daftar layanan aktif dan batasi akses berdasarkan alamat sumber.',
        lambda c: c.section.startswith('ip service'),
    ),
    RiskRule(
        'DESCRIPTION_CHANGED', 'LOW',
        'Deskripsi / identitas perangkat berubah',
        'Nama, catatan, atau deskripsi perangkat berubah. Perubahan ini biasanya '
        'bersifat administratif.',
        'Risiko keamanan rendah, tetapi dapat menandakan perubahan tidak terdokumentasi.',
        'Konfirmasi dengan pemilik perangkat dan perbarui dokumentasi.',
        lambda c: any(k in _text(c) for k in ('description', 'identity', 'note',
                                              'comment', 'contact', 'location')),
    ),
    RiskRule(
        'DEFAULT', 'LOW',
        'Perubahan konfigurasi umum',
        'Parameter berubah tetapi tidak cocok dengan aturan risiko khusus.',
        'Dampak belum dapat dipastikan tanpa konteks tambahan.',
        'Tinjau perubahan terhadap dokumentasi dan change request.',
        lambda c: True,
    ),
]

RULES_BY_ID = {r.id: r for r in RULES}
RULE_CATALOG = [
    {'id': r.id, 'severity': r.severity, 'title': r.title, 'reason': r.reason,
     'impact': r.impact, 'recommendation': r.recommendation}
    for r in RULES
]


def assess_change(change) -> dict:
    for rule in RULES:
        if rule.match(change):
            return {
                'rule_id': rule.id,
                'risk_level': rule.severity,
                'title': rule.title,
                'reason': rule.reason,
                'impact': rule.impact,
                'recommendation': rule.recommendation,
            }
    # Unreachable because DEFAULT matches everything.
    return {
        'rule_id': 'DEFAULT', 'risk_level': 'LOW',
        'title': 'Perubahan konfigurasi umum',
        'reason': 'Tidak ada aturan khusus yang cocok.',
        'impact': 'Belum dapat dipastikan.', 'recommendation': 'Tinjau manual.',
    }


def assess_changes(changes) -> tuple[list[dict], str, str | None]:
    """Return (assessments, highest_risk, combined_note)."""
    assessments = [assess_change(c) for c in changes]
    highest = 'LOW'
    for item in assessments:
        if RISK_ORDER[item['risk_level']] > RISK_ORDER[highest]:
            highest = item['risk_level']

    ids = {item['rule_id'] for item in assessments}
    combined_note = None
    if 'FIREWALL_DISABLED' in ids and 'SERVICE_SSH_ENABLED' in ids:
        highest = 'CRITICAL'
        combined_note = (
            'Kombinasi firewall dinonaktifkan dan SSH diaktifkan meningkatkan '
            'risiko menjadi CRITICAL karena kontrol akses melemah bersamaan '
            'dengan terbukanya akses manajemen.'
        )
    elif {'FIREWALL_DISABLED', 'SERVICE_INSECURE'} <= ids:
        highest = 'CRITICAL'
        combined_note = (
            'Firewall dinonaktifkan bersamaan dengan layanan manajemen tidak aman.'
        )
    return assessments, highest, combined_note


def is_risk_level(value: str) -> bool:
    return value in RISK_LEVELS
