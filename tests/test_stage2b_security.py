import os

import pytest

from app import app as flask_app
import config
from db import (db, AuditLog, Backup, Device, Incident, LoginAttempt,
                ResponseAction, Router, User)
from security import (is_safe_path, safe_join_path, sanitize_filename,
                      validate_csrf_token)
from services import response as response_service
import scheduler as scheduler_service
from services.demo_data import BASE_CONFIG, ensure_demo_baseline
from services.monitoring import (evaluate_configuration,
                                 update_incident_status)
from services.simulation import run_scenario

PASSWORD = 'Str0ng!Passw0rd#2026'
FIREWALL_CONFIG = BASE_CONFIG.replace('set enabled=enabled',
                                      'set enabled=disabled', 1)


def _login_client(username='admin', password=PASSWORD):
    client = flask_app.test_client()
    client.get('/login')
    with client.session_transaction() as sess:
        token = sess.get('csrf_token')
    response = client.post('/login', data={
        'username': username,
        'password': password,
        'csrf_token': token,
    })
    assert response.status_code == 302
    return client


def _token(client, path='/'):
    client.get(path)
    with client.session_transaction() as sess:
        return sess.get('csrf_token')


def _incident(app, content=FIREWALL_CONFIG):
    with app.app_context():
        device, _baseline = ensure_demo_baseline()
        admin = User.query.filter_by(username='admin').one()
        _check, incident = evaluate_configuration(
            device, content, source='test', actor=admin, create_incident=True)
        db.session.commit()
        return incident.id


def test_high_risk_self_approval_is_blocked(app):
    incident_id = _incident(app)
    with app.app_context():
        admin = User.query.filter_by(username='admin').one()
        admin2 = User.query.filter_by(username='admin2').one()
        incident = db.session.get(Incident, incident_id)
        action = response_service.request_restore(incident, admin, 'alasan uji')
        with pytest.raises(ValueError, match='Administrator lain'):
            response_service.approve_action(action, admin, approve=True)
        db.session.refresh(action)
        assert action.status == 'REQUESTED'
        response_service.approve_action(action, admin2, approve=True)
        assert action.status == 'APPROVED'
        assert action.approved_by == 'admin2'


def test_response_service_enforces_roles_and_operator_can_execute(app):
    incident_id = _incident(app)
    with app.app_context():
        admin = User.query.filter_by(username='admin').one()
        admin2 = User.query.filter_by(username='admin2').one()
        operator = User.query.filter_by(username='operator').one()
        auditor = User.query.filter_by(username='auditor').one()
        incident = db.session.get(Incident, incident_id)
        with pytest.raises(ValueError, match='Administrator/Operator'):
            response_service.request_restore(incident, auditor, 'tidak boleh')
        action = response_service.request_restore(incident, admin, 'alasan uji')
        with pytest.raises(ValueError, match='Hanya Administrator'):
            response_service.approve_action(action, operator, approve=True)
        response_service.approve_action(action, admin2, approve=True)
        with pytest.raises(ValueError, match='Administrator/Operator'):
            response_service.execute_action(action, auditor)
        executed, check = response_service.execute_action(action, operator)
        assert executed.status == 'EXECUTED'
        assert check.status == 'OK'
        assert db.session.get(Incident, incident_id).status == 'RESOLVED'


def test_execute_is_blocked_after_incident_is_closed(app):
    incident_id = _incident(app)
    with app.app_context():
        admin = User.query.filter_by(username='admin').one()
        admin2 = User.query.filter_by(username='admin2').one()
        incident = db.session.get(Incident, incident_id)
        action = response_service.request_restore(incident, admin, 'alasan uji')
        response_service.approve_action(action, admin2, approve=True)
        update_incident_status(incident, 'INVESTIGATING', actor=admin)
        update_incident_status(incident, 'VERIFIED', actor=admin)
        update_incident_status(incident, 'RESOLVED', actor=admin,
                               note='ditutup manual')
        with pytest.raises(ValueError, match='sudah ditutup'):
            response_service.execute_action(action, admin)
        assert db.session.get(ResponseAction, action.id).status == 'APPROVED'


def test_rollback_is_blocked_when_configuration_diverged(app):
    with app.app_context():
        admin = User.query.filter_by(username='admin').one()
        admin2 = User.query.filter_by(username='admin2').one()
        result = run_scenario('firewall', actor=admin)
        incident = result['incident']
        device = result['device']
        action = response_service.request_restore(incident, admin, 'alasan uji')
        response_service.approve_action(action, admin2, approve=True)
        response_service.execute_action(action, admin)
        assert incident.status == 'RESOLVED'

        device.lab_config = FIREWALL_CONFIG
        db.session.commit()
        with pytest.raises(ValueError, match='telah berubah'):
            response_service.rollback_action(action, admin)
        db.session.refresh(action)
        assert action.status == 'EXECUTED'
        assert incident.status == 'RESOLVED'


