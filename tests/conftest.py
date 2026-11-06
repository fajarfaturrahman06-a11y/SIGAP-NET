import os
import tempfile
from pathlib import Path

import pytest

TEST_DIR = Path(tempfile.mkdtemp(prefix='sigapnet-tests-'))
os.environ['DATABASE_URL'] = 'sqlite:///' + (TEST_DIR / 'test.db').as_posix()
os.environ['SECRET_KEY'] = 'test-secret-key-not-for-production'
os.environ['SIGAP_SEED_DEMO_USERS'] = 'false'
os.environ['SIGAP_SHOW_DEMO_ACCOUNTS'] = 'false'
os.environ['SIGAP_ALLOW_REAL_RESTORE'] = 'false'
os.environ['ADMIN_USERNAME'] = 'admin'
os.environ['ADMIN_PASSWORD'] = ''
os.environ['SCHEDULER_ENABLED'] = 'false'

from app import app as flask_app  # noqa: E402
from db import db, User  # noqa: E402
from services.demo_data import ensure_demo_baseline  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

PASSWORD = 'Str0ng!Passw0rd#2026'
ADMIN = 'admin'
OPERATOR = 'operator'
AUDITOR = 'auditor'
ADMIN2 = 'admin2'


def _add_user(username, role, active=True):
    user = User(username=username,
                password_hash=generate_password_hash(PASSWORD),
                role=role, active=active)
    db.session.add(user)
    return user


@pytest.fixture(scope='session')
def app():
    flask_app.config.update(
        TESTING=True,
        LOGIN_MAX_ATTEMPTS=5,
        LOGIN_WINDOW_SECONDS=300,
        ALLOW_REAL_RESTORE=False,
        WTF_CSRF_ENABLED=False,
    )
    yield flask_app


@pytest.fixture(autouse=True)
def database(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        _add_user(ADMIN, 'admin')
        _add_user(ADMIN2, 'admin')
        _add_user(OPERATOR, 'operator')
        _add_user(AUDITOR, 'auditor')
        db.session.commit()
        ensure_demo_baseline(actor='test')
    yield
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def csrf(client):
    def _token(path='/login'):
        client.get(path)
        with client.session_transaction() as sess:
            token = sess.get('csrf_token')
        return token
    return _token


@pytest.fixture
def login(client, csrf):
    def _login(username=ADMIN, password=PASSWORD, path='/login'):
        token = csrf('/login')
        return client.post('/login', data={
            'username': username,
            'password': password,
            'csrf_token': token,
        })
    return _login


@pytest.fixture
def ids(app):
    with app.app_context():
        return {
            'admin': User.query.filter_by(username=ADMIN).first().id,
            'admin2': User.query.filter_by(username=ADMIN2).first().id,
            'operator': User.query.filter_by(username=OPERATOR).first().id,
            'auditor': User.query.filter_by(username=AUDITOR).first().id,
        }


@pytest.fixture
def demo_ids(app):
    from db import Device, Baseline
    with app.app_context():
        device = Device.query.filter_by(is_demo=True).first()
        baseline = Baseline.query.filter_by(device_id=device.id, is_active=True).first()
        return {'device': device.id, 'baseline': baseline.id}
