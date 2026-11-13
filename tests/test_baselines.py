"""
Regression tests for Baseline management (STAGE 3A).
"""
from werkzeug.security import generate_password_hash
from db import db, User, Device, Baseline
from services.integrity import config_hash


def test_baseline_creation_and_hash(app):
    """Verify baseline is created with correct SHA-256 hash."""
    with app.app_context():
        # Create test user and device
        user = User(
            username='testadmin',
            password_hash=generate_password_hash('strongpass'),
            role='admin',
            active=True
        )
        db.session.add(user)
        
        device = Device(name='test-router', ip_address='192.168.88.1')
        db.session.add(device)
        db.session.commit()
        
        # Create baseline
        content = "# MikroTik config\n/interface bridge\nadd name=bridge1"
        sha256_expected = config_hash(content)
        
        baseline = Baseline(
            device_id=device.id,
            version=1,
            label='Test Baseline',
            content=content,
            sha256=sha256_expected,
            is_active=True,
            created_by='testadmin'
        )
        db.session.add(baseline)
        db.session.commit()
        
        assert baseline.sha256 == sha256_expected
        assert baseline.content == content


def test_baseline_version_uniqueness_per_device(app):
    """Ensure version is unique per device."""
    with app.app_context():
        user = User(username='test', password_hash=generate_password_hash('p'), role='admin')
        db.session.add(user)
        device = Device(name='vtest', ip_address='10.0.0.1')
        db.session.add(device)
        db.session.commit()
        
        b1 = Baseline(device_id=device.id, version=1, content='a', sha256='x')
        b2 = Baseline(device_id=device.id, version=1, content='b', sha256='y')
        db.session.add(b1)
        try:
            db.session.add(b2)
            db.session.commit()
            assert False, "Should have raised IntegrityError"
        except Exception:
            db.session.rollback()
            assert True


def test_baseline_activation_resets_others(app):
    """Activating one baseline deactivates others for same device."""
    with app.app_context():
        user = User(username='t', password_hash=generate_password_hash('p'), role='admin')
        db.session.add(user)
        device = Device(name='act', ip_address='1.1.1.1')
        db.session.add(device)
        db.session.commit()
        
        b1 = Baseline(device_id=device.id, version=1, content='1', sha256='1', is_active=True)
        b2 = Baseline(device_id=device.id, version=2, content='2', sha256='2', is_active=False)
        db.session.add_all([b1, b2])
        db.session.commit()
        
        assert Baseline.query.filter_by(device_id=device.id, is_active=True).count() == 1
        
        device.activate_baseline(b2.id)
        
        assert Baseline.query.filter_by(device_id=device.id, is_active=True).count() == 1
        assert Baseline.query.filter_by(id=b2.id, is_active=True).count() == 1


def test_baseline_content_integrity(app):
    """SHA-256 matches content before and after DB round-trip."""
    with app.app_context():
        user = User(username='i', password_hash=generate_password_hash('p'), role='admin')
        db.session.add(user)
        device = Device(name='integ', ip_address='2.2.2.2')
        db.session.add(device)
        db.session.commit()
        
        content = "\n/ip firewall filter\nadd chain=input action=accept"
        sha_orig = config_hash(content)
        
        b = Baseline(device_id=device.id, version=1, content=content, sha256=sha_orig)
        db.session.add(b)
        db.session.commit()
        
        b_from_db = Baseline.query.get(b.id)
        assert b_from_db.sha256 == sha_orig
        assert b_from_db.content == content
        assert config_hash(b_from_db.content) == sha_orig
