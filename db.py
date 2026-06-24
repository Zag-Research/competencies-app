"""Database access layer.

Everything that talks to SQLite lives here so the rest of the app never opens a
connection itself. One place to change if the storage ever moves (Postgres, etc).
"""
from contextlib import closing, contextmanager
import sqlite3

DB_PATH = "course-data.db"


@contextmanager
def cursor():
    """Open the database, hand back a cursor, commit on a clean exit, always close.

    Replaces the repeated
        with closing(sqlite3.connect(...)) as connection:
            with closing(connection.cursor()) as sql:
                ...
                connection.commit()
    boilerplate. Use as:  with db.cursor() as sql: ...
    """
    connection = sqlite3.connect(DB_PATH)
    try:
        with closing(connection.cursor()) as sql:
            yield sql
        connection.commit()
    finally:
        connection.close()


def get_setting(key, default=None):
    # Single-value config lookup from the settings table, with a code-side
    # fallback so the app still runs if the row was never seeded.
    with cursor() as sql:
        row = sql.execute(
            "select value from settings where key = ?", (key,)
        ).fetchone()
    return row[0] if row else default


# How many competencies a student may request in one day. Dave to confirm the
# exact number (~5-6); stored in settings so it is a config change, not a code one.
DEFAULT_DAILY_CAP = 6


def daily_cap():
    return int(get_setting('daily_cap', DEFAULT_DAILY_CAP))


def lookup_role(username):
    # Interim role lookup: 'staff' if listed in the 'admins' setting, else
    # 'student' if it matches a student_number, else None (unrecognized).
    with cursor() as sql:
        row = sql.execute(
            "select value from settings where key = 'admins'").fetchone()
        admins = row[0].split() if row else []
        if username in admins:
            return 'staff'
        student = sql.execute(
            "select student_number from students where student_number = ?",
            (username,)
        ).fetchone()
        if student:
            return 'student'
    return None


def requests_used_today(sql, student_number):
    # Count every request the student made today (waiting or already handled):
    # the cap is about slots claimed per day, not just what is still pending.
    # Takes an open cursor so it can run inside a caller's transaction.
    row = sql.execute(
        """select count(*) from requests
           where student_number = ? and date(requested_at) = date('now')""",
        (student_number,)
    ).fetchone()
    return row[0] if row else 0
