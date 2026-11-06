"""Authentication context and role-based access control helpers."""
from functools import wraps

from flask import g, session, redirect, url_for, request, jsonify, abort, flash

from db import db, User, ROLES, ROLE_LABELS


def load_current_user():
    g.user = None
    uid = session.get('user_id')
    if not uid:
        return
    user = db.session.get(User, uid)
    if not user or not user.active:
        session.clear()
        return
    if session.get('session_version', 0) != (user.session_version or 0):
        session.clear()
        return
    g.user = user


def current_user():
    return getattr(g, 'user', None)


def current_username():
    user = current_user()
    return user.username if user else session.get('username', 'anonymous')


def current_role():
    user = current_user()
    return user.role if user else None


def has_role(*roles):
    role = current_role()
    return role in roles


def is_admin():
    return current_role() == 'admin'


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Unauthorized'}), 401
            flash('Silakan login terlebih dahulu.', 'info')
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Unauthorized'}), 401
                return redirect(url_for('login', next=request.path))
            if user.role not in roles:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Forbidden', 'role': user.role}), 403
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def readonly_or_above(view):
    """All authenticated roles may access (explicit for readability)."""
    return roles_required(*ROLES)(view)


def register_auth(app):
    app.before_request(load_current_user)

    @app.context_processor
    def inject_auth():
        user = current_user()
        return {
            'current_user': user,
            'role_labels': ROLE_LABELS,
            'can_manage': bool(user and user.role in ('admin', 'operator')),
            'is_admin': bool(user and user.role == 'admin'),
            'is_auditor': bool(user and user.role == 'auditor'),
        }
