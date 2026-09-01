"""Startup checks for the two production settings that fail confusingly (#92).

Both are one line in the server environment, both are set once a term by somebody who
does not work on this app daily, and both fail in a way that reads like an application
bug rather than a configuration mistake. So they are checked at startup instead.
"""
import os
import sqlite3

import pytest

import app as app_module
import db as db_module


@pytest.fixture
def loaded_db(tmp_path, monkeypatch):
    """A database the way a real deployment builds it: schema plus the real list."""
    path = tmp_path / 'course-data.db'
    connection = sqlite3.connect(path)
    for name in ('schema.sql', 'competencies.sql'):
        with open(name) as f:
            connection.executescript(f.read())
    connection.commit()
    connection.close()
    monkeypatch.setattr(db_module, 'DB_PATH', str(path))
    return str(path)


def test_a_loaded_database_and_a_real_secret_pass(loaded_db, monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'a-real-one')
    app_module.check_production_config()          # does not raise


def test_a_missing_secret_key_stops_startup(loaded_db, monkeypatch):
    """The fallback is a fixed string in a public repo, and sessions would not survive
    a restart."""
    monkeypatch.delenv('SECRET_KEY', raising=False)
    with pytest.raises(app_module.NotReadyForProduction) as caught:
        app_module.check_production_config()
    assert 'SECRET_KEY' in str(caught.value)


def test_an_empty_database_stops_startup(tmp_path, monkeypatch):
    """The failure this exists for.

    DB_PATH is relative by default and under mod_wsgi the working directory is not the
    project folder. SQLite creates a missing file rather than complaining, so a typo in
    the path yields an empty database and then "no such table: settings" on every
    request, which reads like a bug in the app.
    """
    monkeypatch.setenv('SECRET_KEY', 'a-real-one')
    monkeypatch.setattr(db_module, 'DB_PATH', str(tmp_path / 'typo-in-the-path.db'))
    with pytest.raises(app_module.NotReadyForProduction) as caught:
        app_module.check_production_config()
    message = str(caught.value)
    assert 'no tables' in message
    assert 'typo-in-the-path.db' in message      # names the path it actually opened


def test_the_message_names_every_problem_at_once(tmp_path, monkeypatch):
    """Two restarts to learn two things is how a deployment evening gets long."""
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.setattr(db_module, 'DB_PATH', str(tmp_path / 'missing.db'))
    with pytest.raises(app_module.NotReadyForProduction) as caught:
        app_module.check_production_config()
    message = str(caught.value)
    assert 'SECRET_KEY' in message and 'no tables' in message


def test_development_is_not_checked(monkeypatch):
    """Local work must not need a SECRET_KEY or an absolute path."""
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.delenv('APP_ENV', raising=False)
    assert app_module.create_app().config['ENV'] == 'development'
