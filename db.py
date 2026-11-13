import sqlite3
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

from sqlalchemy import DateTime, event
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.engine import Engine
from sqlalchemy.types import TypeDecorator

db = SQLAlchemy()

# MySQL TEXT is capped at 64 KiB while uploads may be up to 1 MiB, so large
# configuration payloads use MEDIUMTEXT on MySQL and TEXT on other backends.
LongText = db.Text().with_variant(MEDIUMTEXT(), 'mysql')


@event.listens_for(Engine, 'connect')
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """Match production (MySQL) FK enforcement when running on SQLite."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.close()


class UTCDateTime(TypeDecorator):
    """Store naive UTC in the database and return timezone-aware UTC values."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def utc_now():
    """Timezone-aware current UTC timestamp for all application writes."""
    return datetime.now(timezone.utc)

ROLES = ('admin', 'operator', 'auditor')
ROLE_LABELS = {
    'admin': 'Administrator',
    'operator': 'Operator',
    'auditor': 'Auditor',
}
RISK_LEVELS = ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
RISK_ORDER = {'LOW': 1, 'MEDIUM': 2, 'HIGH': 3, 'CRITICAL': 4}
INCIDENT_STATUSES = ('NEW', 'INVESTIGATING', 'VERIFIED', 'RESOLVED', 'FALSE_POSITIVE')
INCIDENT_OPEN_STATUSES = ('NEW', 'INVESTIGATING', 'VERIFIED')


# ── Legacy models (kept for the MikroTik backup features) ──────────
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(120))
    role = db.Column(db.String(20), nullable=False, default='operator',
                     server_default='operator')
    active = db.Column(db.Boolean, nullable=False, default=True,
                       server_default='1')
    session_version = db.Column(db.Integer, nullable=False, default=0,
                                server_default='0')
    created_at = db.Column(UTCDateTime, default=utc_now)
    last_login = db.Column(UTCDateTime)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_operator(self):
        return self.role == 'operator'

    @property
    def is_auditor(self):
        return self.role == 'auditor'

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)


class Router(db.Model):
    __tablename__ = 'routers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    host = db.Column(db.String(253), nullable=False)
    port = db.Column(db.Integer, nullable=False, default=22)
    username = db.Column(db.String(50), nullable=False)
    password_enc = db.Column(db.LargeBinary)
    ssh_key_enc = db.Column(db.LargeBinary)
    auth_method = db.Column(db.String(20), default='password')
    enabled = db.Column(db.Boolean, default=True)
    tags = db.Column(db.String(200))
    notes = db.Column(db.Text)
    last_seen = db.Column(UTCDateTime)
    last_status = db.Column(db.String(50))
    created_at = db.Column(UTCDateTime, default=utc_now)
    updated_at = db.Column(UTCDateTime, default=utc_now, onupdate=utc_now)

    backups = db.relationship('Backup', backref='router', cascade='all, delete-orphan')
    schedules = db.relationship('Schedule', backref='router', cascade='all, delete-orphan')

    @property
    def router_name(self):
        return self.name


class Backup(db.Model):
    __tablename__ = 'backups'
    id = db.Column(db.Integer, primary_key=True)
    router_id = db.Column(db.Integer, db.ForeignKey('routers.id', ondelete='CASCADE'), nullable=False)
    backup_type = db.Column(db.String(20), nullable=False)
    filename = db.Column(db.String(255), default='')
    file_path = db.Column(db.String(500), default='')
    file_size = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), nullable=False)
    error_message = db.Column(db.Text)
    triggered_by = db.Column(db.String(100), nullable=False)
    created_at = db.Column(UTCDateTime, default=utc_now)

    @property
    def router_name(self):
        return self.router.name if self.router else None


