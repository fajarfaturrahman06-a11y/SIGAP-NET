from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, abort, Response)
from sqlalchemy.exc import IntegrityError

from db import (db, Device, ConfigCheck, Incident, INCIDENT_OPEN_STATUSES,
                utc_now)
from security import sanitize_filename
from authz import login_required, roles_required, current_user
from csrf import csrf_protect
from services import audit
from services.adapters import get_adapter, AdapterError
from services.monitoring import evaluate_configuration
from services.demo_data import BASE_CONFIG
from routes.helpers import (parse_device_form, device_form_choices)

devices_bp = Blueprint('devices', __name__)


@devices_bp.route('/devices')
@login_required
def index():
    q = (request.args.get('q') or '').strip()
    status = request.args.get('status') or ''
    query = Device.query
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Device.name.ilike(like),
                                    Device.ip_address.ilike(like),
                                    Device.location.ilike(like)))
    if status:
        query = query.filter_by(status=status)
    devices = query.order_by(Device.name).all()

    stats = {
        'total': Device.query.count(),
        'monitored': Device.query.filter_by(monitoring_enabled=True).count(),
        'online': Device.query.filter_by(status='ONLINE').count(),
        'drift': sum(1 for d in devices if d.integrity_state == 'DRIFT'),
    }
    return render_template('devices.html', devices=devices, stats=stats,
                           q=q, status=status)


