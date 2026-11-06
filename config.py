import os
import secrets
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')
LOG_DIR = os.path.join(BASE_DIR, 'logs')
DATA_DIR = os.path.join(BASE_DIR, 'data')
UPLOAD_DIR = os.path.join(DATA_DIR, 'uploads')
os.makedirs(DATA_DIR, exist_ok=True)

_DEFAULT_SQLITE = 'sqlite:///' + os.path.join(DATA_DIR, 'sigapnet.db').replace('\\', '/')
SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or _DEFAULT_SQLITE
SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_pre_ping': True,
    'pool_recycle': 3600,
}

_SECRET_KEY_FILE = os.path.join(BASE_DIR, '.secret_key')


def _read_secret_file(path):
    with open(path, 'rb') as f:
        value = f.read()
    if not value:
        raise RuntimeError(f'File kunci {path} kosong; hapus atau isi ulang.')
    return value


def _get_secret_key() -> bytes:
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        return env_key.encode('utf-8') if isinstance(env_key, str) else env_key
    if os.path.exists(_SECRET_KEY_FILE):
        return _read_secret_file(_SECRET_KEY_FILE)
    key = secrets.token_bytes(32)
    try:
        fd = os.open(_SECRET_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _read_secret_file(_SECRET_KEY_FILE)
    try:
        os.write(fd, key)
        os.fsync(fd)
    finally:
        os.close(fd)
    return key


SECRET_KEY = _get_secret_key()

SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
PERMANENT_SESSION_LIFETIME = 3600 * 8
# Only trust X-Forwarded-For when the app is actually behind a trusted proxy.
TRUST_PROXY_HEADERS = os.environ.get('TRUST_PROXY_HEADERS', 'false').lower() == 'true'

LOGIN_MAX_ATTEMPTS = int(os.environ.get('LOGIN_MAX_ATTEMPTS', '5'))
LOGIN_WINDOW_SECONDS = int(os.environ.get('LOGIN_WINDOW_SECONDS', '300'))
MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB upload limit
SCHEDULER_ENABLED = os.environ.get('SCHEDULER_ENABLED', 'true').lower() == 'true'

# ── SIGAP-NET ─────────────────────────────────────────────────────
APP_NAME = 'SIGAP-NET'
APP_LONG_NAME = 'Sistem Integritas Konfigurasi dan Respons Gangguan Jaringan'
APP_VERSION = '1.0.0'

# Demo accounts are never created automatically. Use `flask seed-demo-users`
# with explicit strong passwords, or `flask create-admin`.
SEED_DEMO_USERS = os.environ.get('SIGAP_SEED_DEMO_USERS', 'false').lower() == 'true'
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')
OPERATOR_USERNAME = os.environ.get('SIGAP_OPERATOR_USERNAME', 'operator')
OPERATOR_PASSWORD = os.environ.get('SIGAP_OPERATOR_PASSWORD', '')
AUDITOR_USERNAME = os.environ.get('SIGAP_AUDITOR_USERNAME', 'auditor')
AUDITOR_PASSWORD = os.environ.get('SIGAP_AUDITOR_PASSWORD', '')
SHOW_DEMO_ACCOUNTS = os.environ.get('SIGAP_SHOW_DEMO_ACCOUNTS', 'false').lower() == 'true'

# Real-device restore is intentionally disabled for the prototype.
ALLOW_REAL_RESTORE = os.environ.get('SIGAP_ALLOW_REAL_RESTORE', 'false').lower() == 'true'

# SSH host-key verification: strict by default. Point this at a known_hosts
# file, or use the system-wide file (`~/.ssh/known_hosts`).
SSH_KNOWN_HOSTS_FILE = os.environ.get('SSH_KNOWN_HOSTS_FILE', '')
