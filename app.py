"""Application entry point.

create_app() builds the Flask app, configures it, and plugs in each blueprint
(a self-contained group of routes). Keeping construction in a function avoids the
circular imports you'd hit if the app and its blueprints all lived at module top
level, and lets a test build a fresh app on demand.

Run with:  flask --app app run --debug --port 8080
"""
import os
import sqlite3

from flask import Flask

from blueprints.auth import auth_bp
from blueprints.main import main_bp
from blueprints.mark import mark_bp
from blueprints.queue import queue_bp
from blueprints.reports import reports_bp


class NotReadyForProduction(RuntimeError):
    """Raised at startup when the server is configured in a way that fails later (#92)."""


def check_production_config():
    """Fail at startup, loudly, rather than per-request in a way that reads as a bug.

    Both of these are one line in the server environment and both fail confusingly if
    missed, which is the worst combination for something checked once a term.

    SECRET_KEY. The dev fallback is a fixed string in a public repository. Identity in
    production comes from CAS headers rather than the session, so a known key does not
    let anybody in, but it does mean every restart is signed with a value anyone can
    read, and sessions do not survive a restart.

    The database. `DB_PATH` is relative by default, and under mod_wsgi the working
    directory is not the project folder. SQLite creates a missing file rather than
    complaining, so a wrong path produces an empty database and every page then fails
    with "no such table: settings", which reads like an application bug rather than a
    path that needs fixing.
    """
    problems = []
    if not os.environ.get('SECRET_KEY'):
        problems.append(
            'SECRET_KEY is not set, so sessions would be signed with the development '
            'fallback, which is a fixed string in a public repository. '
            'Set it in the server environment. See DEPLOYMENT.md.')

    import db
    try:
        with sqlite3.connect(db.DB_PATH) as connection:
            ready = connection.execute(
                "select count(*) from sqlite_master where type = 'table'"
                "   and name = 'settings'").fetchone()[0]
    except sqlite3.Error as error:
        problems.append('cannot open the database at %s: %s' % (db.DB_PATH, error))
    else:
        if not ready:
            problems.append(
                'the database at %s has no tables in it. Either DB_PATH points '
                'somewhere wrong, or schema.sql and competencies.sql have not been '
                'loaded yet. SQLite creates a missing file rather than complaining, so '
                'a typo in the path looks exactly like this. See DEPLOYMENT.md.'
                % os.path.abspath(db.DB_PATH))
    if problems:
        raise NotReadyForProduction(
            'Not starting, because this would fail on every request instead:\n  - '
            + '\n  - '.join(problems))


def create_app():
    app = Flask(__name__)
    # 'development' locally (the interim /login page); set APP_ENV=production in the
    # server environment to switch identity over to TMU CAS. See DEPLOYMENT.md.
    app.config['ENV'] = os.environ.get('APP_ENV', 'development')
    # Dev-only fallback secret so Flask can sign session cookies. In production set a real
    # SECRET_KEY in the environment, so sessions survive restarts and aren't a known value.
    app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-me')

    if app.config['ENV'] == 'production':
        check_production_config()

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(mark_bp)
    app.register_blueprint(queue_bp)
    app.register_blueprint(reports_bp)
    return app


app = create_app()
