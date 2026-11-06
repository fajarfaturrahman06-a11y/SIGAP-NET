import os
import json
import queue
import threading
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, time as dtime, timedelta, timezone

import click
from flask import (Flask, request, session, redirect, url_for,
                   render_template, jsonify, send_file, abort,
                   Response, stream_with_context, flash)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate

import config
from security import (encrypt_password, router_credentials,
                      validate_hostname, validate_port,
                      sanitize_filename, safe_join_path, is_safe_path,
                       generate_csrf_token, validate_csrf_token,
                       validate_password_strength, safe_local_url, client_ip)
from mikrotik import MikrotikClient, BackupType
from db import (db, User, Router, Backup, Schedule, ActivityLog, log_activity,
                Device, ConfigCheck, ConfigChange, Incident,
                AuditLog, INCIDENT_OPEN_STATUSES, RISK_LEVELS, utc_now)
from authz import (register_auth, login_required, roles_required,
                   current_user)
from csrf import csrf_protect
from bootstrap import (init_database, ensure_admin_from_env, seed_demo_users,
                       create_user, ADMIN_INSTRUCTIONS)
from ratelimit import check_login_allowed, record_failure, clear_failures
from routes import register_blueprints
from services import audit
from services.demo_data import ensure_demo_baseline
import scheduler as sched

_DUMMY_PASSWORD_HASH = generate_password_hash('invalid-login-placeholder')

# ── Logging ──────────────────────────────────────────────────────
os.makedirs(config.LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            os.path.join(config.LOG_DIR, 'app.log'),
            maxBytes=10_485_760, backupCount=5
        ),
    ],
)
logger = logging.getLogger('mikrotik_backup')

# ── Flask app ────────────────────────────────────────────────────
app = Flask(__name__)
app.config.from_object(config)
os.makedirs(config.BACKUP_DIR, exist_ok=True)

# Initialize Database & Migrations
db.init_app(app)
migrate = Migrate(app, db)

# SIGAP-NET auth and routes. Database initialization is an explicit CLI step.
register_auth(app)
register_blueprints(app)

# ── CLI Commands ─────────────────────────────────────────────────
@app.cli.command("init-db")
@click.option("--seed-demo/--no-seed-demo", default=False,
              help="Also create the lab device and baseline.")
def init_db(seed_demo):
    """Create tables and patch legacy schemas exactly once (deployment step)."""
    init_database(app, seed_demo=seed_demo)
    print('Database initialized. Create an administrator with `flask create-admin` '
          'or `flask ensure-admin`.')


@app.cli.command("create-admin")
@click.argument("username")
@click.argument("password")
@click.option("--role", default="admin", type=click.Choice(["admin", "operator", "auditor"]))
@click.option("--email", default=None)
def create_admin(username, password, role, email):
    """Creates a user after enforcing the strong-password policy."""
    with app.app_context():
        if User.query.filter_by(username=username).first():
            print("User already exists.")
            return
        try:
            user = create_user(username, password, role, email=email, commit=False)
        except ValueError as exc:
            print(f"User not created: {exc}")
            return
        audit.record('USER_CREATED', 'User', user.id, None,
                     detail={'username': username, 'role': role, 'source': 'cli'})
        db.session.commit()
        print(f"User '{username}' ({role}) created successfully.")


@app.cli.command("ensure-admin")
def ensure_admin():
    """Create ADMIN_USERNAME from env if ADMIN_PASSWORD is strong; otherwise print instructions."""
    with app.app_context():
        if ensure_admin_from_env():
            print(f"Administrator '{config.ADMIN_USERNAME}' is ready.")
        else:
            print(ADMIN_INSTRUCTIONS)


@app.cli.command("seed-demo-users")
@click.option("--admin-password", required=True, prompt=True, hide_input=True)
@click.option("--operator-password", required=True, prompt=True, hide_input=True)
@click.option("--auditor-password", required=True, prompt=True, hide_input=True)
def seed_demo_users_cmd(admin_password, operator_password, auditor_password):
    """Create demo role accounts with explicitly supplied strong passwords."""
    with app.app_context():
        try:
            created = seed_demo_users(admin_password, operator_password,
                                      auditor_password)
        except ValueError as exc:
            print(f"Demo users not created: {exc}")
            return
        print('Created users: ' + (', '.join(created) if created else 'none'))


