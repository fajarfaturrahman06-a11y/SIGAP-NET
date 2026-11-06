from datetime import datetime, timezone

from flask import Blueprint, render_template, request

from db import AuditLog
from authz import login_required, roles_required
from routes.helpers import paginate_query

audit_bp = Blueprint('audit_trail', __name__)


def _utc_boundary(value, end_of_day=False):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed.astimezone(timezone.utc)


@audit_bp.route('/audit')
@login_required
@roles_required('admin', 'auditor')
def index():
    q = (request.args.get('q') or '').strip()
    action = (request.args.get('action') or '').strip()
    username = (request.args.get('username') or '').strip()
    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()

    query = AuditLog.query
    if q:
        like = f'%{q}%'
        query = query.filter(AuditLog.detail.ilike(like)
                             | AuditLog.device_name.ilike(like)
                             | AuditLog.object_type.ilike(like))
    if action:
        query = query.filter(AuditLog.action.ilike(f'%{action}%'))
    if username:
        query = query.filter(AuditLog.username.ilike(f'%{username}%'))
    if date_from:
        try:
            start = _utc_boundary(date_from)
            query = query.filter(AuditLog.created_at >= start)
        except ValueError:
            pass
    if date_to:
        try:
            end = _utc_boundary(date_to, end_of_day=True)
            query = query.filter(AuditLog.created_at <= end)
        except ValueError:
            pass

    query = query.order_by(AuditLog.created_at.desc())
    pagination = paginate_query(query, per_page=50)
    actions = [row[0] for row in (query.with_entities(AuditLog.action)
                                  .distinct().order_by(AuditLog.action).all())]
    return render_template('audit.html', pagination=pagination,
                           logs=pagination.items, actions=actions,
                           q=q, action=action, username=username,
                           date_from=date_from, date_to=date_to)
