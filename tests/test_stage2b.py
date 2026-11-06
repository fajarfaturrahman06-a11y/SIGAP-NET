from datetime import timezone
from pathlib import Path
from urllib.parse import quote

import pytest
from sqlalchemy.exc import IntegrityError

from app import app as flask_app
from db import (db, AuditLog, Baseline, ConfigChange, Device, Incident,
                IncidentEvent, LoginAttempt, ResponseAction, User, utc_now)
from ratelimit import check_login_allowed, clear_failures, record_failure
from security import safe_local_url, sanitize_filename
from services import response as response_service
from services.demo_data import BASE_CONFIG, ensure_demo_baseline
from services.integrity import config_hash
from services.monitoring import (add_incident_note, evaluate_configuration,
                                 update_incident_status)
from services.risk import RULE_CATALOG

PASSWORD = 'Str0ng!Passw0rd#2026'
NEW_PASSWORD = 'N3w!Str0ng#Passw0rd'
FIREWALL_CONFIG = BASE_CONFIG.replace('set enabled=enabled',
                                      'set enabled=disabled', 1)


def _login_client(username='admin', password=PASSWORD, headers=None):
    client = flask_app.test_client()
    client.get('/login')
    with client.session_transaction() as sess:
        token = sess.get('csrf_token')
    response = client.post('/login', data={
        'username': username,
        'password': password,
        'csrf_token': token,
    }, headers=headers or {})
    assert response.status_code == 302
    return client


def _token(client, path='/'):
    client.get(path)
    with client.session_transaction() as sess:
        return sess.get('csrf_token')


def _make_incident(app):
    with app.app_context():
        device, _baseline = ensure_demo_baseline()
        admin = User.query.filter_by(username='admin').one()
        _check, incident = evaluate_configuration(
            device, FIREWALL_CONFIG, source='test', actor=admin,
            create_incident=True)
        db.session.commit()
        return incident.id


def test_safe_local_url_and_login_redirect(client, csrf):
    assert safe_local_url(None, '/') == '/'
    assert safe_local_url('/devices', '/') == '/devices'
    for payload in ('//evil.example', '/\\evil.example', 'https://evil.example',
                    'javascript:alert(1)', '/\r\nLocation: https://evil.example',
                    '/%5Cevil.example', '/%2F%2Fevil.example',
                    '/%0D%0ALocation:%20https://evil.example',
                    'evil.example'):
        assert safe_local_url(payload, '/') == '/'

    for payload in ('//evil.example', '/\\evil.example', 'https://evil.example'):
        fresh = flask_app.test_client()
        fresh.get('/login')
        with fresh.session_transaction() as sess:
            token = sess.get('csrf_token')
        response = fresh.post('/login?next=' + quote(payload, safe=''),
                              data={'username': 'admin', 'password': PASSWORD,
                                    'csrf_token': token})
        assert response.status_code == 302
        assert response.headers['Location'] == '/'

    fresh = flask_app.test_client()
    fresh.get('/login')
    with fresh.session_transaction() as sess:
        token = sess.get('csrf_token')
    response = fresh.post('/login?next=/devices',
                          data={'username': 'admin', 'password': PASSWORD,
                                'csrf_token': token})
    assert response.headers['Location'].endswith('/devices')


def test_login_password_length_is_bounded(client, csrf):
    token = csrf('/login')
    response = client.post('/login', data={
        'username': 'admin', 'password': 'A!' * 600,
        'csrf_token': token,
    })
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert 'user_id' not in sess


def test_logout_post_only_and_csrf(client, login, csrf):
    login()
    assert client.get('/logout').status_code == 405
    assert client.post('/logout', data={}).status_code == 403
    response = client.post('/logout', data={'csrf_token': csrf('/')})
    assert response.status_code == 302
    assert client.get('/').status_code == 302


def test_password_change_invalidates_other_sessions(client, login, csrf):
    assert login('admin').status_code == 302
    other = _login_client('admin')
    token = csrf('/settings')
    response = client.post('/settings', data={
        'action': 'change_password',
        'current_password': PASSWORD,
        'new_password': NEW_PASSWORD,
        'confirm_password': NEW_PASSWORD,
        'csrf_token': token,
    })
    assert response.status_code == 302
    assert client.get('/').status_code == 200
    assert other.get('/devices').status_code == 302
    with flask_app.app_context():
        user = User.query.filter_by(username='admin').one()
        assert user.session_version == 1


