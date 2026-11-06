"""Simulation mode: runs the full pipeline against lab configs.

Each scenario stores a real snapshot, computes SHA-256, diffs against the
baseline, assesses risk, and creates an incident when required.
"""
from db import db, Baseline, ConfigCheck, Incident
from services.demo_data import BASE_CONFIG, ensure_demo_device, ensure_demo_baseline
from services.integrity import config_hash
from services.monitoring import evaluate_configuration
from services import audit


def _replace(text, old, new):
    if old not in text:
        return text.rstrip() + '\n' + new + '\n'
    return text.replace(old, new, 1)


def _scenario_normal(config):
    return _replace(
        config,
        'set note=Core edge router - baseline v1',
        'set note=Core edge router - maintenance window NOC 2026-11-03',
    )


def _scenario_firewall(config):
    return _replace(config, 'set enabled=enabled', 'set enabled=disabled')


def _scenario_ssh(config):
    return _replace(
        config,
        'set ssh disabled=yes port=22',
        'set ssh disabled=no port=22',
    )


SCENARIOS = {
    'normal': {
        'key': 'normal',
        'title': 'Skenario 1 — Perubahan Normal',
        'summary': 'Deskripsi/catatan perangkat diperbarui. Sistem harus mendeteksi '
                   'perubahan administratif dengan risiko LOW.',
        'expected': 'LOW',
        'mutate': _scenario_normal,
    },
    'firewall': {
        'key': 'firewall',
        'title': 'Skenario 2 — Perubahan Mencurigakan',
        'summary': 'Firewall dinonaktifkan. Sistem harus memberi risiko HIGH dan '
                   'membuat insiden baru.',
        'expected': 'HIGH',
        'mutate': _scenario_firewall,
    },
    'ssh': {
        'key': 'ssh',
        'title': 'Skenario 3 — Perubahan Akses',
        'summary': 'SSH yang semula nonaktif diaktifkan. Sistem harus memberi risiko '
                   'HIGH, membuat insiden, lalu operator dapat memverifikasi dan '
                   'mengajukan pemulihan.',
        'expected': 'HIGH',
        'mutate': _scenario_ssh,
    },
}

SCENARIO_ORDER = ['normal', 'firewall', 'ssh']


def run_scenario(key, actor=None):
    if key not in SCENARIOS:
        raise ValueError('Skenario tidak dikenal.')
    scenario = SCENARIOS[key]
    device, baseline = ensure_demo_baseline(actor='system')

    # Always start from the active baseline so runs are deterministic.
    device.lab_config = baseline.content
    db.session.commit()

    current = scenario['mutate'](baseline.content)
    check, incident = evaluate_configuration(
        device, current, source=f'simulation:{key}', actor=actor,
        baseline=baseline, create_incident=True)

    audit.record('SIMULATION_RUN', 'Device', device.id, device.name,
                 detail={'scenario': key, 'check_id': check.id,
                         'incident': incident.code if incident else None,
                         'highest_risk': check.highest_risk},
                 actor=actor)
    db.session.commit()
    return {'scenario': scenario, 'device': device, 'check': check,
            'incident': incident}


def reset_demo(actor=None):
    device = ensure_demo_device()

    for incident in Incident.query.filter_by(device_id=device.id).all():
        db.session.delete(incident)
    for check in ConfigCheck.query.filter_by(device_id=device.id).all():
        db.session.delete(check)
    for baseline in Baseline.query.filter_by(device_id=device.id).all():
        db.session.delete(baseline)
    db.session.flush()

    device.lab_config = BASE_CONFIG
    device.status = 'ONLINE'
    device.last_checked_at = None
    baseline = Baseline(
        device_id=device.id,
        version=1,
        label='Baseline lab v1 (reset)',
        content=BASE_CONFIG,
        sha256=config_hash(BASE_CONFIG),
        is_active=True,
        created_by='system',
        notes='Baseline simulasi setelah reset data demo.',
    )
    db.session.add(baseline)
    audit.record('SIMULATION_RESET', 'Device', device.id, device.name,
                 detail='Data demo (baseline, snapshot, insiden) direset; audit trail tetap disimpan.',
                 actor=actor)
    db.session.commit()
    return device
