"""Database access layer.

Everything that talks to SQLite lives here so the rest of the app never opens a
connection itself. One place to change if the storage ever moves (Postgres, etc).
"""
from contextlib import closing, contextmanager
import os
import sqlite3

# Pure rules only, and logic imports nothing from here, so this stays one-way.
import logic

# Relative default for local dev; set an absolute DB_PATH in production, since under
# Apache/mod_wsgi the working directory is not the project folder. See DEPLOYMENT.md.
DB_PATH = os.environ.get("DB_PATH", "course-data.db")


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


# How many competencies a student may request per studio session (#22). Dave chose
# 3 to start (may bump to 4 later); stored in settings so it is a config change,
# not a code one. This value is only a fallback if the setting row is missing.
DEFAULT_DAILY_CAP = 3


def progress_by_student(sql):
    """Per student, how they are doing in each course they take.

    Returns rows of (last, first, number, [(course, achieved, total), ...]).

    Per course rather than one overall figure, because the courses are graded
    separately: 40 competencies at 2% each in CPS109, and the same again in CPS213.
    A single blended percentage would be the wrong number to type into either.
    """
    per_course = dict(sql.execute(
        "select course, count(*) from competencies where course is not null"
        " group by course").fetchall())
    achieved = {}
    for (number, course, n) in sql.execute(
            """select a.student_number, c.course, count(*)
                 from achievements a
                 join competencies c on c.id = a.competency_id
                where a.status = 'achieved'
                group by a.student_number, c.course"""):
        achieved[(number, course)] = n
    enrolled = {}
    for (number, course) in sql.execute(
            "select student_number, course from enrollments where withdrawn_on is null"):
        enrolled.setdefault(number, []).append(course)
    rows = []
    for (number, first, last) in sql.execute(
            "select student_number, first_name, last_name from students"):
        # No enrollment rows means "not recorded", treated as taking everything (#11).
        courses = sorted(enrolled.get(number) or per_course.keys())
        rows.append((last, first, number,
                     [(course, achieved.get((number, course), 0), per_course.get(course, 0))
                      for course in courses]))
    return rows


def completion_by_student(sql):
    """{student_number: percent of their competencies passed}.

    Used to order the staff queue by who is furthest behind (#69). A percentage rather
    than a raw count, because a part-time student has 40 competencies and a full-time
    one has 80; counting raw would park every part-time student at the top of the queue
    for the whole term.
    """
    done = dict(sql.execute(
        "select student_number, count(*) from achievements where status = 'achieved'"
        " group by student_number").fetchall())
    per_course = dict(sql.execute(
        "select course, count(*) from competencies group by course").fetchall())
    everything = sql.execute("select count(*) from competencies").fetchone()[0]
    enrolled = {}
    for (number, course) in sql.execute(
            "select student_number, course from enrollments where withdrawn_on is null"):
        enrolled.setdefault(number, []).append(course)
    out = {}
    for (number,) in sql.execute("select student_number from students"):
        courses = enrolled.get(number)
        # No enrollment rows means "not recorded", which everywhere else is treated as
        # taking everything (#11). Keep that consistent here.
        total = sum(per_course.get(c, 0) for c in courses) if courses else everything
        out[number] = round(100 * done.get(number, 0) / total) if total else 0
    return out


def attended_days(sql, student_number):
    """Every studio day this student was present for, as a set of ISO date strings."""
    return {row[0] for row in sql.execute(
        "select day from attendance where student_number = ?", (student_number,)
    ).fetchall()}


def daily_cap():
    return int(get_setting('daily_cap', DEFAULT_DAILY_CAP))


# How many upcoming studio sessions a student can book ahead (#17). Six is about two
# weeks. Longer lets them plan further out; shorter keeps the staff planning view
# honest, since a booking made a month early is a guess rather than a plan. Dave's call,
# so it is a setting rather than a number in the code.
DEFAULT_STUDIO_LOOKAHEAD = 6


def studio_lookahead():
    return int(get_setting('studio_lookahead', DEFAULT_STUDIO_LOOKAHEAD))


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


