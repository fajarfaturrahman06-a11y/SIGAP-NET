"""Append-only audit trail (records cannot be edited or deleted)."""
import json

from flask import has_request_context, g
from sqlalchemy import event

from db import db, AuditLog, utc_now
from security import client_ip


def _actor_info(actor=None):
    user = None
    if actor is not None:
        if hasattr(actor, 'username'):
            user = actor
        else:
            return str(actor), None, None
    else:
        user = getattr(g, 'user', None)
    if user is not None:
        return user.username, user.id, user.role
    return 'system', None, None


def record(action, object_type='', object_id=None, device_name='',
           detail='', result='SUCCESS', actor=None):
    username, user_id, role = _actor_info(actor)
    if isinstance(detail, (dict, list)):
        detail = json.dumps(detail, ensure_ascii=False, default=str)
    ip = None
    if has_request_context():
        ip = client_ip()[:64] or None
    log = AuditLog(
        user_id=user_id,
        username=username,
        role=role,
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id is not None else None,
        device_name=(device_name or '')[:100] or None,
        detail=(detail or '')[:10000],
        result=result,
        ip_address=ip,
        created_at=utc_now(),
    )
    db.session.add(log)
    # The calling service/route owns the transaction. Audit rows are committed
    # atomically with the business change they describe.
    return log


def _block_update(mapper, connection, target):
    raise ValueError('Audit log bersifat append-only dan tidak boleh diubah.')


def _block_delete(mapper, connection, target):
    raise ValueError('Audit log bersifat append-only dan tidak boleh dihapus.')


event.listen(AuditLog, 'before_update', _block_update)
event.listen(AuditLog, 'before_delete', _block_delete)