def test_admin_password_reset_invalidates_target_session(app):
    admin_client = _login_client('admin')
    operator_client = _login_client('operator')
    assert operator_client.get('/devices').status_code == 200
    with app.app_context():
        operator_id = User.query.filter_by(username='operator').one().id
    token = _token(admin_client, '/users')
    response = admin_client.post(f'/users/{operator_id}/edit', data={
        'role': 'operator',
        'email': 'operator@example.test',
        'active': 'on',
        'password': NEW_PASSWORD,
        'csrf_token': token,
    })
    assert response.status_code == 302
    assert operator_client.get('/devices').status_code == 302


def test_successful_login_does_not_reset_ip_throttle(app):
    ip = '198.51.100.9'
    with app.app_context():
        for _ in range(4):
            record_failure(ip, 'admin')
        record_failure(ip, 'operator')
        clear_failures(ip, 'operator')
        assert LoginAttempt.query.filter_by(ip_address=ip,
                                            username='admin').count() == 4
        assert LoginAttempt.query.filter_by(ip_address=ip,
                                            username='operator').count() == 0
        assert check_login_allowed(ip, 'admin')[0] is True
        record_failure(ip, 'admin')
        assert check_login_allowed(ip, 'admin') == (False, 'limit')


def test_clear_failures_only_clears_the_authenticated_ip_bucket(app):
    ip_a = '198.51.100.21'
    ip_b = '198.51.100.22'
    with app.app_context():
        record_failure(ip_a, 'admin')
        record_failure(ip_a, 'operator')
        record_failure(ip_b, 'admin')

        clear_failures(ip_a, 'admin')

        assert LoginAttempt.query.filter_by(
            ip_address=ip_a, username='admin').count() == 0
        assert LoginAttempt.query.filter_by(
            ip_address=ip_a, username='operator').count() == 1
        assert LoginAttempt.query.filter_by(
            ip_address=ip_b, username='admin').count() == 1


def test_audit_ip_ignores_untrusted_forwarded_header(app):
    client = flask_app.test_client()
    client.get('/login')
    with client.session_transaction() as sess:
        token = sess.get('csrf_token')
    response = client.post('/login', data={
        'username': 'admin', 'password': PASSWORD, 'csrf_token': token,
    }, headers={'X-Forwarded-For': '203.0.113.50'})
    assert response.status_code == 302
    with app.app_context():
        entry = AuditLog.query.filter_by(action='LOGIN').order_by(
            AuditLog.id.desc()).first()
        assert entry.ip_address != '203.0.113.50'
        assert entry.ip_address in ('127.0.0.1', '::1')


def test_auditor_is_read_only_and_operator_cannot_administer(app):
    auditor = _login_client('auditor')
    assert auditor.get('/devices').status_code == 200
    assert auditor.get('/audit').status_code == 200
    assert auditor.get('/users').status_code == 403
    token = _token(auditor)
    denied_paths = [
        '/devices/new', '/devices/1/edit', '/devices/1/delete',
        '/devices/1/check', '/devices/1/status',
        '/devices/1/toggle-monitoring', '/devices/1/baselines/new',
        '/baselines/1/activate', '/checks/new',
        '/settings/simulation/run/firewall', '/settings/simulation/reset',
        '/routers/new', '/routers/1/edit', '/routers/1/delete',
        '/api/routers/test', '/api/routers/1/test', '/api/routers/1/backup',
        '/schedules/new', '/schedules/1/delete', '/api/schedules/1/toggle',
        '/backups/1/delete', '/users/new', '/users/1/edit', '/users/1/delete',
        '/incidents/1/status', '/incidents/1/note',
        '/incidents/1/response/request',
        '/incidents/1/response/1/approve',
        '/incidents/1/response/1/execute',
        '/incidents/1/response/1/rollback',
    ]
    for path in denied_paths:
        response = auditor.post(path, data={'csrf_token': token})
        assert response.status_code == 403, path

    operator = _login_client('operator')
    token = _token(operator)
    admin_only = [
        '/devices/new', '/devices/1/delete', '/devices/1/baselines/new',
        '/baselines/1/activate', '/routers/new', '/schedules/new',
        '/users/new', '/settings/simulation/reset',
        '/incidents/1/response/1/approve',
        '/incidents/1/response/1/rollback',
    ]
    for path in admin_only:
        response = operator.post(path, data={'csrf_token': token})
        assert response.status_code == 403, path