# A request is up for grabs if the student is actually in the lab, AND nobody holds
# them, or whoever holds them has been sitting on it past the timeout (they closed
# their laptop, lost wifi, went home).
#
# "In the lab" is just: they have a seat. Students sign up before they arrive (from
# home, on the bus), so a request with no seat is a plan, not a person a TA can walk
# over to. Typing a seat is the act of saying "I'm here, at this machine", and it is
# what puts them in front of staff.
#
# Used both to list the queue and to guard the claim itself, so the two can never
# disagree about who is available.
#
# Scoped to one studio day: a student who booked next Tuesday is not standing in
# front of anyone today, so they must not appear in (or be claimable from) today's
# queue. Callers pass the studio date they are working on.
AVAILABLE = """(studio_date = ?
                and seat is not null and seat != ''
                and (status = 'waiting'
                     or (status = 'claimed' and claimed_at < datetime('now', ?))))"""


def students_awaiting_seat(sql, studio_date):
    """Students booked for `studio_date` who have no seat yet, by surname.

    They are invisible on the live queue by design: AVAILABLE requires a seat, because
    a claim means walking over to someone, and there is nowhere to walk to. But staff
    still need to reach them, both to see who has booked and not turned up, and to set
    a seat on their behalf when the student cannot (#46).

    Returns (student_number, first, last, how_many_competencies).
    """
    return sql.execute(
        """select r.student_number, s.first_name, s.last_name, count(*)
             from requests r
             join students s on r.student_number = s.student_number
            where r.studio_date = ? and r.status = 'waiting'
              and (r.seat is null or r.seat = '')
            group by r.student_number, s.first_name, s.last_name
            order by s.last_name, s.first_name""",
        (studio_date,)
    ).fetchall()


def set_seat(sql, student_number, seat, studio_date):
    """The student arrived and sat down, or moved machines, or left.

    Written to two places, because the seat answers two questions.

    `requests` is what the staff queue reads, so a TA can see where to walk. Scoped to
    this session, so sitting down today does not stamp a seat onto something booked for
    next week and make them look present at a session they have not turned up to yet.

    `attendance` is where the seat LIVES for the day. Requests alone were not enough:
    a student who taps "I am here" before choosing what to demonstrate has no request
    for the seat to land on, so it was dropped on the floor while the screen told them
    a TA was coming. Attendance already has exactly one row per student per studio day.
    """
    sql.execute(
        """update requests set seat = ?
            where student_number = ? and studio_date = ?
              and status in ('waiting', 'claimed')""",
        (seat, student_number, studio_date)
    )
    sql.execute(
        "update attendance set seat = ? where student_number = ? and day = ?",
        (seat, student_number, studio_date)
    )


def seat_for(sql, student_number, day):
    """Where this student said they are sitting today, or None (#83).

    The one place to ask. A booking made after they sat down inherits from here, which
    is what stops that ordering from losing the seat.
    """
    row = sql.execute(
        "select seat from attendance where student_number = ? and day = ?",
        (student_number, day)
    ).fetchone()
    return row[0] if row and row[0] else None


def carry_bumped_forward(sql, student_number, studio_date):
    """Move a student's bumped competencies to the session they just showed up for.

    A bumped request (bumped_by set, back to 'waiting') keeps its original session
    date, so if the student does not return that day it would be stranded. When they
    next take a seat, bring those bumped requests to that session so they resurface
    for a TA. Only bumped ones move; a normal future booking stays on its own day.
    """
    sql.execute(
        """update requests set studio_date = ?
            where student_number = ? and status = 'waiting'
              and bumped_by is not null and studio_date != ?""",
        (studio_date, student_number, studio_date)
    )


def claim_student(sql, student_number, evaluator, studio_date):
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
        (evaluator, student_number, studio_date, claim_cutoff())
    )
    return sql.rowcount > 0


def claim_competency_group(sql, competency_id, evaluator, studio_date):
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
        (competency_id, studio_date, claim_cutoff())
    ).fetchall()
    won = 0
    for (student_number,) in students:
        if claim_student(sql, student_number, evaluator, studio_date):
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


