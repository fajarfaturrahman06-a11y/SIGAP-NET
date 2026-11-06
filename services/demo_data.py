"""Lab baseline and demo device used by the simulation mode and seeds."""
from db import db, Device, Baseline
from services.integrity import config_hash

BASE_CONFIG = """# SIGAP-NET LAB BASELINE - EDGE-RTR-01
# Generated for the defensive security demonstration. No real credentials.

/system identity
set name=EDGE-RTR-01

/system note
set note=Core edge router - baseline v1

/ip service
set telnet disabled=yes
set ftp disabled=yes
set www disabled=yes
set ssh disabled=yes port=22

/ip firewall filter
set enabled=enabled
set input-policy=drop
set forward-policy=drop

/ip dns
set servers=192.168.1.1
set allow-remote-requests=disabled

/ip route
set gateway=192.168.1.254

/system logging
set remote=disabled
"""

DEMO_DEVICE = {
    'name': 'EDGE-RTR-01',
    'ip_address': '10.10.10.1',
    'device_type': 'router',
    'location': 'Lab NOC - Gedung A',
    'vendor': 'MikroTik',
    'model': 'RB4011iGS+',
    'description': 'Perangkat simulasi untuk demonstrasi SIGAP-NET.',
    'status': 'ONLINE',
    'monitoring_enabled': True,
    'adapter': 'simulation',
    'is_demo': True,
}


def ensure_demo_device():
    device = Device.query.filter_by(is_demo=True).order_by(Device.id).first()
    if device is None:
        device = Device.query.filter_by(name=DEMO_DEVICE['name']).first()
    if device is None:
        device = Device(**DEMO_DEVICE)
        device.lab_config = BASE_CONFIG
        db.session.add(device)
        db.session.commit()
    return device


def ensure_demo_baseline(actor='system'):
    device = ensure_demo_device()
    baseline = Baseline.query.filter_by(device_id=device.id, is_active=True).first()
    if baseline is None:
        baseline = Baseline(
            device_id=device.id,
            version=1,
            label='Baseline lab v1',
            content=BASE_CONFIG,
            sha256=config_hash(BASE_CONFIG),
            is_active=True,
            created_by=actor,
            notes='Baseline awal perangkat simulasi.',
        )
        db.session.add(baseline)
        if not device.lab_config:
            device.lab_config = BASE_CONFIG
        db.session.commit()
    return device, baseline
