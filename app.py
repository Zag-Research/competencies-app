"""Application entry point.

create_app() builds the Flask app, configures it, and plugs in each blueprint
(a self-contained group of routes). Keeping construction in a function avoids the
circular imports you'd hit if the app and its blueprints all lived at module top
level, and lets a test build a fresh app on demand.

Run with:  flask --app app run --debug --port 8080
"""
import os

from flask import Flask

from blueprints.auth import auth_bp
from blueprints.main import main_bp
from blueprints.mark import mark_bp
from blueprints.queue import queue_bp


def create_app():
    app = Flask(__name__)
    # 'development' locally (the interim /login page); set APP_ENV=production in the
    # server environment to switch identity over to TMU CAS. See DEPLOYMENT.md.
    app.config['ENV'] = os.environ.get('APP_ENV', 'development')
    # Dev-only fallback secret so Flask can sign session cookies. In production set a real
    # SECRET_KEY in the environment, so sessions survive restarts and aren't a known value.
    app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-me')

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(mark_bp)
    app.register_blueprint(queue_bp)
    return app


app = create_app()