def release_request(sql, request_id, evaluator):
    """Hand ONE competency back to the queue, keeping the rest of the claim.

    For the TA who can evaluate this student, just not this one competency: they
    have not prepared it, or it is outside what they are comfortable assessing.
    Only this request returns to 'waiting'. Everything else they claimed for the
    student stays with them, so the rest still gets done in the same sitting.

    Deliberately NOT a result. Nothing is written to achievements, so declining
    starts no cooling-off period and costs the student nothing. The row already
    existed and is only changing status, so the daily cap is untouched too: this
    is the same request going back on the list, not a new one.

    Scoped to this evaluator's own claim, so a TA cannot bounce a request out
    from under someone else. True if we actually released something.

    Records bumped_by = this evaluator (#19/#24): the competency goes back to the
    queue, but the app remembers who bumped it so it can flag the student for that
    TA later and keep it out of the student's cap.
    """
    sql.execute(
        """update requests
              set status = 'waiting', claimed_by = null, claimed_at = null,
                  bumped_by = ?
            where id = ? and status = 'claimed' and claimed_by = ?""",
        (evaluator, request_id, evaluator)
    )
    return sql.rowcount > 0


def requests_used_for_studio(sql, student_number, studio_date):
    # How much of the cap the student has spent on one studio session (waiting or
    # already handled): the cap is about slots booked per session, not just what is
    # still pending. Counting by studio_date rather than by the day they pressed the
    # button is what lets them plan a week ahead without exhausting a single day's
    # allowance. Takes an open cursor so it can run inside a caller's transaction.
    # bumped_by is null: a bumped competency (#19) carried back into a session does
    # not count against the student's cap, per Dave's "no penalty" rule.
    row = sql.execute(
        """select count(*) from requests
           where student_number = ? and studio_date = ? and bumped_by is null""",
        (student_number, studio_date)
    ).fetchone()
    return row[0] if row else 0


def session_course_counts(sql, student_number, studio_date):
    """How many requests the student already has this session, per course.

    Feeds the balance rule (#22): the new picks are added to these existing counts
    and the whole session is checked against the cap-and-1-apart rule. Counts all
    statuses (waiting/claimed/done), because a competency already evaluated this
    session still counts toward that session's balance. Returns [(course, count)].
    """
    return sql.execute(
        """select c.course, count(*) from requests r
             join competencies c on r.competency_id = c.id
            where r.student_number = ? and r.studio_date = ?
              and r.bumped_by is null
            group by c.course""",
        (student_number, studio_date)
    ).fetchall()


# --- peer helpfulness (endorsements) ------------------------------------

def classmates(sql, student_number):
    # Everyone the student could thank: the roster minus themselves. Once courses
    # exist (#11) this would scope to their own section; for now it is everyone.
    return sql.execute(
        """select student_number, first_name, last_name from students
            where student_number != ?
            order by last_name, first_name""",
        (student_number,)
    ).fetchall()


def add_endorsement(sql, from_student, to_student, day):
    """Record a thank-you. True if it was new, False if already given that day.

    'insert or ignore' leans on the (from, to, day) primary key: a repeat tap of
    the same classmate on the same day collides and is ignored, so the count
    cannot be inflated. Self-thanks are refused here as a backstop even though the
    form never offers the student their own name.

    `day` is passed in (the caller's Toronto day) rather than computed with SQL
    date('now'), which is UTC: between ~8pm Toronto and midnight UTC the two
    disagree, which would split a single Toronto day across two keys and let the
    same thank-you land twice.
    """
    if from_student == to_student:
        return False
    sql.execute(
        """insert or ignore into endorsements (from_student, to_student, day)
           values (?, ?, ?)""",
        (from_student, to_student, day)
    )
    return sql.rowcount > 0


def endorsements_given_today(sql, from_student, day):
    # The classmates this student has already thanked on `day` (the caller's
    # Toronto day), by name, so the page can show what registered and the student
    # does not re-tap the same person. See add_endorsement on why day is passed in.
    return sql.execute(
        """select s.first_name, s.last_name from endorsements e
             join students s on e.to_student = s.student_number
            where e.from_student = ? and e.day = ?
            order by s.last_name, s.first_name""",
        (from_student, day)
    ).fetchall()