@app.cli.command("seed-demo")
def seed_demo():
    """Seeds the demo device and a baseline (idempotent)."""
    with app.app_context():
        device, baseline = ensure_demo_baseline(actor='system')
        print(f"Demo device: {device.name} | baseline: {baseline.version_label} "
              f"({baseline.sha256[:12]}…)")

# ── SSE infrastructure ───────────────────────────────────────────
_status_q: queue.Queue = queue.Queue(maxsize=2000)
_subscribers: list[queue.Queue] = []
_subscribers_lock = threading.Lock()

def emit_status(router_id, status, message=''):
    try:
        _status_q.put_nowait(
            {'router_id': router_id, 'status': status,
             'message': message, 'timestamp': utc_now().isoformat()}
        )
    except queue.Full:
        pass

def _broadcaster():
    while True:
        try:
            msg = _status_q.get(timeout=1)
        except queue.Empty:
            continue
        with _subscribers_lock:
            subscribers = list(_subscribers)
        dead = []
        for q in subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        if dead:
            with _subscribers_lock:
                for q in dead:
                    if q in _subscribers:
                        _subscribers.remove(q)

threading.Thread(target=_broadcaster, daemon=True).start()

# ── Context processors ───────────────────────────────────────────
@app.context_processor
def _ctx():
    def page_url(page):
        args = request.args.to_dict()
        args['page'] = page
        return url_for(request.endpoint, **args)

    return {
        'csrf_token': generate_csrf_token(),
        'app_name': config.APP_NAME,
        'app_long_name': config.APP_LONG_NAME,
        'app_version': config.APP_VERSION,
        'show_demo_accounts': config.SHOW_DEMO_ACCOUNTS,
        'page_url': page_url,
        'demo_accounts': [
            {'username': username, 'password': password, 'role': role}
            for username, password, role in (
                (config.ADMIN_USERNAME, config.ADMIN_PASSWORD, 'Administrator'),
                (config.OPERATOR_USERNAME, config.OPERATOR_PASSWORD, 'Operator'),
                (config.AUDITOR_USERNAME, config.AUDITOR_PASSWORD, 'Auditor'),
            )
            if config.SHOW_DEMO_ACCOUNTS and password
        ],
    }

# ── Security headers ─────────────────────────────────────────────
@app.after_request
def _headers(resp):
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['X-XSS-Protection'] = '1; mode=block'
    resp.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
    resp.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    resp.headers['Permissions-Policy'] = (
        'geolocation=(), microphone=(), camera=()'
    )
    resp.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
        "script-src-elem 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://fonts.googleapis.com; "
        "style-src-elem 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none';"
    )
    return resp

# ── Template filters ─────────────────────────────────────────────
@app.template_filter('fmt_dt')
def _fmt_dt(v):
    if not v: return '—'
    try:
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M:%S')
        return v.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(v)

@app.template_filter('fmt_size')
def _fmt_size(s):
    if not s: return '0 B'
    for u in ('B', 'KB', 'MB', 'GB'):
        if s < 1024: return f'{s:.1f} {u}'
        s /= 1024
    return f'{s:.1f} TB'

