from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, abort, Response)

from db import (db, Device, ConfigCheck, ConfigChange, Incident, RISK_LEVELS)
from authz import login_required, roles_required, current_user
from csrf import csrf_protect
from services.monitoring import evaluate_configuration
from services.risk import RULE_CATALOG
from routes.helpers import parse_uploaded_config, paginate_query

checks_bp = Blueprint('checks', __name__)


@checks_bp.route('/checks')
@login_required
def index():
    device_id = request.args.get('device', type=int)
    status = (request.args.get('status') or '').strip()
    risk = (request.args.get('risk') or '').strip()
    query = ConfigCheck.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    if status in ('OK', 'CHANGED'):
        query = query.filter_by(status=status)
    if risk in RISK_LEVELS:
        query = query.filter_by(highest_risk=risk)
    query = query.order_by(ConfigCheck.created_at.desc())
    pagination = paginate_query(query, per_page=25)
    devices = Device.query.order_by(Device.name).all()
    return render_template('checks.html', pagination=pagination,
                           checks=pagination.items, devices=devices,
                           device_id=device_id, status=status, risk=risk)


@checks_bp.route('/checks/new', methods=['GET', 'POST'])
@login_required
@roles_required('admin', 'operator')
@csrf_protect
def new():
    devices = Device.query.order_by(Device.name).all()
    if request.method == 'POST':
        device_id = request.form.get('device_id', type=int)
        device = db.session.get(Device, device_id) if device_id else None
        mode = request.form.get('mode') or 'upload'
        if not device:
            flash('Pilih perangkat terlebih dahulu.', 'error')
            return render_template('check_form.html', devices=devices)
        if not device.active_baseline:
            flash('Perangkat belum memiliki baseline aktif.', 'error')
            return render_template('check_form.html', devices=devices)
        try:
            if mode == 'current':
                content = device.lab_config or ''
            else:
                content = parse_uploaded_config(request.files.get('config_file'),
                                                request.form.get('config_text'))
            check_row, incident = evaluate_configuration(
                device, content, source='manual-upload', actor=current_user(),
                create_incident=True)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('check_form.html', devices=devices)
        if incident:
            reused = getattr(incident, 'was_reused', False)
            flash(f'Perubahan risiko {check_row.highest_risk}. Insiden '
                  f'{incident.code} '
                  f'{"diperbarui (drift berulang)." if reused else "dibuat."}',
                  'warning')
        elif check_row.status == 'OK':
            flash('Konfigurasi identik dengan baseline (SHA-256 cocok).', 'success')
        else:
            flash(f'{check_row.change_count} perubahan, risiko '
                  f'{check_row.highest_risk}.', 'info')
        return redirect(url_for('checks.detail', check_id=check_row.id))
    return render_template('check_form.html', devices=devices)


@checks_bp.route('/checks/<int:check_id>')
@login_required
def detail(check_id):
    check_row = db.session.get(ConfigCheck, check_id) or abort(404)
    changes = sorted(check_row.changes,
                     key=lambda c: ({'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2,
                                     'LOW': 3}.get(c.risk_level, 4), c.id))
    incidents = Incident.query.filter_by(check_id=check_row.id).all()
    return render_template('check_detail.html', check=check_row,
                           changes=changes, incidents=incidents)


@checks_bp.route('/checks/<int:check_id>/download')
@login_required
def download(check_id):
    check_row = db.session.get(ConfigCheck, check_id) or abort(404)
    return Response(check_row.content, mimetype='text/plain', headers={
        'Content-Disposition': f'attachment; filename=snapshot-{check_row.id}.rsc'
    })


@checks_bp.route('/risks')
@login_required
def risks():
    distribution = {risk: ConfigChange.query.filter_by(risk_level=risk).count()
                    for risk in RISK_LEVELS}
    total = sum(distribution.values())
    high_risk = (ConfigChange.query
                 .filter(ConfigChange.risk_level.in_(('HIGH', 'CRITICAL')))
                 .order_by(ConfigChange.id.desc()).limit(50).all())
    rule_usage = {}
    for change in ConfigChange.query.all():
        rule_usage[change.rule_id] = rule_usage.get(change.rule_id, 0) + 1
    return render_template('risks.html', distribution=distribution, total=total,
                           high_risk=high_risk, rules=RULE_CATALOG,
                           rule_usage=rule_usage)