def enrolled_courses(sql, student_number):
    # Courses the student is currently taking. Empty means "not recorded", which callers
    # treat as enrolled in everything rather than nothing (see competencies_for).
    # A dropped course is excluded here but its row survives, so their results do too.
    return [row[0] for row in sql.execute(
        "select course from enrollments where student_number = ? and withdrawn_on is null"
        " order by course",
        (student_number,)
    ).fetchall()]


def has_enrollment_record(sql, student_number):
    """True if we know anything about this student's courses, dropped or not.

    The difference between "we never loaded their enrollment" and "they dropped
    everything". The first should show the full competency list, as a safe default for
    a roster that is not loaded yet (#11). The second should show nothing, because they
    are not taking anything.
    """
    return sql.execute(
        "select 1 from enrollments where student_number = ? limit 1", (student_number,)
    ).fetchone() is not None


def add_or_update_student(sql, student_number, first_name, last_name, courses):
    """Add one student, or correct an existing one, and set which courses they take.

    For a TA with a student in front of them who cannot sign in (#61). Deliberately
    tolerant: re-adding someone who is already there fixes their name and enrollment
    rather than erroring, because the person using this does not know which case they
    are in and should not have to.

    Enrolling in a course they previously dropped clears the withdrawal, which restores
    them exactly: their achievements were never touched by the drop.
    """
    sql.execute(
        "insert or replace into students (student_number, first_name, last_name)"
        " values (?, ?, ?)",
        (student_number, first_name, last_name)
    )
    for course in courses:
        sql.execute(
            "insert or replace into enrollments (student_number, course, withdrawn_on)"
            " values (?, ?, null)",
            (student_number, course)
        )


def all_courses(sql):
    """Every course that has competencies, for the add-a-student form."""
    return [row[0] for row in sql.execute(
        "select distinct course from competencies where course is not null"
        " order by course").fetchall()]


def competencies_for(sql, student_number):
    """(id, name, course) for the courses this student takes, in id order.

    A student with no enrollment rows gets the full list, so an unenrolled or
    not-yet-loaded student is never shown a blank page. A part-time student in one
    course gets only that course's competencies (#11).
    """
    courses = enrolled_courses(sql, student_number)
    if not courses:
        # No current courses. Two very different reasons, so tell them apart: a student
        # we have no enrollment record for at all gets everything (the roster may not be
        # loaded yet), a student who dropped everything gets nothing.
        if has_enrollment_record(sql, student_number):
            return []
        return sql.execute(
            "select id, name, course from competencies order by id"
        ).fetchall()
    marks = ','.join('?' * len(courses))
    return sql.execute(
        "select id, name, course from competencies where course in (" + marks
        + ") order by id",
        courses
    ).fetchall()


def achieved_competency_ids(sql, student_number):
    """The set of competency ids this student has already passed (status 'achieved').

    Used by the balance rule to spot a course the student has finished, and to stop a
    hand-crafted sign-up re-requesting something already passed.
    """
    rows = sql.execute(
        "select competency_id from achievements "
        "where student_number = ? and status = 'achieved'",
        (student_number,)
    ).fetchall()
    return {row[0] for row in rows}


def coverage_edges(sql):
    """Which competencies each one DIRECTLY covers, as {id: {ids}} (#80).

    Direct links only, as stored. logic.covered_by follows the chain from here, so
    nobody has to write out the implied pairs or keep them in sync.
    """
    edges = {}
    for (competency_id, covers_id) in sql.execute(
            "select competency_id, covers_id from competency_covers"):
        edges.setdefault(competency_id, set()).add(covers_id)
    return edges


