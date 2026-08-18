"""Apply pending schema migrations to an existing database.

`schema.sql` builds a database from nothing, which is right for a fresh install and
catastrophic for a live one: it drops every table. Once students have real results,
schema changes have to arrive as migrations instead. See migrations/README.md.

    ./venv/bin/python migrate.py            # what is pending
    ./venv/bin/python migrate.py --apply    # dated backup, then apply

Deliberately a standalone script with no Flask involved. It runs on a server, possibly
by someone who has never seen this codebase, and the fewer moving parts the better.
"""
import os
import re
import shutil
import sqlite3
import sys
from datetime import date

MIGRATIONS_DIR = 'migrations'
# NNN-anything.sql. The number is the version this file brings the database up to.
MIGRATION_NAME = re.compile(r'^(\d+)-.*\.sql$')


def available():
    """Every migration on disk as (version, path), lowest first."""
    found = []
    for name in sorted(os.listdir(MIGRATIONS_DIR)):
        match = MIGRATION_NAME.match(name)
        if match:
            found.append((int(match.group(1)), os.path.join(MIGRATIONS_DIR, name)))
    return sorted(found)


def latest_available():
    versions = [version for (version, _path) in available()]
    return max(versions) if versions else 0


def current_version(connection):
    """The schema version recorded in the database; 0 if it has never been stamped."""
    row = connection.execute(
        "select value from settings where key = 'schema_version'").fetchone()
    return int(row[0]) if row and row[0] else 0


def pending(connection):
    at = current_version(connection)
    return [(version, path) for (version, path) in available() if version > at]


def backup(db_path, today=None):
    """Copy the database beside itself with a date stamp, and return the new path.

    Dave's preference on #55: a date stamp, no finer granularity. So a second run on
    the same day overwrites that day's copy rather than filling the directory, which
    also means the backup is the state at the start of the day's work.
    """
    target = db_path + '.' + (today or date.today()).isoformat()
    shutil.copyfile(db_path, target)
    return target


def apply(db_path, today=None):
    """Apply every pending migration. Returns the list of versions applied."""
    connection = sqlite3.connect(db_path)
    try:
        todo = pending(connection)
        if not todo:
            return []
        # Before touching anything. If a migration fails halfway, this file is the
        # recovery path: SQLite's executescript does not give us all-or-nothing across
        # multiple statements, so the backup is the guarantee, not the transaction.
        connection.close()
        made = backup(db_path, today)
        print('backed up to ' + made)
        connection = sqlite3.connect(db_path)
        applied = []
        for (version, path) in todo:
            with open(path) as f:
                connection.executescript(f.read())
            connection.execute(
                "insert or replace into settings (key, value) values ('schema_version', ?)",
                (str(version),))
            connection.commit()
            applied.append(version)
            print('applied ' + path)
        return applied
    finally:
        connection.close()


def main(argv):
    db_path = os.environ.get('DB_PATH', 'course-data.db')
    if not os.path.exists(db_path):
        print('no database at ' + db_path + '; a fresh one comes from schema.sql')
        return 1
    connection = sqlite3.connect(db_path)
    try:
        at = current_version(connection)
        todo = pending(connection)
    finally:
        connection.close()
    print(db_path + ' is at schema version ' + str(at)
          + '; latest available is ' + str(latest_available()))
    if not todo:
        print('nothing to apply')
        return 0
    print('pending: ' + ', '.join(path for (_v, path) in todo))
    if '--apply' not in argv:
        print('re-run with --apply to take a dated backup and apply them')
        return 0
    apply(db_path)
    print('done')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