def test_baseline_creation_activation_and_download(client, login, csrf,
                                                   demo_ids):
    login('admin')
    device_id = demo_ids['device']
    old_id = demo_ids['baseline']
    token = csrf(f'/devices/{device_id}/baselines/new')
    content = BASE_CONFIG + '\n# baseline v2\n'
    response = client.post(f'/devices/{device_id}/baselines/new', data={
        'label': 'Baseline v2',
        'notes': 'test',
        'config_text': content,
        'csrf_token': token,
    })
    assert response.status_code == 302
    with flask_app.app_context():
        baseline = Baseline.query.filter_by(device_id=device_id,
                                            version=2).one()
        new_id = baseline.id
        assert baseline.is_active is True
        assert baseline.sha256 == config_hash(content)
        assert db.session.get(Baseline, old_id).is_active is False

    token = csrf('/baselines')
    activated = client.post(f'/baselines/{old_id}/activate',
                            data={'csrf_token': token})
    assert activated.status_code == 302
    with flask_app.app_context():
        active = Baseline.query.filter_by(device_id=device_id,
                                          is_active=True).all()
        assert [b.id for b in active] == [old_id]
        assert db.session.get(Baseline, new_id).is_active is False

    download = client.get(f'/baselines/{new_id}/download')
    assert download.status_code == 200
    disposition = download.headers['Content-Disposition']
    assert '\r' not in disposition and '\n' not in disposition


def test_duplicate_baseline_version_rejected_by_constraint(app, demo_ids):
    with app.app_context():
        device = db.session.get(Device, demo_ids['device'])
        duplicate = Baseline(
            device_id=device.id,
            version=1,
            label='duplicate',
            content='duplicate',
            sha256=config_hash('duplicate'),
            is_active=False,
            created_by='test',
        )
        db.session.add(duplicate)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_risk_metadata_and_change_explanations(app):
    for rule in RULE_CATALOG:
        assert rule['id']
        assert rule['severity'] in ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
        for field in ('title', 'reason', 'impact', 'recommendation'):
            assert rule[field].strip()

    with app.app_context():
        device, _baseline = ensure_demo_baseline()
        admin = User.query.filter_by(username='admin').one()
        check, incident = evaluate_configuration(
            device, FIREWALL_CONFIG, source='test', actor=admin,
            create_incident=True)
        db.session.commit()
        change = ConfigChange.query.filter_by(check_id=check.id).first()
        assert change is not None
        assert change.title and change.reason and change.impact
        assert change.recommendation
        assert incident.severity == 'HIGH'
        assert incident.check_id == check.id


def test_repeated_identical_drift_reuses_open_incident(app):
    with app.app_context():
        device, _baseline = ensure_demo_baseline()
        admin = User.query.filter_by(username='admin').one()
        _check1, first = evaluate_configuration(
            device, FIREWALL_CONFIG, source='test', actor=admin,
            create_incident=True)
        _check2, second = evaluate_configuration(
            device, FIREWALL_CONFIG, source='test', actor=admin,
            create_incident=True)
        db.session.commit()
        assert second.id == first.id
        assert getattr(second, 'was_reused', False) is True
        assert Incident.query.count() == 1
        assert IncidentEvent.query.filter_by(
            incident_id=first.id, action='REDETECTED').count() == 1