def _credit_covered(sql, student_number, competency_id):
    """Pass everything this competency proves, without recording an evaluation (#80).

    Two rules, and the second is what makes an undo possible later:

    - Only competencies with NO row in `achievements` are credited. A competency the
      student has already been marked on, passed or not, keeps the result a TA gave
      it. A credit never overwrites somebody's evaluation.
    - Nothing is written to `evaluations`. One sitting of work happened, on the
      competency that was actually demonstrated, and the per-evaluator report counts
      sittings. Writing a row per credited competency would inflate that TA's count
      to five for one evaluation.

    Together those mean a credited pass is exactly a pass with no evaluation behind
    it, which is how _remove_credits finds them again. No extra column needed.

    The id is coerced because it does not always arrive as one. `/save/<competency_id>`
    is an untyped route, so that screen hands over the string '4' while the queue screen
    hands over the integer 4. SQLite compares them the same, so the achievement row
    lands either way, but a dict lookup does not: the string missed every edge and the
    whole feature quietly did nothing from one of the two marking screens.
    """
    covered = logic.covered_by(int(competency_id), coverage_edges(sql))
    for covered_id in covered:
        sql.execute(
            "insert into achievements "
            "(student_number, competency_id, status, date_recorded) "
            "select ?, ?, 'achieved', CURRENT_TIMESTAMP "
            " where not exists (select 1 from achievements "
            "                    where student_number = ? and competency_id = ?)",
            (student_number, covered_id, student_number, covered_id)
        )


def _remove_credits(sql, student_number, competency_id):
    """Take back the passes that only existed because of this one (#80).

    Called after the competency itself is cleared, so it is already gone from the
    student's achieved set by the time we ask what is still proven.

    The mis-tap this exists for: a TA taps the wrong student, that one tap credits
    four other competencies, and the undo a second later clears only the one they
    tapped. Without this the student keeps four passes nobody tested them on, and
    because credits leave no evaluation row there is no screen that would ever show
    why.

    Two things survive an undo:

    - anything the student EARNED. A competency with an evaluation row behind it was
      marked by a TA, and this had nothing to do with it.
    - anything still proven by something else they passed. If two competencies both
      cover simple ifs and only one is undone, the other still proves it.
    """
    edges = coverage_edges(sql)
    # Coerced for the same reason as in _credit_covered: one marking screen sends a
    # string, and a dict lookup does not forgive that the way SQLite does.
    candidates = logic.covered_by(int(competency_id), edges)
    if not candidates:
        return
    # Only what the student EARNED can justify keeping a credit. Asking "is anything
    # they hold still proving this" would count the credits themselves: undoing nested
    # ifs would find simple ifs still sitting there, credited by the very tap being
    # undone, and let it justify keeping comparison operators. The chain would survive
    # its own undo. An earned pass is one with an evaluation row behind it.
    still_proven = set()
    for (other_id,) in sql.execute(
            "select a.competency_id from achievements a"
            " where a.student_number = ? and a.status = 'achieved'"
            "   and exists (select 1 from evaluations e"
            "                where e.student_number = a.student_number"
            "                  and e.competency_id = a.competency_id)",
            (student_number,)):
        still_proven |= logic.covered_by(other_id, edges)
    for covered_id in candidates - still_proven:
        sql.execute(
            "delete from achievements "
            " where student_number = ? and competency_id = ? "
            "   and not exists (select 1 from evaluations "
            "                    where student_number = ? and competency_id = ?)",
            (student_number, covered_id, student_number, covered_id)
        )


def record_achievement(sql, student_number, competency_id, status, evaluated_by):
    """Record one evaluation, from whichever marking screen produced it.

    Two writes, because two different questions are being answered:

    - `achievements` gets the student's CURRENT state for this competency, replacing
      whatever was there. That is what their progress page reads.
    - `evaluations` gets a new row for the evaluation that just happened, appended.
      That is what the per-evaluator report counts.

    Keeping both matters on a retry. A student marked 'not passed' on Tuesday and
    'achieved' on Thursday should show one state (achieved) and two evaluations, one
    each for the TAs who did them. Counting from `achievements` alone would erase the
    Tuesday evaluator, which is exactly the harder evaluation to have done.

    The queue screen and the /mark page both stay (#44), so this is the single place
    either of them writes a result. That is what keeps them consistent: a rule added
    for one is a rule for both, and neither blueprint has to remember any of it.
    """
    sql.execute(
        "insert or replace into achievements "
        "(student_number, competency_id, status, date_recorded) "
        "values (?, ?, ?, CURRENT_TIMESTAMP)",
        (student_number, competency_id, status)
    )
    sql.execute(
        "insert into evaluations "
        "(student_number, competency_id, status, recorded_at, evaluated_by) "
        "values (?, ?, ?, CURRENT_TIMESTAMP, ?)",
        (student_number, competency_id, status, evaluated_by)
    )
    # A pass credits everything it proves (#80). Only on a pass: failing nested ifs
    # says nothing either way about simple ifs.
    if status == 'achieved':
        _credit_covered(sql, student_number, competency_id)


