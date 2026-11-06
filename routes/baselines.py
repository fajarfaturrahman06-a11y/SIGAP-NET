from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, abort, Response, g)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db import db, Device, Baseline
from security import sanitize_filename
from authz import login_required, roles_required
from csrf import csrf_protect
from services import audit
from services.integrity import config_hash
from routes.helpers import parse_uploaded_config, paginate_query

baselines_bp = Blueprint('baselines', __name__)


@baselines_bp.route('/baselines')
@login_required
def index():
    device_id = request.args.get('device', type=int)
    query = Baseline.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    query = query.order_by(Baseline.created_at.desc())
    pagination = paginate_query(query, per_page=20)
    devices = Device.query.order_by(Device.name).all()
    return render_template('baselines.html', pagination=pagination,
                           baselines=pagination.items, devices=devices,
                           device_id=device_id)


@baselines_bp.route('/devices/<int:device_id>/baselines/new', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
@csrf_protect
def new_for_device(device_id):
    device = db.session.execute(
        select(Device).where(Device.id == device_id).with_for_update()
    ).scalar_one_or_none() or abort(404)
    if request.method == 'POST':
        label = (request.form.get('label') or '').strip()[:160]
        notes = (request.form.get('notes') or '').strip()[:2000]
        try:
            content = parse_uploaded_config(request.files.get('config_file'),
                                            request.form.get('config_text'))
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('baseline_form.html', device=device)
        if not label:
            label = f'Baseline {device.name}'
        versions = db.session.execute(
            select(Baseline).where(Baseline.device_id == device.id)
            .with_for_update().execution_options(populate_existing=True)
        ).scalars().all()
        next_version = max((b.version for b in versions), default=0) + 1
        Baseline.query.filter_by(device_id=device.id, is_active=True).update(
            {'is_active': False})
        baseline = Baseline(
            device_id=device.id,
            version=next_version,
            label=label,
            content=content,
            sha256=config_hash(content),
            is_active=True,
            created_by=(g.user.username if getattr(g, 'user', None) else 'system'),
            notes=notes,
        )
        db.session.add(baseline)
        db.session.flush()
        audit.record('BASELINE_CREATED', 'Baseline', baseline.id, device.name,
                     detail={'version': baseline.version, 'sha256': baseline.sha256,
                             'label': label})
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('Baseline lain baru saja dibuat. Silakan muat ulang dan coba lagi.',
                  'error')
            return redirect(url_for('devices.detail', device_id=device.id))
        flash(f'Baseline {baseline.version_label} dibuat (SHA-256 {baseline.short_hash}…).',
              'success')
        return redirect(url_for('baselines.detail', baseline_id=baseline.id))
    return render_template('baseline_form.html', device=device)


@baselines_bp.route('/baselines/<int:baseline_id>')
@login_required
def detail(baseline_id):
    baseline = db.session.get(Baseline, baseline_id) or abort(404)
    return render_template('baseline_detail.html', baseline=baseline)


@baselines_bp.route('/baselines/<int:baseline_id>/activate', methods=['POST'])
@login_required
@roles_required('admin')
@csrf_protect
def activate(baseline_id):
    baseline = db.session.get(Baseline, baseline_id) or abort(404)
    device = db.session.execute(
        select(Device).where(Device.id == baseline.device_id).with_for_update()
    ).scalar_one_or_none() or abort(404)
    Baseline.query.filter_by(device_id=baseline.device_id).update({'is_active': False})
    baseline.is_active = True
    audit.record('BASELINE_ACTIVATED', 'Baseline', baseline.id, device.name,
                 detail={'version': baseline.version, 'sha256': baseline.sha256})
    db.session.commit()
    flash(f'Baseline {baseline.version_label} diaktifkan.', 'success')
    return redirect(url_for('baselines.detail', baseline_id=baseline.id))


@baselines_bp.route('/baselines/<int:baseline_id>/download')
@login_required
def download(baseline_id):
    baseline = db.session.get(Baseline, baseline_id) or abort(404)
    filename = sanitize_filename(
        f'{baseline.device.name}-baseline-v{baseline.version}.rsc')
    return Response(baseline.content, mimetype='text/plain', headers={
        'Content-Disposition': f'attachment; filename={filename}'
    })
