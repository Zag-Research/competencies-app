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