@devices_bp.route('/devices/new', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
@csrf_protect
def new():
    if request.method == 'POST':
        data, errors = parse_device_form()
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('device_form.html', device=data,
                                   is_edit=False, **device_form_choices())
        device = Device(**data)
        device.lab_config = (request.form.get('lab_config') or BASE_CONFIG).strip()
        db.session.add(device)
        try:
            db.session.flush()
            audit.record('DEVICE_CREATED', 'Device', device.id, device.name,
                         detail={'ip': device.ip_address, 'adapter': device.adapter})
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('Nama perangkat sudah digunakan. Muat ulang dan coba lagi.', 'error')
            return render_template('device_form.html', device=data,
                                   is_edit=False, **device_form_choices())
        flash(f'Perangkat "{device.name}" berhasil ditambahkan.', 'success')
        return redirect(url_for('devices.detail', device_id=device.id))
    return render_template('device_form.html', device=None, is_edit=False,
                           **device_form_choices())


@devices_bp.route('/devices/<int:device_id>')
@login_required
def detail(device_id):
    device = db.session.get(Device, device_id) or abort(404)
    checks = (ConfigCheck.query.filter_by(device_id=device.id)
              .order_by(ConfigCheck.created_at.desc()).limit(10).all())
    incidents = (Incident.query.filter_by(device_id=device.id)
                 .order_by(Incident.detected_at.desc()).limit(10).all())
    open_count = Incident.query.filter(
        Incident.device_id == device.id,
        Incident.status.in_(INCIDENT_OPEN_STATUSES)).count()
    return render_template('device_detail.html', device=device, checks=checks,
                           incidents=incidents, open_count=open_count)


@devices_bp.route('/devices/<int:device_id>/edit', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
@csrf_protect
def edit(device_id):
    device = db.session.get(Device, device_id) or abort(404)
    if request.method == 'POST':
        data, errors = parse_device_form(existing=device)
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('device_form.html', device=data, is_edit=True,
                                   device_id=device.id, **device_form_choices())
        for key, value in data.items():
            setattr(device, key, value)
        if request.form.get('lab_config') is not None:
            device.lab_config = (request.form.get('lab_config') or '').strip() or None
        device.updated_at = utc_now()
        audit.record('DEVICE_UPDATED', 'Device', device.id, device.name,
                     detail={'ip': device.ip_address, 'adapter': device.adapter})
        db.session.commit()
        flash('Perubahan perangkat disimpan.', 'success')
        return redirect(url_for('devices.detail', device_id=device.id))
    return render_template('device_form.html', device=device, is_edit=True,
                           device_id=device.id, **device_form_choices())


@devices_bp.route('/devices/<int:device_id>/delete', methods=['POST'])
@login_required
@roles_required('admin')
@csrf_protect
def delete(device_id):
    device = db.session.get(Device, device_id) or abort(404)
    name = device.name
    if (request.form.get('confirm_name') or '').strip() != name:
        flash('Konfirmasi nama perangkat tidak cocok. Penghapusan dibatalkan.', 'error')
        return redirect(url_for('devices.detail', device_id=device.id))
    audit.record('DEVICE_DELETED', 'Device', device.id, device.name,
                 detail={'ip': device.ip_address, 'baselines': len(device.baselines),
                         'checks': len(device.checks), 'incidents': len(device.incidents)})
    db.session.delete(device)
    db.session.commit()
    flash(f'Perangkat "{name}" dan seluruh data terkait telah dihapus.', 'success')
    return redirect(url_for('devices.index'))


@devices_bp.route('/devices/<int:device_id>/check', methods=['POST'])
@login_required
@roles_required('admin', 'operator')
@csrf_protect
def check(device_id):
    device = db.session.get(Device, device_id) or abort(404)
    if not device.active_baseline:
        flash('Perangkat belum memiliki baseline aktif. Buat baseline terlebih dahulu.',
              'error')
        return redirect(url_for('baselines.new_for_device', device_id=device.id))
    try:
        content = get_adapter(device).collect_config(device)
        check_row, incident = evaluate_configuration(
            device, content, source=f'adapter:{device.adapter}',
            actor=current_user(), create_incident=True)
        if incident:
            reused = getattr(incident, 'was_reused', False)
            flash(f'Perubahan berisiko {check_row.highest_risk} terdeteksi. '
                  f'Insiden {incident.code} '
                  f'{"diperbarui (drift berulang)." if reused else "dibuat."}',
                  'warning')
        elif check_row.status == 'OK':
            flash('Integritas konfigurasi sesuai baseline (SHA-256 cocok).', 'success')
        else:
            flash(f'{check_row.change_count} perubahan terdeteksi '
                  f'(risiko {check_row.highest_risk}).', 'info')
        return redirect(url_for('checks.detail', check_id=check_row.id))
    except (AdapterError, ValueError) as exc:
        flash(f'Gagal memeriksa konfigurasi: {exc}', 'error')
        return redirect(url_for('devices.detail', device_id=device.id))


@devices_bp.route('/devices/<int:device_id>/status', methods=['POST'])
@login_required
@roles_required('admin', 'operator')
@csrf_protect
def refresh_status(device_id):
    device = db.session.get(Device, device_id) or abort(404)
    try:
        device.status = get_adapter(device).check_status(device)
        device.last_checked_at = utc_now()
        audit.record('DEVICE_STATUS_CHECK', 'Device', device.id, device.name,
                     detail={'status': device.status})
        db.session.commit()
        flash(f'Status perangkat: {device.status}.', 'success')
    except AdapterError as exc:
        flash(f'Gagal memeriksa status: {exc}', 'error')
    return redirect(url_for('devices.detail', device_id=device.id))


@devices_bp.route('/devices/<int:device_id>/toggle-monitoring', methods=['POST'])
@login_required
@roles_required('admin', 'operator')
@csrf_protect
def toggle_monitoring(device_id):
    device = db.session.get(Device, device_id) or abort(404)
    device.monitoring_enabled = not device.monitoring_enabled
    audit.record('DEVICE_MONITORING', 'Device', device.id, device.name,
                 detail={'monitoring_enabled': device.monitoring_enabled})
    db.session.commit()
    flash('Pemantauan ' + ('diaktifkan' if device.monitoring_enabled else 'dinonaktifkan') + '.',
          'success')
    return redirect(url_for('devices.detail', device_id=device.id))


@devices_bp.route('/devices/<int:device_id>/config')
@login_required
def download_config(device_id):
    device = db.session.get(Device, device_id) or abort(404)
    content = device.lab_config or ''
    filename = sanitize_filename(f'{device.name}-current.rsc')
    return Response(content, mimetype='text/plain', headers={
        'Content-Disposition': f'attachment; filename={filename}'
    })
