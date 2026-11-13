"""
Test database initialization using in-memory SQLite.
Verifies that db.create_all() creates all required tables correctly.
"""
from flask import Flask
from sqlalchemy import inspect
from db import db


def test_database_initialization():
    """Test that database initialization creates all required tables."""
    # Create a minimal Flask app for testing
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Initialize SQLAlchemy with the app
    db.init_app(app)
    
    # Create all tables and verify
    with app.app_context():
        db.create_all()
        
        # Verify tables exist
        engine = db.engine
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert 'baselines' in tables
        assert 'devices' in tables
        assert 'config_checks' in tables
        assert 'incidents' in tables
        assert 'users' in tables
        assert 'routers' in tables
        assert 'backups' in tables
        assert 'schedules' in tables
        
        # Drop all tables
        db.drop_all()
        
        # Verify tables are gone
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert 'baselines' not in tables
        assert 'devices' not in tables
        assert 'config_checks' not in tables
        assert 'incidents' not in tables
        assert 'users' not in tables
        assert 'routers' not in tables
        assert 'backups' not in tables
        assert 'schedules' not in tables
