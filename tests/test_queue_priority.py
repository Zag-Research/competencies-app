"""Order the staff queue by who is furthest behind (#69).

Dave, Aug 19: "the list of people to mark will be prioritized by the person who's the
furthest behind, so that hopefully we keep everybody more or less on track. Just in case
we run out of time in a given session."

This replaces first-come-first-served, which was a fairness rule of its own. The new
rule is that when a session runs out of time, the people who miss out should be the ones
who can most afford to.
"""
import sqlite3

import pytest

import db as db_module
import logic

STUDIO = '2026-07-28'


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Four CPS109 competencies and three students, all taking that course."""
    path = tmp_path / 'test.db'
    with open('schema.sql') as f:
        schema = f.read()
    connection = sqlite3.connect(path)
    connection.executescript(schema)
    connection.commit()
    connection.close()
    monkeypatch.setattr(db_module, 'DB_PATH', str(path))
    with db_module.cursor() as sql:
        for i in range(1, 5):
            sql.execute("insert into competencies (id, name, course)"
                        " values (?, ?, 'CPS109')", (i, 'Comp %d' % i))
        for (number, first, last) in (('500111111', 'Alice', 'Chen'),
                                      ('500222222', 'Ben', 'Okafor'),
                                      ('500333333', 'Chloe', 'Diaz')):
            sql.execute("insert into students values (?, ?, ?)", (first, last, number))
            sql.execute("insert into enrollments (student_number, course)"
                        " values (?, 'CPS109')", (number,))
    return db_module


def passed(student_number, *competency_ids):
    with db_module.cursor() as sql:
        for cid in competency_ids:
            sql.execute(
                "insert into achievements (student_number, competency_id, status,"
                " date_recorded) values (?, ?, 'achieved', '2026-07-01 10:00')",
                (student_number, cid))


def queued(student_number, competency_id):
    with db_module.cursor() as sql:
        sql.execute(
            """insert into requests
                   (student_number, competency_id, seat, requested_at, status, studio_date)
               values (?, ?, '12', CURRENT_TIMESTAMP, 'waiting', ?)""",
            (student_number, competency_id, STUDIO))


def staff_queue(monkeypatch):
    from datetime import date
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 28))
    monkeypatch.setattr(logic, 'upcoming_studios', lambda *a, **k: [STUDIO])
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = 'dmason'
        s['role'] = 'staff'
    return client.get('/queue').get_data(as_text=True)


# --- the measure ----------------------------------------------------------

def test_completion_is_a_percentage_of_their_own_courses(db):
    passed('500111111', 1, 2)          # 2 of 4
    with db.cursor() as sql:
        assert db.completion_by_student(sql)['500111111'] == 50


def test_a_student_with_nothing_passed_is_at_zero(db):
    with db.cursor() as sql:
        assert db.completion_by_student(sql)['500222222'] == 0


def test_a_part_time_student_is_not_permanently_first(db):
    """Counting raw would park every part-time student at the top all term.

    Chloe takes one course and has passed half of it. Ben takes the same course and has
    passed none. Ben is further behind, even though both have small raw counts.
    """
    passed('500333333', 1, 2)
    with db.cursor() as sql:
        progress = db.completion_by_student(sql)
    assert progress['500222222'] < progress['500333333']


# --- the order on the page ------------------------------------------------

def test_the_furthest_behind_is_listed_first(db, monkeypatch):
    passed('500111111', 1, 2, 3)        # Alice 75%, signed up first
    queued('500111111', 4)
    queued('500222222', 1)             # Ben 0%, signed up second
    body = staff_queue(monkeypatch)
    assert body.index('Okafor') < body.index('Chen')


def test_equal_progress_keeps_first_come_first_served(db, monkeypatch):
    """The tie-break is the rule the queue used to run on entirely."""
    queued('500222222', 1)             # Ben first, both at 0%
    queued('500333333', 1)             # Chloe second
    body = staff_queue(monkeypatch)
    assert body.index('Okafor') < body.index('Diaz')
