"""Pace indicator (#50): a student's completion measured against the studio's."""
import sqlite3
from datetime import date

import pytest

import db as db_module
import logic


# --- the term, counted rather than assumed ---------------------------------

def test_the_term_holds_the_thirty_six_sessions_the_course_is_built_around():
    # The number Dave designed the course around, arrived at independently here from
    # the term dates, the Tue/Wed/Thu pattern and the reading weeks. If this fails,
    # one of those three is wrong, not this assertion.
    assert len(logic.studio_days()) == 36


def test_the_term_starts_and_ends_on_a_studio_day():
    days = logic.studio_days()
    assert days[0] == date(2026, 9, 8)     # Tuesday, first day of classes
    assert days[-1] == date(2026, 12, 3)   # Thursday; Dec 7 is the Monday after


def test_reading_week_is_not_a_session():
    assert date(2026, 10, 14) not in logic.studio_days()  # Wednesday of study week


# --- elapsed ---------------------------------------------------------------

def test_todays_session_does_not_count_until_it_is_over():
    # Sitting in the first session, nothing has finished yet.
    assert logic.term_elapsed(date(2026, 9, 8)) == (0, 36)
    assert logic.term_elapsed(date(2026, 9, 9)) == (1, 36)


def test_the_whole_term_has_elapsed_once_it_is_over():
    assert logic.term_elapsed(date(2026, 12, 8)) == (36, 36)


# --- percentages -----------------------------------------------------------

def test_percent_rounds_to_whole_numbers():
    assert logic.percent(1, 3) == 33
    assert logic.percent(2, 3) == 67


def test_percent_survives_a_student_with_no_competencies():
    # A student enrolled in nothing yet must not crash their own progress page.
    assert logic.percent(0, 0) == 0


# --- the wording -----------------------------------------------------------

def test_a_small_gap_reads_as_on_pace():
    assert 'keeping pace' in logic.pace_note(38, 40, elapsed=14)


def test_behind_reads_as_a_nudge_not_a_failure():
    note = logic.pace_note(20, 40, elapsed=14)
    assert 'picking up the pace' in note
    assert 'fail' not in note.lower()


def test_ahead_reads_as_praise():
    assert 'ahead' in logic.pace_note(60, 40, elapsed=14)


def test_before_the_first_session_there_is_nothing_to_catch_up_on():
    # 0% done against 0% elapsed is not "behind", it is "not started".
    assert 'not started' in logic.pace_note(0, 0, elapsed=0)


# --- on the page -----------------------------------------------------------

@pytest.fixture
def db(tmp_path, monkeypatch):
    """One student in CPS109 with two competencies, one of them passed."""
    path = tmp_path / 'test.db'
    with open('schema.sql') as f:
        schema = f.read()
    connection = sqlite3.connect(path)
    connection.executescript(schema)
    connection.commit()
    connection.close()
    monkeypatch.setattr(db_module, 'DB_PATH', str(path))
    with db_module.cursor() as sql:
        sql.execute("insert into students values ('Alice', 'Chen', '500111111')")
        sql.execute("insert into competencies (id, name, course) values (1, 'Nested loops', 'CPS109')")
        sql.execute("insert into competencies (id, name, course) values (2, 'Recursion', 'CPS109')")
        sql.execute("insert into enrollments (student_number, course) values ('500111111', 'CPS109')")
        sql.execute("insert into achievements (student_number, competency_id, status, date_recorded)"
                    " values ('500111111', 1, 'achieved', '2026-09-15 10:00')")
    return db_module


def signed_in_as(username, role):
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = username
        s['role'] = role
    return client


def test_the_progress_page_shows_the_student_against_the_studio(db):
    body = signed_in_as('500111111', 'student').get(
        '/view/500111111').get_data(as_text=True)
    assert 'pace-track' in body
    assert '50%' in body   # one of the student's two competencies is passed


# --- a tripwire for the next term (#64) ------------------------------------

def test_the_term_dates_are_the_term_we_are_actually_in():
    """Fails as soon as TERM_START/TERM_END go stale, which is the whole point.

    Nothing in the app is scoped to a term (#64), so when the studio runs again the
    hard-coded dates here would silently describe the wrong one: the pace bar would sit
    at 100% from the first day and nobody would notice, because it looks like a working
    feature rather than a broken one.

    This turns that into a failing test the moment the dates stop matching reality. It
    is deliberately annoying. If it fails, either update the dates for the new term, or
    do #64 properly, but do not skip it.
    """
    from datetime import timedelta
    today = logic.today_toronto()
    # A month of slack either side, so it does not fail during the break between terms
    # or while setting up for the next one.
    assert today <= logic.TERM_END + timedelta(days=31), (
        'TERM_END is %s, which is in the past. The pace indicator is now describing a '
        'term that has ended. Update the dates or see #64.' % logic.TERM_END
    )


# --- per-course session counts (#81) ---------------------------------------

