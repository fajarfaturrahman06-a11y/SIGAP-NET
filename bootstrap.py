"""Explicit, one-time database initialization.

Nothing in this module runs automatically at import time. Deployment must call
`flask init-db` exactly once before starting Gunicorn, so worker processes never
race to create tables, patch columns, or seed data.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from werkzeug.security import generate_password_hash

import config
from db import db, User
from security import validate_password_strength
from services.demo_data import ensure_demo_baseline

logger = logging.getLogger('sigapnet.bootstrap')

ADMIN_INSTRUCTIONS = (
    'Tidak ada akun administrator yang dibuat otomatis. '
    'Set ADMIN_USERNAME dan ADMIN_PASSWORD yang kuat, lalu jalankan '
    '`flask ensure-admin`; atau buat akun manual dengan '
    '`flask create-admin <username> <password>`.'
)


def _add_columns_if_missing():
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    statements = []
    if 'users' in tables:
        columns = {c['name'] for c in inspector.get_columns('users')}
        if 'role' not in columns:
            statements.append(
                "ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'admin'")
        if 'active' not in columns:
            statements.append(
                "ALTER TABLE users ADD COLUMN active BOOLEAN NOT NULL DEFAULT 1")
        if 'session_version' not in columns:
            statements.append(
                "ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0")
    if 'response_actions' in tables:
        columns = {c['name'] for c in inspector.get_columns('response_actions')}
        if 'baseline_id' not in columns:
            statements.append(
                "ALTER TABLE response_actions ADD COLUMN baseline_id INTEGER NULL")
        if 'baseline_sha256' not in columns:
            statements.append(
                "ALTER TABLE response_actions ADD COLUMN baseline_sha256 VARCHAR(64) NULL")
    for statement in statements:
        try:
            db.session.execute(text(statement))
            db.session.commit()
            logger.info('Schema patched: %s', statement)
        except (OperationalError, IntegrityError) as exc:
            db.session.rollback()
            logger.warning('Schema patch skipped (%s)', exc)


def _ensure_baseline_version_index():
    inspector = inspect(db.engine)
    if 'baselines' not in inspector.get_table_names():
        return
    indexes = {idx['name'] for idx in inspector.get_indexes('baselines')}
    if 'uq_baselines_device_version' in indexes:
        return
    try:
        db.session.execute(text(
            'CREATE UNIQUE INDEX uq_baselines_device_version '
            'ON baselines (device_id, version)'))
        db.session.commit()
        logger.info('Schema patched: unique baseline version index')
    except (OperationalError, IntegrityError) as exc:
        db.session.rollback()
        logger.warning('Baseline version index skipped (%s)', exc)


def create_user(username, password, role='admin', email=None, commit=True):
    """Create a user only after enforcing the strong-password policy."""
    username = (username or '').strip()
    if not username:
        raise ValueError('Username wajib diisi.')
    if role not in ('admin', 'operator', 'auditor'):
        raise ValueError('Role tidak valid.')
    errors = validate_password_strength(password, username)
    if errors:
        raise ValueError(' '.join(errors))
    if User.query.filter_by(username=username).first():
        return None
    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        role=role,
        active=True,
        email=email,
    )
    db.session.add(user)
    db.session.flush()
    if commit:
        db.session.commit()
    logger.info('Created %s user: %s', role, username)
    return user


def seed_demo_users(admin_password, operator_password, auditor_password):
    """Create demo accounts only when explicitly requested with strong passwords."""
    created = []
    for username, password, role in (
        (config.ADMIN_USERNAME, admin_password, 'admin'),
        (config.OPERATOR_USERNAME, operator_password, 'operator'),
        (config.AUDITOR_USERNAME, auditor_password, 'auditor'),
    ):
        user = create_user(username, password, role, commit=False)
        if user is not None:
            created.append(user.username)
    db.session.commit()
    return created


def ensure_admin_from_env():
    """Create the admin from env vars if (and only if) a strong password is set."""
    username = (config.ADMIN_USERNAME or '').strip()
    password = config.ADMIN_PASSWORD or ''
    if not username or not password:
        logger.warning(ADMIN_INSTRUCTIONS)
        return False
    existing = User.query.filter_by(username=username).first()
    if existing is not None:
        if existing.role == 'admin' and existing.active:
            return True
        logger.error('Akun %s sudah ada tetapi bukan administrator aktif. %s',
                     username, ADMIN_INSTRUCTIONS)
        return False
    try:
        create_user(username, password, 'admin')
    except ValueError as exc:
        logger.error('Admin tidak dibuat: %s %s', exc, ADMIN_INSTRUCTIONS)
        return False
    return True


def init_database(app, seed_demo=False):
    """Run schema creation/patches once from a CLI or deployment hook."""
    with app.app_context():
        try:
            db.create_all()
            _add_columns_if_missing()
            _ensure_baseline_version_index()
            if seed_demo:
                ensure_demo_baseline(actor='system')
                db.session.commit()
            if User.query.first() is None:
                logger.warning(ADMIN_INSTRUCTIONS)
        except Exception:
            db.session.rollback()
            logger.exception('Database initialization failed')
            raise