@app.template_filter('status_class')
def _status_cls(s):
    return {
        'online':         'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
        'offline':        'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300',
        'error':          'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
        'backup_running': 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 animate-pulse',
        'backup_success': 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
        'backup_failed':  'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
        'success':        'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
        'failed':         'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
    }.get(s, 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300')


@app.template_filter('risk_class')
def _risk_cls(level):
    return {
        'LOW': 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
        'MEDIUM': 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
        'HIGH': 'bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300',
        'CRITICAL': 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
    }.get(level, 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300')


@app.template_filter('incident_class')
def _incident_cls(status):
    return {
        'NEW': 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
        'INVESTIGATING': 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
        'VERIFIED': 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
        'RESOLVED': 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
        'FALSE_POSITIVE': 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300',
    }.get(status, 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300')


@app.template_filter('change_class')
def _change_cls(change_type):
    return {
        'ADDED': 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
        'REMOVED': 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
        'MODIFIED': 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
    }.get(change_type, 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300')


@app.template_filter('integrity_class')
def _integrity_cls(state):
    return {
        'INTACT': 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
        'DRIFT': 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
        'NOT_CHECKED': 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
        'NO_BASELINE': 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300',
    }.get(state, 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300')

# ── Routes: Auth ─────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        if not validate_csrf_token(request.form.get('csrf_token')):
            flash('Session expired. Please retry.', 'error')
            return render_template('login.html')
            
        ip = client_ip()
        username = (request.form.get('username') or '').strip()[:100]
        password = request.form.get('password') or ''

        allowed, reason = check_login_allowed(ip, username)
        if not allowed:
            if reason == 'backend':
                logger.critical('Login blocked: rate-limit backend unavailable')
                flash('Layanan login sementara tidak tersedia. Hubungi Administrator.', 'error')
                return render_template('login.html'), 503
            flash('Terlalu banyak percobaan login. Coba lagi beberapa menit lagi.',
                  'error')
            return render_template('login.html'), 429

        if len(password) > 1024:
            record_failure(ip, username)
            flash('Invalid username or password.', 'error')
            return render_template('login.html')

        user = User.query.filter_by(username=username).first()
        password_ok = check_password_hash(
            user.password_hash if user else _DUMMY_PASSWORD_HASH, password)

        if user and password_ok:
            if not user.active:
                record_failure(ip, username)
                flash('Akun dinonaktifkan. Hubungi Administrator.', 'error')
                return render_template('login.html')
            session.clear()
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            session['session_version'] = user.session_version or 0
            session.permanent = True

            try:
                user.last_login = utc_now()
                clear_failures(ip, username)
                audit.record('LOGIN', 'User', user.id, None,
                             detail={'username': user.username, 'role': user.role},
                             actor=user)
                db.session.commit()
            except Exception:
                db.session.rollback()
                session.clear()
                logger.exception('Login could not be persisted')
                flash('Layanan login sementara tidak tersedia. Hubungi Administrator.',
                      'error')
                return render_template('login.html'), 503

            next_url = request.args.get('next') or request.form.get('next')
            return redirect(safe_local_url(next_url, url_for('dashboard')))

        record_failure(ip, username)
        flash('Invalid username or password.', 'error')
        
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
@login_required
@csrf_protect
def logout():
    user = current_user()
    try:
        if user:
            audit.record('LOGOUT', 'User', user.id, None,
                         detail={'username': user.username}, actor=user)
            db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Could not persist logout audit entry')
    finally:
        session.clear()
    return redirect(url_for('login'))

# ── Routes: Dashboard ────────────────────────────────────────────
@app.route('/')
@login_required
def dashboard():
    devices = Device.query.order_by(Device.name).all()
    baseline_devices = [d for d in devices if d.active_baseline]
    intact = sum(1 for d in baseline_devices if d.integrity_state == 'INTACT')
    drift = sum(1 for d in baseline_devices if d.integrity_state == 'DRIFT')
    not_checked = sum(1 for d in baseline_devices if d.integrity_state == 'NOT_CHECKED')
    no_baseline = len(devices) - len(baseline_devices)
    integrity_pct = round(intact / len(baseline_devices) * 100) if baseline_devices else None

    stats = {
        'devices': len(devices),
        'monitored': sum(1 for d in devices if d.monitoring_enabled),
        'changes': ConfigChange.query.count(),
        'high_risk': ConfigChange.query.filter(
            ConfigChange.risk_level.in_(('HIGH', 'CRITICAL'))).count(),
        'open_incidents': Incident.query.filter(
            Incident.status.in_(INCIDENT_OPEN_STATUSES)).count(),
        'intact': intact,
        'drift': drift,
        'not_checked': not_checked,
        'no_baseline': no_baseline,
        'integrity_pct': integrity_pct,
    }

    activity = (AuditLog.query.order_by(AuditLog.created_at.desc())
                .limit(12).all())
    recent_checks = (ConfigCheck.query.order_by(ConfigCheck.created_at.desc())
                     .limit(6).all())
    recent_incidents = (Incident.query.order_by(Incident.detected_at.desc())
                        .limit(5).all())

    today = utc_now().date()
    days = [today - timedelta(days=i) for i in range(13, -1, -1)]
    start = datetime.combine(days[0], dtime.min, tzinfo=timezone.utc)
    checks = ConfigCheck.query.filter(ConfigCheck.created_at >= start).all()
    changes_by_day = {d.isoformat(): 0 for d in days}
    high_by_day = {d.isoformat(): 0 for d in days}
    for check in checks:
        key = check.created_at.date().isoformat()
        if key in changes_by_day and check.status == 'CHANGED':
            changes_by_day[key] += check.change_count
            if check.highest_risk in ('HIGH', 'CRITICAL'):
                high_by_day[key] += check.change_count

    risk_dist = {risk: ConfigChange.query.filter_by(risk_level=risk).count()
                 for risk in RISK_LEVELS}

    from services.simulation import SCENARIOS, SCENARIO_ORDER
    return render_template(
        'dashboard.html', devices=devices, stats=stats, activity=activity,
        recent_checks=recent_checks, recent_incidents=recent_incidents,
        chart_labels=[d.strftime('%d %b') for d in days],
        chart_changes=[changes_by_day[d.isoformat()] for d in days],
        chart_high=[high_by_day[d.isoformat()] for d in days],
        risk_dist=risk_dist,
        scenarios=[SCENARIOS[k] for k in SCENARIO_ORDER])

# ── Routes: Routers ──────────────────────────────────────────────
@app.route('/routers')
@login_required
def routers():
    rows = Router.query.order_by(Router.name).all()
    return render_template('routers.html', routers=rows)

@app.route('/routers/new', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
@csrf_protect
def router_new():
    if request.method == 'POST':
        errors = _validate_router_form(request.form)
        if errors:
            for e in errors: flash(e, 'error')
            return render_template('router_form.html', router=request.form, is_edit=False)
        _insert_router(request.form)
        flash(f'Router "{request.form["name"]}" added.', 'success')
        return redirect(url_for('routers'))
    return render_template('router_form.html', router=None, is_edit=False)

@app.route('/routers/<int:rid>/edit', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
@csrf_protect
def router_edit(rid):
    row = db.session.get(Router, rid)
    if not row:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'success': False, 'message': 'Data router tidak ditemukan.'}), 404
        flash('Data router tidak ditemukan.', 'error')
        return redirect(url_for('routers'))
        
    if request.method == 'POST':
        errors = _validate_router_form(request.form, is_edit=True)
        if errors:
            for e in errors: flash(e, 'error')
            return render_template('router_form.html', router=request.form, is_edit=True, rid=rid)
            
        _update_router(row, request.form)
        flash(f'Router "{request.form["name"]}" berhasil diperbarui.', 'success')
        return redirect(url_for('routers'))
        
    return render_template('router_form.html', router=row, is_edit=True, rid=rid)

@app.route('/routers/<int:rid>/delete', methods=['POST'])
@login_required
@roles_required('admin')
@csrf_protect
def router_delete(rid):
    row_data = db.session.get(Router, rid)
    if not row_data:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'success': False, 'message': 'Data router tidak ditemukan atau sudah dihapus.'}), 404
        flash('Data router tidak ditemukan atau sudah dihapus.', 'error')
        return redirect(url_for('routers'))
        
    for s in Schedule.query.filter_by(router_id=rid).all():
        sched.remove_schedule_job(s.id)

    # Cascaded Backup rows would otherwise leave orphaned files on disk.
    for backup in list(row_data.backups):
        if not backup.file_path:
            continue
        fp = os.path.join(config.BACKUP_DIR, backup.file_path)
        if is_safe_path(config.BACKUP_DIR, fp) and os.path.exists(fp):
            try:
                os.remove(fp)
            except OSError as exc:
                logger.warning(f'Could not remove backup file {fp}: {exc}')

    name = row_data.name
    db.session.delete(row_data)
    # The router row no longer exists after commit, so its activity entry must
    # not reference it (MySQL enforces the FK even though SQLite historically
    # did not). Keep the audit row and the delete in one transaction.
    db.session.add(ActivityLog(
        router_id=None, action='router_deleted', status='success',
        message=f'"{name}" removed',
    ))
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({'success': True, 'message': f'Router "{name}" berhasil dihapus.'})
        
    flash(f'Router "{name}" berhasil dihapus.', 'success')
    return redirect(url_for('routers'))

@app.route('/api/routers/test', methods=['POST'])
@login_required
@roles_required('admin', 'operator')
@csrf_protect
def api_test_inline():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        d = request.form
    host = (d.get('host') or '').strip()
    port = validate_port(d.get('port', 22)) or 22
    username = (d.get('username') or '').strip()
    password = d.get('password', '')
    auth_method = d.get('auth_method', 'password')
    ssh_key = d.get('ssh_key', '')
    if not validate_hostname(host):
        return jsonify({'success': False, 'message': 'Invalid host.'})
    if not username:
        return jsonify({'success': False, 'message': 'Username required.'})
    try:
        c = MikrotikClient(
            host=host, port=port, username=username,
            password=password if auth_method == 'password' else None,
            ssh_key=ssh_key if auth_method == 'key' else None,
            timeout=12,
        )
        ok, info = c.test_connection()
        return jsonify({'success': ok, 'message': 'OK' if ok else str(info), 'info': info if ok else None})
    except Exception:
        logger.exception('Inline router test failed')
        return jsonify({'success': False, 'message': 'Connection failed.'})

@app.route('/api/routers/<int:rid>/test', methods=['POST'])
@login_required
@roles_required('admin', 'operator')
@csrf_protect
def api_test_saved(rid):
    row = db.get_or_404(Router, rid)
    pwd, key = router_credentials(row)
    try:
        c = MikrotikClient(host=row.host, port=row.port, username=row.username, password=pwd, ssh_key=key, timeout=12)
        ok, info = c.test_connection()
        row.last_status = 'online' if ok else 'offline'
        if ok: row.last_seen = utc_now()
        db.session.commit()
        log_activity(rid, 'connection_test', 'success' if ok else 'failed', 'OK' if ok else str(info))
        emit_status(rid, row.last_status, 'Connection OK' if ok else str(info))
        return jsonify({'success': ok, 'message': str(info) if not ok else 'OK', 'info': info if ok else None})
    except Exception:
        row.last_status = 'error'
        db.session.commit()
        logger.exception('Saved router test failed')
        return jsonify({'success': False, 'message': 'Connection failed.'})

# ── Router form helpers ──────────────────────────────────────────
def _validate_router_form(form, is_edit=False):
    errors = []
    name = (form.get('name') or '').strip()
    host = (form.get('host') or '').strip()
    port = validate_port(form.get('port', 22))
    username = (form.get('username') or '').strip()
    auth_method = form.get('auth_method', 'password')
    password = form.get('password', '')
    ssh_key = form.get('ssh_key', '')
    if not name or len(name) > 100: errors.append('Name is required (max 100 chars).')
    if not host or not validate_hostname(host): errors.append('A valid IP address or hostname is required.')
    if port is None: errors.append('Port must be 1–65535.')
    if not username or len(username) > 50: errors.append('Username is required (max 50 chars).')
    if auth_method not in ('password', 'key'): errors.append('Invalid authentication method.')
    if auth_method == 'password' and not password and not is_edit: errors.append('Password is required.')
    if auth_method == 'key' and not ssh_key and not is_edit: errors.append('SSH private key is required.')
    if len(form.get('notes', '') or '') > 2000: errors.append('Notes too long (max 2000 chars).')
    return errors

def _insert_router(form):
    router = Router(
        name=form.get('name').strip(),
        host=form.get('host').strip(),
        port=validate_port(form.get('port', 22)) or 22,
        username=form.get('username').strip(),
        auth_method=form.get('auth_method', 'password'),
        enabled=bool(form.get('enabled')),
        tags=(form.get('tags') or '').strip()[:200],
        notes=(form.get('notes') or '').strip()[:2000]
    )
    password = form.get('password', '')
    ssh_key = form.get('ssh_key', '')
    if password: router.password_enc = encrypt_password(password)
    if ssh_key: router.ssh_key_enc = encrypt_password(ssh_key)
    db.session.add(router)
    db.session.commit()
    log_activity(router.id, 'router_created', 'success', f'"{router.name}" added')

def _update_router(router, form):
    router.name = form.get('name').strip()
    router.host = form.get('host').strip()
    router.port = validate_port(form.get('port', 22)) or 22
    router.username = form.get('username').strip()
    router.auth_method = form.get('auth_method', 'password')
    router.enabled = bool(form.get('enabled'))
    router.tags = (form.get('tags') or '').strip()[:200]
    router.notes = (form.get('notes') or '').strip()[:2000]
    
    password = form.get('password', '')
    ssh_key = form.get('ssh_key', '')
    if password: router.password_enc = encrypt_password(password)
    if ssh_key: router.ssh_key_enc = encrypt_password(ssh_key)
    db.session.commit()
    log_activity(router.id, 'router_updated', 'success', f'"{router.name}" updated')

# ── Backup execution ─────────────────────────────────────────────
def perform_backup(router_id, backup_type_str, triggered_by='manual', schedule_id=None):
    router = db.session.get(Router, router_id)
    if not router: return None
    if backup_type_str not in ('full', 'config'): return None
    
    btype = BackupType.FULL if backup_type_str == 'full' else BackupType.CONFIG
    emit_status(router_id, 'backup_running', f'Starting {backup_type_str} backup…')
    safe_name = sanitize_filename(router.name)
    date_str = utc_now().strftime('%Y-%m-%d')
    
    try:
        bdir = safe_join_path(config.BACKUP_DIR, safe_name, date_str)
    except ValueError:
        logger.error(f'Path error for router {router_id}')
        return None
    os.makedirs(bdir, exist_ok=True)
    
    pwd, key = router_credentials(router)
    client = None
    try:
        client = MikrotikClient(host=router.host, port=router.port, username=router.username, password=pwd, ssh_key=key, timeout=30)
        client.connect()
        emit_status(router_id, 'backup_running', 'Creating backup on router…')
        remote_name = client.create_backup(btype, safe_name)
        emit_status(router_id, 'backup_running', 'Downloading file…')
        local_name = sanitize_filename(remote_name)
        local_path = safe_join_path(bdir, local_name)
        client.download_file(remote_name, local_path)
        fsize = os.path.getsize(local_path)
        client.delete_file(remote_name)
        rel = os.path.relpath(local_path, config.BACKUP_DIR)
        
        backup = Backup(router_id=router_id, backup_type=backup_type_str, filename=local_name,
                        file_path=rel, file_size=fsize, status='success', triggered_by=triggered_by)
        db.session.add(backup)
        router.last_status = 'online'
        router.last_seen = utc_now()
        db.session.commit()
        
        log_activity(router_id, 'backup', 'success', f'{backup_type_str} ({fsize} bytes)', json.dumps({'backup_id': backup.id}))
        emit_status(router_id, 'backup_success', f'Completed: {local_name}')
        
        if schedule_id:
            _apply_retention(router_id, schedule_id)
            sched_obj = db.session.get(Schedule, schedule_id)
            if sched_obj:
                sched_obj.last_run = utc_now()
                db.session.commit()
                sched.reload_all()
        return backup.id
    except Exception as exc:
        msg = str(exc)[:10000]
        backup = Backup(router_id=router_id, backup_type=backup_type_str, status='failed',
                        error_message=msg, triggered_by=triggered_by)
        db.session.add(backup)
        router.last_status = 'error'
        db.session.commit()
        log_activity(router_id, 'backup', 'failed', msg)
        emit_status(router_id, 'backup_failed', msg)
        logger.exception(f'Backup failed for router {router_id}')
        return None
    finally:
        if client: client.close()

def _apply_retention(router_id, schedule_id):
    s = db.session.get(Schedule, schedule_id)
    if not s or not s.keep_count: return
    keep = s.keep_count
    bk = Backup.query.filter_by(router_id=router_id, status='success').order_by(Backup.created_at.desc()).all()
    if len(bk) <= keep: return
    for b in bk[keep:]:
        fp = os.path.join(config.BACKUP_DIR, b.file_path)
        if is_safe_path(config.BACKUP_DIR, fp) and os.path.exists(fp):
            try: os.remove(fp)
            except OSError as e: logger.warning(f'rm {fp}: {e}')
        db.session.delete(b)
    db.session.commit()

@app.route('/api/routers/<int:rid>/backup', methods=['POST'])
@login_required
@roles_required('admin', 'operator')
@csrf_protect
def api_trigger_backup(rid):
    db.get_or_404(Router, rid)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    btype = data.get('backup_type', 'full')
    if btype not in ('full', 'config'):
        return jsonify({'success': False, 'message': 'Invalid type'}), 400
    user = session.get('username', 'unknown')
    
    def _bg():
        with app.app_context():
            perform_backup(rid, btype, triggered_by=f'manual:{user}')
    
    threading.Thread(target=_bg, daemon=True).start()
    return jsonify({'success': True, 'message': f'{btype} backup started'})

# ── Routes: Schedules ────────────────────────────────────────────
@app.route('/schedules')
@login_required
def schedules():
    rows = Schedule.query.order_by(Schedule.name).all()
    routers = Router.query.filter_by(enabled=True).order_by(Router.name).all()
    return render_template('schedules.html', schedules=rows, routers=routers)

@app.route('/schedules/new', methods=['POST'])
@login_required
@roles_required('admin')
@csrf_protect
def schedule_new():
    f = request.form
    name = (f.get('name') or '').strip()
    router_id = f.get('router_id', type=int)
    backup_type = f.get('backup_type', 'full')
    cron_expr = (f.get('cron_expr') or '').strip()
    enabled = bool(f.get('enabled'))
    keep_count = f.get('keep_count', 10, type=int)
    
    errors = []
    if not name or len(name) > 100: errors.append('Name is required (max 100 chars).')
    if not router_id: errors.append('Router is required.')
    if backup_type not in ('full', 'config'): errors.append('Invalid backup type.')
    if not cron_expr: errors.append('Cron expression is required.')
    elif len(cron_expr) > 100: errors.append('Cron expression is too long (max 100 chars).')
    else:
        try:
            from apscheduler.triggers.cron import CronTrigger
            CronTrigger.from_crontab(cron_expr)
        except Exception:
            errors.append(f'Invalid cron expression: {cron_expr}')
    if not (1 <= (keep_count or 10) <= 1000): errors.append('Keep count must be 1–1000.')
    if not db.session.get(Router, router_id): errors.append('Router not found.')
    
    if errors:
        for e in errors: flash(e, 'error')
        return redirect(url_for('schedules'))
    
    s = Schedule(router_id=router_id, name=name, backup_type=backup_type,
                 cron_expr=cron_expr, enabled=enabled, keep_count=keep_count)
    db.session.add(s)
    db.session.commit()
    
    if enabled: sched.add_schedule_job(s)
    log_activity(router_id, 'schedule_created', 'success', f'"{name}"')
    flash(f'Schedule "{name}" created.', 'success')
    return redirect(url_for('schedules'))

@app.route('/schedules/<int:sid>/delete', methods=['POST'])
@login_required
@roles_required('admin')
@csrf_protect
def schedule_delete(sid):
    s = db.get_or_404(Schedule, sid)
    sched.remove_schedule_job(sid)
    name = s.name
    router_id = s.router_id
    db.session.delete(s)
    db.session.commit()
    log_activity(router_id, 'schedule_deleted', 'success', f'"{name}"')
    flash(f'Schedule "{name}" deleted.', 'success')
    return redirect(url_for('schedules'))

@app.route('/api/schedules/<int:sid>/toggle', methods=['POST'])
@login_required
@roles_required('admin')
@csrf_protect
def schedule_toggle(sid):
    s = db.get_or_404(Schedule, sid)
    s.enabled = not s.enabled
    db.session.commit()
    if s.enabled: sched.add_schedule_job(s)
    else: sched.remove_schedule_job(s.id)
    return jsonify({'success': True, 'enabled': s.enabled})

# ── Routes: History ──────────────────────────────────────────────
@app.route('/history')
@login_required
def history():
    page = max(1, request.args.get('page', 1, type=int))
    per_page = 50
    rf = request.args.get('router', '', type=str)
    sf = request.args.get('status', '', type=str)
    
    q = Backup.query
    if rf: q = q.filter_by(router_id=rf)
    if sf: q = q.filter_by(status=sf)
    
    pagination = q.order_by(Backup.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    activity = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(100).all()
    routers = Router.query.order_by(Router.name).all()
    
    return render_template('history.html', backups=pagination.items, activity=activity,
                           routers=routers, page=page, per_page=per_page,
                           total=pagination.total, rf=rf, sf=sf)

# ── Routes: Download / Delete backup ─────────────────────────────
@app.route('/backups/<int:bid>/download')
@login_required
def backup_download(bid):
    b = db.get_or_404(Backup, bid)
    if b.status != 'success': abort(404)
    fp = os.path.join(config.BACKUP_DIR, b.file_path)
    if not is_safe_path(config.BACKUP_DIR, fp): abort(403)
    if not os.path.isfile(fp): abort(404)
    log_activity(b.router_id, 'backup_download', 'success', f'Downloaded {b.filename}')
    return send_file(fp, as_attachment=True,
                     download_name=sanitize_filename(b.filename))

@app.route('/backups/<int:bid>/delete', methods=['POST'])
@login_required
@roles_required('admin', 'operator')
@csrf_protect
def backup_delete(bid):
    b = db.get_or_404(Backup, bid)
    router_id = b.router_id
    filename = b.filename
    if b.file_path:
        fp = os.path.join(config.BACKUP_DIR, b.file_path)
        if is_safe_path(config.BACKUP_DIR, fp) and os.path.exists(fp):
            try: os.remove(fp)
            except OSError as e: logger.warning(f'rm {fp}: {e}')
    db.session.delete(b)
    db.session.commit()
    log_activity(router_id, 'backup_deleted', 'success', f'Removed {filename}')
    flash('Backup deleted.', 'success')
    return redirect(url_for('history'))

# ── Routes: Settings ─────────────────────────────────────────────
@app.route('/settings', methods=['GET', 'POST'])
@login_required
@csrf_protect
def settings():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'change_password':
            cur = request.form.get('current_password', '')
            new = request.form.get('new_password', '')
            con = request.form.get('confirm_password', '')
            user = db.session.get(User, session.get('user_id'))
            if not user or not check_password_hash(user.password_hash, cur):
                flash('Current password incorrect.', 'error')
            elif new != con:
                flash('Passwords do not match.', 'error')
            else:
                policy_errors = validate_password_strength(new, user.username)
                if policy_errors:
                    for error in policy_errors:
                        flash(error, 'error')
                else:
                    user.password_hash = generate_password_hash(new)
                    user.session_version = (user.session_version or 0) + 1
                    session['session_version'] = user.session_version
                    audit.record('PASSWORD_CHANGED', 'User', user.id, None,
                                 detail={'username': user.username}, actor=user)
                    db.session.commit()
                    flash('Password changed.', 'success')
        elif action == 'test_all':
            if not current_user() or current_user().role not in ('admin', 'operator'):
                flash('Hanya Administrator/Operator yang dapat menguji koneksi.', 'error')
                return redirect(url_for('settings'))
            for r in Router.query.filter_by(enabled=True).all():
                def _bg(rid=r.id):
                    with app.app_context():
                        _bg_test(rid)
                threading.Thread(target=_bg, daemon=True).start()
            flash('Testing all routers in background…', 'info')
        return redirect(url_for('settings'))
    from services.simulation import SCENARIOS, SCENARIO_ORDER
    return render_template('settings.html',
                           scenarios=[SCENARIOS[k] for k in SCENARIO_ORDER])

def _bg_test(rid):
    router = db.session.get(Router, rid)
    if not router: return
    pwd, key = router_credentials(router)
    try:
        c = MikrotikClient(host=router.host, port=router.port, username=router.username, password=pwd, ssh_key=key, timeout=10)
        ok, _ = c.test_connection()
        router.last_status = 'online' if ok else 'offline'
        if ok: router.last_seen = utc_now()
        db.session.commit()
        emit_status(rid, router.last_status, 'OK' if ok else 'Connection failed')
    except Exception as exc:
        router.last_status = 'error'
        db.session.commit()
        emit_status(rid, 'error', str(exc))

# ── SSE endpoint ─────────────────────────────────────────────────
@app.route('/api/events')
@login_required
def sse_events():
    def stream():
        q: queue.Queue = queue.Queue(maxsize=200)
        with _subscribers_lock:
            _subscribers.append(q)
        try:
            yield 'event: ping\ndata: {}\n\n'
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield f'event: status\ndata: {json.dumps(msg)}\n\n'
                except queue.Empty:
                    yield 'event: ping\ndata: {}\n\n'
        finally:
            with _subscribers_lock:
                if q in _subscribers:
                    _subscribers.remove(q)
    return Response(
        stream_with_context(stream()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'},
    )

@app.route('/api/routers/status')
@login_required
def api_routers_status():
    routers = Router.query.order_by(Router.name).all()
    return jsonify({'routers': [{'id': r.id, 'name': r.name, 'last_status': r.last_status, 'last_seen': r.last_seen.isoformat() if r.last_seen else None} for r in routers]})

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

# ── Error handlers ───────────────────────────────────────────────
@app.errorhandler(404)
def _e404(e):
    if request.path.startswith('/api/'): return jsonify({'error': 'Not found'}), 404
    return render_template('error.html', code=404, msg='Page not found'), 404

@app.errorhandler(403)
def _e403(e):
    if request.path.startswith('/api/'): return jsonify({'error': 'Forbidden'}), 403
    return render_template('error.html', code=403, msg='Access denied'), 403

@app.errorhandler(413)
def _e413(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Payload too large'}), 413
    return render_template('error.html', code=413,
                           msg='File terlalu besar (maksimal 2 MB)'), 413

@app.errorhandler(500)
def _e500(e):
    db.session.rollback()
    if request.path.startswith('/api/'): return jsonify({'error': 'Internal error'}), 500
    return render_template('error.html', code=500, msg='Internal server error'), 500

# ── Bootstrap ────────────────────────────────────────────────────
sched.set_status_queue(_status_q)
sched.init_scheduler(app)
sched.reload_all()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)