def test_incident_lifecycle_and_note(app):
    incident_id = _make_incident(app)
    with app.app_context():
        admin = User.query.filter_by(username='admin').one()
        incident = db.session.get(Incident, incident_id)
        update_incident_status(incident, 'INVESTIGATING', actor=admin,
                               note='mulai investigasi')
        incident = db.session.get(Incident, incident_id)
        add_incident_note(incident, '<script>alert(1)</script>', actor=admin,
                          assign=True)
        incident = db.session.get(Incident, incident_id)
        update_incident_status(incident, 'VERIFIED', actor=admin,
                               note='terverifikasi')
        incident = db.session.get(Incident, incident_id)
        update_incident_status(incident, 'RESOLVED', actor=admin,
                               note='selesai')
        incident = db.session.get(Incident, incident_id)
        assert incident.status == 'RESOLVED'
        assert incident.closed_at is not None
        assert incident.closed_at.tzinfo == timezone.utc
        assert incident.assigned_to == 'admin'
        actions = [event.action for event in incident.events]
        assert actions.count('STATUS_CHANGED') == 3
        assert 'NOTE_ADDED' in actions


def test_reopened_incident_clears_closed_at(app):
    incident_id = _make_incident(app)
    with app.app_context():
        admin = User.query.filter_by(username='admin').one()
        incident = db.session.get(Incident, incident_id)
        update_incident_status(incident, 'INVESTIGATING', actor=admin)
        incident = db.session.get(Incident, incident_id)
        update_incident_status(incident, 'VERIFIED', actor=admin)
        incident = db.session.get(Incident, incident_id)
        update_incident_status(incident, 'RESOLVED', actor=admin)
        incident = db.session.get(Incident, incident_id)
        assert incident.closed_at is not None
        update_incident_status(incident, 'INVESTIGATING', actor=admin)
        incident = db.session.get(Incident, incident_id)
        assert incident.status == 'INVESTIGATING'
        assert incident.closed_at is None


def test_invalid_incident_transition_is_rejected(app):
    incident_id = _make_incident(app)
    with app.app_context():
        admin = User.query.filter_by(username='admin').one()
        incident = db.session.get(Incident, incident_id)
        with pytest.raises(ValueError):
            update_incident_status(incident, 'RESOLVED', actor=admin)
        assert db.session.get(Incident, incident_id).status == 'NEW'


def test_response_request_is_bound_to_baseline(app):
    with app.app_context():
        device, baseline = ensure_demo_baseline()
        admin = User.query.filter_by(username='admin').one()
        admin2 = User.query.filter_by(username='admin2').one()
        _check, incident = evaluate_configuration(
            device, FIREWALL_CONFIG, source='test', actor=admin,
            create_incident=True)
        action = response_service.request_restore(incident, admin,
                                                  'pulihkan baseline')
        response_service.approve_action(action, admin2)
        assert action.baseline_id == baseline.id
        assert action.baseline_sha256 == baseline.sha256

        new_content = baseline.content + '\n# v2\n'
        baseline.is_active = False
        new_baseline = Baseline(
            device_id=device.id, version=2, label='v2',
            content=new_content, sha256=config_hash(new_content),
            is_active=True, created_by='test')
        db.session.add(new_baseline)
        db.session.commit()

        with pytest.raises(ValueError, match='tidak lagi aktif'):
            response_service.execute_action(action, admin)
        db.session.refresh(action)
        assert action.status == 'FAILED'
        assert AuditLog.query.filter_by(action='RESPONSE_FAILED').count() == 1


def test_tampered_baseline_blocks_restore(app):
    with app.app_context():
        device, baseline = ensure_demo_baseline()
        admin = User.query.filter_by(username='admin').one()
        admin2 = User.query.filter_by(username='admin2').one()
        _check, incident = evaluate_configuration(
            device, FIREWALL_CONFIG, source='test', actor=admin,
            create_incident=True)
        action = response_service.request_restore(incident, admin,
                                                  'pulihkan baseline')
        response_service.approve_action(action, admin2)
        baseline.content = baseline.content.replace(
            'set servers=192.168.1.1', 'set servers=203.0.113.66')
        db.session.commit()

        with pytest.raises(ValueError, match='Integritas baseline'):
            response_service.execute_action(action, admin)
        db.session.refresh(action)
        assert action.status == 'FAILED'


def test_duplicate_pending_response_request_rejected(app):
    with app.app_context():
        device, _baseline = ensure_demo_baseline()
        admin = User.query.filter_by(username='admin').one()
        _check, incident = evaluate_configuration(
            device, FIREWALL_CONFIG, source='test', actor=admin,
            create_incident=True)
        response_service.request_restore(incident, admin, 'pertama')
        with pytest.raises(ValueError, match='menunggu persetujuan'):
            response_service.request_restore(incident, admin, 'kedua')
        assert ResponseAction.query.count() == 1


