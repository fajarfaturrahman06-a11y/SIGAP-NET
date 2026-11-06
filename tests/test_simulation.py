import pytest

from db import (db, AuditLog, Baseline, ConfigCheck, Device, Incident, User)
from services import audit
from services.demo_data import BASE_CONFIG
from services.integrity import config_hash
from services.monitoring import evaluate_configuration
from services import response as response_service
from services.simulation import SCENARIO_ORDER, reset_demo, run_scenario


def test_three_scenarios(app):
    with app.app_context():
        expected = {
            'normal': ('LOW', 'DESCRIPTION_CHANGED'),
            'firewall': ('HIGH', 'FIREWALL_DISABLED'),
            'ssh': ('HIGH', 'SERVICE_SSH_ENABLED'),
        }
        for key in SCENARIO_ORDER:
            result = run_scenario(key)
            check = result['check']
            incident = result['incident']
            risk, rule = expected[key]
            assert check.highest_risk == risk, key
            assert check.change_count == 1, key
            assert check.changes[0].rule_id == rule, key
            if key == 'normal':
                assert incident is None
                assert (check.changes[0].new_value
                        == 'Core edge router - maintenance window NOC 2026-11-03')
            else:
                assert incident is not None
                assert incident.severity == 'HIGH'
                assert incident.code.startswith('INC-')


def test_incident_creation_and_audit_are_persisted(app):
    with app.app_context():
        result = run_scenario('firewall')
        incident = result['incident']
        assert Incident.query.count() == 1
        actions = {log.action for log in AuditLog.query.all()}
        assert 'CONFIG_CHECK' in actions
        assert 'INCIDENT_CREATED' in actions
        assert 'SIMULATION_RUN' in actions
        assert incident.check_id == result['check'].id


def test_reset_demo_is_repeatable(app):
    with app.app_context():
        run_scenario('firewall')
        run_scenario('ssh')
        reset_demo()
        assert ConfigCheck.query.count() == 0
        assert Incident.query.count() == 0
        assert Baseline.query.count() == 1
        assert AuditLog.query.filter_by(action='SIMULATION_RESET').count() == 1
        result = run_scenario('normal')
        assert result['check'].highest_risk == 'LOW'


def test_audit_record_does_not_commit(app):
    with app.app_context():
        audit.record('TRANSACTION_TEST', 'Test', 1)
        db.session.rollback()
        assert AuditLog.query.filter_by(action='TRANSACTION_TEST').count() == 0


def test_audit_log_is_immutable(app):
    with app.app_context():
        audit.record('IMMUTABLE_TEST', 'Test', 1)
        db.session.commit()
        log = AuditLog.query.filter_by(action='IMMUTABLE_TEST').one()
        log.detail = 'tampered'
        with pytest.raises(ValueError):
            db.session.commit()
        db.session.rollback()


def test_simulation_restore_and_rollback(app):
    with app.app_context():
        admin = User.query.filter_by(username='admin').one()
        admin2 = User.query.filter_by(username='admin2').one()
        result = run_scenario('firewall')
        incident = result['incident']
        device = incident.device
        baseline = device.active_baseline
        pre_restore_config = device.lab_config

        action = response_service.request_restore(incident, admin, 'pulihkan demo')
        response_service.approve_action(action, admin2, approve=True)
        executed, check = response_service.execute_action(action, admin)
        db.session.refresh(executed)
        db.session.refresh(incident)
        assert executed.status == 'EXECUTED'
        assert check.status == 'OK'
        assert incident.status == 'RESOLVED'
        assert device.lab_config == baseline.content

        response_service.rollback_action(executed, admin)
        db.session.refresh(executed)
        db.session.refresh(incident)
        assert executed.status == 'ROLLED_BACK'
        assert incident.status == 'INVESTIGATING'
        assert device.lab_config == pre_restore_config
        actions = {log.action for log in AuditLog.query.all()}
        assert {'RESPONSE_EXECUTED', 'RESPONSE_ROLLED_BACK'} <= actions


def test_real_device_restore_is_blocked(app):
    with app.app_context():
        admin = User.query.filter_by(username='admin').one()
        admin2 = User.query.filter_by(username='admin2').one()
        device = Device(name='REAL-RTR-01', ip_address='10.0.0.1',
                        adapter='mikrotik', device_type='router',
                        lab_config=BASE_CONFIG)
        db.session.add(device)
        db.session.flush()
        baseline = Baseline(device_id=device.id, version=1,
                            label='REAL baseline', content=BASE_CONFIG,
                            sha256=config_hash(BASE_CONFIG), is_active=True,
                            created_by='test')
        db.session.add(baseline)
        db.session.commit()

        current = BASE_CONFIG.replace('set enabled=enabled', 'set enabled=disabled')
        check, incident = evaluate_configuration(
            device, current, source='test', actor=admin,
            baseline=baseline, create_incident=True)
        assert check.highest_risk == 'HIGH'
        assert incident is not None

        action = response_service.request_restore(incident, admin, 'uji keamanan')
        with pytest.raises(ValueError, match='Administrator lain'):
            response_service.approve_action(action, admin, approve=True)
        response_service.approve_action(action, admin2, approve=True)
        app.config['ALLOW_REAL_RESTORE'] = True
        try:
            with pytest.raises(ValueError, match='belum diimplementasikan'):
                response_service.execute_action(action, admin)
        finally:
            app.config['ALLOW_REAL_RESTORE'] = False
        db.session.refresh(action)
        assert action.status == 'FAILED'
        assert AuditLog.query.filter_by(action='RESPONSE_FAILED').count() == 1
        assert Device.query.filter_by(name='REAL-RTR-01').one().lab_config != BASE_CONFIG
