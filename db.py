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


# How long a TA's claim on a student lasts before it is treated as abandoned.
DEFAULT_CLAIM_TIMEOUT_MINUTES = 20


def claim_timeout_minutes():
    return int(get_setting('claim_timeout_minutes', DEFAULT_CLAIM_TIMEOUT_MINUTES))


def claim_cutoff():
    # SQLite modifier for "claimed longer ago than the timeout", e.g. '-20 minutes'.
    # Passed as a bind parameter to datetime('now', ?).
    return '-' + str(claim_timeout_minutes()) + ' minutes'


# A request is up for grabs if nobody holds it, or if whoever holds it has been
# sitting on it past the timeout (they closed their laptop, lost wifi, went home).
# Used both to list the queue and to guard the claim itself, so the two can never
# disagree about who is available.
AVAILABLE = """(status = 'waiting'
                or (status = 'claimed' and claimed_at < datetime('now', ?)))"""


def claim_student(sql, student_number, evaluator):
    """Try to claim every available request for one student. True if we got them.

    Two TAs can tap the same student at the same moment. The guard against both
    winning is the WHERE clause: it only matches requests that are still
    available, and the winner's own write is what makes that false for everyone
    else. So the loser's UPDATE matches no rows and changes nothing.

    That means the row count IS the answer. Changed some rows -> the student is
    ours. Changed zero -> another TA got there first.

    Doing this as one conditional UPDATE (rather than SELECT-then-UPDATE) is the
    whole point: a separate check and write leaves a gap where both TAs read
    'waiting', both decide they won, and both walk over.
    """
    sql.execute(
        """update requests
              set status = 'claimed', claimed_by = ?, claimed_at = CURRENT_TIMESTAMP
            where student_number = ?
              and """ + AVAILABLE,
        (evaluator, student_number, claim_cutoff())
    )
    return sql.rowcount > 0


def claim_competency_group(sql, competency_id, evaluator):
    """Claim every student with an available request for one competency.

    Returns (won, lost): how many students we got, and how many another TA had
    already taken since the page was rendered.

    Note this claims each student *whole*, not just their request for this one
    competency. A student can only talk to one TA at a time, so handing the same
    student to two TAs (one per competency) just moves the collision out of the
    queue and into the room. The cost is that a student claimed here drops out of
    every other competency's cohort until this TA is done with them.
    """
    students = sql.execute(
        "select distinct student_number from requests"
        " where competency_id = ? and " + AVAILABLE,
        (competency_id, claim_cutoff())
    ).fetchall()
    won = 0
    for (student_number,) in students:
        if claim_student(sql, student_number, evaluator):
            won += 1
    return won, len(students) - won


def release_students_for_competency(sql, competency_id, evaluator):
    # Hand a whole cohort back. Scoped to this evaluator's own claims.
    students = sql.execute(
        """select distinct student_number from requests
            where competency_id = ? and status = 'claimed' and claimed_by = ?""",
        (competency_id, evaluator)
    ).fetchall()
    for (student_number,) in students:
        release_student(sql, student_number, evaluator)


def release_student(sql, student_number, evaluator):
    # Hand a student back to the queue. Scoped to this evaluator's own claims so a
    # TA can never release a student out from under someone else.
    sql.execute(
        """update requests
              set status = 'waiting', claimed_by = null, claimed_at = null
            where student_number = ? and status = 'claimed' and claimed_by = ?""",
        (student_number, evaluator)
    )


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
