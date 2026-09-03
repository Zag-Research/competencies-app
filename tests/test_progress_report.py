"""The progress page (#72): everyone's standing, per course, on one screen.

Two uses, which is why the order is switchable. During term it answers "who should a
TA go and encourage". At the end it answers "what do I type into D2L".
"""
import sqlite3
from datetime import date

import pytest

import db as db_module
import logic


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Two courses of two competencies, and three students."""
    path = tmp_path / 'test.db'
    with open('schema.sql') as f:
        schema = f.read()
    connection = sqlite3.connect(path)
    connection.executescript(schema)
    connection.commit()
    connection.close()
    monkeypatch.setattr(db_module, 'DB_PATH', str(path))
    with db_module.cursor() as sql:
        for (cid, course) in ((1, 'CPS109'), (2, 'CPS109'), (3, 'CPS213'), (4, 'CPS213')):
            sql.execute("insert into competencies (id, name, course) values (?, ?, ?)",
                        (cid, 'Comp %d' % cid, course))
        for (number, first, last) in (('500111111', 'Alice', 'Chen'),
                                      ('500222222', 'Ben', 'Okafor'),
                                      ('500333333', 'Chloe', 'Diaz')):
            sql.execute("insert into students values (?, ?, ?)", (first, last, number))
            for course in ('CPS109', 'CPS213'):
                sql.execute("insert into enrollments (student_number, course)"
                            " values (?, ?)", (number, course))
    return db_module


def passed(student_number, *cids):
    with db_module.cursor() as sql:
        for cid in cids:
            sql.execute("insert into achievements (student_number, competency_id,"
                        " status, date_recorded)"
                        " values (?, ?, 'achieved', '2026-09-15 10:00')",
                        (student_number, cid))


def staff():
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = 'dmason'
        s['role'] = 'staff'
    return client


# --- the numbers ----------------------------------------------------------

def test_progress_is_reported_per_course(db):
    """Two courses graded separately, so one blended percentage would be the wrong
    number to type into either."""
    passed('500111111', 1, 3)          # one in each course
    with db.cursor() as sql:
        rows = {last: courses for (last, _f, _n, courses) in db.progress_by_student(sql)}
    assert rows['Chen'] == [('CPS109', 1, 2), ('CPS213', 1, 2)]


def test_a_part_time_student_only_lists_their_course(db):
    with db.cursor() as sql:
        sql.execute("update enrollments set withdrawn_on = '2026-09-20'"
                    " where student_number = '500333333' and course = 'CPS213'")
        rows = {last: courses for (last, _f, _n, courses) in db.progress_by_student(sql)}
    assert [c for (c, _d, _t) in rows['Diaz']] == ['CPS109']


# --- the page -------------------------------------------------------------

def test_the_competencies_are_worth_eighty_percent_between_them(db):
    """Dave's design: passing all of them is roughly 80%, remarks are the rest (#22).

    The fixture has two competencies per course, so one of them is half the course's
    share. That the arithmetic works at two and not only at forty is the point (#98).
    """
    passed('500111111', 1)
    assert 'CPS109 40%' in staff().get('/progress').get_data(as_text=True)


def test_a_perfect_student_reads_eighty_whatever_the_list_length(db):
    """The share per competency was hardcoded at 2%, which is only right at exactly 40.

    The list is not final, and one competency added or retired would quietly have made
    a student who passed everything read 82% or 78% (#98).
    """
    with db_module.cursor() as sql:
        sql.execute("insert into competencies (id, name, course)"
                    " values (99, 'A late addition', 'CPS109')")
    passed('500111111', 1, 2, 99)                      # every CPS109 competency there is
    assert 'CPS109 80%' in staff().get('/progress').get_data(as_text=True)


def test_furthest_behind_is_first_by_default(db):
    passed('500111111', 1, 2, 3, 4)     # Alice finished
    body = staff().get('/progress').get_data(as_text=True)
    assert body.index('Diaz') < body.index('Chen')


def test_by_name_orders_by_surname_for_reading_into_d2l(db):
    passed('500111111', 1, 2, 3, 4)
    body = staff().get('/progress?order=name').get_data(as_text=True)
    assert body.index('Chen') < body.index('Diaz') < body.index('Okafor')


def test_no_final_grade_is_computed(db):
    """Dave adds remarks by judgement, so the app shows inputs and stops there."""
    passed('500111111', 1, 2, 3, 4)
    body = staff().get('/progress').get_data(as_text=True)
    assert 'Final' not in body and 'Grade:' not in body


def test_students_cannot_see_everyone_elses_progress(db):
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = '500111111'
        s['role'] = 'student'
    assert client.get('/progress').status_code == 302


# --- students in only one of the two courses (#81) --------------------------

def only_cps109(number='500333333'):
    """Chloe drops CPS213, so she is registered for only some studio sessions."""
    with db_module.cursor() as sql:
        sql.execute("delete from enrollments where student_number = ? and course = 'CPS213'",
                    (number,))


def badges_for(body, surname):
    return body.split(surname)[1].split('progress-row')[0]


def test_a_single_course_student_is_measured_against_their_own_sessions(db, monkeypatch):
    """Chloe takes CPS109, which meets Tuesday and Thursday. Wednesdays are not hers.

    Against the whole term she is counted absent for every Wednesday of the studio, for
    a session she was never registered in, and the under-half flag feeds the attendance
    penalty. That is a mark against somebody who came to everything she signed up for.
    """
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 10, 1))
    only_cps109()
    with db_module.cursor() as sql:
        sql.execute("insert into attendance (student_number, day)"
                    " values ('500333333', '2026-09-08')")
        sql.execute("insert into attendance (student_number, day)"
                    " values ('500111111', '2026-09-08')")
    body = staff().get('/progress').get_data(as_text=True)
    # Same one session attended, different denominators: Alice is due on all three
    # weekdays, Chloe only on two of them.
    assert '1 of 7' in badges_for(body, 'Diaz, Chloe')
    assert '1 of 11' in badges_for(body, 'Chen, Alice')


def test_the_flag_uses_the_students_own_denominator(db, monkeypatch):
    """Four of Chloe's seven is over half, so she is not flagged. Alice's is under."""
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 10, 1))
    only_cps109()
    with db_module.cursor() as sql:
        for day in ('2026-09-08', '2026-09-10', '2026-09-15', '2026-09-17'):
            sql.execute("insert into attendance (student_number, day) values"
                        " ('500333333', ?)", (day,))
            sql.execute("insert into attendance (student_number, day) values"
                        " ('500111111', ?)", (day,))
    body = staff().get('/progress').get_data(as_text=True)
    assert 'state-cooling_off' not in badges_for(body, 'Diaz, Chloe')   # 4 of 7
    assert 'state-cooling_off' in badges_for(body, 'Chen, Alice')       # 4 of 11


def test_the_session_happening_now_counts_on_neither_side(db, monkeypatch):
    """Attendance lands when a student sits down; the denominator waits until the
    session is over. Counting them differently reads as "3 of 2", and on the first
    morning of term as "1 of 0" (#89).
    """
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 9, 15))  # a Tuesday
    with db_module.cursor() as sql:
        for day in ('2026-09-08', '2026-09-09', '2026-09-10', '2026-09-15'):
            sql.execute("insert into attendance (student_number, day)"
                        " values ('500111111', ?)", (day,))
    alice = badges_for(staff().get('/progress').get_data(as_text=True), 'Chen, Alice')
    assert '3 of 3' in alice          # today attended, but today is not over
    assert '4 of 3' not in alice


def test_turning_up_on_the_first_morning_is_not_one_of_zero(db, monkeypatch):
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 9, 8))
    with db_module.cursor() as sql:
        sql.execute("insert into attendance (student_number, day)"
                    " values ('500111111', '2026-09-08')")
    alice = badges_for(staff().get('/progress').get_data(as_text=True), 'Chen, Alice')
    assert 'of 0' not in alice


# --- the attendance line is a setting, not a constant (#108) ----------------

def test_the_attendance_line_is_where_dave_set_it(db, monkeypatch):
    """Half, which is what he said on July 15. Shipping his number, not a new one."""
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 10, 1))
    with db_module.cursor() as sql:
        for day in ('2026-09-08', '2026-09-09', '2026-09-10', '2026-09-15', '2026-09-16'):
            sql.execute("insert into attendance (student_number, day) values"
                        " ('500111111', ?)", (day,))
    # 5 of the 11 finished sessions, so just under half.
    assert 'state-cooling_off' in badges_for(
        staff().get('/progress').get_data(as_text=True), 'Chen, Alice')


def test_moving_the_line_needs_no_deploy(db, monkeypatch):
    """Dave was unsure of the number when he set it, and may want it lower mid-term.

    A row update has to be enough. It was hardcoded as `here * 2 < due`, so softening it
    would have meant cutting a release during teaching.
    """
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 10, 1))
    with db_module.cursor() as sql:
        for day in ('2026-09-08', '2026-09-09', '2026-09-10', '2026-09-15', '2026-09-16'):
            sql.execute("insert into attendance (student_number, day) values"
                        " ('500111111', ?)", (day,))
        sql.execute("update settings set value = '0.4' where key = 'attendance_floor'")
    # 5 of 11 clears a 40% line, so the same student is no longer flagged.
    assert 'state-cooling_off' not in badges_for(
        staff().get('/progress').get_data(as_text=True), 'Chen, Alice')


def test_nobody_is_short_before_the_term_starts():
    assert logic.attendance_is_short(0, 0) is False


def test_the_signup_link_says_what_it_is_for(db):
    """"Sign up" on its own reads as creating an account, which is the wrong idea.

    It was shortened to that for symmetry with "← My progress" and put straight back:
    a student who has already signed in should never be invited to sign up again (#115).
    """
    import app as app_module
    student = app_module.app.test_client()
    with student.session_transaction() as sess:
        sess['user'], sess['role'] = '500111111', 'student'
    forward = student.get('/view/500111111').get_data(as_text=True)
    assert 'Sign up to be evaluated →' in forward
    assert '← My progress' in student.get('/queue').get_data(as_text=True)


# --- colour says whether the number is good for the week (#125) --------------

def badge_colours(body, surname):
    import re
    chunk = body.split(surname)[1].split('progress-row')[0]
    return re.findall(r'<span style="background: (#[0-9a-f]{6})" class="progress-badge">', chunk)


def test_the_number_and_the_colour_say_different_things(db, monkeypatch):
    """Dave's proposal on Sept 2. The number is how much of the course they have done;
    the colour is whether that is good for this point in the term. 22% means nothing
    until you know what week it is, and his use for this page is spotting who to talk to.
    """
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 10, 6))
    passed('500111111', 1)                      # 1 of 2 in CPS109, none in CPS213
    body = staff().get('/progress').get_data(as_text=True)
    ahead, behind = badge_colours(body, 'Chen, Alice')
    assert ahead != behind                      # same student, two very different weeks
    # The number is untouched: still the share of the course's marks the competencies
    # are worth, which is 1 of 2 competencies at 80% between them.
    assert 'CPS109 40%' in body


def test_every_badge_is_pale_enough_to_read_dark_text_on(db, monkeypatch):
    """Dave asked for a light red to light green range here rather than the bar's
    saturated colours, because a badge is a background behind dark text."""
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 10, 6))
    body = staff().get('/progress').get_data(as_text=True)
    for colour in badge_colours(body, 'Chen, Alice'):
        rgb = [int(colour[i:i + 2], 16) for i in (1, 3, 5)]
        assert min(rgb) > 200, colour           # nothing dark enough to swallow text


def test_before_term_the_badges_keep_their_old_states(db, monkeypatch):
    """No sessions have run, so there is nothing to be behind and no colour to show.
    The page falls back to the achieved and unassessed classes it used before."""
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 9, 1))
    body = staff().get('/progress').get_data(as_text=True)
    assert 'background: #' not in body
    assert 'state-unassessed' in body
