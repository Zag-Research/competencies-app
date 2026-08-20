"""The progress page (#72): everyone's standing, per course, on one screen.

Two uses, which is why the order is switchable. During term it answers "who should a
TA go and encourage". At the end it answers "what do I type into D2L".
"""
import sqlite3

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

def test_percentages_are_two_per_competency(db):
    """40 competencies at 2% is the 80% ceiling before remarks (#22)."""
    passed('500111111', 1)
    body = staff().get('/progress').get_data(as_text=True)
    assert 'CPS109 2%' in body


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