def clear_achievement(sql, student_number, competency_id):
    """Undo the most recent evaluation, so the competency reads 'not assessed' again.

    Both screens offer this for the same reason: a TA mis-tapped. So it drops the
    state AND the single most recent evaluation row, because an evaluation recorded
    by accident did not happen and must not be counted as somebody's work.

    Only the most recent one. An undo after a genuine earlier evaluation (fail on
    Tuesday, mis-tap on Thursday) must not quietly delete Tuesday's record too.
    """
    sql.execute(
        "delete from achievements where student_number = ? and competency_id = ?",
        (student_number, competency_id)
    )
    sql.execute(
        "delete from evaluations where id = ("
        "  select id from evaluations"
        "   where student_number = ? and competency_id = ?"
        "   order by id desc limit 1)",
        (student_number, competency_id)
    )
    _remove_credits(sql, student_number, competency_id)


def links_newest_first(sql):
    """Every curated link (#51), newest first, as (id, title, why, url) rows.

    All of them, not just the three the page shows: Dave asked for the last 3 visible
    with the rest reachable by scrolling, which is a height on the container rather
    than a limit on the query.
    """
    return sql.execute(
        "select id, title, why, url from links order by added_at desc, id desc"
    ).fetchall()


def add_link(sql, title, why, url):
    sql.execute(
        "insert into links (title, why, url, added_at) values (?, ?, ?, CURRENT_TIMESTAMP)",
        (title, why, url)
    )


def remove_link(sql, link_id):
    # The clicks go with it: a click on a link nobody can see any more is not a fact
    # anyone can act on, and leaving them would make the engagement counts refer to
    # things the instructor has already decided against.
    sql.execute("delete from link_clicks where link_id = ?", (link_id,))
    sql.execute("delete from links where id = ?", (link_id,))


def link_url(sql, link_id):
    row = sql.execute("select url from links where id = ?", (link_id,)).fetchone()
    return row[0] if row else None


def record_link_click(sql, student_number, link_id):
    # insert or ignore: this records WHETHER a student opened it, so a second click is
    # a no-op rather than a number that could be mistaken for enthusiasm.
    sql.execute(
        "insert or ignore into link_clicks (student_number, link_id, clicked_at) "
        "values (?, ?, CURRENT_TIMESTAMP)",
        (student_number, link_id)
    )


def link_engagement(sql):
    """Per link, how many students have opened it: {link_id: count}."""
    return {lid: n for (lid, n) in sql.execute(
        "select link_id, count(*) from link_clicks group by link_id").fetchall()}


def students_with_no_clicks(sql):
    """Students who have opened nothing, as (first, last, number), by surname.

    Encouraging the students who are drifting is the whole reason Dave wanted clicks
    tracked per student. This is the list that makes that possible.
    """
    return sql.execute(
        """select first_name, last_name, student_number from students
            where student_number not in (select student_number from link_clicks)
            order by last_name, first_name"""
    ).fetchall()


def evaluator_counts(sql, since=None):
    """How many evaluations each staff member has recorded, as {evaluator: count}.

    Counts evaluations, not passes: recording 'not passed' is exactly as much work
    as recording 'achieved', and the question this answers is whether the load is
    being shared (#49), not who is generous.

    `since` (an ISO date) narrows to recent work, which is what separates "has done
    little all term" from "is not helping this week".

    Counted from `evaluations`, not `achievements`, and that is the whole reason
    that table exists: a student who fails on Tuesday and passes on Thursday has one
    achievement but two evaluations, and both TAs did the work.
    """
    if since:
        rows = sql.execute(
            "select evaluated_by, count(*) from evaluations "
            "where recorded_at >= ? group by evaluated_by",
            (since,)
        ).fetchall()
    else:
        rows = sql.execute(
            "select evaluated_by, count(*) from evaluations group by evaluated_by"
        ).fetchall()
    return {who: count for (who, count) in rows}


