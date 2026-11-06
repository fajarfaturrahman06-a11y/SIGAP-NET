"""
Security utilities: credential encryption, input validation,
path-traversal prevention, CSRF token management.
"""
import os
import re
import ipaddress
import secrets
import hmac
from cryptography.fernet import Fernet
from flask import has_request_context, request, session

import config

_BASE_DIR = os.path.dirname(__file__)
_LEGACY_ENC_KEY_FILE = os.path.join(_BASE_DIR, '.encryption_key')
_DATA_DIR = os.path.join(_BASE_DIR, 'data')
_ENC_KEY_FILE = os.path.join(_DATA_DIR, '.encryption_key')


def _get_encryption_key() -> bytes:
    env_key = os.environ.get('ENCRYPTION_KEY')
    if env_key:
        return env_key.encode('utf-8') if isinstance(env_key, str) else env_key
    for path in (_LEGACY_ENC_KEY_FILE, _ENC_KEY_FILE):
        if os.path.exists(path):
            with open(path, 'rb') as f:
                value = f.read()
            if not value:
                raise RuntimeError(
                    f'File kunci enkripsi {path} kosong; hapus atau isi ulang.')
            return value
    os.makedirs(_DATA_DIR, exist_ok=True)
    key = Fernet.generate_key()
    try:
        fd = os.open(_ENC_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with open(_ENC_KEY_FILE, 'rb') as f:
            value = f.read()
        if not value:
            raise RuntimeError(
                f'File kunci enkripsi {_ENC_KEY_FILE} kosong; hapus atau isi ulang.')
        return value
    try:
        os.write(fd, key)
        os.fsync(fd)
    finally:
        os.close(fd)
    return key

_fernet: Fernet | None = None

def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_get_encryption_key())
    return _fernet

def encrypt_password(password: str) -> bytes:
    if not password:
        return b''
    return _get_fernet().encrypt(password.encode('utf-8'))

def decrypt_password(encrypted: bytes) -> str:
    if not encrypted:
        return ''
    try:
        return _get_fernet().decrypt(encrypted).decode('utf-8')
    except Exception:
        return ''


def router_credentials(router) -> tuple[str, str]:
    """Return (password, ssh_key) for the method selected on the router."""
    password = (decrypt_password(router.password_enc)
                if getattr(router, 'password_enc', None) else '')
    ssh_key = (decrypt_password(router.ssh_key_enc)
               if getattr(router, 'ssh_key_enc', None) else '')
    if (getattr(router, 'auth_method', None) or 'password') == 'key':
        return '', ssh_key
    return password, ''

# ── Input validation ──────────────────────────────────────────────────
_HOSTNAME_RE = re.compile(
    r'^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*'
    r'[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$'
)

def client_ip() -> str:
    """Return the caller IP, trusting X-Forwarded-For only when configured."""
    if not has_request_context():
        return 'unknown'
    if config.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get('X-Forwarded-For', '')
        if forwarded:
            return (forwarded.split(',')[0].strip() or 'unknown')[:64]
    return (request.remote_addr or 'unknown')[:64]


def validate_hostname(value: str) -> bool:
    """Accept IPv4, IPv6, or DNS hostname."""
    if not value or len(value) > 253:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return bool(_HOSTNAME_RE.match(value))

def validate_port(value) -> int | None:
    try:
        p = int(value)
        return p if 1 <= p <= 65535 else None
    except (TypeError, ValueError):
        return None

_SAFE_FILENAME_RE = re.compile(r'[^a-zA-Z0-9._\-]')


def _has_url_controls(value: str) -> bool:
    return ('\\' in value
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in value))


def safe_local_url(value: str, fallback: str = '/') -> str:
    """Return a same-origin absolute path, rejecting open-redirect payloads."""
    from urllib.parse import unquote, urlsplit

    if not isinstance(value, str) or not value:
        return fallback
    value = value.strip()
    if not value.startswith('/') or value.startswith('//'):
        return fallback
    if _has_url_controls(value):
        return fallback
    # Browsers may percent-decode before treating backslashes or `//` as a
    # network path, so validate the decoded form as well.
    decoded = unquote(value)
    if decoded.startswith('//') or _has_url_controls(decoded):
        return fallback
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return fallback
    return value


def sanitize_filename(name: str) -> str:
    """Strip path separators and dangerous characters."""
    name = _SAFE_FILENAME_RE.sub('_', name or '').strip('._')
    return (name or 'unnamed')[:100]

def safe_join_path(base: str, *parts: str) -> str:
    """
    Join paths and guarantee the result stays inside *base*.
    Raises ValueError on path-traversal attempt (LFI prevention).
    """
    base_real = os.path.realpath(base)
    target = os.path.realpath(os.path.join(base_real, *parts))
    if target != base_real and not target.startswith(base_real + os.sep):
        raise ValueError(f'Path traversal blocked: {target}')
    return target

def is_safe_path(base: str, path: str) -> bool:
    base_real = os.path.realpath(base)
    target = os.path.realpath(path)
    return target == base_real or target.startswith(base_real + os.sep)

# ── Password policy ───────────────────────────────────────────────────
_WEAK_PASSWORDS = {
    'password', 'password123', 'admin', 'admin123', 'administrator',
    'operator', 'auditor', 'qwerty', '12345678', '123456789', 'letmein',
    'changeme', 'welcome', 'admin#12345', 'operator#12345', 'auditor#12345',
}


def validate_password_strength(password: str, username: str = '') -> list[str]:
    """Return a list of policy violations; an empty list means acceptable."""
    password = password or ''
    errors = []
    if len(password) > 1024:
        errors.append('Password maksimal 1024 karakter.')
    if len(password) < 12:
        errors.append('Password minimal 12 karakter.')
    if not re.search(r'[A-Z]', password):
        errors.append('Password harus mengandung huruf besar.')
    if not re.search(r'[a-z]', password):
        errors.append('Password harus mengandung huruf kecil.')
    if not re.search(r'[0-9]', password):
        errors.append('Password harus mengandung angka.')
    if not re.search(r'[^A-Za-z0-9]', password):
        errors.append('Password harus mengandung simbol.')
    if password.lower() in _WEAK_PASSWORDS:
        errors.append('Password terlalu umum dan mudah ditebak.')
    if username and username.lower() in password.lower():
        errors.append('Password tidak boleh mengandung username.')
    return errors


# ── CSRF tokens ───────────────────────────────────────────────────────
def generate_csrf_token() -> str:
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

def validate_csrf_token(token: str | None) -> bool:
    stored = session.get('csrf_token')
    if not isinstance(stored, str) or not isinstance(token, str):
        return False
    if not stored or not token:
        return False
    return hmac.compare_digest(stored, token)