class Schedule(db.Model):
    __tablename__ = 'schedules'
    id = db.Column(db.Integer, primary_key=True)
    router_id = db.Column(db.Integer, db.ForeignKey('routers.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    backup_type = db.Column(db.String(20), nullable=False)
    cron_expr = db.Column(db.String(100), nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    keep_count = db.Column(db.Integer, default=10)
    last_run = db.Column(UTCDateTime)
    next_run = db.Column(UTCDateTime)
    created_at = db.Column(UTCDateTime, default=utc_now)
    updated_at = db.Column(UTCDateTime, default=utc_now, onupdate=utc_now)

    @property
    def router_name(self):
        return self.router.name if self.router else None

    @property
    def router_host(self):
        return self.router.host if self.router else None


class ActivityLog(db.Model):
    __tablename__ = 'activity_log'
    id = db.Column(db.Integer, primary_key=True)
    router_id = db.Column(db.Integer, db.ForeignKey('routers.id', ondelete='SET NULL'))
    action = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    message = db.Column(db.String(500))
    details = db.Column(db.Text)
    created_at = db.Column(UTCDateTime, default=utc_now)

    router = db.relationship('Router', backref='activity_logs')

    @property
    def router_name(self):
        return self.router.name if self.router else 'System'


def log_activity(router_id, action, status, message='', details=''):
    log = ActivityLog(
        router_id=router_id, action=action, status=status,
        message=(message or '')[:500], details=(details or '')[:10000]
    )
    db.session.add(log)
    db.session.commit()


# ── SIGAP-NET models ───────────────────────────────────────────────
class Device(db.Model):
    __tablename__ = 'devices'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    ip_address = db.Column(db.String(253), nullable=False)
    device_type = db.Column(db.String(50), nullable=False, default='router')
    location = db.Column(db.String(120))
    vendor = db.Column(db.String(80))
    model = db.Column(db.String(80))
    description = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default='UNKNOWN',
                       server_default='UNKNOWN')
    monitoring_enabled = db.Column(db.Boolean, nullable=False, default=True,
                                   server_default='1')
    adapter = db.Column(db.String(20), nullable=False, default='simulation',
                        server_default='simulation')
    lab_config = db.Column(LongText)
    is_demo = db.Column(db.Boolean, nullable=False, default=False,
                        server_default='0')
    router_id = db.Column(db.Integer, db.ForeignKey('routers.id', ondelete='SET NULL'))
    last_checked_at = db.Column(UTCDateTime)
    created_at = db.Column(UTCDateTime, default=utc_now)
    updated_at = db.Column(UTCDateTime, default=utc_now, onupdate=utc_now)

    router = db.relationship('Router', backref='sigap_devices')
    baselines = db.relationship('Baseline', backref='device', cascade='all, delete-orphan',
                                order_by='Baseline.version.desc()')
    checks = db.relationship('ConfigCheck', backref='device', cascade='all, delete-orphan',
                             order_by='ConfigCheck.created_at.desc()')
    incidents = db.relationship('Incident', backref='device', cascade='all, delete-orphan',
                                order_by='Incident.detected_at.desc()')

    @property
    def active_baseline(self):
        for b in self.baselines:
            if b.is_active:
                return b
        return None

    def activate_baseline(self, baseline_id):
        """Activate a baseline and deactivate all others for this device."""
        from db import db
        # Deactivate all baselines for this device
        Baseline.query.filter_by(device_id=self.id).update({Baseline.is_active: False})
        # Activate the specified baseline
        Baseline.query.filter_by(id=baseline_id, device_id=self.id).update({Baseline.is_active: True})
        db.session.commit()

    @property
    def integrity_state(self):
        """Return the integrity state of the device: 'INTACT', 'DRIFT', or 'UNKNOWN'."""
        # If no baseline, state is unknown
        if not self.active_baseline:
            return 'UNKNOWN'
        
        # Get the most recent config check
        latest_check = ConfigCheck.query.filter_by(device_id=self.id).order_by(
            ConfigCheck.created_at.desc()).first()
        
        if not latest_check:
            return 'UNKNOWN'
        
        # Map check status to integrity state
        if latest_check.status == 'OK':
            return 'INTACT'
        elif latest_check.status == 'DRIFT':
            return 'DRIFT'
        else:
            return 'UNKNOWN'



class Baseline(db.Model):
    __tablename__ = 'baselines'
    __table_args__ = (
        db.UniqueConstraint('device_id', 'version',
                            name='uq_baselines_device_version'),
    )
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'),
                          nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    label = db.Column(db.String(160))
    content = db.Column(LongText, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True,
                          server_default='1')
    created_by = db.Column(db.String(80), nullable=False, default='system')
    notes = db.Column(db.Text)
    created_at = db.Column(UTCDateTime, default=utc_now)

    @property
    def short_hash(self):
        return (self.sha256 or '')[:12]

    @property
    def version_label(self):
        return f'v{self.version}'

    def save(self):
        """Save baseline with automatic single-active enforcement."""
        from db import db
        if self.is_active:
            # Deactivate all other baselines for the same device
            if self.device_id:
                Baseline.query.filter(
                    Baseline.device_id == self.device_id,
                    Baseline.id != self.id
                ).update({Baseline.is_active: False})
        db.session.add(self)
        db.session.commit()


class ConfigCheck(db.Model):
    __tablename__ = 'config_checks'
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'),
                          nullable=False)
    baseline_id = db.Column(db.Integer, db.ForeignKey('baselines.id', ondelete='SET NULL'))
    content = db.Column(LongText, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    baseline_sha256 = db.Column(db.String(64))
    status = db.Column(db.String(20), nullable=False, default='OK')
    highest_risk = db.Column(db.String(20), nullable=False, default='LOW')
    change_count = db.Column(db.Integer, nullable=False, default=0)
    source = db.Column(db.String(60), nullable=False, default='manual')
    checked_by = db.Column(db.String(80), nullable=False, default='system')
    created_at = db.Column(UTCDateTime, default=utc_now)

    baseline = db.relationship('Baseline', backref='checks')
    changes = db.relationship('ConfigChange', backref='check', cascade='all, delete-orphan',
                              order_by='ConfigChange.id')
    incidents = db.relationship('Incident', backref='check')

    @property
    def short_hash(self):
        return (self.sha256 or '')[:12]

    @property
    def risk_counts(self):
        out = {r: 0 for r in RISK_LEVELS}
        for c in self.changes:
            out[c.risk_level] = out.get(c.risk_level, 0) + 1
        return out


class ConfigChange(db.Model):
    __tablename__ = 'config_changes'
    id = db.Column(db.Integer, primary_key=True)
    check_id = db.Column(db.Integer, db.ForeignKey('config_checks.id', ondelete='CASCADE'),
                         nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'),
                          nullable=False)
    change_type = db.Column(db.String(20), nullable=False)  # ADDED/REMOVED/MODIFIED
    section = db.Column(LongText, nullable=False, default='global')
    param = db.Column(LongText, nullable=False)
    old_value = db.Column(LongText)
    new_value = db.Column(LongText)
    risk_level = db.Column(db.String(20), nullable=False, default='LOW')
    rule_id = db.Column(db.String(60), nullable=False, default='DEFAULT')
    title = db.Column(db.String(200), nullable=False, default='Configuration change')
    reason = db.Column(db.Text)
    impact = db.Column(db.Text)
    recommendation = db.Column(db.Text)
    created_at = db.Column(UTCDateTime, default=utc_now)

    @property
    def qualified_name(self):
        return f'/{self.section} · {self.param}'

    @property
    def display_old(self):
        return self.old_value if self.old_value is not None else '—'

    @property
    def display_new(self):
        return self.new_value if self.new_value is not None else '—'


class Incident(db.Model):
    __tablename__ = 'incidents'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'),
                          nullable=False)
    check_id = db.Column(db.Integer, db.ForeignKey('config_checks.id', ondelete='SET NULL'))
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    severity = db.Column(db.String(20), nullable=False, default='HIGH')
    status = db.Column(db.String(20), nullable=False, default='NEW')
    assigned_to = db.Column(db.String(80))
    created_by = db.Column(db.String(80), nullable=False, default='system')
    investigation_notes = db.Column(LongText)
    resolution_notes = db.Column(db.Text)
    detected_at = db.Column(UTCDateTime, default=utc_now)
    updated_at = db.Column(UTCDateTime, default=utc_now, onupdate=utc_now)
    closed_at = db.Column(UTCDateTime)

    events = db.relationship('IncidentEvent', backref='incident', cascade='all, delete-orphan',
                             order_by='IncidentEvent.created_at')
    response_actions = db.relationship('ResponseAction', backref='incident',
                                       cascade='all, delete-orphan',
                                       order_by='ResponseAction.created_at.desc()')

    @property
    def is_open(self):
        return self.status in INCIDENT_OPEN_STATUSES

    @property
    def risk_counts(self):
        if not self.check:
            return {r: 0 for r in RISK_LEVELS}
        return self.check.risk_counts


class IncidentEvent(db.Model):
    __tablename__ = 'incident_events'
    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey('incidents.id', ondelete='CASCADE'),
                            nullable=False)
    action = db.Column(db.String(60), nullable=False)
    actor = db.Column(db.String(80), nullable=False, default='system')
    note = db.Column(db.Text)
    from_status = db.Column(db.String(20))
    to_status = db.Column(db.String(20))
    created_at = db.Column(UTCDateTime, default=utc_now)


