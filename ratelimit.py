"""Database-backed login throttling.

The state lives in the shared database, so limits apply across all Gunicorn
workers. If the backend cannot be queried, authentication fails closed instead
of silently disabling the limiter.
"""
import logging
from datetime import timedelta

from flask import current_app

from db import db, LoginAttempt, utc_now

logger = logging.getLogger('sigapnet.ratelimit')


def _config(name, default):
    try:
        return current_app.config.get(name, default)
    except RuntimeError:
        return default


def _cutoff(now=None):
    now = now or utc_now()
    return now - timedelta(seconds=_config('LOGIN_WINDOW_SECONDS', 300))


def check_login_allowed(ip_address, username=''):
    """Return (allowed, reason) where reason is 'limit' or 'backend'."""
    try:
        cutoff = _cutoff()
        limit = int(_config('LOGIN_MAX_ATTEMPTS', 5))
        ip_count = (LoginAttempt.query
                    .filter(LoginAttempt.ip_address == ip_address,
                            LoginAttempt.success.is_(False),
                            LoginAttempt.attempted_at >= cutoff)
                    .count())
        if ip_count >= limit:
            return False, 'limit'
        username = (username or '').strip()
        if username:
            user_count = (LoginAttempt.query
                          .filter(LoginAttempt.username == username,
                                  LoginAttempt.success.is_(False),
                                  LoginAttempt.attempted_at >= cutoff)
                          .count())
            if user_count >= limit:
                return False, 'limit'
        return True, None
    except Exception:
        db.session.rollback()
        logger.exception('Login rate-limit backend unavailable; failing closed')
        return False, 'backend'


def record_failure(ip_address, username=''):
    try:
        now = utc_now()
        db.session.add(LoginAttempt(
            ip_address=(ip_address or 'unknown')[:64],
            username=(username or '')[:100],
            success=False,
            attempted_at=now,
        ))
        # Best-effort pruning keeps the table small without disabling the limiter.
        old = now - timedelta(seconds=_config('LOGIN_WINDOW_SECONDS', 300) * 4)
        (db.session.query(LoginAttempt)
         .filter(LoginAttempt.attempted_at < old)
         .delete(synchronize_session=False))
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Could not persist failed login attempt')


def clear_failures(ip_address, username=''):
    try:
        # Successful authentication only clears the exact (IP, username)
        # bucket it proved. A global username reset would let someone who
        # knows one valid password wipe the throttle for every other IP.
        query = LoginAttempt.query.filter(
            LoginAttempt.success.is_(False),
            LoginAttempt.ip_address == ip_address,
        )
        if username:
            query = query.filter(LoginAttempt.username == username)
        query.delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Could not clear login attempt history')
