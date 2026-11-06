"""Shared request helpers for SIGAP-NET blueprints."""
from flask import request, abort

from security import validate_hostname
from db import db, Router, Device, utc_now

DEVICE_TYPES = ('router', 'switch', 'firewall', 'server', 'access-point', 'other')
DEVICE_ADAPTERS = ('simulation', 'mikrotik')


def form_value(name, default=''):
    return (request.form.get(name) or default).strip()


def parse_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_device_form(existing=None):
    data = {
        'name': form_value('name'),
        'ip_address': form_value('ip_address'),
        'device_type': form_value('device_type', 'router'),
        'location': form_value('location'),
        'vendor': form_value('vendor'),
        'model': form_value('model'),
        'description': form_value('description'),
        'adapter': form_value('adapter', 'simulation'),
        'monitoring_enabled': bool(request.form.get('monitoring_enabled')),
        'router_id': parse_int(request.form.get('router_id')),
    }
    errors = []
    if not data['name'] or len(data['name']) > 100:
        errors.append('Nama perangkat wajib diisi (maksimal 100 karakter).')
    if not data['ip_address'] or not validate_hostname(data['ip_address']):
        errors.append('IP address / hostname tidak valid.')
    if data['device_type'] not in DEVICE_TYPES:
        errors.append('Jenis perangkat tidak valid.')
    if data['adapter'] not in DEVICE_ADAPTERS:
        errors.append('Adapter perangkat tidak valid.')
    if len(data['location']) > 120:
        errors.append('Lokasi maksimal 120 karakter.')
    if len(data['vendor']) > 80 or len(data['model']) > 80:
        errors.append('Vendor/model maksimal 80 karakter.')
    if len(data['description']) > 2000:
        errors.append('Deskripsi maksimal 2000 karakter.')

    duplicate = Device.query.filter_by(name=data['name']).first()
    if duplicate and (existing is None or duplicate.id != existing.id):
        errors.append('Nama perangkat sudah digunakan.')

    if data['adapter'] == 'mikrotik':
        if not data['router_id']:
            errors.append('Adapter MikroTik membutuhkan tautan ke data Router.')
        elif not db.session.get(Router, data['router_id']):
            errors.append('Router yang ditautkan tidak ditemukan.')
        else:
            linked = Device.query.filter_by(router_id=data['router_id']).first()
            if linked and (existing is None or linked.id != existing.id):
                errors.append('Router tersebut sudah ditautkan ke perangkat lain.')
    if data['monitoring_enabled'] is False and existing is None:
        data['monitoring_enabled'] = True

    return data, errors


def device_form_choices():
    return {
        'device_types': DEVICE_TYPES,
        'adapters': DEVICE_ADAPTERS,
        'routers': Router.query.order_by(Router.name).all(),
    }


def get_baseline_or_404(baseline_id):
    from db import Baseline
    baseline = db.session.get(Baseline, baseline_id)
    if baseline is None:
        abort(404)
    return baseline


def parse_uploaded_config(file_storage, text_value):
    content = (text_value or '').strip()
    if file_storage and getattr(file_storage, 'filename', ''):
        raw = file_storage.read()
        if raw:
            try:
                content = raw.decode('utf-8')
            except UnicodeDecodeError:
                raise ValueError('File harus berupa teks UTF-8 (mis. .rsc).')
    if not content:
        raise ValueError('Konten konfigurasi kosong.')
    if len(content) > 1_000_000:
        raise ValueError('Konfigurasi terlalu besar (maks 1 MB).')
    return content


def paginate_query(query, per_page=25):
    page = max(1, request.args.get('page', 1, type=int) or 1)
    return query.paginate(page=page, per_page=per_page, error_out=False)


def today_bounds():
    now = utc_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, now