class ResponseAction(db.Model):
    __tablename__ = 'response_actions'
    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey('incidents.id', ondelete='CASCADE'),
                            nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'),
                          nullable=False)
    action_type = db.Column(db.String(40), nullable=False, default='RESTORE_BASELINE')
    status = db.Column(db.String(30), nullable=False, default='REQUESTED')
    baseline_id = db.Column(db.Integer, db.ForeignKey('baselines.id', ondelete='SET NULL'))
    baseline_sha256 = db.Column(db.String(64))
    reason = db.Column(db.Text)
    requested_by = db.Column(db.String(80), nullable=False)
    approved_by = db.Column(db.String(80))
    approved_at = db.Column(UTCDateTime)
    executed_at = db.Column(UTCDateTime)
    before_content = db.Column(LongText)
    after_content = db.Column(LongText)
    before_sha256 = db.Column(db.String(64))
    after_sha256 = db.Column(db.String(64))
    result_note = db.Column(db.Text)
    created_at = db.Column(UTCDateTime, default=utc_now)

    @property
    def is_pending(self):
        return self.status == 'REQUESTED'

    @property
    def is_approved(self):
        return self.status == 'APPROVED'


class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    username = db.Column(db.String(80), nullable=False, default='system')
    role = db.Column(db.String(20))
    action = db.Column(db.String(80), nullable=False)
    object_type = db.Column(db.String(60))
    object_id = db.Column(db.String(60))
    device_name = db.Column(db.String(100))
    detail = db.Column(db.Text)
    result = db.Column(db.String(20), nullable=False, default='SUCCESS')
    ip_address = db.Column(db.String(64))
    created_at = db.Column(UTCDateTime, default=utc_now)


class AppSetting(db.Model):
    __tablename__ = 'app_settings'
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text)
    updated_at = db.Column(UTCDateTime, default=utc_now, onupdate=utc_now)


class LoginAttempt(db.Model):
    """Shared, database-backed login throttling state (works across workers)."""
    __tablename__ = 'login_attempts'
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(64), nullable=False, index=True)
    username = db.Column(db.String(100), nullable=False, default='', index=True)
    success = db.Column(db.Boolean, nullable=False, default=False)
    attempted_at = db.Column(UTCDateTime, nullable=False, default=utc_now,
                             index=True)
