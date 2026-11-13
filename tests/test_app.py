from click.testing import CliRunner

from app import app as flask_app
from db import (db, ActivityLog, AuditLog, Device, Incident, LoginAttempt,
                Router, User)
from security import validate_password_strength
from services.simulation import run_scenario

PASSWORD = 'Str0ng!Passw0rd#2026'


def test_password_policy():
    assert validate_password_strength('short') != []
    assert validate_password_strength('alllowercase123!', 'user') != []
    assert validate_password_strength('Str0ng!Passw0rd#2026') == []
    assert validate_password_strength('Str0ng!Passw0rd#2026', 'strong') == []
    assert validate_password_strength('User!Passw0rd#2026', 'user') != []


def test_login_success_and_dashboard(client, login):
    response = login()
    assert response.status_code == 302
    dashboard = client.get('/')
    assert dashboard.status_code == 200
    assert b'Dashboard Monitoring' in dashboard.data


def test_login_rejects_invalid_and_inactive(client, csrf):
    token = csrf('/login')
    bad = client.post('/login', data={'username': 'admin', 'password': 'wrong',
                                      'csrf_token': token})
    assert bad.status_code == 200
    assert b'Invalid username or password' in bad.data

    with flask_app.app_context():
        auditor = User.query.filter_by(username='auditor').one()
        auditor.active = False
        db.session.commit()
    token = csrf('/login')
    inactive = client.post('/login', data={'username': 'auditor',
                                           'password': PASSWORD,
                                           'csrf_token': token})
    assert inactive.status_code == 200
    assert b'Akun dinonaktifkan' in inactive.data


def test_login_rate_limit_is_shared_and_fails_closed(client, csrf):
    token = csrf('/login')
    for _ in range(5):
        response = client.post('/login', data={'username': 'admin',
                                               'password': 'wrong',
                                               'csrf_token': token})
        assert response.status_code == 200
    blocked = client.post('/login', data={'username': 'admin',
                                          'password': PASSWORD,
                                          'csrf_token': token})
    assert blocked.status_code == 429
    assert b'Terlalu banyak' in blocked.data
    with flask_app.app_context():
        assert LoginAttempt.query.count() == 5


def test_login_page_hides_demo_credentials(client):
    response = client.get('/login')
    assert response.status_code == 200
    assert b'Admin#12345' not in response.data
    assert b'Akun demo' not in response.data


def test_anonymous_access_is_redirected(client):
    response = client.get('/devices')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_rbac_matrix(client, login, csrf, demo_ids):
    login('auditor')
    assert client.get('/devices').status_code == 200
    assert client.get('/audit').status_code == 200
    assert client.get('/users').status_code == 403
    token = csrf('/')
    denied = client.post('/settings/simulation/run/firewall',
                         data={'csrf_token': token})
    assert denied.status_code == 403

    client.post('/logout', data={'csrf_token': csrf('/')})
    login('operator')
    assert client.get('/users').status_code == 403
    token = csrf('/')
    started = client.post('/settings/simulation/run/firewall',
                          data={'csrf_token': token})
    assert started.status_code == 302
    with flask_app.app_context():
        incident = Incident.query.first()
        incident_id = incident.id
    token = csrf('/')
    note = client.post(f'/incidents/{incident_id}/note',
                       data={'note': 'operator note', 'csrf_token': token})
    assert note.status_code == 302
    token = csrf('/')
    approve = client.post(
        f'/incidents/{incident_id}/response/1/approve',
        data={'decision': 'approve', 'csrf_token': token})
    assert approve.status_code == 403

    client.post('/logout', data={'csrf_token': csrf('/')})
    login('admin')
    assert client.get('/users').status_code == 200


def test_csrf_required_on_state_changing_routes(client, login):
    login()
    response = client.post('/settings/simulation/run/firewall', data={})
    assert response.status_code == 403


def test_all_templates_render(client, login, csrf, demo_ids, ids):
    with flask_app.app_context():
        result = run_scenario('firewall')
        check_id = result['check'].id
        incident_id = result['incident'].id
        user_id = User.query.filter_by(username='operator').one().id

    login()
    paths = [
        '/', '/devices', '/devices/new', f"/devices/{demo_ids['device']}",
        f"/devices/{demo_ids['device']}/edit", '/baselines',
        f"/devices/{demo_ids['device']}/baselines/new",
        f"/baselines/{demo_ids['baseline']}", '/checks', '/checks/new',
        f'/checks/{check_id}', '/risks', '/incidents',
        f'/incidents/{incident_id}', '/audit', '/users', '/users/new',
        f'/users/{user_id}/edit', '/settings', '/routers', '/schedules',
        '/history', '/health',
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)

    missing = client.get('/does-not-exist')
    assert missing.status_code == 404
    assert b'Page not found' in missing.data


def test_legacy_router_crud_still_works(client, login, csrf):
    login()
    token = csrf('/routers')
    created = client.post('/routers/new', data={
        'name': 'LEGACY-RTR', 'host': '192.0.2.10', 'port': '22',
        'username': 'admin', 'auth_method': 'password',
        'password': 'RouterPass!123', 'notes': 'legacy test',
        'csrf_token': token,
    })
    assert created.status_code == 302
    with flask_app.app_context():
        router = Router.query.filter_by(name='LEGACY-RTR').one()
        router_id = router.id
    assert client.get('/routers').status_code == 200

    deleted = client.post(
        f'/routers/{router_id}/delete',
        data={'csrf_token': token},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert deleted.status_code == 200
    with flask_app.app_context():
        assert Router.query.filter_by(name='LEGACY-RTR').count() == 0
        entry = ActivityLog.query.filter_by(action='router_deleted').one()
        assert entry.router_id is None


def test_init_db_cli_creates_schema_without_users(app):
    runner = CliRunner()
    with app.app_context():
        db.drop_all()
    result = runner.invoke(flask_app.cli, ['init-db'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        assert User.query.count() == 0
        assert Device.query.count() == 0


def test_weak_admin_password_is_rejected_by_cli(app):
    runner = CliRunner()
    result = runner.invoke(flask_app.cli, ['create-admin', 'weakadmin'],
                           input='password\npassword\n')
    assert result.exit_code == 0
    assert 'User not created' in result.output
    with app.app_context():
        assert User.query.filter_by(username='weakadmin').first() is None


def test_strong_admin_can_be_created_by_cli(app):
    runner = CliRunner()
    result = runner.invoke(flask_app.cli, ['create-admin', 'cliadmin'],
                           input=f'{PASSWORD}\n{PASSWORD}\n')
    assert result.exit_code == 0, result.output
    assert 'created successfully' in result.output
    with app.app_context():
        user = User.query.filter_by(username='cliadmin').one()
        assert user.role == 'admin'
        assert AuditLog.query.filter_by(action='USER_CREATED').count() == 1
