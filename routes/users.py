import re

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, abort, g, session)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db import db, User, ROLES, ROLE_LABELS
from authz import login_required, roles_required
from csrf import csrf_protect
from services import audit
from security import validate_password_strength
from werkzeug.security import generate_password_hash

users_bp = Blueprint('users', __name__)
USERNAME_RE = re.compile(r'^[A-Za-z0-9_.-]{3,80}$')


def _lock_active_admins():
    return (User.query.filter_by(role='admin', active=True)
            .order_by(User.id).with_for_update()
            .execution_options(populate_existing=True).all())


def _lock_user(user_id):
    return db.session.execute(
        select(User).where(User.id == user_id).with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _has_other_active_admin(admins, user_id):
    return any(admin.id != user_id for admin in admins)


@users_bp.route('/users')
@login_required
@roles_required('admin')
def index():
    users = User.query.order_by(User.username).all()
    return render_template('users.html', users=users, roles=ROLES,
                           role_labels=ROLE_LABELS)


@users_bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
@csrf_protect
def new():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        role = (request.form.get('role') or 'operator').strip()
        email = (request.form.get('email') or '').strip()[:120]
        errors = []
        if not USERNAME_RE.match(username):
            errors.append('Username 3–80 karakter (huruf, angka, . _ -).')
        if User.query.filter_by(username=username).first():
            errors.append('Username sudah digunakan.')
        if password:
            errors.extend(validate_password_strength(password, username))
        else:
            errors.append('Password wajib diisi.')
        if role not in ROLES:
            errors.append('Role tidak valid.')
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('user_form.html', user=None, roles=ROLES,
                                   role_labels=ROLE_LABELS, is_edit=False)
        user = User(username=username, password_hash=generate_password_hash(password),
                    role=role, email=email, active=True)
        db.session.add(user)
        try:
            db.session.flush()
            audit.record('USER_CREATED', 'User', user.id, None,
                         detail={'username': username, 'role': role})
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('Username sudah digunakan. Muat ulang dan coba lagi.', 'error')
            return render_template('user_form.html', user=None, roles=ROLES,
                                   role_labels=ROLE_LABELS, is_edit=False)
        flash(f'Pengguna "{username}" dibuat.', 'success')
        return redirect(url_for('users.index'))
    return render_template('user_form.html', user=None, roles=ROLES,
                           role_labels=ROLE_LABELS, is_edit=False)


@users_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
@csrf_protect
def edit(user_id):
    admins = _lock_active_admins() if request.method == 'POST' else None
    user = (_lock_user(user_id) if request.method == 'POST'
            else db.session.get(User, user_id)) or abort(404)
    if request.method == 'POST':
        role = (request.form.get('role') or user.role).strip()
        email = (request.form.get('email') or '').strip()[:120]
        active = bool(request.form.get('active'))
        password = request.form.get('password') or ''
        errors = []
        if role not in ROLES:
            errors.append('Role tidak valid.')
        if user.id == getattr(g, 'user', None).id:
            if role != 'admin':
                errors.append('Anda tidak dapat menurunkan role akun sendiri.')
            if not active:
                errors.append('Anda tidak dapat menonaktifkan akun sendiri.')
        if user.role == 'admin' and (role != 'admin' or not active):
            if not _has_other_active_admin(admins, user.id):
                errors.append('Harus ada minimal satu Administrator aktif.')
        if password:
            errors.extend(validate_password_strength(password, user.username))
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('user_form.html', user=user, roles=ROLES,
                                   role_labels=ROLE_LABELS, is_edit=True)
        before = {'role': user.role, 'active': user.active}
        user.role = role
        user.email = email
        user.active = active
        if password:
            user.password_hash = generate_password_hash(password)
            user.session_version = (user.session_version or 0) + 1
            if user.id == getattr(g, 'user', None).id:
                session['session_version'] = user.session_version
        if before['active'] and not active:
            user.session_version = (user.session_version or 0) + 1
        audit.record('USER_UPDATED', 'User', user.id, None,
                     detail={'username': user.username, 'before': before,
                             'after': {'role': role, 'active': active},
                             'password_reset': bool(password)})
        db.session.commit()
        flash('Data pengguna diperbarui.', 'success')
        return redirect(url_for('users.index'))
    return render_template('user_form.html', user=user, roles=ROLES,
                           role_labels=ROLE_LABELS, is_edit=True)


@users_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@roles_required('admin')
@csrf_protect
def delete(user_id):
    admins = _lock_active_admins()
    user = _lock_user(user_id) or abort(404)
    current = getattr(g, 'user', None)
    if current and user.id == current.id:
        flash('Anda tidak dapat menghapus akun sendiri.', 'error')
        return redirect(url_for('users.index'))
    if user.role == 'admin' and not _has_other_active_admin(admins, user.id):
        flash('Harus ada minimal satu Administrator aktif.', 'error')
        return redirect(url_for('users.index'))
    username = user.username
    audit.record('USER_DELETED', 'User', user.id, None,
                 detail={'username': username, 'role': user.role})
    db.session.delete(user)
    db.session.commit()
    flash(f'Pengguna "{username}" dihapus.', 'success')
    return redirect(url_for('users.index'))