def test_download_filename_and_xss_are_sanitized(app):
    dangerous = '<script>alert(1)</script>'
    with app.app_context():
        device = Device(name=dangerous, ip_address='192.0.2.55',
                        device_type='router', adapter='simulation',
                        monitoring_enabled=True)
        device.lab_config = '# lab'
        db.session.add(device)
        db.session.commit()
        device_id = device.id

    client = _login_client('admin')
    listing = client.get('/devices')
    assert b'&lt;script&gt;alert(1)&lt;/script&gt;' in listing.data
    assert dangerous.encode() not in listing.data

    download = client.get(f'/devices/{device_id}/config')
    assert download.status_code == 200
    disposition = download.headers['Content-Disposition']
    assert '\r' not in disposition and '\n' not in disposition
    assert '<' not in disposition and '>' not in disposition
    assert sanitize_filename(dangerous) in disposition


def test_timezone_aware_timestamps_everywhere(app):
    with app.app_context():
        user = User.query.filter_by(username='admin').one()
        assert user.created_at.tzinfo == timezone.utc
        record_failure('127.0.0.1', 'admin')
        attempt = LoginAttempt.query.order_by(LoginAttempt.id.desc()).first()
        assert attempt.attempted_at.tzinfo == timezone.utc

        device, _baseline = ensure_demo_baseline()
        _check, incident = evaluate_configuration(
            device, FIREWALL_CONFIG, source='test', actor=user,
            create_incident=True)
        db.session.commit()
        assert incident.detected_at.tzinfo == timezone.utc
        assert incident.events[0].created_at.tzinfo == timezone.utc
        audit_entry = AuditLog.query.order_by(AuditLog.id.desc()).first()
        assert audit_entry.created_at.tzinfo == timezone.utc
        assert utc_now().tzinfo == timezone.utc


def test_ensure_admin_env_does_not_accept_non_admin(app, monkeypatch):
    import config
    from bootstrap import ensure_admin_from_env

    with app.app_context():
        monkeypatch.setattr(config, 'ADMIN_USERNAME', 'admin')
        monkeypatch.setattr(config, 'ADMIN_PASSWORD', NEW_PASSWORD)
        assert ensure_admin_from_env() is True

        monkeypatch.setattr(config, 'ADMIN_USERNAME', 'operator')
        assert ensure_admin_from_env() is False
        assert User.query.filter_by(username='operator').one().role == 'operator'


def test_no_naive_utcnow_remains():
    import re
    root = Path(__file__).resolve().parents[1]
    offenders = []
    pattern = re.compile(r'\butcnow\s*\(')
    for path in root.rglob('*.py'):
        if any(part in {'.venv', 'venv', '__pycache__'} for part in path.parts):
            continue
        content = path.read_text(encoding='utf-8', errors='ignore')
        if pattern.search(content):
            offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_docker_and_env_secret_hygiene():
    root = Path(__file__).resolve().parents[1]
    dockerignore = (root / '.dockerignore').read_text(encoding='utf-8')
    for entry in ('.env', '.encryption_key', '.secret_key', 'data/',
                  'backups/', 'logs/', '*.db'):
        assert entry in dockerignore

    dockerfile = (root / 'Dockerfile').read_text(encoding='utf-8')
    assert 'USER appuser' in dockerfile
    assert 'FROM python' in dockerfile

    compose = (root / 'docker-compose.yml').read_text(encoding='utf-8')
    assert 'ENCRYPTION_KEY' in compose
    assert './data:/app/data' in compose
    assert 'no-new-privileges:true' in compose
    assert not [line for line in compose.splitlines()
                if '3306:3306' in line and not line.lstrip().startswith('#')]

    env_example = (root / '.env-example').read_text(encoding='utf-8')
    assert 'SIGAP_ALLOW_REAL_RESTORE=false' in env_example
    assert 'SIGAP_SEED_DEMO_USERS=false' in env_example
    assert 'ADMIN_PASSWORD=\n' in env_example
    assert 'ENCRYPTION_KEY=' in env_example