def test_backup_download_filename_is_sanitized(app):
    relative = 'stage2b-header-test.backup'
    path = os.path.join(config.BACKUP_DIR, relative)
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    with open(path, 'wb') as handle:
        handle.write(b'test')
    try:
        with app.app_context():
            router = Router(name='HEADER-RTR', host='192.0.2.77', port=22,
                            username='admin', auth_method='password')
            db.session.add(router)
            db.session.flush()
            dangerous = '<script>\r\nX-Evil: 1</script>.backup'
            backup = Backup(router_id=router.id, backup_type='full',
                            filename=dangerous, file_path=relative,
                            file_size=4, status='success', triggered_by='test')
            db.session.add(backup)
            db.session.commit()
            backup_id = backup.id

        client = _login_client('admin')
        response = client.get(f'/backups/{backup_id}/download')
        assert response.status_code == 200
        disposition = response.headers['Content-Disposition']
        assert '\r' not in disposition and '\n' not in disposition
        assert '<' not in disposition and '>' not in disposition
        assert sanitize_filename(dangerous) in disposition
        response.close()
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_path_traversal_helpers(tmp_path):
    base = tmp_path / 'base'
    base.mkdir()
    (base / 'ok.txt').write_text('ok', encoding='utf-8')
    assert is_safe_path(str(base), safe_join_path(str(base), 'ok.txt'))
    with pytest.raises(ValueError):
        safe_join_path(str(base), '..', 'outside.txt')
    assert not is_safe_path(str(base), str(tmp_path / 'outside.txt'))


def test_rbac_get_admin_pages_and_audit_are_backend_enforced(app):
    auditor = _login_client('auditor')
    for path in ('/devices/new', '/users', '/users/new', '/routers/new'):
        assert auditor.get(path).status_code == 403, path

    operator = _login_client('operator')
    assert operator.get('/users').status_code == 403
    assert operator.get('/audit').status_code == 403
    assert operator.get('/devices/new').status_code == 403


def test_duplicate_device_name_is_rejected_without_server_error(client, login,
                                                               csrf):
    login('admin')
    token = csrf('/devices/new')
    response = client.post('/devices/new', data={
        'name': 'EDGE-RTR-01',
        'ip_address': '192.0.2.88',
        'device_type': 'router',
        'adapter': 'simulation',
        'csrf_token': token,
    })
    assert response.status_code == 200
    assert b'sudah digunakan' in response.data
    with flask_app.app_context():
        assert Device.query.filter_by(name='EDGE-RTR-01').count() == 1


def test_rate_limit_backend_failure_fails_closed(client, csrf, monkeypatch):
    token = csrf('/login')
    monkeypatch.setattr('app.check_login_allowed',
                        lambda ip, username='': (False, 'backend'))
    response = client.post('/login', data={
        'username': 'admin',
        'password': PASSWORD,
        'csrf_token': token,
    })
    assert response.status_code == 503
    assert b'tidak tersedia' in response.data


def test_csrf_token_comparison_rejects_non_strings(app):
    from flask import session
    with app.test_request_context('/'):
        session['csrf_token'] = 'abc123'
        assert validate_csrf_token('abc123') is True
        assert validate_csrf_token(['abc123']) is False
        assert validate_csrf_token(None) is False


def test_csrf_json_array_is_rejected_without_server_error(client, login):
    login('admin')
    response = client.post('/settings', json=['not', 'an', 'object'])
    assert response.status_code == 403


def test_login_form_preserves_next(app, client, csrf):
    page = client.get('/login?next=/devices')
    assert b'name="next" value="/devices"' in page.data

    token = csrf('/login?next=/devices')
    response = client.post('/login', data={
        'username': 'admin',
        'password': PASSWORD,
        'csrf_token': token,
        'next': '/devices',
    })
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/devices')


def test_security_headers_present(client):
    response = client.get('/health')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert response.headers['Referrer-Policy'] == 'strict-origin-when-cross-origin'
    csp = response.headers['Content-Security-Policy']
    assert "script-src-elem 'self' 'unsafe-inline'" in csp


def test_scheduler_is_disabled_in_test_configuration():
    assert config.SCHEDULER_ENABLED is False
    assert scheduler_service._scheduler is None


