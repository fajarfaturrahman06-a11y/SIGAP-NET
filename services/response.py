"""Controlled response: explicit request, approval, execution, rollback.

Restoration is only applied to simulation devices. Pushing configuration to a
real router is not implemented, so real devices are always rejected even when
SIGAP_ALLOW_REAL_RESTORE is set.
"""
from sqlalchemy import select

from authz import current_user
from db import (db, Baseline, Device, Incident, IncidentEvent, ResponseAction,
                utc_now)
from services.integrity import config_hash
from services.monitoring import evaluate_configuration, actor_name
from services import audit


def _lock_incident_by_id(incident_id):
    return db.session.execute(
        select(Incident).where(Incident.id == incident_id).with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def _lock_incident(incident):
    return _lock_incident_by_id(incident.id)


def _lock_action(action):
    return db.session.execute(
        select(ResponseAction).where(ResponseAction.id == action.id)
        .with_for_update().execution_options(populate_existing=True)
    ).scalar_one()


def _lock_device(device_id):
    return db.session.execute(
        select(Device).where(Device.id == device_id).with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def _lock_baseline(baseline_id):
    return db.session.execute(
        select(Baseline).where(Baseline.id == baseline_id).with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _lock_active_baseline(device_id):
    return db.session.execute(
        select(Baseline).where(Baseline.device_id == device_id,
                               Baseline.is_active.is_(True))
        .with_for_update().execution_options(populate_existing=True)
    ).scalars().first()


def _fail_action(action, incident, actor, note):
    action.status = 'FAILED'
    action.result_note = note
    _event(incident, 'RESPONSE_FAILED', actor, note=note)
    audit.record('RESPONSE_FAILED', 'ResponseAction', action.id,
                 incident.device.name, detail=note, result='FAILED',
                 actor=actor)
    db.session.commit()
    raise ValueError(note)


def _event(incident, action, actor, note='', from_status=None, to_status=None):
    db.session.add(IncidentEvent(
        incident_id=incident.id,
        action=action,
        actor=actor_name(actor),
        note=note,
        from_status=from_status,
        to_status=to_status,
    ))


def request_restore(incident, actor, reason):
    if getattr(actor, 'role', None) not in ('admin', 'operator'):
        raise ValueError('Hanya Administrator/Operator yang dapat mengajukan pemulihan.')
    reason = (reason or '').strip()[:2000]
    if not reason:
        raise ValueError('Alasan permintaan pemulihan wajib diisi.')
    incident = _lock_incident(incident)
    device = _lock_device(incident.device_id)
    baseline = _lock_active_baseline(device.id)
    if not baseline:
        raise ValueError('Tidak ada baseline aktif untuk dipulihkan.')
    if not incident.is_open:
        raise ValueError('Insiden sudah ditutup.')
    existing = db.session.execute(
        select(ResponseAction).where(
            ResponseAction.incident_id == incident.id,
            ResponseAction.status.in_(('REQUESTED', 'APPROVED')))
        .with_for_update()
    ).scalars().all()
    if existing:
        raise ValueError('Sudah ada permintaan pemulihan yang menunggu persetujuan.')
    action = ResponseAction(
        incident_id=incident.id,
        device_id=incident.device_id,
        action_type='RESTORE_BASELINE',
        status='REQUESTED',
        baseline_id=baseline.id,
        baseline_sha256=baseline.sha256,
        reason=reason,
        requested_by=actor_name(actor),
    )
    db.session.add(action)
    db.session.flush()
    _event(incident, 'RESPONSE_REQUESTED', actor,
           note=f'Permintaan pemulihan baseline: {reason}')
    audit.record('RESPONSE_REQUESTED', 'ResponseAction', action.id,
                 device.name,
                 detail={'incident': incident.code, 'reason': reason,
                         'baseline_id': baseline.id,
                         'baseline_sha256': baseline.sha256},
                 actor=actor)
    db.session.commit()
    return action


def approve_action(action, actor, approve=True, note=''):
    actor = actor or current_user()
    if getattr(actor, 'role', None) != 'admin':
        raise ValueError('Hanya Administrator yang dapat menyetujui pemulihan.')

    incident = _lock_incident_by_id(action.incident_id)
    action = _lock_action(action)
    if action.incident_id != incident.id:
        raise ValueError('Permintaan pemulihan tidak sesuai dengan insiden.')
    if action.status != 'REQUESTED':
        raise ValueError('Permintaan ini sudah diproses.')

    if approve and not incident.is_open:
        raise ValueError('Insiden sudah ditutup; permintaan tidak dapat disetujui.')

    note = (note or '').strip()[:2000]
    self_approval = (getattr(actor, 'username', None) == action.requested_by)
    if approve and self_approval and incident.severity in ('HIGH', 'CRITICAL'):
        raise ValueError(
            'Tindakan berisiko tinggi wajib disetujui oleh Administrator lain. '
            'Self-approval tidak diizinkan.')

    action.approved_by = actor_name(actor)
    action.approved_at = utc_now()
    if not approve:
        action.status = 'REJECTED'
        action.result_note = note or 'Ditolak oleh approver.'
        _event(incident, 'RESPONSE_REJECTED', actor, note=action.result_note)
        audit.record('RESPONSE_REJECTED', 'ResponseAction', action.id,
                     incident.device.name,
                     detail={'incident': incident.code, 'note': note},
                     actor=actor)
        db.session.commit()
        return action

    action.status = 'APPROVED'
    action.result_note = ('Disetujui (self-approval untuk risiko non-tinggi).'
                          if self_approval else 'Disetujui oleh administrator.')
    _event(incident, 'RESPONSE_APPROVED', actor, note=action.result_note)
    audit.record('RESPONSE_APPROVED', 'ResponseAction', action.id,
                 incident.device.name,
                 detail={'incident': incident.code, 'self_approval': self_approval},
                 actor=actor)
    db.session.commit()
    return action


def _resolve_after_restore(incident, actor, note):
    old = incident.status
    incident.status = 'RESOLVED'
    incident.closed_at = utc_now()
    incident.resolution_notes = note
    incident.updated_at = utc_now()
    _event(incident, 'RESTORED', actor, note=note,
           from_status=old, to_status='RESOLVED')


def execute_action(action, actor):
    if getattr(actor, 'role', None) not in ('admin', 'operator'):
        raise ValueError('Hanya Administrator/Operator yang dapat mengeksekusi pemulihan.')
    incident = _lock_incident_by_id(action.incident_id)
    action = _lock_action(action)
    if action.incident_id != incident.id:
        raise ValueError('Pemulihan tidak sesuai dengan insiden.')
    if action.status != 'APPROVED':
        raise ValueError('Pemulihan hanya dapat dijalankan setelah disetujui.')
    if not incident.is_open:
        raise ValueError('Insiden sudah ditutup; pemulihan tidak dapat dijalankan.')
    device = _lock_device(incident.device_id)
    baseline = (_lock_baseline(action.baseline_id)
                if action.baseline_id else None)
    if baseline is None:
        _fail_action(action, incident, actor,
                     'Baseline yang disetujui tidak ditemukan; ajukan ulang.')
    if baseline.device_id != device.id or not baseline.is_active:
        _fail_action(action, incident, actor,
                     'Baseline yang disetujui tidak lagi aktif; ajukan ulang.')
    if action.baseline_sha256 != baseline.sha256:
        _fail_action(action, incident, actor,
                     'Baseline berubah setelah persetujuan; ajukan ulang.')
    if config_hash(baseline.content) != baseline.sha256:
        _fail_action(action, incident, actor,
                     'Integritas baseline gagal diverifikasi (SHA-256 tidak cocok).')

    if device.adapter != 'simulation':
        _fail_action(action, incident, actor,
                     'Restore perangkat nyata belum diimplementasikan dan '
                     'tetap diblokir pada prototipe ini.')

    before_content = device.lab_config or ''
    before_hash = config_hash(before_content) if before_content.strip() else None
    action.before_content = before_content if before_content.strip() else None
    action.before_sha256 = before_hash
    action.executed_at = utc_now()

    check, _ = evaluate_configuration(
        device, baseline.content, source='restore', actor=actor,
        baseline=baseline, create_incident=False, commit=False)

    action.status = 'EXECUTED'
    action.after_content = baseline.content
    action.after_sha256 = check.sha256
    action.result_note = (f'Baseline {baseline.version_label} dipulihkan. '
                          f'Verifikasi ulang: {check.status}.')
    _resolve_after_restore(incident, actor, action.result_note)
    audit.record('RESPONSE_EXECUTED', 'ResponseAction', action.id, device.name,
                 detail={'incident': incident.code, 'check_id': check.id,
                         'before_sha256': before_hash,
                         'after_sha256': check.sha256,
                         'verified_status': check.status},
                 actor=actor)
    db.session.commit()
    return action, check


def rollback_action(action, actor):
    if getattr(actor, 'role', None) != 'admin':
        raise ValueError('Hanya Administrator yang dapat membatalkan pemulihan.')
    incident = _lock_incident_by_id(action.incident_id)
    action = _lock_action(action)
    if action.incident_id != incident.id:
        raise ValueError('Pemulihan tidak sesuai dengan insiden.')
    if action.status != 'EXECUTED':
        raise ValueError('Hanya pemulihan yang sudah dieksekusi yang dapat dibatalkan.')
    if not (action.before_content or '').strip():
        raise ValueError('Konten sebelum pemulihan tidak tersedia.')

    device = _lock_device(incident.device_id)
    baseline = _lock_active_baseline(device.id)
    current_content = device.lab_config or ''
    if action.after_sha256 and config_hash(current_content) != action.after_sha256:
        raise ValueError(
            'Konfigurasi perangkat telah berubah setelah pemulihan; rollback '
            'dibatalkan agar perubahan terbaru tidak tertimpa.')
    check, _ = evaluate_configuration(
        device, action.before_content, source='rollback', actor=actor,
        baseline=baseline, create_incident=False, commit=False)

    action.status = 'ROLLED_BACK'
    action.result_note = (action.result_note or '') + '\nRollback dijalankan. ' \
        f'Verifikasi: {check.status}.'
    old = incident.status
    incident.status = 'INVESTIGATING'
    incident.closed_at = None
    incident.updated_at = utc_now()
    _event(incident, 'ROLLBACK_EXECUTED', actor,
           note='Pemulihan dibatalkan; konfigurasi sebelum restore dikembalikan.',
           from_status=old, to_status='INVESTIGATING')
    audit.record('RESPONSE_ROLLED_BACK', 'ResponseAction', action.id, device.name,
                 detail={'incident': incident.code, 'check_id': check.id,
                         'restored_sha256': check.sha256},
                 actor=actor)
    db.session.commit()
    return action, check