def achievement_states(sql, student_number):
    """A student's recorded results as two dicts keyed by competency_id:
    {id: status} and {id: date_recorded}.

    A competency with no row is simply absent from both, which callers read as
    'not assessed'. This is the one place the achievements table is read for display,
    so the queue, the progress page, and the marking page all agree.
    """
    states = {}
    recorded_at = {}
    for (cid, status, recorded) in sql.execute(
        "select competency_id, status, date_recorded from achievements where student_number = ?",
        (student_number,)
    ).fetchall():
        states[cid] = status
        recorded_at[cid] = recorded
    return states, recorded_at


def pending_competencies(sql, student_number):
    """Competency ids the student currently has in the queue, mapped to how they got
    there: 'carried_over' (a bumped request) or 'in_queue' (a normal sign-up).

    Lets the progress page show that a competency is queued, instead of it looking
    identical to a never-attempted 'not assessed'.
    """
    rows = sql.execute(
        "select competency_id, bumped_by from requests "
        "where student_number = ? and status in ('waiting', 'claimed')",
        (student_number,)
    ).fetchall()
    return {cid: ('carried_over' if bumped_by else 'in_queue')
            for (cid, bumped_by) in rows}


def mark_present(sql, student_number, day):
    # Record that a student showed up for one studio session. Idempotent: the
    # (student, day) primary key means a second check-in the same day is ignored,
    # so tapping "I'm here" again, or entering a seat after checking in, is safe.
    sql.execute(
        "insert or ignore into attendance (student_number, day) values (?, ?)",
        (student_number, day)
    )


def is_present(sql, student_number, day):
    # Whether this student has already checked in for the given session.
    return sql.execute(
        "select 1 from attendance where student_number = ? and day = ?",
        (student_number, day)
    ).fetchone() is not None


def attendance_counts(sql, before=None):
    """(student_number, first, last, sessions attended), most attended first.

    The raw signal behind the instructor's miss-more-than-half rule. Keyed on the
    student number so the progress page can look them up (#75).

    `before` excludes the session currently running, and callers that show a ratio must
    pass it (#89). The denominator counts a session once it is over, so that a student
    is not told they are behind on the strength of one still in progress. Attendance,
    though, lands the moment they sit down. Counting both the same way is the only thing
    that stops a student who turned up today reading as "13 of 12", or as "1 of 0" on
    the very first morning of term.
    """
    where = ' where a.day < ?' if before else ''
    return sql.execute(
        """select a.student_number, s.first_name, s.last_name, count(*) as n
             from attendance a
             join students s on a.student_number = s.student_number"""
        + where +
        """ group by a.student_number
            order by n desc, s.last_name, s.first_name""",
        (before,) if before else ()
    ).fetchall()


def endorsement_tallies(sql):
    """Per student: (number, first, last, thank_yous, how_many_different_classmates).

    Both numbers, because the total alone cannot tell being helpful apart from having
    a friend. The schema already stops the crudest gaming, one thank-you per classmate
    per day, but two students can still thank each other every session and each end the
    term on 36. That looks identical to someone thanked 36 times by 28 different people
    unless the second number is on the page.

    Nothing is blocked or capped by this. A cap would punish genuine repeated help, and
    the instructor decides remarks by judgement anyway (#20). This just makes the shape
    visible so the judgement is an informed one.
    """
    return sql.execute(
        """select e.to_student, s.first_name, s.last_name, count(*) as n,
                  count(distinct e.from_student) as people
             from endorsements e
             join students s on e.to_student = s.student_number
            group by e.to_student
            order by people desc, n desc, s.last_name, s.first_name"""
    ).fetchall()
