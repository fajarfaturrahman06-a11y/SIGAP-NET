"""Orchestration: configuration checks, change persistence, incident creation."""
import uuid

from flask import has_request_context, g
from sqlalchemy import select

from db import (db, Baseline, Device, ConfigCheck, ConfigChange, Incident,
                IncidentEvent, INCIDENT_OPEN_STATUSES, utc_now)
from services.integrity import config_hash, diff_configs
from services.risk import assess_changes
from services import audit


def actor_name(actor=None):
    if actor is not None:
        if hasattr(actor, 'username'):
            return actor.username
        return str(actor)
    if has_request_context():
        user = getattr(g, 'user', None)
        if user:
            return user.username
    return 'system'


def evaluate_configuration(device, content, source='manual', actor=None,
                           baseline=None, create_incident=True, commit=True):
    if device is None:
        raise ValueError('Perangkat tidak ditemukan.')
    if not (content or '').strip():
        raise ValueError('Konten konfigurasi kosong.')

    device = db.session.execute(
        select(Device).where(Device.id == device.id).with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if device is None:
        raise ValueError('Perangkat tidak ditemukan.')

    if baseline is None:
        baseline = db.session.execute(
            select(Baseline).where(Baseline.device_id == device.id,
                                   Baseline.is_active.is_(True))
            .with_for_update().execution_options(populate_existing=True)
        ).scalars().first()
    else:
        baseline = db.session.execute(
            select(Baseline).where(Baseline.id == baseline.id)
            .with_for_update().execution_options(populate_existing=True)
        ).scalar_one_or_none()
    if baseline is None:
        raise ValueError('Perangkat belum memiliki baseline aktif.')

    changes, _old_entries, _new_entries = diff_configs(baseline.content, content)
    assessments, highest, combined_note = assess_changes(changes)
    now = utc_now()
    checked_by = actor_name(actor)

    check = ConfigCheck(
        device_id=device.id,
        baseline_id=baseline.id,
        content=content,
        sha256=config_hash(content),
        baseline_sha256=baseline.sha256,
        status='OK' if not changes else 'CHANGED',
        highest_risk=highest,
        change_count=len(changes),
        source=source,
        checked_by=checked_by,
        created_at=now,
    )
    db.session.add(check)
    db.session.flush()

    for change, assessment in zip(changes, assessments):
        db.session.add(ConfigChange(
            check_id=check.id,
            device_id=device.id,
            change_type=change.change_type,
            section=change.section,
            param=change.param,
            old_value=change.old_value,
            new_value=change.new_value,
            risk_level=assessment['risk_level'],
            rule_id=assessment['rule_id'],
            title=assessment['title'],
            reason=assessment['reason'],
            impact=assessment['impact'],
            recommendation=assessment['recommendation'],
        ))

    device.lab_config = content
    device.last_checked_at = now
    device.status = 'ONLINE'

    details = {
        'check_id': check.id,
        'sha256': check.sha256,
        'baseline_sha256': baseline.sha256,
        'changes': len(changes),
        'highest_risk': highest,
        'source': source,
    }
    if combined_note:
        details['combined_note'] = combined_note
    audit.record('CONFIG_CHECK', 'ConfigCheck', check.id, device.name,
                 detail=details, actor=actor,
                 result='CHANGED' if changes else 'OK')

    incident = None
    if create_incident and highest in ('HIGH', 'CRITICAL'):
        incident = create_incident_for_check(
            check, actor=actor, combined_note=combined_note)
    # Callers such as the response workflow need to commit the configuration
    # snapshot and their own state change in one transaction.
    if commit:
        db.session.commit()
    return check, incident


def _next_incident_code(now):
    # Temporary unique value; replaced with the ID-based code after flush.
    return f'TMP-{uuid.uuid4().hex}'


def create_incident_for_check(check, actor=None, combined_note=None):
    device = check.device
    now = utc_now()
    created_by = actor_name(actor)

    existing = (
        db.session.query(Incident)
        .join(ConfigCheck, Incident.check_id == ConfigCheck.id)
        .filter(Incident.device_id == device.id,
                Incident.status.in_(INCIDENT_OPEN_STATUSES),
                ConfigCheck.sha256 == check.sha256,
                ConfigCheck.baseline_sha256 == check.baseline_sha256)
        .order_by(Incident.id.desc())
        .first()
    )
    if existing is not None:
        existing.updated_at = now
        db.session.add(IncidentEvent(
            incident_id=existing.id,
            action='REDETECTED',
            actor=created_by,
            note=(f'Drift yang sama terdeteksi ulang pada check #{check.id}; '
                  'insiden terbuka digunakan kembali.'),
            created_at=now,
        ))
        audit.record('INCIDENT_REDETECTED', 'Incident', existing.id, device.name,
                     detail={'code': existing.code, 'check_id': check.id,
                             'sha256': check.sha256},
                     actor=actor)
        existing.was_reused = True
        return existing

    counts = check.risk_counts
    summary = (f'{check.change_count} perubahan konfigurasi terdeteksi '
               f'(HIGH={counts.get("HIGH", 0)}, CRITICAL={counts.get("CRITICAL", 0)}, '
               f'MEDIUM={counts.get("MEDIUM", 0)}, LOW={counts.get("LOW", 0)}).')
    if combined_note:
        summary += ' ' + combined_note
    incident = Incident(
        code=_next_incident_code(now),
        device_id=device.id,
        check_id=check.id,
        title=f'{check.highest_risk} risk configuration change on {device.name}',
        description=summary,
        severity=check.highest_risk,
        status='NEW',
        created_by=created_by,
        detected_at=now,
    )
    db.session.add(incident)
    db.session.flush()
    incident.code = f'INC-{now.strftime("%Y%m%d")}-{incident.id:04d}'
    db.session.add(IncidentEvent(
        incident_id=incident.id,
        action='CREATED',
        actor=created_by,
        note='Insiden dibuat otomatis setelah analisis risiko.',
        to_status='NEW',
        created_at=now,
    ))
    audit.record('INCIDENT_CREATED', 'Incident', incident.id, device.name,
                 detail={'code': incident.code, 'severity': incident.severity,
                         'check_id': check.id},
                 actor=actor)
    return incident


INCIDENT_TRANSITIONS = {
    'NEW': ('INVESTIGATING', 'FALSE_POSITIVE'),
    'INVESTIGATING': ('VERIFIED', 'FALSE_POSITIVE', 'NEW'),
    'VERIFIED': ('RESOLVED', 'INVESTIGATING', 'FALSE_POSITIVE'),
    'RESOLVED': ('INVESTIGATING',),
    'FALSE_POSITIVE': ('INVESTIGATING',),
}


def update_incident_status(incident, new_status, actor=None, note=''):
    incident = db.session.execute(
        select(Incident).where(Incident.id == incident.id).with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    note = (note or '').strip()[:2000]
    if new_status not in INCIDENT_TRANSITIONS.get(incident.status, ()):
        raise ValueError(f'Transisi status {incident.status} → {new_status} tidak diizinkan.')
    old = incident.status
    incident.status = new_status
    incident.updated_at = utc_now()
    if new_status not in ('RESOLVED', 'FALSE_POSITIVE'):
        # Reopening a closed incident must not leave a stale close timestamp.
        incident.closed_at = None
    if new_status == 'RESOLVED':
        incident.closed_at = utc_now()
        if note:
            incident.resolution_notes = note
    if new_status == 'FALSE_POSITIVE':
        incident.closed_at = utc_now()
        if note:
            incident.resolution_notes = note
    db.session.add(IncidentEvent(
        incident_id=incident.id,
        action='STATUS_CHANGED',
        actor=actor_name(actor),
        note=note,
        from_status=old,
        to_status=new_status,
    ))
    audit.record('INCIDENT_STATUS', 'Incident', incident.id, incident.device.name,
                 detail={'from': old, 'to': new_status, 'note': note}, actor=actor)
    db.session.commit()
    return incident


def add_incident_note(incident, note, actor=None, assign=False):
    note = (note or '').strip()[:2000]
    if not note:
        raise ValueError('Catatan tidak boleh kosong.')
    incident = db.session.execute(
        select(Incident).where(Incident.id == incident.id).with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    incident.investigation_notes = (
        (incident.investigation_notes + '\n\n' if incident.investigation_notes else '')
        + f'[{actor_name(actor)}] {note}'
    )
    if assign:
        incident.assigned_to = actor_name(actor)
    incident.updated_at = utc_now()
    db.session.add(IncidentEvent(
        incident_id=incident.id,
        action='NOTE_ADDED',
        actor=actor_name(actor),
        note=note,
    ))
    audit.record('INCIDENT_NOTE', 'Incident', incident.id, incident.device.name,
                 detail=note, actor=actor)
    db.session.commit()
    return incident