def test_login_fails_closed_when_commit_fails(client, csrf, monkeypatch):
    token = csrf('/login')

    def failing_commit():
        raise RuntimeError('database write unavailable')

    with monkeypatch.context() as patch:
        patch.setattr(db.session, 'commit', failing_commit)
        response = client.post('/login', data={
            'username': 'admin', 'password': PASSWORD, 'csrf_token': token,
        })
    assert response.status_code == 503
    assert client.get('/').status_code == 302


def test_logout_clears_session_even_when_audit_write_fails(client, login, csrf,
                                                           monkeypatch):
    login('admin')

    def failing_record(*args, **kwargs):
        raise RuntimeError('audit backend unavailable')

    token = csrf('/')
    monkeypatch.setattr('services.audit.record', failing_record)
    response = client.post('/logout', data={'csrf_token': token})
    assert response.status_code == 302
    assert client.get('/').status_code == 302


def test_trusted_proxy_ip_is_used_for_throttle_and_audit(app, client, csrf,
                                                         monkeypatch):
    monkeypatch.setattr(config, 'TRUST_PROXY_HEADERS', True)
    headers = {'X-Forwarded-For': '203.0.113.9, 10.0.0.1'}
    token = csrf('/login')
    failed = client.post('/login', data={
        'username': 'admin', 'password': 'wrong', 'csrf_token': token,
    }, headers=headers)
    assert failed.status_code == 200
    with app.app_context():
        attempt = LoginAttempt.query.order_by(LoginAttempt.id.desc()).first()
        assert attempt.ip_address == '203.0.113.9'

    token = csrf('/login')
    success = client.post('/login', data={
        'username': 'admin', 'password': PASSWORD, 'csrf_token': token,
    }, headers=headers)
    assert success.status_code == 302
    with app.app_context():
        entry = (AuditLog.query.filter_by(action='LOGIN')
                 .order_by(AuditLog.id.desc()).first())
        assert entry.ip_address == '203.0.113.9'


def test_audit_search_payload_is_treated_as_text(client, login):
    login('admin')
    response = client.get('/audit', query_string={
        'q': "' OR 1=1 --",
        'action': "' OR 1=1 --",
        'username': "' OR 1=1 --",
    })
    assert response.status_code == 200


def test_admin_cannot_remove_own_admin_access(app, client, login, csrf, ids):
    login('admin')
    url = f"/users/{ids['admin']}/edit"
    token = csrf(url)
    demote = client.post(url, data={
        'role': 'operator', 'active': 'on', 'csrf_token': token,
    })
    assert b'tidak dapat menurunkan role akun sendiri' in demote.data

    token = csrf(url)
    deactivate = client.post(url, data={
        'role': 'admin', 'csrf_token': token,
    })
    assert b'tidak dapat menonaktifkan akun sendiri' in deactivate.data

    with app.app_context():
        admin = db.session.get(User, ids['admin'])
        assert admin.role == 'admin'
        assert admin.active is True


def test_execute_restore_commits_atomically(app, monkeypatch):
    incident_id = _incident(app)
    with app.app_context():
        admin = User.query.filter_by(username='admin').one()
        admin2 = User.query.filter_by(username='admin2').one()
        incident = db.session.get(Incident, incident_id)
        action = response_service.request_restore(incident, admin, 'alasan uji')
        response_service.approve_action(action, admin2, approve=True)
        device = incident.device
        before_content = device.lab_config

        def fail_after_verification(*args, **kwargs):
            raise RuntimeError('kegagalan setelah verifikasi')

        monkeypatch.setattr(response_service, '_resolve_after_restore',
                            fail_after_verification)
        with pytest.raises(RuntimeError):
            response_service.execute_action(action, admin)

        db.session.rollback()
        db.session.refresh(action)
        db.session.refresh(incident)
        db.session.refresh(device)
        assert action.status == 'APPROVED'
        assert incident.status == 'NEW'
        assert device.lab_config == before_content


def test_closed_incident_cannot_be_approved(app):
    incident_id = _incident(app)
    with app.app_context():
        admin = User.query.filter_by(username='admin').one()
        admin2 = User.query.filter_by(username='admin2').one()
        incident = db.session.get(Incident, incident_id)
        action = response_service.request_restore(incident, admin, 'alasan uji')

        update_incident_status(incident, 'INVESTIGATING', actor=admin)
        incident = db.session.get(Incident, incident_id)
        update_incident_status(incident, 'VERIFIED', actor=admin)
        incident = db.session.get(Incident, incident_id)
        update_incident_status(incident, 'RESOLVED', actor=admin)

        with pytest.raises(ValueError, match='sudah ditutup'):
            response_service.approve_action(action, admin2, approve=True)
        db.session.refresh(action)
        assert action.status == 'REQUESTED'
