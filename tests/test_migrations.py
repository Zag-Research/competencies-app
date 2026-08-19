"""Schema migrations (#55): changing the schema once real data exists.

The failure this guards against is specific. `schema.sql` drops every table, so running
it against a live database destroys student results. Migrations are the way a change
reaches a database that already has data in it.
"""
import os
import shutil
import sqlite3
from datetime import date

import pytest

import migrate


@pytest.fixture
def live_db(tmp_path, monkeypatch):
    """A database built from schema.sql, with a student result in it worth not losing."""
    path = tmp_path / 'course-data.db'
    connection = sqlite3.connect(path)
    with open('schema.sql') as f:
        connection.executescript(f.read())
    connection.execute("insert into students values ('Alice', 'Chen', '500111111')")
    connection.execute("insert into competencies (id, name) values (1, 'Nested loops')")
    connection.execute(
        "insert into achievements (student_number, competency_id, status, date_recorded) "
        "values ('500111111', 1, 'achieved', '2026-09-15 10:00')")
    # Stamp it back to 0. These tests supply their own throwaway migrations numbered from
    # 001, so how many real ones exist is irrelevant to them, and hard-coding around the
    # real count would make them fail every time one is added.
    connection.execute(
        "update settings set value = '0' where key = 'schema_version'")
    connection.commit()
    connection.close()
    return str(path)


@pytest.fixture
def migrations_dir(tmp_path, monkeypatch):
    """Point migrate at a throwaway directory, so tests never depend on real ones."""
    directory = tmp_path / 'migrations'
    directory.mkdir()
    monkeypatch.setattr(migrate, 'MIGRATIONS_DIR', str(directory))
    return directory


def write_migration(directory, name, sql):
    (directory / name).write_text(sql)


# --- the guard that keeps schema.sql and migrations/ in step ---------------

def test_schema_version_in_schema_sql_matches_the_migrations_on_disk():
    """The step that is easiest to forget when adding a migration.

    A fresh database is born with every change, so schema.sql must claim the highest
    migration number. If it claims less, migrate.py would re-apply a change the
    database already has; if more, a real migration would be skipped forever.
    """
    with open('schema.sql') as f:
        schema = f.read()
    marker = "INSERT INTO settings VALUES('schema_version','"
    assert marker in schema, 'schema.sql must stamp a schema_version'
    claimed = int(schema.split(marker)[1].split("'")[0])
    assert claimed == migrate.latest_available(), (
        'schema.sql claims schema_version %d but migrations/ goes up to %d'
        % (claimed, migrate.latest_available()))


# --- reading the current state --------------------------------------------

def test_a_fresh_database_has_nothing_pending(live_db, migrations_dir):
    connection = sqlite3.connect(live_db)
    try:
        assert migrate.pending(connection) == []
    finally:
        connection.close()


def test_a_new_migration_shows_as_pending(live_db, migrations_dir):
    write_migration(migrations_dir, '001-add-a-column.sql',
                    'alter table students add column cas_username TEXT;')
    connection = sqlite3.connect(live_db)
    try:
        assert [v for (v, _p) in migrate.pending(connection)] == [1]
    finally:
        connection.close()


# --- applying --------------------------------------------------------------

def test_applying_changes_the_schema_and_keeps_the_data(live_db, migrations_dir):
    """The whole point: the change lands and the student's result survives."""
    write_migration(migrations_dir, '001-add-a-column.sql',
                    'alter table students add column cas_username TEXT;')
    assert migrate.apply(live_db) == [1]
    connection = sqlite3.connect(live_db)
    try:
        columns = [c[1] for c in connection.execute('pragma table_info(students)')]
        assert 'cas_username' in columns
        assert connection.execute('select count(*) from achievements').fetchone()[0] == 1
        assert migrate.current_version(connection) == 1
    finally:
        connection.close()


def test_applying_twice_does_nothing_the_second_time(live_db, migrations_dir):
    write_migration(migrations_dir, '001-add-a-column.sql',
                    'alter table students add column cas_username TEXT;')
    assert migrate.apply(live_db) == [1]
    # A second run must be a no-op, not an error: `alter table` on an existing column
    # would fail, which is exactly what the version stamp is for.
    assert migrate.apply(live_db) == []


def test_migrations_apply_in_order(live_db, migrations_dir):
    write_migration(migrations_dir, '002-second.sql',
                    'alter table students add column second TEXT;')
    write_migration(migrations_dir, '001-first.sql',
                    'alter table students add column first_added TEXT;')
    # 002 sorts before 001 as text in some locales; the numbers must decide.
    assert migrate.apply(live_db) == [1, 2]


def test_a_partial_run_leaves_the_version_at_the_last_success(live_db, migrations_dir):
    """A broken migration must not mark itself, or it would be skipped forever."""
    write_migration(migrations_dir, '001-fine.sql',
                    'alter table students add column fine TEXT;')
    write_migration(migrations_dir, '002-broken.sql', 'this is not sql;')
    with pytest.raises(sqlite3.Error):
        migrate.apply(live_db)
    connection = sqlite3.connect(live_db)
    try:
        assert migrate.current_version(connection) == 1
    finally:
        connection.close()


# --- the backup ------------------------------------------------------------

def test_applying_takes_a_dated_backup_first(live_db, migrations_dir):
    write_migration(migrations_dir, '001-add-a-column.sql',
                    'alter table students add column cas_username TEXT;')
    migrate.apply(live_db, today=date(2026, 9, 15))
    copy = live_db + '.2026-09-15'
    assert os.path.exists(copy)
    # And it is the state from BEFORE the change, which is what makes it a recovery.
    connection = sqlite3.connect(copy)
    try:
        columns = [c[1] for c in connection.execute('pragma table_info(students)')]
        assert 'cas_username' not in columns
        assert connection.execute('select count(*) from achievements').fetchone()[0] == 1
    finally:
        connection.close()


def test_no_backup_is_taken_when_there_is_nothing_to_do(live_db, migrations_dir):
    migrate.apply(live_db, today=date(2026, 9, 15))
    assert not os.path.exists(live_db + '.2026-09-15')


def test_a_date_stamp_is_all_the_granularity_there_is(live_db, migrations_dir):
    """Dave on #55: "Backup should include a date stamp. (no need for finer
    granularity)" So two runs on one day share one file, which keeps the copy as the
    state at the start of that day's work rather than filling the directory."""
    write_migration(migrations_dir, '001-one.sql',
                    'alter table students add column one TEXT;')
    migrate.apply(live_db, today=date(2026, 9, 15))
    write_migration(migrations_dir, '002-two.sql',
                    'alter table students add column two TEXT;')
    migrate.apply(live_db, today=date(2026, 9, 15))
    backups = [n for n in os.listdir(os.path.dirname(live_db))
               if n.startswith('course-data.db.')]
    assert backups == ['course-data.db.2026-09-15']