def test_each_course_meets_on_its_own_weekdays():
    """From Dave's Fall 2026 sections: CPS109 is Tue/Thu, CPS213 is Tue/Wed."""
    whole_term = date(2026, 12, 31)
    assert logic.sessions_for(['CPS109'], whole_term) == (24, 24)
    assert logic.sessions_for(['CPS213'], whole_term) == (24, 24)


def test_a_student_in_both_courses_is_due_at_every_session():
    assert logic.sessions_for(['CPS109', 'CPS213'], date(2026, 12, 31)) == (36, 36)


def test_an_unknown_course_falls_back_to_the_whole_studio():
    """A third course, or a renamed one, must not silently report a smaller denominator."""
    assert logic.sessions_for(['CPS999'], date(2026, 12, 31)) == (36, 36)
    assert logic.sessions_for([], date(2026, 12, 31)) == (36, 36)


def test_todays_session_does_not_count_here_either():
    # Sept 8 is a Tuesday, which CPS109 meets. Sitting in it, none have finished.
    assert logic.sessions_for(['CPS109'], date(2026, 9, 8))[0] == 0
    assert logic.sessions_for(['CPS109'], date(2026, 9, 9))[0] == 1


# --- saying what "behind" is measured against (#128) ------------------------

def test_the_working_is_shown_in_counts():
    """Daniel asked for this on Sept 2: the bar says behind without saying behind what.

    Counts rather than percentages, because "11 of 40" is checkable against the list
    underneath, and repeating 28% would explain the number with itself.
    """
    assert logic.pace_explanation(11, 40, 12, 36) == (
        'You have passed 11 of your 40 competencies. '
        'The studio has run 12 of its 36 sessions.')


def test_nothing_is_explained_before_the_studio_starts():
    """pace_note already says the studio has not started. "0 of 36 sessions" under it
    adds only discouragement."""
    assert logic.pace_explanation(0, 40, 0, 36) is None


def test_the_working_appears_on_the_students_page(db, monkeypatch):
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 10, 6))
    body = signed_in_as('500111111', 'student').get(
        '/view/500111111').get_data(as_text=True)
    assert 'pace-working' in body
    assert 'The studio has run' in body


def test_it_narrows_with_the_course_filter(db, monkeypatch):
    """The bar is filtered by course, so the working underneath has to describe the
    same list or it explains a different number from the one on screen."""
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 10, 6))
    body = signed_in_as('500111111', 'student').get(
        '/view/500111111?course=CPS109').get_data(as_text=True)
    assert 'of your 2 competencies' in body      # the fixture has two in CPS109


# --- the colour ramp (#124) -------------------------------------------------

def test_the_ramp_runs_red_to_green_and_then_blue():
    """Dave's proposal on Sept 2, so an evaluator spots who needs attention without
    reading a number."""
    assert logic.pace_colour(0, 33) == '#c63a2d'          # nothing done, red
    assert logic.pace_colour(33, 33) == '#217a46'         # keeping pace, green
    assert logic.pace_colour(50, 33) == '#1a5fb4'         # ahead, blue


def test_keeping_pace_exactly_is_green_not_blue():
    """Blue is for genuinely ahead. A student who is exactly on track has not done
    anything extra and should not be coloured as though they had."""
    assert logic.pace_colour(33, 33) == '#217a46'
    assert logic.pace_colour(34, 33) == '#1a5fb4'


def test_the_colour_is_about_expected_progress_not_raw_percentage():
    """The whole point. 10% in week two is fine; 10% in week ten is not, and a ramp on
    the raw number would paint them the same."""
    early = logic.pace_colour(10, 10)      # ten percent done, ten percent through
    late = logic.pace_colour(10, 60)       # ten percent done, sixty percent through
    assert early != late
    assert early == '#217a46'              # on track, green

    # A long way behind, so somewhere in the red end of the ramp rather than at the
    # exact endpoint: 17% of expected is not 0% and should not look identical to it.
    red, green, _blue = (int(late[i:i + 2], 16) for i in (1, 3, 5))
    assert red > green * 2


def test_the_ramp_is_gradual_rather_than_three_states():
    """A student at 49% of expected and one at 51% are not meaningfully different and
    should not look it."""
    shades = {logic.pace_colour(p, 100) for p in (20, 40, 60, 80)}
    assert len(shades) == 4


def test_there_is_no_colour_before_the_studio_starts():
    """No sessions have run, so there is no expectation to be behind. The page falls
    back to the stylesheet rather than painting somebody red on day one."""
    assert logic.pace_ratio(0, 0) is None
    assert logic.pace_colour(0, 0) is None


def test_the_bar_carries_the_colour(db, monkeypatch):
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 10, 6))
    body = signed_in_as('500111111', 'student').get(
        '/view/500111111').get_data(as_text=True)
    assert 'background: #' in body


def test_the_bar_carries_no_colour_before_term(db, monkeypatch):
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 9, 1))
    body = signed_in_as('500111111', 'student').get(
        '/view/500111111').get_data(as_text=True)
    assert 'background: #' not in body
