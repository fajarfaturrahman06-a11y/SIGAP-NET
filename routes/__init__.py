"""Blueprint registration."""
from routes.devices import devices_bp
from routes.baselines import baselines_bp
from routes.checks import checks_bp
from routes.incidents import incidents_bp
from routes.audittrail import audit_bp
from routes.users import users_bp
from routes.simulation_routes import simulation_bp


def register_blueprints(app):
    app.register_blueprint(devices_bp)
    app.register_blueprint(baselines_bp)
    app.register_blueprint(checks_bp)
    app.register_blueprint(incidents_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(simulation_bp)
