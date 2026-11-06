from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, abort)

from db import db, Device, Incident, ResponseAction, INCIDENT_STATUSES, RISK_LEVELS
from authz import login_required, roles_required, current_user
from csrf import csrf_protect
from services import response as response_service
from services import monitoring
from routes.helpers import paginate_query

incidents_bp = Blueprint('incidents', __name__)


@incidents_bp.route('/incidents')
@login_required
def index():
    status = request.args.get('status') or ''
    severity = request.args.get('severity') or ''
    device_id = request.args.get('device', type=int)
    query = Incident.query
    if status in INCIDENT_STATUSES:
        query = query.filter_by(status=status)
    if severity in RISK_LEVELS:
        query = query.filter_by(severity=severity)
    if device_id:
        query = query.filter_by(device_id=device_id)
    query = query.order_by(Incident.detected_at.desc())
    pagination = paginate_query(query, per_page=20)
    devices = Device.query.order_by(Device.name).all()
    counts = {s: Incident.query.filter_by(status=s).count()
              for s in INCIDENT_STATUSES}
    return render_template('incidents.html', pagination=pagination,
                           incidents=pagination.items, devices=devices,
                           status=status, severity=severity, device_id=device_id,
                           counts=counts, statuses=INCIDENT_STATUSES)


@incidents_bp.route('/incidents/<int:incident_id>')
@login_required
def detail(incident_id):
    incident = db.session.get(Incident, incident_id) or abort(404)
    transitions = monitoring.INCIDENT_TRANSITIONS.get(incident.status, ())
    return render_template('incident_detail.html', incident=incident,
                           transitions=transitions,
                           statuses=INCIDENT_STATUSES)


@incidents_bp.route('/incidents/<int:incident_id>/status', methods=['POST'])
@login_required
@roles_required('admin', 'operator')
@csrf_protect
def change_status(incident_id):
    incident = db.session.get(Incident, incident_id) or abort(404)
    new_status = (request.form.get('status') or '').strip()
    note = (request.form.get('note') or '').strip()
    try:
        monitoring.update_incident_status(incident, new_status, note=note, actor=current_user())
        flash(f'Status insiden diubah menjadi {new_status}.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('incidents.detail', incident_id=incident.id))


@incidents_bp.route('/incidents/<int:incident_id>/note', methods=['POST'])
@login_required
@roles_required('admin', 'operator')
@csrf_protect
def add_note(incident_id):
    incident = db.session.get(Incident, incident_id) or abort(404)
    note = (request.form.get('note') or '').strip()
    assign = bool(request.form.get('assign'))
    try:
        monitoring.add_incident_note(incident, note, assign=assign, actor=current_user())
        flash('Catatan investigasi disimpan.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('incidents.detail', incident_id=incident.id))


@incidents_bp.route('/incidents/<int:incident_id>/response/request', methods=['POST'])
@login_required
@roles_required('admin', 'operator')
@csrf_protect
def request_restore(incident_id):
    incident = db.session.get(Incident, incident_id) or abort(404)
    reason = (request.form.get('reason') or '').strip()
    try:
        action = response_service.request_restore(incident, current_user(), reason)
        flash(f'Permintaan pemulihan #{action.id} dibuat dan menunggu persetujuan '
              f'Administrator.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('incidents.detail', incident_id=incident.id))


@incidents_bp.route('/incidents/<int:incident_id>/response/<int:action_id>/approve',
                    methods=['POST'])
@login_required
@roles_required('admin')
@csrf_protect
def approve(incident_id, action_id):
    incident = db.session.get(Incident, incident_id) or abort(404)
    action = db.session.get(ResponseAction, action_id) or abort(404)
    if action.incident_id != incident.id:
        abort(404)
    decision = request.form.get('decision') == 'approve'
    note = (request.form.get('note') or '').strip()
    try:
        response_service.approve_action(action, current_user(), approve=decision,
                                        note=note)
        flash('Permintaan disetujui.' if decision else 'Permintaan ditolak.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('incidents.detail', incident_id=incident.id))


@incidents_bp.route('/incidents/<int:incident_id>/response/<int:action_id>/execute',
                    methods=['POST'])
@login_required
@roles_required('admin', 'operator')
@csrf_protect
def execute(incident_id, action_id):
    incident = db.session.get(Incident, incident_id) or abort(404)
    action = db.session.get(ResponseAction, action_id) or abort(404)
    if action.incident_id != incident.id:
        abort(404)
    try:
        response_service.execute_action(action, current_user())
        flash('Pemulihan dieksekusi dan diverifikasi terhadap baseline.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('incidents.detail', incident_id=incident.id))


@incidents_bp.route('/incidents/<int:incident_id>/response/<int:action_id>/rollback',
                    methods=['POST'])
@login_required
@roles_required('admin')
@csrf_protect
def rollback(incident_id, action_id):
    incident = db.session.get(Incident, incident_id) or abort(404)
    action = db.session.get(ResponseAction, action_id) or abort(404)
    if action.incident_id != incident.id:
        abort(404)
    try:
        response_service.rollback_action(action, current_user())
        flash('Rollback dijalankan; konfigurasi sebelum pemulihan dikembalikan.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('incidents.detail', incident_id=incident.id))
